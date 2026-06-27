"""Table aggregate unit steps (create / join / leave families).

Drives the generated TableAggregate wiring through the FFI core: "exists" /
"is seated" Givens seed a prior-events history the core folds to rebuild state;
When steps dispatch a command; Then steps assert the emitted event or the coded
rejection. Cross-component scenarios (tournament balancing, hand lifecycle,
busts, reseating) are tagged @wip until their components are ported.
"""

from __future__ import annotations

from behave import given, then, use_step_matcher, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from angzarr_poker.table.aggregate.handler import TableAggregate
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "table"
P = "io.angzarr.examples.v1."  # FQ prefix for table commands/events

_VARIANTS = {
    "Texas Hold'em": pt.TEXAS_HOLDEM,
    "Five Card Draw": pt.FIVE_CARD_DRAW,
    "Omaha": pt.OMAHA,
}

# Defaults for a seeded "a table exists" history (mirror the legacy fixtures).
_DEF = dict(small_blind=5, big_blind=10, min_buy_in=200, max_buy_in=1000, max_players=9)


def _table_root(context) -> bytes:
    """The root of the table the un-named "the table" steps act on. Each table is
    a distinct aggregate keyed by ``uuid_for(name)``; the most recently named
    table is current, so single-table scenarios need no name in the When/Then and
    multi-table scenarios (Source/Dest) switch by naming the next table. Defaults
    to b"" for scenarios that never name a table (e.g. create-on-empty)."""
    return getattr(context, "current_table_root", b"")


def _use_table(context, name) -> bytes:
    """Make ``name`` the current table and return its root."""
    root = uuid_for(name)
    context.current_table_root = root
    return root


def _pid_root(pid: str) -> bytes:
    """A player's root id, or empty bytes when the scenario passes "" to assert
    the player_root-required guard. ``uuid_for("")`` would hash to non-empty
    bytes, so the empty-identity case is mapped to ``b""`` explicitly."""
    return uuid_for(pid) if pid else b""


def _seed_table(context, name, **overrides):
    cfg = dict(_DEF, **overrides)
    context.world.seed_event(
        DOMAIN,
        P + "TableCreated",
        table.TableCreated(
            table_name=name,
            game_variant=pt.TEXAS_HOLDEM,
            action_timeout_seconds=30,
            **cfg,
        ),
        root=_use_table(context, name),
    )


def _seed_seat(context, pid, position, stack=500):
    context.world.seed_event(
        DOMAIN,
        P + "PlayerJoined",
        table.PlayerJoined(
            player_root=uuid_for(pid),
            seat_position=position,
            buy_in_amount=stack,
            stack=stack,
        ),
        root=_table_root(context),
    )


# --- Given: seed prior state ---


@given("the table has not yet been created")
def _given_uncreated(context):
    pass  # fresh World — no prior history


@given('a table "{name}" exists')
def _given_table_exists(context, name):
    _seed_table(context, name)


@given('a table "{name}" exists with a minimum buy-in of {n:d}')
def _given_table_min_buyin(context, name, n):
    _seed_table(context, name, min_buy_in=n)


@given('a table "{name}" exists with a maximum of {n:d} players')
def _given_table_max_players(context, name, n):
    _seed_table(context, name, max_players=n)


@given('a table "{name}" exists with blinds {sb:d}/{bb:d}')
def _given_table_blinds(context, name, sb, bb):
    _seed_table(context, name, small_blind=sb, big_blind=bb)


@given('player "{pid}" is seated at position {pos:d}')
def _given_seated(context, pid, pos):
    _seed_seat(context, pid, pos)


@given('player "{pid}" is seated at position {pos:d} with a {stack:d}-chip stack')
def _given_seated_stack(context, pid, pos, stack):
    _seed_seat(context, pid, pos, stack)


@given('player "{pid}" is seated at position {pos:d} with an {stack:d}-chip stack')
def _given_seated_stack_an(context, pid, pos, stack):
    """The "an" variant for stacks beginning with a vowel sound (e.g. an
    800-chip stack); behave's literal "a " matcher would not otherwise match."""
    _seed_seat(context, pid, pos, stack)


# Regex matcher (scoped) so this tolerates the column-alignment whitespace some
# multi-table scenarios put between the player name and "is" (e.g.
# 'player "Ivy"   is seated at position 3 of "Semi-2"').
use_step_matcher("re")


