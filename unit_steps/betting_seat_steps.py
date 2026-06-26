"""Seat-indexed betting steps — the raise-tracking observable surface.

raise_tracking.feature drives the hand aggregate BY SEAT and asserts on the
``TurnAssigned`` the cluster emits for the next actor (``amount_to_call`` /
``min_raise``), distinct from hand_steps.py's player-id, state-shape vocabulary.
Seat ``N`` maps to the dealt ``player-{N+1}`` (the same naming hand_steps uses).

This module is named so it loads before ``hand_steps.py``: behave returns the
first registered step whose pattern matches, so the seat-prefixed
``seat {n} raises to {m}`` here wins over the generic ``{pid} raises to {amt}``
there for inputs like "seat 0 raises to 30".
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker.hand.aggregate.handler import _fresh_deck
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "hand"
P = "io.angzarr.examples.v1."
_TABLE_ROOT = uuid_for("table-main")
_VARIANTS = {"Texas Hold'em": pt.TEXAS_HOLDEM, "Omaha": pt.OMAHA}


def _seat_root(seat: int) -> bytes:
    return uuid_for(f"player-{seat + 1}")


def _seed_hand(context, n, big_blind, stacks=None) -> None:
    context.big_blind = big_blind
    context.last_turn_assigned = None
    # Betting-round observables accumulated across the scenario's actions.
    context.contributions = {}
    context.action_count = 0
    context.seat_actions = {}
    context.last_action = {}
    context.round_complete_event = None
    if stacks is None:
        stacks = [10000] * n
    players = [
        hand.PlayerInHand(player_root=_seat_root(i), position=i, stack=stacks[i])
        for i in range(n)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=_VARIANTS[context.variant],
            players=players,
            dealer_position=0,
            # Hole cards are immaterial here; just leave a real post-deal deck.
            remaining_deck=_fresh_deck()[2 * n :],
        ),
    )


def _capture_turn_assigned(context) -> None:
    """Record the latest TurnAssigned the last dispatch emitted, if any."""
    for page in context.world.emitted_pages():
        if page.event.type_url.rsplit("/", 1)[-1] == P + "TurnAssigned":
            ta = hand.TurnAssigned()
            ta.ParseFromString(page.event.value)
            context.last_turn_assigned = ta


def _act(context, seat, action, amount=0) -> None:
    """Dispatch a seat's action, capture the emitted TurnAssigned, then fold so
    the next action rebuilds over it."""
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=_seat_root(seat), action=action, amount=amount),
    )
    _capture_turn_assigned(context)
    context.world.fold_emitted(DOMAIN)


def _attempt(context, seat, action, amount) -> None:
    """Dispatch an action expected to be rejected — leave the rejection on the
    response for assert_rejected; don't fold (no events were emitted)."""
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=_seat_root(seat), action=action, amount=amount),
    )


# --- Given ---


@given("a {n:d}-handed {variant} hand with big_blind {bb:d}")
def _given_hand(context, n, variant, bb):
    context.variant = variant
    _seed_hand(context, n, bb)


@given("a {n:d}-handed {variant} hand with big_blind {bb:d} and stacks {stacks}")
def _given_hand_stacks(context, n, variant, bb, stacks):
    context.variant = variant
    _seed_hand(context, n, bb, [int(s) for s in stacks.split(",")])


# --- When ---


@when("SB at seat {s1:d} and BB at seat {s2:d} post blinds")
def _when_post_blinds(context, s1, s2):
    bb = context.big_blind
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=_seat_root(s1), blind_type="small", amount=bb // 2),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=_seat_root(s2), blind_type="big", amount=bb),
    )
    _capture_turn_assigned(context)
    context.world.fold_emitted(DOMAIN)


@when("seat {seat:d} raises to {amount:d}")
def _when_raises(context, seat, amount):
    _act(context, seat, pt.RAISE, amount)


@when("seat {seat:d} calls")
def _when_calls(context, seat):
    _act(context, seat, pt.CALL)


@when("seat {seat:d} checks")
def _when_checks(context, seat):
    _act(context, seat, pt.CHECK)


@when("seat {seat:d} bets {amount:d}")
def _when_bets(context, seat, amount):
    _act(context, seat, pt.BET, amount)


@when("seat {seat:d} goes all-in to {amount:d}")
def _when_all_in(context, seat, amount):
    _act(context, seat, pt.ALL_IN, amount)


@when("seat {seat:d} attempts to raise to {amount:d}")
def _when_attempt_raise(context, seat, amount):
    _attempt(context, seat, pt.RAISE, amount)


@when("seat {seat:d} attempts to bet {amount:d}")
def _when_attempt_bet(context, seat, amount):
    _attempt(context, seat, pt.BET, amount)


# --- Then ---


@then("the latest TurnAssigned has amount_to_call {n:d}")
def _then_amount_to_call(context, n):
    ta = getattr(context, "last_turn_assigned", None)
    assert ta is not None, "no TurnAssigned was emitted"
    assert ta.amount_to_call == n, f"amount_to_call = {ta.amount_to_call}, want {n}"


@then("the latest TurnAssigned has min_raise {n:d}")
def _then_min_raise(context, n):
    ta = getattr(context, "last_turn_assigned", None)
    assert ta is not None, "no TurnAssigned was emitted"
    assert ta.min_raise == n, f"min_raise = {ta.min_raise}, want {n}"


@then("the raise is refused because it is below the minimum")
def _then_raise_below_min(context):
    assert_rejected(context, "RAISE_BELOW_MIN")


