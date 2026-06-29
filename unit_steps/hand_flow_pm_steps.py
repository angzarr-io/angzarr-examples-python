"""Hand-flow process-manager unit steps — the opening orchestration cluster
(EU-0401..EU-0410): blinds, betting-round hand-off, and street/showdown deals.

Each scenario seeds the PM's event-sourced ``HandFlowState`` as a prior
``HandFlowAdvanced`` own-event the core folds, dispatches ONE trigger event from
the hand domain through the FFI ``Router.dispatch_process_manager``, then asserts
the next COMMAND the PM emits (PostBlind / DealCommunityCards / AwardPot) and/or
the post-transition flow state (decoded from the emitted HandFlowAdvanced and
folded through the PM's applier — the same rebuild path production takes).
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."

# HandFlowState.phase values (mirrors the proto + handler).
_DEALING = 1
_BLINDS = 2
_BETTING = 3
_COMPLETE = 4
_DEALING_COMMUNITY = 5
_SHOWDOWN = 6
_DRAW = 7

HAND_ROOT = uuid_for("hand-flow-1")
_DEFAULT_POSITIONS = (0, 1, 2)
_CURRENT_BET = 10


def _seat_root(position: int) -> bytes:
    return uuid_for(f"seat-{position}")


def _seed(context) -> hand.HandFlowState:
    if getattr(context, "flow_seed", None) is None:
        context.flow_seed = hand.HandFlowState(hand_root=HAND_ROOT)
    return context.flow_seed


def _add_default_seats(state: hand.HandFlowState, positions=_DEFAULT_POSITIONS) -> None:
    for pos in positions:
        state.seats.add(position=pos, player_root=_seat_root(pos), stack=500)


def _seat(state: hand.HandFlowState, position: int):
    for seat in state.seats:
        if seat.position == position:
            return seat
    return None


def _setup_blinds(state: hand.HandFlowState) -> None:
    """Three-handed table: dealer 0, small blind 5 at seat 1, big blind 10 at
    seat 2 — the canonical layout the blind/betting scenarios assert against."""
    state.dealer_position = 0
    state.small_blind_position = 1
    state.big_blind_position = 2
    state.small_blind = 5
    state.big_blind = 10
    state.game_variant = pt.TEXAS_HOLDEM
    state.player_count = len(_DEFAULT_POSITIONS)
    _add_default_seats(state)


def _dispatch(context, fq: str, event) -> None:
    seed = _seed(context)
    context.world.dispatch_process_manager(
        "hand",
        P + fq,
        event,
        prior_events=[(P + "HandFlowAdvanced", hand.HandFlowAdvanced(state=seed))],
    )


def _result(context) -> hand.HandFlowState:
    """The PM's post-transition state: decode the emitted HandFlowAdvanced and
    fold it through the applier (exercising the event-sourced rebuild path)."""
    event = context.world.process_event(P + "HandFlowAdvanced", hand.HandFlowAdvanced())
    state = hand.HandFlowState()
    context.world.hand_flow_pm.apply_hand_flow_advanced(state, event)
    return state


def _find_command(context, name: str, message):
    """Decode the first emitted command whose message type is ``name`` (the bare
    proto name, e.g. ``PostBlind``); ``emitted_commands`` yields fully-qualified
    type names, so match on the trailing segment."""
    for _domain, fq, command in context.world.emitted_commands():
        if fq.rsplit(".", 1)[-1] == name:
            message.ParseFromString(command.value)
            return message
    return None


def _expected_next(state: hand.HandFlowState, actor: int) -> int:
    positions = sorted(
        s.position for s in state.seats if not s.has_folded and not s.is_all_in
    )
    later = [p for p in positions if p > actor]
    return later[0] if later else positions[0]


def _positions(text: str):
    return [int(t) for t in text.replace("and", ",").replace(" ", "").split(",") if t]


# ===========================================================================
# Blind posting (EU-0401 .. EU-0403)
# ===========================================================================


@given("a hand is in the dealing phase")
def _given_dealing_phase(context):
    seed = _seed(context)
    seed.phase = _DEALING
    _setup_blinds(seed)


@when("the cards are dealt to the players")
def _when_cards_dealt(context):
    _dispatch(context, "CardsDealt", hand.CardsDealt(dealer_position=0))


@then("the hand moves to posting blinds")
def _then_posting_blinds(context):
    assert _result(context).phase == _BLINDS, "phase is not BLINDS"


@then("the small blind is asked of the player due to post it")
def _then_small_blind_asked(context):
    cmd = _find_command(context, "PostBlind", hand.PostBlind())
    assert cmd is not None, "no PostBlind command emitted"
    assert cmd.blind_type == "small", f"expected small blind, got {cmd.blind_type!r}"
    assert cmd.player_root == _seat_root(1), "small blind asked of the wrong seat"
    assert cmd.amount == 5, f"expected small blind 5, got {cmd.amount}"


@given("a hand is posting blinds")
def _given_posting_blinds(context):
    seed = _seed(context)
    seed.phase = _BLINDS
    _setup_blinds(seed)


@given("the small blind has been posted")
def _given_small_blind_posted(context):
    seed = _seed(context)
    seed.small_blind_posted = True
    seed.current_bet = seed.small_blind
    sb = _seat(seed, seed.small_blind_position)
    if sb is not None:
        sb.bet_this_round = seed.small_blind


@when("the small blind is posted")
def _when_small_blind_posted(context):
    seed = _seed(context)
    _dispatch(
        context,
        "BlindPosted",
        hand.BlindPosted(
            player_root=_seat_root(seed.small_blind_position),
            blind_type="small",
            amount=seed.small_blind,
        ),
    )


@then("the big blind is asked of the player due to post it")
def _then_big_blind_asked(context):
    cmd = _find_command(context, "PostBlind", hand.PostBlind())
    assert cmd is not None, "no PostBlind command emitted"
    assert cmd.blind_type == "big", f"expected big blind, got {cmd.blind_type!r}"
    assert cmd.player_root == _seat_root(2), "big blind asked of the wrong seat"
    assert cmd.amount == 10, f"expected big blind 10, got {cmd.amount}"


@when("the big blind is posted")
def _when_big_blind_posted(context):
    seed = _seed(context)
    _dispatch(
        context,
        "BlindPosted",
        hand.BlindPosted(
            player_root=_seat_root(seed.big_blind_position),
            blind_type="big",
            amount=seed.big_blind,
        ),
    )


@then("the hand moves to the betting round")
def _then_betting_round(context):
    assert _result(context).phase == _BETTING, "phase is not BETTING"


@then("action is on the player under the gun")
def _then_action_utg(context):
    # Three-handed: the big blind sits at seat 2, so the under-the-gun seat (the
    # first to act preflop) wraps round to the button at seat 0.
    assert _result(context).action_on == 0, "action is not under the gun"


# ===========================================================================
# Betting-round hand-off (EU-0404 .. EU-0406)
# ===========================================================================


@given("a hand is in a betting round")
def _given_betting_round(context):
    seed = _seed(context)
    seed.phase = _BETTING
    seed.betting_phase = pt.PREFLOP
    seed.current_bet = _CURRENT_BET
    if not seed.seats:
        _add_default_seats(seed)
        seed.player_count = len(_DEFAULT_POSITIONS)


@given("action is on the player at position {pos:d}")
def _given_action_on(context, pos):
    _seed(context).action_on = pos


@when("the player at position {pos:d} calls")
def _when_player_calls(context, pos):
    seed = _seed(context)
    context.actor_pos = pos
    seat = _seat(seed, pos)
    to_call = seed.current_bet - (seat.bet_this_round if seat else 0)
    _dispatch(
        context,
        "ActionTaken",
        hand.ActionTaken(
            player_root=_seat_root(pos),
            action=pt.CALL,
            amount=to_call,
            player_stack=490,
        ),
    )


@then("action passes to the next active player")
def _then_action_passes(context):
    state = _result(context)
    expected = _expected_next(_seed(context), context.actor_pos)
    assert state.action_on != context.actor_pos, "action stayed on the actor"
    assert (
        state.action_on == expected
    ), f"expected action on {expected}, got {state.action_on}"


@given("the players at positions {positions} have all acted")
def _given_all_acted(context, positions):
    seed = _seed(context)
    for pos in _positions(positions):
        seat = _seat(seed, pos)
        if seat is None:
            seat = seed.seats.add(position=pos, player_root=_seat_root(pos), stack=500)
        seat.has_acted = True
        seat.bet_this_round = seed.current_bet


@when("the player at position {pos:d} raises")
def _when_player_raises(context, pos):
    seed = _seed(context)
    context.actor_pos = pos
    _dispatch(
        context,
        "ActionTaken",
        hand.ActionTaken(
            player_root=_seat_root(pos),
            action=pt.RAISE,
            amount=seed.current_bet,  # raise by one bet, to 2x the current level
            player_stack=480,
        ),
    )


@then("the players at positions {positions} must act again")
def _then_must_act_again(context, positions):
    state = _result(context)
    for pos in _positions(positions):
        seat = _seat(state, pos)
        assert seat is not None, f"no seat at position {pos}"
        assert not seat.has_acted, f"seat {pos} was not reopened to act again"


@given("every active player has acted and matched the current bet")
def _given_all_but_last_acted(context):
    """All contenders but the last-to-act have already acted and matched — the
    last seat's action (next) is what closes the round."""
    seed = _seed(context)
    positions = sorted(s.position for s in seed.seats)
    last = positions[-1]
    for pos in positions:
        seat = _seat(seed, pos)
        if pos != last:
            seat.has_acted = True
            seat.bet_this_round = seed.current_bet
    seed.action_on = last