@given(
    r'player "(?P<pid>[^"]+)"\s+is seated at position (?P<pos>\d+) of "(?P<name>[^"]+)"'
)
def _given_seated_of(context, pid, pos, name):
    """Seat at a named table (multi-table scenarios): switch the current table to
    ``name`` and seed there, so a later Source/Dest aggregate is addressed by its
    own root rather than colliding with the previously-named table."""
    _use_table(context, name)
    _seed_seat(context, pid, int(pos))


use_step_matcher("parse")


@given("the {which} table has the dealer button at seat {seat:d}")
def _given_button(context, which, seat):
    """Seed the current table's dealer position (a played-then-ended hand leaves
    ``dealer_position`` set with the table idle). ``which`` ("source"/"the") is
    descriptive only — the button lands on the current table."""
    hand = uuid_for("button-hand")
    context.world.seed_event(
        DOMAIN,
        P + "HandStarted",
        table.HandStarted(hand_root=hand, hand_number=1, dealer_position=seat),
        root=_table_root(context),
    )
    context.world.seed_event(
        DOMAIN,
        P + "HandEnded",
        table.HandEnded(hand_root=hand),
        root=_table_root(context),
    )


@given("the first hand at the table has begun")
def _given_hand_begun(context):
    context.world.seed_event(
        DOMAIN,
        P + "HandStarted",
        table.HandStarted(
            hand_root=uuid_for("hand-1"), hand_number=1, dealer_position=0
        ),
        root=_table_root(context),
    )


# --- When: dispatch a command ---


@when('a {variant} table named "{name}" is created with:')
def _when_create(context, variant, name):
    row = context.table[0]
    cmd = table.CreateTable(
        table_name=name,
        game_variant=_VARIANTS[variant],
        small_blind=int(row["small_blind"]),
        big_blind=int(row["big_blind"]),
        min_buy_in=int(row["min_buy_in"]),
        max_buy_in=int(row["max_buy_in"]),
        max_players=int(row["max_players"]),
    )
    # Table identity is the aggregate root, not the display name. A create that
    # follows an "a table exists" Given targets that already-established root (so
    # "create twice" is refused even when the names differ); a fresh create mints
    # identity from its own name.
    existing = getattr(context, "current_table_root", None)
    root = existing if existing is not None else _use_table(context, name)
    context.world.dispatch(DOMAIN, P + "CreateTable", cmd, root=root)


@when('player "{pid}" joins the table at seat {seat:d} with a buy-in of {amt:d}')
def _when_join_seat(context, pid, seat, amt):
    cmd = table.JoinTable(
        player_root=_pid_root(pid), preferred_seat=seat, buy_in_amount=amt
    )
    context.world.dispatch(DOMAIN, P + "JoinTable", cmd, root=_table_root(context))


@when('player "{pid}" joins the table at any available seat with a buy-in of {amt:d}')
def _when_join_any(context, pid, amt):
    cmd = table.JoinTable(
        player_root=uuid_for(pid), preferred_seat=-1, buy_in_amount=amt
    )
    context.world.dispatch(DOMAIN, P + "JoinTable", cmd, root=_table_root(context))


@when('player "{pid}" leaves the table')
def _when_leave(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "LeaveTable",
        table.LeaveTable(player_root=_pid_root(pid)),
        root=_table_root(context),
    )


# --- Then: assert emitted event or rejection ---


@then('the table is named "{name}"')
def _then_named(context, name):
    ev = context.world.emitted(P + "TableCreated", table.TableCreated())
    assert ev.table_name == name, f"table_name = {ev.table_name!r}, want {name!r}"


@then("the table is configured as a {variant} game")
def _then_variant(context, variant):
    ev = context.world.emitted(P + "TableCreated", table.TableCreated())
    assert ev.game_variant == _VARIANTS[variant], f"variant = {ev.game_variant}"


@then("the blinds are {sb:d}/{bb:d}")
def _then_blinds(context, sb, bb):
    ev = context.world.emitted(P + "TableCreated", table.TableCreated())
    assert (ev.small_blind, ev.big_blind) == (sb, bb)


@then("the create-table is refused because the table already exists")
def _then_create_dup(context):
    assert_rejected(context, "TABLE_EXISTS")


