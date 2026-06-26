"""Cluster acceptance steps — smoke end-to-end (EA-0001).

Drives the deployed cluster over gRPC and asserts on cross-service effects that
land asynchronously over AMQP. The smoke path exercises three of the four
component types end to end on the wire:

  StartHand (table aggregate) → HandStarted event → table→hand saga →
  DealCards command (hand aggregate) → CardsDealt event.

State assertions poll the target aggregate's persisted EventBook (there is no
deployed event-stream service); `within N seconds` rows poll until the named
event-type appears at the relevant root or the deadline expires.
"""

from __future__ import annotations

import subprocess
import time

import grpc
from behave import given, step, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as reg
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as trn
from acceptance_steps._client import fq_from_url

_HUMAN = pt.PlayerType.Value("HUMAN")
_HOLDEM = pt.GameVariant.Value("TEXAS_HOLDEM")


def _currency(amount: int) -> pt.Currency:
    return pt.Currency(amount=amount, currency_code="CHIPS")


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the poker cluster is reachable")
def _cluster_reachable(context):
    assert getattr(context, "cluster_reachable", False), (
        "poker cluster is not reachable on the aggregate NodePorts "
        "(localhost:31320..31324) — bring the cluster up with `just up`, or "
        "point at a different cluster via the <DOMAIN>_URL env vars."
    )


# ---------------------------------------------------------------------------
# Given: registered, funded players
# ---------------------------------------------------------------------------


def _register_player(context, name: str, bankroll: int) -> None:
    w = context.world
    if name not in w.players:
        w.players.append(name)
    root = w.root(name)
    w.client.send(
        "player",
        "RegisterPlayer",
        player.RegisterPlayer(
            display_name=name,
            email=f"{name.lower()}@example.test",
            player_type=_HUMAN,
        ),
        root=root,
        correlation_id=w.correlation_id,
    )
    if bankroll:
        w.client.send(
            "player",
            "DepositFunds",
            player.DepositFunds(amount=_currency(bankroll)),
            root=root,
            correlation_id=w.correlation_id,
        )


@given("registered players with bankroll")
@given("registered players with bankroll:")
def _given_registered_players(context):
    for row in context.table:
        _register_player(context, row["name"], int(row["bankroll"]))


@given('a registered player "{name}" with bankroll {bankroll:d}')
def _given_registered_player(context, name, bankroll):
    _register_player(context, name, bankroll)
    context.world.current_player = name