@when("the last player acts")
def _when_last_player_acts(context):
    seed = _seed(context)
    pos = seed.action_on
    seat = _seat(seed, pos)
    to_call = seed.current_bet - (seat.bet_this_round if seat else 0)
    _dispatch(
        context,
        "ActionTaken",
        hand.ActionTaken(
            player_root=_seat_root(pos),
            action=pt.CALL,
            amount=to_call,
            player_stack=490,
        ),
    )


@then("the betting round ends")
def _then_betting_round_ends(context):
    state = _result(context)
    assert state.action_on == -1, "a seat is still on the clock"
    assert state.phase != _BETTING, "the hand is still in the betting round"


@then("the hand advances to the next phase")
def _then_advances_phase(context):
    assert (
        _result(context).phase == _DEALING_COMMUNITY
    ), "the hand did not advance past betting"


# ===========================================================================
# Street and showdown deals (EU-0407 .. EU-0410)
# ===========================================================================


def _seed_completed_round(context, betting_phase):
    seed = _seed(context)
    seed.phase = _BETTING
    seed.betting_phase = betting_phase
    if not seed.seats:
        _add_default_seats(seed)
        seed.player_count = len(_DEFAULT_POSITIONS)
    context.completed_phase = betting_phase
    context.pot_total = 60