def _seat_result(context):
    """The seat-grant event from the last dispatch, whether it came from join
    (PlayerJoined) or the PM-orchestrated path (PlayerSeated) — both carry
    seat_position + stack."""
    for page in context.world.emitted_pages():
        fq = page.event.type_url.rsplit("/", 1)[-1]
        if fq == P + "PlayerJoined":
            return table.PlayerJoined.FromString(page.event.value)
        if fq == P + "PlayerSeated":
            return buy_in.PlayerSeated.FromString(page.event.value)
    raise AssertionError(f"no seat event; got {context.world.emitted_fqs()}")


@then('player "{pid}" is seated at position {pos:d} with a {stack:d}-chip stack')
def _then_seated_stack(context, pid, pos, stack):
    ev = _seat_result(context)
    assert ev.seat_position == pos, f"seat = {ev.seat_position}, want {pos}"
    assert ev.stack == stack, f"stack = {ev.stack}, want {stack}"


@then('player "{pid}" is seated at position {pos:d}')
def _then_seated(context, pid, pos):
    ev = _seat_result(context)
    assert ev.seat_position == pos, f"seat = {ev.seat_position}, want {pos}"


@then("the join is refused because seat {seat:d} is already occupied")
def _then_join_occupied(context, seat):
    assert_rejected(context, "SEAT_OCCUPIED")


@then("the join is refused because the player is already seated")
def _then_join_dup(context):
    assert_rejected(context, "PLAYER_ALREADY_SEATED")


@then(
    "the join is refused because the buy-in of {n:d} is below the table minimum of {m:d}"
)
def _then_join_below_min(context, n, m):
    assert_rejected(context, "INVALID_ARGUMENT")


@then(
    "the join is refused because the buy-in of {n:d} is above the table maximum of {m:d}"
)
def _then_join_above_max(context, n, m):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the join is refused because the table is full")
def _then_join_full(context):
    assert_rejected(context, "TABLE_FULL")


@then("the join is refused because the table does not exist")
def _then_join_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


@then('player "{pid}" cashes out {n:d} chips')
def _then_cashes_out(context, pid, n):
    ev = context.world.emitted(P + "PlayerLeft", table.PlayerLeft())
    assert ev.chips_cashed_out == n, f"cashed_out = {ev.chips_cashed_out}, want {n}"


@then("the leave is refused because a hand is in progress")
def _then_leave_in_hand(context):
    assert_rejected(context, "HAND_IN_PROGRESS")


@then("the leave is refused because the player is not seated")
def _then_leave_not_seated(context):
    assert_rejected(context, "PLAYER_NOT_SEATED")


# --- hand lifecycle: start / end ---

_HAND_ROOT = uuid_for("hand-1")  # the root _given_hand_begun seeds


@given("hand {n:d} was played with the dealer at seat {seat:d} and has ended")
def _given_hand_played(context, n, seat):
    hand_root = uuid_for(f"hand-{n}")
    context.world.seed_event(
        DOMAIN,
        P + "HandStarted",
        table.HandStarted(hand_root=hand_root, hand_number=n, dealer_position=seat),
        root=_table_root(context),
    )
    context.world.seed_event(
        DOMAIN,
        P + "HandEnded",
        table.HandEnded(hand_root=hand_root),
        root=_table_root(context),
    )


@when("the next hand at the table begins")
@when("the first hand at the table begins")
def _when_start_hand(context):
    context.world.dispatch(
        DOMAIN, P + "StartHand", table.StartHand(), root=_table_root(context)
    )


@when('the hand ends with "{pid}" winning {amt:d}')
def _when_end_hand_winner(context, pid, amt):
    cmd = table.EndHand(
        hand_root=_HAND_ROOT,
        results=[table.PotResult(winner_root=uuid_for(pid), amount=amt)],
    )
    context.world.dispatch(DOMAIN, P + "EndHand", cmd, root=_table_root(context))


@when("the hand ends with the following results:")
def _when_end_hand_results(context):
    cmd = table.EndHand(hand_root=_HAND_ROOT)
    for row in context.table:
        cmd.results.add(winner_root=uuid_for(row["player"]), amount=int(row["change"]))
    context.world.dispatch(DOMAIN, P + "EndHand", cmd, root=_table_root(context))