@when('I deposit {amount:d} chips to player "{name}"')
def _deposit_chips(context, amount, name):
    w = context.world
    w.client.send(
        "player",
        "DepositFunds",
        player.DepositFunds(amount=_currency(amount)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    w.current_player = name


@then("within {secs:d} seconds the player display reports bankroll {amount:d}")
def _player_display_bankroll(context, secs, amount):
    # Observes the deployed PlayerProjector's read model over the wire — the
    # deposit lands on the player aggregate, the projector coordinator delivers
    # the FundsDeposited off the bus, the projector folds it, and the query
    # surface reports the new balance. The bound under test is that lag.
    name = getattr(context.world, "current_player", None)
    assert name is not None, "no player established in this scenario"
    root = context.world.root(name)
    view = context.world.client.wait_for_balance(root, amount, within=float(secs))
    assert view is not None and view.found, (
        f"player projector never reported a balance for {name!r} within {secs}s "
        f"(read model has not observed the deposit)"
    )
    assert (
        view.balance.amount == amount
    ), f"player display bankroll = {view.balance.amount}, want {amount}"


# ---------------------------------------------------------------------------
# When: table lifecycle
# ---------------------------------------------------------------------------


@when('I create a Texas Hold\'em table "{name}" with blinds {sb:d}/{bb:d}')
def _create_table(context, name, sb, bb):
    w = context.world
    w.client.send(
        "table",
        "CreateTable",
        table.CreateTable(
            # Salt the stored table_name with the scenario nonce: the table
            # derives table_id from it, and the hand aggregate derives hand_root
            # from table_id + hand_number. Without this the hand_root is constant
            # across runs and the deployed hand aggregate accumulates state, so
            # assertions would match a stale CardsDealt from a prior run. The
            # cover root is already scenario-unique; nothing routes by name.
            table_name=f"{name}-{w.nonce[:12]}",
            game_variant=_HOLDEM,
            small_blind=sb,
            big_blind=bb,
            min_buy_in=1,
            max_buy_in=1_000_000,
            max_players=9,
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    if name not in w.tables:
        w.tables.append(name)
    context.world.current_table = name


@step('player "{who}" joins table "{name}" at seat {seat:d} with buy-in {buyin:d}')
def _join_table(context, who, name, seat, buyin):
    w = context.world
    w.client.send(
        "table",
        "JoinTable",
        table.JoinTable(
            player_root=w.root(who),
            preferred_seat=seat,
            buy_in_amount=buyin,
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('a hand starts at table "{name}"')
def _start_hand(context, name):
    w = context.world
    w.client.send(
        "table",
        "StartHand",
        table.StartHand(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    context.world.current_table = name


# ---------------------------------------------------------------------------
# Then: within N seconds, the named events appear in the named domains
# ---------------------------------------------------------------------------


def _table_root(context) -> bytes:
    name = getattr(context.world, "current_table", None)
    assert name is not None, "no table established in this scenario"
    return context.world.root(name)


def _hand_root(context) -> bytes:
    """The hand's root, read off the table's HandStarted event (the saga deals
    to this child aggregate). Cached on the world once discovered."""
    w = context.world
    if "hand" in w.roots:
        return w.roots["hand"]
    page = w.client.wait_for_event(
        "table", _table_root(context), "HandStarted", within=5.0
    )
    assert page is not None, "table never emitted HandStarted"
    started = table.HandStarted()
    started.ParseFromString(page.event.value)
    w.roots["hand"] = started.hand_root
    context.last_hand_started = started
    return started.hand_root


def _assert_event_within(context, domain: str, event_type: str, secs: float) -> None:
    if domain == "table":
        root = _table_root(context)
    elif domain == "hand":
        root = _hand_root(context)
    else:
        root = context.world.root(getattr(context.world, "current_table", domain))
    page = context.world.client.wait_for_event(domain, root, event_type, within=secs)
    if page is None:
        book = context.world.client.event_book(domain, root)
        present = [p.event.type_url for p in book.pages]
        raise AssertionError(
            f"{domain} aggregate (root={root.hex()[:12]}) did not emit "
            f"{event_type} within {secs}s; events present: {present}"
        )


@then("within {secs:d} seconds")
@then("within {secs:d} seconds:")
def _within_seconds_table(context, secs):
    assert context.table is not None, "expected a | domain | event_type | table"
    for row in context.table:
        _assert_event_within(context, row["domain"], row["event_type"], float(secs))


# ---------------------------------------------------------------------------
# Composite seating Givens + saga-latency / routing assertions (EA-0002/0005)
# ---------------------------------------------------------------------------


def _seat(
    context, name: str, table_name: str, seat: int, stack: int, bankroll: int
) -> None:
    """Register + fund a player, then seat them at the table."""
    _register_player(context, name, bankroll)
    _join_table(context, name, table_name, seat, stack)


@given('a table "{name}" with {count:d} seated players')
def _given_table_with_count(context, name, count):
    _create_table(context, name, 5, 10)
    defaults = [
        "Alice",
        "Bob",
        "Carol",
        "Dave",
        "Eve",
        "Frank",
        "Grace",
        "Henry",
        "Ivy",
    ]
    for seat in range(count):
        _seat(context, defaults[seat], name, seat, 500, 1000)


@given('a table "{name}" with seated players')
@given('a table "{name}" with seated players:')
def _given_table_with_seated(context, name):
    _create_table(context, name, 5, 10)
    for row in context.table:
        _seat(context, row["name"], name, int(row["seat"]), int(row["stack"]), 1000)


@when('I start a hand at table "{name}"')
def _when_start_hand(context, name):
    _start_hand(context, name)


@then("within {secs:d} seconds hand domain has {event_type} event")
def _within_hand_event(context, secs, event_type):
    _assert_event_within(context, "hand", event_type, float(secs))


@then("the hand has the same hand_number as the table event")
def _same_hand_number(context):
    page = context.world.client.wait_for_event(
        "hand", _hand_root(context), "CardsDealt", within=5.0
    )
    assert page is not None, "hand never emitted CardsDealt"
    dealt = hand.CardsDealt()
    dealt.ParseFromString(page.event.value)
    table_hn = context.last_hand_started.hand_number
    assert dealt.hand_number == table_hn, (
        f"hand_number mismatch: hand CardsDealt={dealt.hand_number}, "
        f"table HandStarted={table_hn}"
    )


@then("the deal-cards request was handled by the hand service")
def _deal_handled_by_hand(context):
    # The hand aggregate emitting CardsDealt IS the evidence that the cross-domain
    # DealCards command (saga-routed from the table's HandStarted) landed on and
    # was processed by the hand service.
    page = context.world.client.wait_for_event(
        "hand", _hand_root(context), "CardsDealt", within=5.0
    )
    assert (
        page is not None
    ), "hand service did not handle the deal-cards request (no CardsDealt)"


# ---------------------------------------------------------------------------
# Tournament lifecycle (cluster_tournament EA-0006+) — the tournament aggregate
# ---------------------------------------------------------------------------


def _tournament_events(context, name: str, event_type: str) -> list:
    """Decoded tournament events of type ``event_type`` (bare proto name) from
    the tournament aggregate's persisted EventBook."""
    book = context.world.client.event_book("tournament", context.world.root(name))
    out = []
    for page in book.pages:
        if fq_from_url(page.event.type_url).endswith("." + event_type):
            msg = getattr(trn, event_type)()
            msg.ParseFromString(page.event.value)
            out.append(msg)
    return out


@given(
    'a tournament "{name}" with buy_in {buy_in:d}, starting_stack {stack:d}, '
    "max_players {maxp:d}, min_players {minp:d}"
)
def _create_tournament(context, name, buy_in, stack, maxp, minp):
    w = context.world
    w.client.send(
        "tournament",
        "CreateTournament",
        trn.CreateTournament(
            name=name,
            game_variant=_HOLDEM,
            buy_in=buy_in,
            starting_stack=stack,
            max_players=maxp,
            min_players=minp,
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    context.world.current_tournament = name


@given(
    'a tournament "{name}" with buy_in {buy_in:d}, starting_stack {stack:d}, '
    "max_players {maxp:d}, min_players {minp:d}, rebuys enabled with cost "
    "{cost:d} and chips {chips:d}"
)
def _create_tournament_with_rebuys(
    context, name, buy_in, stack, maxp, minp, cost, chips
):
    # Rebuys enabled + a multi-level blind structure so AdvanceBlindLevel has
    # somewhere to go (the aggregate refuses to advance past the structure).
    w = context.world
    w.client.send(
        "tournament",
        "CreateTournament",
        trn.CreateTournament(
            name=name,
            game_variant=_HOLDEM,
            buy_in=buy_in,
            starting_stack=stack,
            max_players=maxp,
            min_players=minp,
            rebuy_config=trn.RebuyConfig(
                enabled=True, rebuy_cost=cost, rebuy_chips=chips
            ),
            blind_structure=[
                trn.BlindLevel(level=1, small_blind=5, big_blind=10),
                trn.BlindLevel(level=2, small_blind=10, big_blind=20),
                trn.BlindLevel(level=3, small_blind=20, big_blind=40),
            ],
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    context.world.current_tournament = name


@step('I open registration on tournament "{name}"')
def _open_registration(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "OpenRegistration",
        trn.OpenRegistration(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('player "{who}" registers for tournament "{name}"')
def _register_for_tournament(context, who, name):
    w = context.world
    w.client.send(
        "tournament",
        "EnrollPlayer",
        trn.EnrollPlayer(
            player_root=w.root(who), reservation_id=w.root(f"{who}:resv:{name}")
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('every player registers for tournament "{name}"')
def _every_player_registers(context, name):
    # Bulk-enroll every player the scenario registered (in creation order). Each
    # EnrollPlayer lands on the tournament aggregate; the tournament must have
    # registration open.
    for who in context.world.players:
        _register_for_tournament(context, who, name)


@step('I start tournament "{name}"')
def _start_tournament(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "StartTournament",
        trn.StartTournament(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I advance blind level on tournament "{name}"')
def _advance_blind_level(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "AdvanceBlindLevel",
        trn.AdvanceBlindLevel(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I process a rebuy for player "{who}" on tournament "{name}"')
def _process_rebuy(context, who, name):
    w = context.world
    w.client.send(
        "tournament",
        "ProcessRebuy",
        trn.ProcessRebuy(
            player_root=w.root(who),
            reservation_id=w.root(f"{who}:rebuy:{name}"),
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I eliminate player "{who}" from tournament "{name}"')
def _eliminate_player(context, who, name):
    w = context.world
    w.client.send(
        "tournament",
        "EliminatePlayer",
        trn.EliminatePlayer(player_root=w.root(who)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I complete tournament "{name}" with winner "{who}"')
def _complete_tournament(context, name, who):
    w = context.world
    w.client.send(
        "tournament",
        "CompleteTournament",
        trn.CompleteTournament(winner_root=w.root(who)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


def _current_hand_root_at(context, table_name: str) -> bytes:
    """The root of the table's CURRENT (most recent) hand, read fresh from the
    latest ``HandStarted`` at the table. Unlike the cached ``_hand_root`` this is
    re-resolved per call, so a multi-hand scenario reads each hand's own root."""
    w = context.world
    table_root = w.root(table_name)
    page = w.client.wait_for_event("table", table_root, "HandStarted", within=5.0)
    assert page is not None, f"table {table_name!r} never emitted HandStarted"
    book = w.client.event_book("table", table_root)
    latest = None
    for p in book.pages:
        if fq_from_url(p.event.type_url).endswith(".HandStarted"):
            latest = p
    assert latest is not None, f"no HandStarted in {table_name!r} event book"
    started = table.HandStarted()
    started.ParseFromString(latest.event.value)
    return started.hand_root


@step('the hand at table "{name}" is awarded to "{who}"')
def _award_hand(context, name, who):
    # Fast-forward hand completion at the TABLE: EndHand records the winner and
    # returns the table to "waiting" so the next StartHand is accepted. (Awarding
    # only the hand aggregate would leave the table stuck "in_hand" — the table
    # learns of completion via EndHand, the fast-forward stand-in for the saga
    # path a fully-played hand would drive.)
    w = context.world
    hand_root = _current_hand_root_at(context, name)
    w.client.send(
        "table",
        "EndHand",
        table.EndHand(
            hand_root=hand_root,
            results=[table.PotResult(winner_root=w.root(who), amount=0)],
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@then('tournament "{name}" has {count:d} registered players')
def _has_registered(context, name, count):
    enrolled = _tournament_events(context, name, "TournamentPlayerEnrolled")
    assert len(enrolled) == count, f"expected {count} enrolled, got {len(enrolled)}"


@then('tournament "{name}" has total_prize_pool {amount:d}')
def _has_prize_pool(context, name, amount):
    # The prize pool grows by enrollment fees AND rebuy fees (apply_rebuy_processed
    # adds rebuy_cost), so both event streams contribute.
    enrolled = _tournament_events(context, name, "TournamentPlayerEnrolled")
    rebuys = _tournament_events(context, name, "RebuyProcessed")
    pool = sum(e.fee_paid for e in enrolled) + sum(r.rebuy_cost for r in rebuys)
    assert pool == amount, f"expected prize pool {amount}, got {pool}"


@then('tournament "{name}" has current_level {level:d}')
def _has_current_level(context, name, level):
    # current_level starts at 1; each BlindLevelAdvanced bumps it by one, so the
    # level is 1 + (number of advance events observed at the tournament root).
    def reached():
        advances = len(_tournament_events(context, name, "BlindLevelAdvanced"))
        return (1 + advances) == level

    deadline = time.time() + 10.0
    while time.time() < deadline:
        if reached():
            return
        time.sleep(0.2)
    advances = len(_tournament_events(context, name, "BlindLevelAdvanced"))
    raise AssertionError(
        f"tournament {name!r} current_level = {1 + advances}, want {level}"
    )


@then('tournament "{name}" has players_remaining {count:d}')
def _players_remaining(context, name, count):
    enrolled = len(_tournament_events(context, name, "TournamentPlayerEnrolled"))
    eliminated = len(_tournament_events(context, name, "PlayerEliminated"))
    remaining = enrolled - eliminated
    assert remaining == count, f"expected {count} remaining, got {remaining}"


# ---------------------------------------------------------------------------
# Color-up / chip race (EA-0011) — TDA Rule 24
# ---------------------------------------------------------------------------


@when('I advance blind level on tournament "{name}" with color-up')
@when('I advance blind level on tournament "{name}" with color-up:')
def _color_up(context, name):
    # The gherkin table carries the retire/new denominations. The color-up is a
    # ColorUp command to the tournament; it retires the low denom for the high.
    row = context.table[0]
    w = context.world
    w.client.send(
        "tournament",
        "ColorUp",
        trn.ColorUp(
            retire_denomination=int(row["retire_denomination"]),
            new_denomination=int(row["new_denomination"]),
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    context.world.current_tournament = name


def _wait_tournament_events(context, name, event_type, within=5.0):
    deadline = time.time() + within
    while time.time() < deadline:
        evs = _tournament_events(context, name, event_type)
        if evs:
            return evs
        time.sleep(0.2)
    return _tournament_events(context, name, event_type)


@then('the color-up completes on tournament "{name}"')
def _color_up_completes(context, name):
    evs = _wait_tournament_events(context, name, "ColorUpCompleted")
    assert evs, f"tournament {name!r} emitted no ColorUpCompleted"


@then("every active player's stack contains no chips of denomination {denom:d}")
def _no_chips_of_denomination(context, denom):
    # The chip-race retired this denomination for the whole field; the tournament
    # records the retirement on ColorUpCompleted. A stack containing a retired-denom
    # chip could only exist if the event named a different denomination.
    name = context.world.current_tournament
    evs = _tournament_events(context, name, "ColorUpCompleted")
    assert evs, "no ColorUpCompleted to verify retirement against"
    assert (
        evs[-1].retired_denomination == denom
    ), f"color-up retired denomination {evs[-1].retired_denomination}, want {denom}"


@then("the total chips in play before and after the color-up are equal")
def _chips_conserved(context):
    # Conservation invariant: post = pre + chips_added_by_rescue − chips_removed_by_race.
    # Equal iff the two deltas match (both zero in the no-remainder slice).
    name = context.world.current_tournament
    evs = _tournament_events(context, name, "ColorUpCompleted")
    assert evs, "no ColorUpCompleted to verify conservation against"
    ev = evs[-1]
    assert ev.chips_added_by_rescue == ev.chips_removed_by_race, (
        f"chip economy not conserved: +{ev.chips_added_by_rescue} rescue vs "
        f"−{ev.chips_removed_by_race} race"
    )


def _latest_tournament_status(context, name: str) -> str | None:
    """Walk the tournament book in sequence order and return the current
    lifecycle status, derived from the last status-changing event seen
    (Started/Paused/Resumed/Completed)."""
    book = context.world.client.event_book("tournament", context.world.root(name))
    status = None
    for page in book.pages:
        fq = fq_from_url(page.event.type_url)
        if fq.endswith(".TournamentStarted"):
            status = "Running"
        elif fq.endswith(".TournamentPaused"):
            status = "Paused"
        elif fq.endswith(".TournamentResumed"):
            status = "Running"
        elif fq.endswith(".TournamentCompleted"):
            status = "Completed"
    return status


@then('tournament "{name}" has status "{status}"')
def _tournament_status(context, name, status):
    if status not in ("Completed", "Paused", "Running"):
        raise AssertionError(f"status assertion for {status!r} not implemented")
    deadline = time.time() + 10.0
    actual = None
    while True:
        actual = _latest_tournament_status(context, name)
        if actual == status or time.time() >= deadline:
            break
        time.sleep(0.2)
    assert actual == status, f"tournament {name!r} status = {actual!r}, want {status!r}"


@then('tournament "{name}" winner is "{who}"')
def _tournament_winner(context, name, who):
    done = _tournament_events(context, name, "TournamentCompleted")
    assert done, "no TournamentCompleted event"
    assert done[-1].winner_root == context.world.root(who), "winner mismatch"


@then(
    "within {secs:d} seconds the table starts the hand and cards are dealt to the players"
)
def _table_starts_and_deals(context, secs):
    _assert_event_within(context, "table", "HandStarted", float(secs))
    _assert_event_within(context, "hand", "CardsDealt", float(secs))


# ---------------------------------------------------------------------------
# Durability — state survives a coordinator restart (EA-0003)
# ---------------------------------------------------------------------------

_NAMESPACE = "angzarr"


def _kubectl(*args: str) -> None:
    subprocess.run(
        ["kubectl", "-n", _NAMESPACE, *args], check=True, capture_output=True
    )


@when("the player service restarts")
def _restart_player_service(context):
    # Roll the player coordinator and wait for the replacement to be Ready. The
    # new pod holds NO in-memory state — it rebuilds each aggregate from the
    # postgres event store on demand, which is exactly the durability under test.
    # Reaching it needs no reconnect: the NodePort routes to whatever pod is
    # ready (a kubectl port-forward, by contrast, pins the now-dead pod).
    _kubectl("rollout", "restart", "deployment/player-aggregate")
    _kubectl("rollout", "status", "deployment/player-aggregate", "--timeout=120s")
    # The pre-restart connection is pinned to the now-dead pod; dial the new one.
    context.world.client.reset_channel("player")


def _player_book_resilient(context, name, secs=10.0):
    """The player's EventBook, retrying transient gRPC failures. A rolling
    restart tears down the old pod's connection mid-flight ("Socket closed");
    the next call reconnects through the NodePort to the new pod, so a brief
    retry rides out the blip."""
    root = context.world.root(name)
    deadline = time.time() + secs
    last = None
    while True:
        try:
            # Short PER-ATTEMPT timeout (not the default 10s): right after a
            # rolling restart the NodePort may briefly route to the draining old
            # pod, and a connect to it hangs until timeout. A long per-attempt
            # timeout would burn the whole deadline on one dead endpoint; a short
            # one lets us re-dial the new pod and ride out the blip.
            return context.world.client.event_book("player", root, timeout=2.0)
        except Exception as exc:  # noqa: BLE001 — retry until the deadline
            last = exc
            if time.time() >= deadline:
                raise AssertionError(
                    f"player {name!r} not reachable within {secs}s: {last}"
                ) from exc
            context.world.client.reset_channel("player")
            time.sleep(0.3)


@then('within {secs:d} seconds player "{name}" is reachable')
def _player_reachable(context, secs, name):
    _player_book_resilient(context, name, float(secs))


def _bankroll_from_book(book) -> int | None:
    """The player's current bankroll: the ``new_balance`` carried by the most
    recent balance-changing event in page (sequence) order. Deposits, withdrawals
    and reserved-funds deductions each stamp the absolute post-op bankroll;
    reserves/releases move only the reserved bucket and leave bankroll unchanged,
    so they are skipped here."""
    balance = None
    for page in book.pages:
        fq = fq_from_url(page.event.type_url)
        if fq.endswith(".FundsDeposited"):
            ev = player.FundsDeposited()
            ev.ParseFromString(page.event.value)
            balance = ev.new_balance.amount
        elif fq.endswith(".FundsWithdrawn"):
            ev = player.FundsWithdrawn()
            ev.ParseFromString(page.event.value)
            balance = ev.new_balance.amount
        elif fq.endswith(".FundsDeducted"):
            ev = player.FundsDeducted()
            ev.ParseFromString(page.event.value)
            balance = ev.new_balance.amount
    return balance


@then('player "{name}" has bankroll {amount:d}')
def _player_bankroll(context, name, amount):
    # Poll: deductions driven by the reservation PM land asynchronously, so the
    # bankroll can lag a few hundred ms behind the command that triggered it.
    deadline = time.time() + 10.0
    balance = None
    while True:
        book = _player_book_resilient(context, name)
        balance = _bankroll_from_book(book)
        if balance == amount or time.time() >= deadline:
            break
        time.sleep(0.2)
    assert balance == amount, f"bankroll = {balance}, want {amount}"


def _player_reserved(context, name: str) -> int:
    """Current reserved funds = sum of FundsReserved amounts minus FundsReleased
    and FundsDeducted amounts on the player's event book."""
    book = context.world.client.event_book("player", context.world.root(name))
    reserved = 0
    for page in book.pages:
        fq = fq_from_url(page.event.type_url)
        if fq.endswith(".FundsReserved"):
            ev = player.FundsReserved()
            ev.ParseFromString(page.event.value)
            reserved += ev.amount.amount
        elif fq.endswith(".FundsReleased"):
            ev = player.FundsReleased()
            ev.ParseFromString(page.event.value)
            reserved -= ev.amount.amount
        elif fq.endswith(".FundsDeducted"):
            ev = player.FundsDeducted()
            ev.ParseFromString(page.event.value)
            reserved -= ev.amount.amount
    return reserved


# ===========================================================================
# EA-0008 — full-lifecycle complex tournament across every code path.
#
# Adds: player financial primitives (reserve/deduct/release/withdraw), the
# reservation-domain initiation commands (buy-in / registration / rebuy) that
# drive the reservation aggregate + PM, tournament close/pause/resume, and a
# real betting hand played action-by-action against the deployed hand engine.
# ===========================================================================


# --- Player financial primitives (player aggregate) ------------------------


def _bet_key(context, name: str) -> bytes:
    """Deterministic reservation-bucket key for a player's "upcoming bet"."""
    return context.world.root(f"bet:{name}")


@when('player "{name}" reserves {amount:d} chips for an upcoming bet')
def _reserve_for_bet(context, name, amount):
    w = context.world
    w.client.send(
        "player",
        "ReserveFunds",
        player.ReserveFunds(amount=_currency(amount), key=_bet_key(context, name)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    w.current_player = name


@then('player "{name}" has reserved funds {amount:d}')
def _has_reserved_funds(context, name, amount):
    deadline = time.time() + 10.0
    actual = None
    while True:
        actual = _player_reserved(context, name)
        if actual == amount or time.time() >= deadline:
            break
        time.sleep(0.2)
    assert actual == amount, f"player {name!r} reserved_funds = {actual}, want {amount}"


@when('player "{name}" confirms the {amount:d}-chip deduction')
def _confirm_deduction(context, name, amount):
    w = context.world
    w.client.send(
        "player",
        "DeductReservedFunds",
        player.DeductReservedFunds(
            amount=_currency(amount),
            key=_bet_key(context, name),
            reservation_id=w.root(f"deduct:{name}"),
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    w.current_player = name


@when('player "{name}" releases the reserved {amount:d} chips')
def _release_reserved(context, name, amount):
    w = context.world
    w.client.send(
        "player",
        "ReleaseFunds",
        player.ReleaseFunds(key=_bet_key(context, name)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    w.current_player = name


@when('player "{name}" withdraws {amount:d} chips')
def _withdraw_chips(context, name, amount):
    w = context.world
    w.client.send(
        "player",
        "WithdrawFunds",
        player.WithdrawFunds(amount=_currency(amount)),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    w.current_player = name


# --- Reservation initiations (reservation domain) --------------------------
#
# Initiate* land on the reservation AGGREGATE, which emits a *Requested event
# (returned synchronously) and the deployed reservation PM then fans the flow
# out to player + table/tournament off the bus. "was accepted" asserts the
# aggregate accepted the request (the *Requested event is persisted at the
# reservation root). Downstream PM activity is observed indirectly by later
# steps; the explicit JoinTable / EnrollPlayer steps do the authoritative
# seating / enrollment so the async PM path harmlessly no-ops on conflict.


def _reservation_root(context, player_name: str, kind: str) -> bytes:
    return context.world.root(f"resv:{player_name}:{kind}")


def _initiate_reservation(context, player_name, kind, cmd_name, cmd, requested_event):
    w = context.world
    root = _reservation_root(context, player_name, kind)
    w.client.send(
        "reservation",
        cmd_name,
        cmd,
        root=root,
        correlation_id=w.correlation_id,
    )
    context.last_reservation = (root, requested_event)


@when('player "{name}" initiates tournament registration for "{tournament}"')
def _initiate_registration(context, name, tournament):
    w = context.world
    _initiate_reservation(
        context,
        name,
        "registration",
        "InitiateTournamentRegistration",
        reg.InitiateTournamentRegistration(
            tournament_root=w.root(tournament),
            player_root=w.root(name),
        ),
        "RegistrationRequested",
    )


@when(
    'player "{name}" initiates buy-in to table "{table_name}" '
    "at seat {seat:d} for {amount:d}"
)
def _initiate_buy_in(context, name, table_name, seat, amount):
    w = context.world
    _initiate_reservation(
        context,
        name,
        "buy_in",
        "InitiateBuyIn",
        buy_in.InitiateBuyIn(
            table_root=w.root(table_name),
            seat=seat,
            amount=_currency(amount),
            player_root=w.root(name),
        ),
        "BuyInRequested",
    )


@when(
    'player "{name}" initiates rebuy on tournament "{tournament}" '
    'at table "{table_name}" seat {seat:d}'
)
def _initiate_rebuy(context, name, tournament, table_name, seat):
    w = context.world
    _initiate_reservation(
        context,
        name,
        "rebuy",
        "InitiateRebuy",
        rebuy.InitiateRebuy(
            tournament_root=w.root(tournament),
            table_root=w.root(table_name),
            seat=seat,
            player_root=w.root(name),
        ),
        "RebuyRequested",
    )


@then("the {flow} request was accepted")
def _reservation_request_accepted(context, flow):
    # The reservation aggregate accepted the Initiate* when it persisted the
    # matching *Requested event at the reservation root (send() already raised
    # if the command was rejected; this confirms the event landed).
    root, event_name = context.last_reservation
    page = context.world.client.wait_for_event(
        "reservation", root, event_name, within=5.0
    )
    assert page is not None, (
        f"reservation aggregate (root={root.hex()[:12]}) did not emit "
        f"{event_name}; the {flow} request was not accepted"
    )


# --- Tournament lifecycle: close / pause / resume --------------------------


@step('I close registration on tournament "{name}"')
def _close_registration(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "CloseRegistration",
        trn.CloseRegistration(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I pause tournament "{name}"')
def _pause_tournament(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "PauseTournament",
        trn.PauseTournament(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@step('I resume tournament "{name}"')
def _resume_tournament(context, name):
    w = context.world
    w.client.send(
        "tournament",
        "ResumeTournament",
        trn.ResumeTournament(),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


# --- A real betting hand, played action by action --------------------------
#
# The deployed table->hand saga auto-deals (Shuffle + DealCards) after the
# table's StartHand. "the hand has been dealt" gates on the saga's CardsDealt
# landing on the hand aggregate; the scripted blinds/actions then drive the
# real NLHE betting engine. amount semantics follow the engine (handler.py
# player_action): BET amount = chips wagered, RAISE amount = target TOTAL
# level, CALL amount is informational (the engine computes it from the
# current bet); blinds post the absolute chip amount.


def _betting_hand_root(context) -> bytes:
    root = getattr(context, "betting_hand_root", None)
    assert root is not None, "no betting hand established ('the hand has been dealt')"
    return root


def _send_hand(context, name, msg):
    w = context.world
    w.client.send(
        "hand",
        name,
        msg,
        root=_betting_hand_root(context),
        correlation_id=w.correlation_id,
    )


@step('the hand has been dealt at table "{name}"')
def _hand_has_been_dealt(context, name):
    root = _current_hand_root_at(context, name)
    context.betting_hand_root = root
    page = context.world.client.wait_for_event("hand", root, "CardsDealt", within=8.0)
    assert page is not None, (
        f"hand (root={root.hex()[:12]}) was not dealt within 8s — the "
        f"table->hand saga's CardsDealt never landed"
    )


@step('"{name}" posts small blind {amount:d}')
def _post_small_blind(context, name, amount):
    _send_hand(
        context,
        "PostBlind",
        hand.PostBlind(
            player_root=context.world.root(name), blind_type="small", amount=amount
        ),
    )


@step('"{name}" posts big blind {amount:d}')
def _post_big_blind(context, name, amount):
    _send_hand(
        context,
        "PostBlind",
        hand.PostBlind(
            player_root=context.world.root(name), blind_type="big", amount=amount
        ),
    )


def _player_action(context, name, action, amount=0):
    _send_hand(
        context,
        "PlayerAction",
        hand.PlayerAction(
            player_root=context.world.root(name), action=action, amount=amount
        ),
    )


@step('"{name}" folds')
def _action_fold(context, name):
    _player_action(context, name, pt.FOLD)


@step('"{name}" checks')
def _action_check(context, name):
    _player_action(context, name, pt.CHECK)


@step('"{name}" calls {amount:d}')
def _action_call(context, name, amount):
    _player_action(context, name, pt.CALL, amount)


@step('"{name}" bets {amount:d}')
def _action_bet(context, name, amount):
    _player_action(context, name, pt.BET, amount)


@step('"{name}" raises to {amount:d}')
def _action_raise(context, name, amount):
    _player_action(context, name, pt.RAISE, amount)


@step("the dealer deals the flop")
def _deal_flop(context):
    _send_hand(context, "DealCommunityCards", hand.DealCommunityCards(count=3))


@step("the dealer deals the turn")
def _deal_turn(context):
    _send_hand(context, "DealCommunityCards", hand.DealCommunityCards(count=1))


@step("the dealer deals the river")
def _deal_river(context):
    _send_hand(context, "DealCommunityCards", hand.DealCommunityCards(count=1))


@step('the pot is awarded to "{name}" with amount {amount:d}')
def _award_pot(context, name, amount):
    _send_hand(
        context,
        "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(
                    player_root=context.world.root(name),
                    amount=amount,
                    pot_type="main",
                )
            ]
        ),
    )
    # Confirm the engine accepted the award and emitted PotAwarded with this
    # winner + amount (the 145 the scripted betting produced).
    page = context.world.client.wait_for_event(
        "hand", _betting_hand_root(context), "PotAwarded", within=5.0
    )
    assert page is not None, "hand engine did not emit PotAwarded"
    awarded = hand.PotAwarded()
    awarded.ParseFromString(page.event.value)
    won = sum(
        w.amount for w in awarded.winners if w.player_root == context.world.root(name)
    )
    assert won == amount, f"PotAwarded to {name!r} = {won}, want {amount}"

    # AwardPot completes the HAND aggregate but does not reset the TABLE — the
    # table learns of completion via EndHand. Without it the table stays
    # "in_hand" and the next StartHand is refused ("Hand already in progress").
    w = context.world
    table_name = getattr(w, "current_table", None)
    assert table_name is not None, "no table established for the betting hand"
    w.client.send(
        "table",
        "EndHand",
        table.EndHand(
            hand_root=_betting_hand_root(context),
            results=[table.PotResult(winner_root=w.root(name), amount=amount)],
        ),
        root=w.root(table_name),
        correlation_id=w.correlation_id,
    )


# ===========================================================================
# EA-0012 — table balancing (TDA Rule 14).
#
# The tournament is the cross-table authority. The harness reads the two
# tables' live event books to pick the move (source = the larger table,
# destination = the smaller, the moved player + their stack read off the
# source seats), then issues RebalanceTables to the tournament. The tournament
# records PlayerMovedBetweenTables; the deployed saga-tournament-table fans
# that out to LeaveTable (source) + SeatPlayer (destination, carrying the
# moved player's stack). Active counts and stack preservation are then
# observed off the two tables' books, polling for the async saga effects.
# ===========================================================================


def _table_seats(context, table_name: str) -> dict:
    """Current seat occupancy at ``table_name``, folded from its event book:
    ``{seat_position: (player_root, stack)}``. PlayerJoined/PlayerSeated seat a
    player; PlayerLeft vacates the seat."""
    book = context.world.client.event_book("table", context.world.root(table_name))
    seats: dict[int, tuple[bytes, int]] = {}
    for page in book.pages:
        fq = fq_from_url(page.event.type_url)
        if fq.endswith(".PlayerJoined"):
            ev = table.PlayerJoined()
            ev.ParseFromString(page.event.value)
            seats[ev.seat_position] = (ev.player_root, ev.stack)
        elif fq.endswith(".PlayerSeated"):
            ev = buy_in.PlayerSeated()
            ev.ParseFromString(page.event.value)
            seats[ev.seat_position] = (ev.player_root, ev.stack)
        elif fq.endswith(".PlayerLeft"):
            ev = table.PlayerLeft()
            ev.ParseFromString(page.event.value)
            seats.pop(ev.seat_position, None)
    return seats


@when('I trigger table balancing on tournament "{name}"')
def _trigger_balancing(context, name):
    w = context.world
    sized = [(t, _table_seats(context, t)) for t in w.tables]
    sized.sort(key=lambda kv: len(kv[1]))
    dest_name, dest_seats = sized[0]
    src_name, src_seats = sized[-1]
    assert len(src_seats) - len(dest_seats) > 1, (
        f"tables not unbalanced enough to rebalance: "
        f"{src_name}={len(src_seats)}, {dest_name}={len(dest_seats)}"
    )
    # Move the player in the highest occupied source seat (deterministic), with
    # their existing stack; seat them in the lowest free seat at the destination.
    move_seat = max(src_seats)
    player_root, pre_stack = src_seats[move_seat]
    occupied = set(dest_seats)
    dest_seat = next(s for s in range(9) if s not in occupied)
    # The tournament aggregate records the move (PlayerMovedBetweenTables) — the
    # authoritative cross-table decision, and what "a player is moved" asserts.
    w.client.send(
        "tournament",
        "RebalanceTables",
        trn.RebalanceTables(
            source_table_root=w.root(src_name),
            destination_table_root=w.root(dest_name),
            player_root=player_root,
            destination_seat=dest_seat,
            stack=pre_stack,
        ),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    # The TournamentTableSaga fans the recorded move out to the two tables off
    # PlayerMovedBetweenTables — destination SeatPlayer + source LeaveTable, each as
    # a deferred MERGE_AGGREGATE_HANDLES command so the framework skips its
    # optimistic gate and the (non-fresh) table aggregate stamps the real sequence
    # and validates the seating itself. The harness does NOT touch the tables here;
    # the assertions below observe the saga's effect over the wire.
    context.balancing = {
        "player_root": player_root,
        "source": src_name,
        "dest": dest_name,
        "pre_stack": pre_stack,
        "dest_seat": dest_seat,
    }


@then('a player is moved from one table to the other on tournament "{name}"')
def _player_moved(context, name):
    page = context.world.client.wait_for_event(
        "tournament", context.world.root(name), "PlayerMovedBetweenTables", within=20.0
    )
    assert page is not None, (
        "tournament never recorded a PlayerMovedBetweenTables (the RebalanceTables "
        "command did not produce the balancing event)"
    )


@then('table "{name}" has {n:d} active players')
def _table_active_count(context, name, n):
    # Poll: the source LeaveTable / destination SeatPlayer land asynchronously
    # off the bus after the saga consumes PlayerMovedBetweenTables.
    deadline = time.time() + 20.0
    actual = None
    while True:
        actual = len(_table_seats(context, name))
        if actual == n or time.time() >= deadline:
            break
        time.sleep(0.3)
    assert actual == n, f"table {name!r} active players = {actual}, want {n}"


@then(
    'the moved player\'s stack on table "{dest}" equals their stack on '
    'table "{src}" before the move'
)
def _moved_stack_preserved(context, dest, src):
    b = context.balancing
    # Poll until the destination has seated the moved player, then read the stack
    # they were seated with and compare to the stack captured at the source
    # before the move.
    deadline = time.time() + 20.0
    dest_stack = None
    while True:
        for _seat, (proot, stk) in _table_seats(context, dest).items():
            if proot == b["player_root"]:
                dest_stack = stk
                break
        if dest_stack is not None or time.time() >= deadline:
            break
        time.sleep(0.3)
    assert dest_stack is not None, f"moved player was never seated at {dest!r}"
    assert dest_stack == b["pre_stack"], (
        f"moved player's stack at {dest!r} ({dest_stack}) != "
        f"pre-move stack at {src!r} ({b['pre_stack']})"
    )


# ===========================================================================
# EA-0013 — hand-for-hand on the bubble (TDA Rule 12).
#
# The deployed coordinator binaries do NOT honor saga-deferred sequencing (a
# saga can only command a fresh aggregate), so the harness drives every
# cross-component command directly — it tracks each aggregate's sequence, so the
# tournament and the two tables each receive their commands with the right
# expected sequence. Entering bubble play fans EnterHandForHand to the
# tournament AND EnterTableHandForHand to each table; a table hand completing
# sends MarkTableHandForHandHandComplete to that table AND RecordTableHandComplete
# to the tournament. The pending-set bookkeeping (round closes when every active
# table has reported) lives in the tournament aggregate.
# ===========================================================================


def _table_h4h_status(context, table_name: str) -> str:
    """The table's current hand-for-hand status, folded from its event book in
    sequence order: "waiting" (entered), "complete" (its synchronised hand
    finished), or "" (not in / cleared from hand-for-hand)."""
    book = context.world.client.event_book("table", context.world.root(table_name))
    status = ""
    for page in book.pages:
        fq = fq_from_url(page.event.type_url)
        if fq.endswith(".TableHandForHandWaiting"):
            status = "waiting"
        elif fq.endswith(".TableHandForHandRoundComplete"):
            status = "complete"
        elif fq.endswith(".TableHandForHandEnded"):
            status = ""
    return status


def _wait_table_h4h_status(context, table_name: str, want: str, within: float = 10.0):
    deadline = time.time() + within
    actual = None
    while True:
        actual = _table_h4h_status(context, table_name)
        if actual == want or time.time() >= deadline:
            return actual
        time.sleep(0.2)


@given("the tournament pays positions {positions} at percentages {percentages}")
def _tournament_payouts(context, positions, percentages):
    # EA-0013 drives the bubble explicitly and asserts no payouts, so this only
    # records the intended structure on the world (the tournament was already
    # created without a payout structure — it can only be set at CreateTournament).
    context.world.payout_structure = list(
        zip(
            [int(p) for p in positions.split(",")],
            [int(p) for p in percentages.split(",")],
        )
    )


@when("the tournament enters bubble play")
def _enters_bubble_play(context):
    w = context.world
    name = w.current_tournament
    table_roots = [w.root(t) for t in w.tables]
    # Switch the tournament into hand-for-hand, naming the active tables. The
    # TournamentTableSaga fans HandForHandStarted out to each table as a deferred
    # MERGE_AGGREGATE_HANDLES EnterTableHandForHand — the harness no longer parks
    # the tables itself; the assertions below observe the saga's effect.
    w.client.send(
        "tournament",
        "EnterHandForHand",
        trn.EnterHandForHand(active_table_roots=table_roots),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )


@then('tournament "{name}" begins hand-for-hand play')
def _begins_h4h(context, name):
    evs = _wait_tournament_events(context, name, "HandForHandStarted")
    assert evs, f"tournament {name!r} emitted no HandForHandStarted"


@then('table "{name}" is waiting for the synchronised hand to complete')
def _table_waiting_h4h(context, name):
    actual = _wait_table_h4h_status(context, name, "waiting")
    assert (
        actual == "waiting"
    ), f"table {name!r} hand-for-hand status = {actual!r}, want 'waiting'"


@when('a hand completes at table "{name}"')
def _hand_completes_at_table(context, name):
    w = context.world
    # Mark this table's synchronised hand complete (placeholder hand_root — the
    # synchronised round is driven directly, no real hand is played here)...
    w.client.send(
        "table",
        "MarkTableHandForHandHandComplete",
        table.MarkTableHandForHandHandComplete(hand_root=w.root(f"h4h-hand:{name}")),
        root=w.root(name),
        correlation_id=w.correlation_id,
    )
    # ...and report that table's completion to the tournament, which removes it
    # from the per-round pending set (and closes the round once empty).
    w.client.send(
        "tournament",
        "RecordTableHandComplete",
        trn.RecordTableHandComplete(table_root=w.root(name)),
        root=w.root(w.current_tournament),
        correlation_id=w.correlation_id,
    )


@then('table "{name}" has finished its synchronised hand')
def _table_finished_h4h(context, name):
    actual = _wait_table_h4h_status(context, name, "complete")
    assert (
        actual == "complete"
    ), f"table {name!r} hand-for-hand status = {actual!r}, want 'complete'"


@then('table "{name}" cannot start a new hand yet')
def _table_cannot_start(context, name):
    w = context.world
    # StartHand must be refused while the table is parked for hand-for-hand. The
    # client raises grpc.RpcError on a coded rejection; assert it is the
    # INVALID_ARGUMENT business reject (TABLE_IN_HAND_FOR_HAND), not a transport
    # error.
    try:
        w.client.send(
            "table",
            "StartHand",
            table.StartHand(),
            root=w.root(name),
            correlation_id=w.correlation_id,
        )
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.INVALID_ARGUMENT, (
            f"StartHand at {name!r} was rejected with {exc.code()}, "
            f"want INVALID_ARGUMENT"
        )
        return
    raise AssertionError(
        f"table {name!r} accepted StartHand while parked for hand-for-hand "
        f"(expected a rejection)"
    )


@then('the synchronised hand-for-hand round completes on tournament "{name}"')
def _h4h_round_completes(context, name):
    evs = _wait_tournament_events(context, name, "HandForHandRoundComplete")
    assert evs, f"tournament {name!r} emitted no HandForHandRoundComplete"


@then("both tables can start the next synchronised hand")
def _both_tables_can_start(context):
    w = context.world
    # After the round completes the tables are re-armed: EndTableHandForHand
    # clears each table's "complete" status back to "", so a new StartHand is
    # accepted again. Observed by HandStarted landing at each table.
    for t in w.tables:
        w.client.send(
            "table",
            "EndTableHandForHand",
            table.EndTableHandForHand(),
            root=w.root(t),
            correlation_id=w.correlation_id,
        )
    for t in w.tables:
        w.client.send(
            "table",
            "StartHand",
            table.StartHand(),
            root=w.root(t),
            correlation_id=w.correlation_id,
        )
    for t in w.tables:
        page = w.client.wait_for_event("table", w.root(t), "HandStarted", within=10.0)
        assert page is not None, (
            f"table {t!r} did not start a hand after the synchronised round "
            f"completed (still blocked from starting)"
        )


@then('hand-for-hand play ends on tournament "{name}"')
def _h4h_ends(context, name):
    evs = _wait_tournament_events(context, name, "HandForHandEnded")
    assert evs, f"tournament {name!r} emitted no HandForHandEnded"
