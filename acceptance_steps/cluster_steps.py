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

from behave import given, step, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
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


@step('the hand at table "{name}" is awarded to "{who}"')
def _award_hand(context, name, who):
    w = context.world
    w.client.send(
        "hand",
        "AwardPot",
        hand.AwardPot(awards=[hand.PotAward(player_root=w.root(who), amount=0)]),
        root=_hand_root(context),
        correlation_id=w.correlation_id,
    )


@then('tournament "{name}" has {count:d} registered players')
def _has_registered(context, name, count):
    enrolled = _tournament_events(context, name, "TournamentPlayerEnrolled")
    assert len(enrolled) == count, f"expected {count} enrolled, got {len(enrolled)}"


@then('tournament "{name}" has total_prize_pool {amount:d}')
def _has_prize_pool(context, name, amount):
    enrolled = _tournament_events(context, name, "TournamentPlayerEnrolled")
    pool = sum(e.fee_paid for e in enrolled)
    assert pool == amount, f"expected prize pool {amount}, got {pool}"


@then('tournament "{name}" has players_remaining {count:d}')
def _players_remaining(context, name, count):
    enrolled = len(_tournament_events(context, name, "TournamentPlayerEnrolled"))
    eliminated = len(_tournament_events(context, name, "PlayerEliminated"))
    remaining = enrolled - eliminated
    assert remaining == count, f"expected {count} remaining, got {remaining}"


@then('tournament "{name}" has status "{status}"')
def _tournament_status(context, name, status):
    if status == "Completed":
        done = _tournament_events(context, name, "TournamentCompleted")
        assert done, "tournament is not Completed (no TournamentCompleted event)"
    else:
        raise AssertionError(f"status assertion for {status!r} not implemented")


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


@then('player "{name}" has bankroll {amount:d}')
def _player_bankroll(context, name, amount):
    book = _player_book_resilient(context, name)
    balance = None
    for page in book.pages:
        if fq_from_url(page.event.type_url).endswith(".FundsDeposited"):
            ev = player.FundsDeposited()
            ev.ParseFromString(page.event.value)
            balance = ev.new_balance.amount
    assert balance == amount, f"bankroll = {balance}, want {amount}"