@then("the table is on hand number {n:d} with {p:d} active players")
def _then_hand_number_active(context, n, p):
    ev = context.world.emitted(P + "HandStarted", table.HandStarted())
    assert ev.hand_number == n, f"hand_number = {ev.hand_number}, want {n}"
    assert len(ev.active_players) == p, f"active = {len(ev.active_players)}, want {p}"


@then("the table is on hand number {n:d}")
def _then_hand_number(context, n):
    ev = context.world.emitted(P + "HandStarted", table.HandStarted())
    assert ev.hand_number == n, f"hand_number = {ev.hand_number}, want {n}"


@then("the dealer is at seat {seat:d}")
def _then_dealer_seat(context, seat):
    ev = context.world.emitted(P + "HandStarted", table.HandStarted())
    assert ev.dealer_position == seat, f"dealer = {ev.dealer_position}, want {seat}"


@then("the start-hand is refused because there are not enough players")
def _then_start_few(context):
    assert_rejected(context, "NOT_ENOUGH_PLAYERS")


@then("the start-hand is refused because a hand is already in progress")
def _then_start_in_progress(context):
    assert_rejected(context, "HAND_IN_PROGRESS")


@then("the start-hand is refused because the table does not exist")
def _then_start_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


@then('player "{pid}"\'s stack change is {delta}')
def _then_stack_change(context, pid, delta):
    ev = context.world.emitted(P + "HandEnded", table.HandEnded())
    key = uuid_for(pid).hex()
    assert ev.stack_changes.get(key) == int(
        delta
    ), f"stack change for {pid} = {ev.stack_changes.get(key)}, want {delta}"


@then("the end-hand is refused because no hand is in progress")
def _then_end_no_hand(context):
    assert_rejected(context, "NO_HAND_IN_PROGRESS")


@then("the end-hand is refused because the hand identity does not match")
def _then_end_mismatch(context):
    assert_rejected(context, "HAND_ROOT_MISMATCH")


@then("the end-hand is refused because the table does not exist")
def _then_end_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


# --- PM-orchestrated seating / rebuy ---
#
# SeatPlayer is the process-manager path: a seating FAILURE is an emitted
# SeatingRejected EVENT (so the PM can compensate), not a coded rejection — only
# a nonexistent table is a hard coded rejection. AddRebuyChips rejects with coded
# errors like a normal command.


def _assert_seating_rejected(context, reason_keyword=None):
    fqs = context.world.emitted_fqs()
    assert P + "SeatingRejected" in fqs, f"expected SeatingRejected event; got {fqs}"
    if reason_keyword is not None:
        ev = context.world.emitted(P + "SeatingRejected", buy_in.SeatingRejected())
        assert (
            reason_keyword.lower() in ev.reason.lower()
        ), f"SeatingRejected reason = {ev.reason!r}, want keyword {reason_keyword!r}"


@when(
    'player "{pid}" is seated at position {seat:d} with reservation "{res}" for {amt:d} chips'
)
def _when_seat_player(context, pid, seat, res, amt):
    cmd = buy_in.SeatPlayer(
        player_root=_pid_root(pid), reservation_id=uuid_for(res), seat=seat, amount=amt
    )
    context.world.dispatch(DOMAIN, P + "SeatPlayer", cmd, root=_table_root(context))


@when(
    'player "{pid}" is seated at any available seat with reservation "{res}" for {amt:d} chips'
)
def _when_seat_player_any(context, pid, res, amt):
    cmd = buy_in.SeatPlayer(
        player_root=uuid_for(pid), reservation_id=uuid_for(res), seat=-1, amount=amt
    )
    context.world.dispatch(DOMAIN, P + "SeatPlayer", cmd, root=_table_root(context))


@then("the seating is rejected because the amount is below the table minimum")
def _then_seat_below_min(context):
    _assert_seating_rejected(context, "at least")


@then("the seating is rejected because the amount is above the table maximum")
def _then_seat_above_max(context):
    _assert_seating_rejected(context, "maximum")


@then("the seating is rejected because the seat is already occupied")
def _then_seat_occupied(context):
    _assert_seating_rejected(context, "occupied")


@then("the seating is rejected because the player is already seated")
def _then_seat_dup(context):
    _assert_seating_rejected(context, "already seated")