@given("preflop betting is complete")
def _given_preflop_complete(context):
    _seed_completed_round(context, pt.PREFLOP)


@given("flop betting is complete")
def _given_flop_complete(context):
    _seed_completed_round(context, pt.FLOP)


@given("turn betting is complete")
def _given_turn_complete(context):
    _seed_completed_round(context, pt.TURN)


@given("river betting is complete")
def _given_river_complete(context):
    _seed_completed_round(context, pt.RIVER)


@when("the betting round ends")
def _when_betting_round_ends(context):
    seed = _seed(context)
    stacks = [
        hand.PlayerStackSnapshot(
            player_root=s.player_root, stack=s.stack, has_folded=s.has_folded
        )
        for s in seed.seats
    ]
    _dispatch(
        context,
        "BettingRoundComplete",
        hand.BettingRoundComplete(
            completed_phase=context.completed_phase,
            pot_total=context.pot_total,
            stacks=stacks,
        ),
    )


@then("the flop is dealt")
def _then_flop_dealt(context):
    cmd = _find_command(context, "DealCommunityCards", hand.DealCommunityCards())
    assert cmd is not None, "no DealCommunityCards command emitted"
    assert cmd.count == 3, f"expected a 3-card flop, got {cmd.count}"


@then("the hand is dealing community cards")
def _then_dealing_community(context):
    assert (
        _result(context).phase == _DEALING_COMMUNITY
    ), "phase is not DEALING_COMMUNITY"