@then("the bet is refused because it is below the minimum raise")
def _then_bet_below_min_raise(context):
    assert_rejected(context, "BET_BELOW_MIN")


# ---------------------------------------------------------------------------
# Betting-round engine (betting_round.feature) + cross-street community deals
# (raise_tracking.feature). Round-completion fires BettingRoundComplete; the
# observables are per-seat contributions, action counts, and the post-action
# stacks read off the emitted events.
# ---------------------------------------------------------------------------

_VERB = {
    "FOLD": pt.FOLD,
    "CHECK": pt.CHECK,
    "CALL": pt.CALL,
    "BET": pt.BET,
    "RAISE": pt.RAISE,
    "ALL_IN": pt.ALL_IN,
}

_PHASE = {
    "PREFLOP": pt.PREFLOP,
    "FLOP": pt.FLOP,
    "TURN": pt.TURN,
    "RIVER": pt.RIVER,
}


@given("a {n:d}-handed {variant} hand")
def _given_hand_plain(context, n, variant):
    context.variant = variant
    # The blind amounts come from the explicit "blinds posted" step; seed with a
    # nominal BB so context is initialised.
    _seed_hand(context, n, 10)


@given("a table with players:")
def _given_table_players(context):
    context.variant = "Texas Hold'em"
    rows = list(context.table)
    n = len(rows)
    stacks = [0] * n
    for r in rows:
        stacks[int(r["seat"])] = int(r["stack"])
    _seed_hand(context, n, 10, stacks)


def _post_blind(context, seat, blind_type, amount):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(
            player_root=_seat_root(seat), blind_type=blind_type, amount=amount
        ),
    )
    context.contributions[seat] = context.contributions.get(seat, 0) + amount
    _capture_turn_assigned(context)
    context.world.fold_emitted(DOMAIN)


@given(
    "blinds posted: SB at seat {s1:d} amount {a1:d}, " "BB at seat {s2:d} amount {a2:d}"
)
@when(
    "blinds posted: SB at seat {s1:d} amount {a1:d}, " "BB at seat {s2:d} amount {a2:d}"
)
def _step_blinds_posted(context, s1, a1, s2, a2):
    _post_blind(context, s1, "small", a1)
    _post_blind(context, s2, "big", a2)


def _drive_action(context, seat, action, amount):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=_seat_root(seat), action=action, amount=amount),
    )
    for page in context.world.emitted_pages():
        name = page.event.type_url.rsplit("/", 1)[-1]
        if name == P + "ActionTaken":
            at = hand.ActionTaken()
            at.ParseFromString(page.event.value)
            context.action_count += 1
            context.seat_actions[seat] = context.seat_actions.get(seat, 0) + 1
            context.contributions[seat] = context.contributions.get(seat, 0) + at.amount
            context.last_action[seat] = at
        elif name == P + "BettingRoundComplete":
            brc = hand.BettingRoundComplete()
            brc.ParseFromString(page.event.value)
            context.round_complete_event = brc
        elif name == P + "TurnAssigned":
            ta = hand.TurnAssigned()
            ta.ParseFromString(page.event.value)
            context.last_turn_assigned = ta
    context.world.fold_emitted(DOMAIN)


@when("players act in sequence:")
def _when_act_sequence(context):
    for row in context.table:
        _drive_action(
            context, int(row["seat"]), _VERB[row["action"]], int(row["amount"])
        )


def _deal_street(context, count):
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=count)
    )
    _capture_turn_assigned(context)
    context.world.fold_emitted(DOMAIN)


@when("the flop is dealt")
def _when_flop_dealt(context):
    _deal_street(context, 3)


@when("the turn is dealt")
def _when_turn_dealt(context):
    _deal_street(context, 1)


@then("a BettingRoundComplete event is emitted for phase {phase}")
def _then_round_complete(context, phase):
    brc = getattr(context, "round_complete_event", None)
    assert brc is not None, "no BettingRoundComplete was emitted"
    want = _PHASE[phase]
    assert (
        brc.completed_phase == want
    ), f"completed_phase = {pt.BettingPhase.Name(brc.completed_phase)}, want {phase}"


@then("seat {seat:d} contributed {amt:d} chips this round")
def _then_contributed(context, seat, amt):
    got = context.contributions.get(seat, 0)
    assert got == amt, f"seat {seat} contributed {got}, want {amt}"


@then("the pot total is {amt:d}")
def _then_pot_total(context, amt):
    got = sum(context.contributions.values())
    assert got == amt, f"pot total = {got}, want {amt}"


@then("exactly {n:d} ActionTaken events were emitted this round")
def _then_action_count(context, n):
    assert (
        context.action_count == n
    ), f"{context.action_count} ActionTaken emitted, want {n}"


@then("seat {seat:d} acted exactly {k:d} time this round")
@then("seat {seat:d} acted exactly {k:d} times this round")
def _then_seat_acted(context, seat, k):
    got = context.seat_actions.get(seat, 0)
    assert got == k, f"seat {seat} acted {got} times, want {k}"


@then("seat {seat:d} is all-in")
def _then_seat_all_in(context, seat):
    at = context.last_action.get(seat)
    assert at is not None, f"seat {seat} took no action"
    assert (
        at.action == pt.ALL_IN or at.player_stack == 0
    ), f"seat {seat} is not all-in (stack={at.player_stack})"


@then("seat {seat:d} has stack {amt:d}")
def _then_seat_stack(context, seat, amt):
    at = context.last_action.get(seat)
    assert at is not None, f"seat {seat} took no action"
    assert at.player_stack == amt, f"seat {seat} stack = {at.player_stack}, want {amt}"