@then("the seating is rejected because the table is full")
def _then_seat_full(context):
    _assert_seating_rejected(context, "full")


@then("the seating is rejected because a player identity is required")
def _then_seat_no_player(context):
    _assert_seating_rejected(context, "player_root")


@then("the seating is rejected because the seat is out of range")
def _then_seat_out_of_range(context):
    _assert_seating_rejected(context, "Invalid seat")


@then("the seat-player is refused because the table does not exist")
def _then_seat_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


@when('player "{pid}" re-buys {amt:d} chips with reservation "{res}" at seat {seat:d}')
def _when_rebuy(context, pid, amt, res, seat):
    cmd = rebuy.AddRebuyChips(
        player_root=_pid_root(pid), reservation_id=uuid_for(res), seat=seat, amount=amt
    )
    context.world.dispatch(DOMAIN, P + "AddRebuyChips", cmd, root=_table_root(context))


@then(
    'player "{pid}" at seat {seat:d} has a stack of {total:d} after adding {amt:d} chips'
)
def _then_rebuy_added(context, pid, seat, total, amt):
    ev = context.world.emitted(P + "RebuyChipsAdded", rebuy.RebuyChipsAdded())
    assert ev.seat == seat, f"seat = {ev.seat}, want {seat}"
    assert ev.amount == amt, f"amount = {ev.amount}, want {amt}"
    assert ev.new_stack == total, f"new_stack = {ev.new_stack}, want {total}"


@then("the re-buy is refused because the player is not seated")
def _then_rebuy_not_seated(context):
    assert_rejected(context, "PLAYER_NOT_SEATED")


@then("the re-buy is refused because the seat does not match the player's seat")
def _then_rebuy_seat_mismatch(context):
    assert_rejected(context, "SEAT_MISMATCH")