@then("the turn card is dealt")
def _then_turn_dealt(context):
    cmd = _find_command(context, "DealCommunityCards", hand.DealCommunityCards())
    assert cmd is not None, "no DealCommunityCards command emitted"
    assert cmd.count == 1, f"expected a single turn card, got {cmd.count}"


@then("the river card is dealt")
def _then_river_dealt(context):
    cmd = _find_command(context, "DealCommunityCards", hand.DealCommunityCards())
    assert cmd is not None, "no DealCommunityCards command emitted"
    assert cmd.count == 1, f"expected a single river card, got {cmd.count}"


@then("the hand moves to showdown")
def _then_showdown(context):
    assert _result(context).phase == _SHOWDOWN, "phase is not SHOWDOWN"


@then("the pot is awarded")
def _then_pot_awarded(context):
    cmd = _find_command(context, "AwardPot", hand.AwardPot())
    assert cmd is not None, "no AwardPot command emitted"
    assert len(cmd.awards) >= 1, "AwardPot carried no awards"


# ===========================================================================
# All-in (EU-0412)
# ===========================================================================


@when("a player moves all-in")
def _when_player_all_in(context):
    context.actor_pos = 0
    _dispatch(
        context,
        "ActionTaken",
        hand.ActionTaken(
            player_root=_seat_root(0),
            action=pt.ALL_IN,
            amount=500,
            player_stack=0,
        ),
    )


@then("that player is marked as all-in")
def _then_marked_all_in(context):
    seat = _seat(_result(context), context.actor_pos)
    assert seat is not None and seat.is_all_in, "the player is not marked all-in"


@then("that player no longer acts in this betting round")
def _then_no_longer_acts(context):
    state = _result(context)
    assert state.action_on != context.actor_pos, "action is still on the all-in player"


# ===========================================================================
# Positional action order (EU-0445 BB option; EU-0446/0447 post-flop order)
# ===========================================================================


@given("the dealer is at position {d:d} with players at positions {positions}")
def _given_dealer_with_players(context, d, positions):
    seed = _seed(context)
    seed.dealer_position = d
    del seed.seats[:]
    for pos in _positions(positions):
        seed.seats.add(position=pos, player_root=_seat_root(pos), stack=500)
    seed.player_count = len(_positions(positions))


@given(
    "the small blind of {sb:d} was posted by position {sbpos:d} and the big "
    "blind of {bb:d} was posted by position {bbpos:d}"
)
def _given_blinds_posted_by(context, sb, sbpos, bb, bbpos):
    seed = _seed(context)
    seed.small_blind = sb
    seed.big_blind = bb
    seed.small_blind_position = sbpos
    seed.big_blind_position = bbpos
    seed.small_blind_posted = True
    seed.big_blind_posted = True
    seed.current_bet = bb
    sb_seat = _seat(seed, sbpos)
    if sb_seat is not None:
        sb_seat.bet_this_round = sb
    bb_seat = _seat(seed, bbpos)
    if bb_seat is not None:
        bb_seat.bet_this_round = bb