@then("the re-buy is refused because the amount must be positive")
def _then_rebuy_amount(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the re-buy is refused because the table does not exist")
def _then_rebuy_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


@then("the re-buy is refused because a player identity is required")
def _then_rebuy_no_player(context):
    assert_rejected(context, "INVALID_ARGUMENT")


# =============================================================================
# State reconstruction + Phase-2 validation
#   EU-0119/0120 (rebuild), EU-0531/0532 (create validation),
#   EU-0535/0537/0538 (join/leave guards), EU-0541/0542 (end-hand lifecycle),
#   EU-0543/0544 (blind placement), EU-0545 (table-id derivation)
# =============================================================================
#
# Reconstruction scenarios carry no When: they seed a prior-events history and
# assert the rebuilt TableState. The FFI seam exposes no state query, so we fold
# the seeded (and, for lifecycle scenarios, the just-emitted) events through the
# real ``TableAggregate`` appliers — the same fold the core runs — and assert on
# the resulting proto state.

_EVENT_APPLIERS = {
    "TableCreated": (table.TableCreated, "apply_table_created"),
    "PlayerJoined": (table.PlayerJoined, "apply_player_joined"),
    "PlayerLeft": (table.PlayerLeft, "apply_player_left"),
    "PlayerSatOut": (table.PlayerSatOut, "apply_player_sat_out"),
    "PlayerSatIn": (table.PlayerSatIn, "apply_player_sat_in"),
    "HandStarted": (table.HandStarted, "apply_hand_started"),
    "HandEnded": (table.HandEnded, "apply_hand_ended"),
    "ChipsAdded": (table.ChipsAdded, "apply_chips_added"),
}


def _rebuild_state(context) -> table.TableState:
    """Fold the current table's seeded prior events through the TableAggregate
    appliers into a fresh proto ``TableState`` — mirrors the core's rebuild."""
    agg = TableAggregate()
    state = table.TableState()
    for page in context.world.prior_pages(DOMAIN, _table_root(context)):
        short = page.event.type_url.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        entry = _EVENT_APPLIERS.get(short)
        if entry is None:
            continue
        cls, method = entry
        getattr(agg, method)(state, cls.FromString(page.event.value))
    return state


# --- When: end-hand mismatch / start-then-end lifecycle ---


@when("the hand ends but the hand identity does not match the one in progress")
def _when_end_hand_wrong_root(context):
    cmd = table.EndHand(
        hand_root=uuid_for("not-the-current-hand"),
        results=[table.PotResult(winner_root=uuid_for("player-1"), amount=50)],
    )
    context.world.dispatch(DOMAIN, P + "EndHand", cmd, root=_table_root(context))


@when('a hand is started and then ended with "{pid}" winning {amt:d}')
def _when_start_then_end(context, pid, amt):
    """Run StartHand then EndHand in sequence, reusing the emitted hand_root and
    folding each emitted event back into the history so the EndHand command (and
    the rebuilt-state Then steps) observe the lifecycle progress."""
    root = _table_root(context)
    context.world.dispatch(DOMAIN, P + "StartHand", table.StartHand(), root=root)
    started = context.world.emitted(P + "HandStarted", table.HandStarted())
    context.world.fold_emitted(DOMAIN, root)
    cmd = table.EndHand(
        hand_root=started.hand_root,
        results=[table.PotResult(winner_root=uuid_for(pid), amount=amt)],
    )
    context.world.dispatch(DOMAIN, P + "EndHand", cmd, root=root)
    context.world.fold_emitted(DOMAIN, root)


# --- Then: rebuilt-state assertions ---


@then("the table has {n:d} seated players")
def _then_seated_count(context, n):
    state = _rebuild_state(context)
    assert len(state.seats) == n, f"seated = {len(state.seats)}, want {n}"


@then('seat {seat:d} is occupied by "{pid}"')
def _then_seat_occupied_by(context, seat, pid):
    state = _rebuild_state(context)
    occupant = next((s for s in state.seats if s.position == seat), None)
    assert occupant is not None, f"seat {seat} is empty"
    assert occupant.player_root == uuid_for(
        pid
    ), f"seat {seat} occupant = {occupant.player_root!r}, want {uuid_for(pid)!r}"


@then("the table is waiting for a hand to start")
def _then_waiting(context):
    state = _rebuild_state(context)
    assert state.status == "waiting", f"status = {state.status!r}, want 'waiting'"


@then("a hand is in progress at the table")
def _then_hand_in_progress(context):
    state = _rebuild_state(context)
    assert state.status == "in_hand", f"status = {state.status!r}, want 'in_hand'"


@then("the table has played {n:d} hand")
def _then_played_hands(context, n):
    state = _rebuild_state(context)
    assert state.hand_count == n, f"hand_count = {state.hand_count}, want {n}"


@then("no hand is currently in progress at the table")
def _then_no_hand_in_progress(context):
    state = _rebuild_state(context)
    assert state.status != "in_hand", f"status = {state.status!r}, want not in_hand"
    assert (
        state.current_hand_root == b""
    ), f"current_hand_root = {state.current_hand_root!r}, want empty"


@then('the table carries the identity derived from its name "{name}"')
def _then_identity_from_name(context, name):
    state = _rebuild_state(context)
    expected = f"table_{name}"
    assert (
        state.table_id == expected
    ), f"table_id = {state.table_id!r}, want {expected!r}"


# --- Then: heads-up / 3-handed blind placement (emitted HandStarted) ---


@then("the dealer is the small blind for the heads-up hand")
def _then_dealer_is_sb(context):
    ev = context.world.emitted(P + "HandStarted", table.HandStarted())
    assert ev.small_blind_position == ev.dealer_position, (
        f"SB = {ev.small_blind_position}, dealer = {ev.dealer_position}; "
        "heads-up dealer must post the small blind"
    )


@then("the small blind is in a different seat from the dealer")
def _then_sb_differs(context):
    ev = context.world.emitted(P + "HandStarted", table.HandStarted())
    assert ev.small_blind_position != ev.dealer_position, (
        f"SB and dealer both at {ev.small_blind_position}; with 3+ players the "
        "small blind is left of the dealer"
    )


# --- Then: identity-required / table-existence rejections ---


@then("the join is refused because a player identity is required")
def _then_join_no_player(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the leave is refused because a player identity is required")
def _then_leave_no_player(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the leave is refused because the table does not exist")
def _then_leave_no_table(context):
    assert_rejected(context, "TABLE_NOT_FOUND")


# --- Then: CreateTable validation rejections (all coded INVALID_ARGUMENT) ---


@then("the create-table is refused because a table name is required")
def _then_create_no_name(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the create-table is refused because the minimum buy-in must be positive")
def _then_create_min_buyin(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then(
    "the create-table is refused because the maximum buy-in of {hi:d} must "
    "exceed the minimum buy-in of {lo:d}"
)
def _then_create_max_below_min(context, hi, lo):
    assert_rejected(context, "INVALID_ARGUMENT")


@then("the create-table is refused because the small blind must be positive")
def _then_create_small_blind(context):
    assert_rejected(context, "INVALID_ARGUMENT")


@then(
    "the create-table is refused because the big blind of {bb:d} must exceed "
    "the small blind of {sb:d}"
)
def _then_create_big_blind(context, bb, sb):
    assert_rejected(context, "INVALID_ARGUMENT")


@then(
    "the create-table is refused because max_players of {n:d} is out of the "
    "allowed 2-10 range"
)
def _then_create_max_players(context, n):
    assert_rejected(context, "INVALID_ARGUMENT")


# --- When: empty-quote inputs (required-field guards) ---
#
# behave's parse ``{field}`` will not bind an empty ``""`` capture, so these
# regex steps match only the empty-quote forms and exercise the same handler
# dispatch as their non-empty parse siblings (which still own the populated
# inputs, so there is no ambiguity).
use_step_matcher("re")


@when('a Texas Hold\'em table named "" is created with:')
def _when_create_empty_name(context):
    _when_create(context, "Texas Hold'em", "")


@when(r'player "" joins the table at seat (?P<seat>\d+) with a buy-in of (?P<amt>\d+)')
def _when_join_empty(context, seat, amt):
    _when_join_seat(context, "", int(seat), int(amt))


@when(r'player "" leaves the table')
def _when_leave_empty(context):
    _when_leave(context, "")


@when(
    r'player "" is seated at position (?P<seat>-?\d+) with reservation '
    r'"(?P<res>[^"]+)" for (?P<amt>\d+) chips'
)
def _when_seat_player_empty(context, seat, res, amt):
    _when_seat_player(context, "", int(seat), res, int(amt))


@when(
    r'player "" re-buys (?P<amt>\d+) chips with reservation '
    r'"(?P<res>[^"]+)" at seat (?P<seat>-?\d+)'
)
def _when_rebuy_empty(context, amt, res, seat):
    _when_rebuy(context, "", int(amt), res, int(seat))


use_step_matcher("parse")


# --- Given: sit-out / sit-in / re-buy facts (seeded prior events) ---


@given('player "{pid}" is sitting out')
def _given_sitting_out(context, pid):
    context.world.seed_event(
        DOMAIN,
        P + "PlayerSatOut",
        table.PlayerSatOut(player_root=uuid_for(pid)),
        root=_table_root(context),
    )


@given('player "{pid}" sits back in')
def _given_sits_back_in(context, pid):
    context.world.seed_event(
        DOMAIN,
        P + "PlayerSatIn",
        table.PlayerSatIn(player_root=uuid_for(pid)),
        root=_table_root(context),
    )


@given('player "{pid}" re-buys to bring the stack to {total:d}')
def _given_rebuy_to(context, pid, total):
    context.world.seed_event(
        DOMAIN,
        P + "ChipsAdded",
        table.ChipsAdded(player_root=uuid_for(pid), new_stack=total),
        root=_table_root(context),
    )


# --- Then: state accessors (rebuilt TableState) ---


@then("the table is full")
def _then_full(context):
    state = _rebuild_state(context)
    assert len(state.seats) >= state.max_players, (
        f"seated {len(state.seats)} < max_players {state.max_players}; "
        "expected the table to be full"
    )


@then("{n:d} player is currently active at the table")
def _then_active_count(context, n):
    state = _rebuild_state(context)
    active = sum(1 for s in state.seats if not s.is_sitting_out)
    assert active == n, f"active = {active}, want {n}"


@then("the player at seat {seat:d} has an {stack:d}-chip stack")
def _then_seat_stack(context, seat, stack):
    state = _rebuild_state(context)
    occupant = next((s for s in state.seats if s.position == seat), None)
    assert occupant is not None, f"seat {seat} is empty"
    assert (
        occupant.stack.amount == stack
    ), f"seat {seat} stack = {occupant.stack.amount}, want {stack}"