@when("the player at position {pos:d} calls {amt:d}")
def _when_player_calls_amount(context, pos, amt):
    context.actor_pos = pos
    _dispatch(
        context,
        "ActionTaken",
        hand.ActionTaken(
            player_root=_seat_root(pos),
            action=pt.CALL,
            amount=amt,
            player_stack=490,
        ),
    )
    # Carry the post-action state forward so a following action in the same
    # scenario folds onto it (the BB-option sequence dispatches twice).
    context.flow_seed = _result(context)


@then("the betting round is not yet complete")
def _then_not_yet_complete(context):
    state = _result(context)
    assert state.phase == _BETTING, "the betting round already ended"
    assert state.action_on != -1, "no seat is on the clock"


@then("action is on the big blind at position {pos:d}")
def _then_action_on_big_blind(context, pos):
    state = _result(context)
    assert state.action_on == pos, f"action on {state.action_on}, want big blind {pos}"


@then("action is on the player at position {pos:d}")
def _then_action_on_position(context, pos):
    state = _result(context)
    assert state.action_on == pos, f"action on {state.action_on}, want {pos}"


# ===========================================================================
# Community-card reset (EU-0417) — driven by the shared "the flop is dealt"
# When in betting_seat_steps, which routes a CommunityCardsDealt to the PM
# when a HandFlowState seed is present.
# ===========================================================================


@then("no player has anything committed this round")
def _then_nothing_committed(context):
    state = _result(context)
    assert all(
        s.bet_this_round == 0 for s in state.seats
    ), "a seat still has chips committed this round"


@then("no player has yet acted this round")
def _then_nobody_acted(context):
    state = _result(context)
    assert all(not s.has_acted for s in state.seats), "a seat is still marked as acted"


@then("there is no bet to call")
def _then_no_bet_to_call(context):
    assert _result(context).current_bet == 0, "there is still a bet to call"


@then("action is on the first active player left of the dealer")
def _then_action_left_of_dealer(context):
    state = _result(context)
    expected = _expected_next(state, state.dealer_position)
    assert (
        state.action_on == expected
    ), f"action on {state.action_on}, want first-active-left-of-dealer {expected}"


# ===========================================================================
# Five Card Draw flow (EU-0415, EU-0416)
# ===========================================================================


@given("a Five Card Draw hand has finished the first betting round")
def _given_draw_first_betting_done(context):
    seed = _seed(context)
    seed.phase = _BETTING
    seed.betting_phase = pt.PREFLOP
    seed.game_variant = pt.FIVE_CARD_DRAW
    if not seed.seats:
        _add_default_seats(seed)
        seed.player_count = len(_DEFAULT_POSITIONS)
    context.completed_phase = pt.PREFLOP
    context.pot_total = 60


@then("the hand moves to the draw")
def _then_moves_to_draw(context):
    assert _result(context).phase == _DRAW, "phase is not DRAW"


@given("a Five Card Draw hand is in the draw")
def _given_in_the_draw(context):
    seed = _seed(context)
    seed.phase = _DRAW
    seed.game_variant = pt.FIVE_CARD_DRAW
    if not seed.seats:
        _add_default_seats(seed)
        seed.player_count = len(_DEFAULT_POSITIONS)


@given("every player has finished drawing")
def _given_every_player_drawn(context):
    """All contenders but the last-to-draw have drawn — the last player's draw
    (next) is what closes the draw round."""
    seed = _seed(context)
    positions = sorted(s.position for s in seed.seats)
    context.last_drawer = positions[-1]
    for pos in positions:
        if pos != context.last_drawer:
            _seat(seed, pos).has_drawn = True


@when("the last player finishes drawing")
def _when_last_player_draws(context):
    seed = _seed(context)
    pos = getattr(context, "last_drawer", sorted(s.position for s in seed.seats)[-1])
    _dispatch(context, "DrawCompleted", hand.DrawCompleted(player_root=_seat_root(pos)))


@then("the hand moves to the final betting round")
def _then_final_betting_round(context):
    state = _result(context)
    assert state.phase == _BETTING, "phase is not BETTING (final round)"
    assert state.betting_phase == pt.DRAW, "betting_phase is not the post-draw round"
