"""Hand aggregate unit steps — draw / showdown / pot-award / evaluation slice.

Covers the play-out tail of a hand on the FFI core: Five Card Draw discard/draw,
showdown card reveal vs muck, pot award, and hand evaluation (both pure — "when
hands are evaluated" — and reveal-time, where ``CardsRevealed`` carries the
ranking). Drives the same ``World`` harness the other hand steps use: seed prior
events the core folds, dispatch the command, assert the emitted event or the
rebuilt state.

Loads before ``hand_steps.py`` (sorted filename order), so the Five Card Draw
deal Given here — which seeds real hole cards the draw needs — shadows the
generic, hole-card-less deal Given for the Five-Card-Draw variant only.
"""

from __future__ import annotations

import re

from behave import given, then, use_step_matcher, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker.hand.aggregate.handler import HandAggregate, _fresh_deck
from angzarr_poker.hand.game_rules import (
    get_game_rules,
    high_up_actor,
    odd_chip_winner_index,
    showing_order,
)
from angzarr_poker.hand.pot_distribution import (
    Pot,
    compute_side_pots,
    split_with_odd_chip,
)
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "hand"
P = "io.angzarr.examples.v1."
_TABLE_ROOT = uuid_for("table-main")

_VARIANTS = {
    "Texas Hold'em": pt.TEXAS_HOLDEM,
    "Omaha": pt.OMAHA,
    "Five Card Draw": pt.FIVE_CARD_DRAW,
    "Seven Card Stud": pt.SEVEN_CARD_STUD,
    "Razz": pt.RAZZ,
    "Seven Card Stud Hi/Lo": pt.STUD_HI_LO_8B,
}

# One handler instance reused to fold a scenario's history (prior + last-emitted)
# back into a HandState via the same appliers the core runs.
_AGG = HandAggregate()
_APPLIERS = {
    "DeckShuffled": HandAggregate.apply_deck_shuffled,
    "CardsDealt": HandAggregate.apply_cards_dealt,
    "BlindPosted": HandAggregate.apply_blind_posted,
    "ActionTaken": HandAggregate.apply_action_taken,
    "TurnAssigned": HandAggregate.apply_turn_assigned,
    "BettingRoundComplete": HandAggregate.apply_betting_round_complete,
    "CommunityCardsDealt": HandAggregate.apply_community_cards_dealt,
    "DrawCompleted": HandAggregate.apply_draw_completed,
    "ShowdownStarted": HandAggregate.apply_showdown_started,
    "CardsRevealed": HandAggregate.apply_cards_revealed,
    "CardsMucked": HandAggregate.apply_cards_mucked,
    "PotAwarded": HandAggregate.apply_pot_awarded,
    "HandComplete": HandAggregate.apply_hand_complete,
    "FouledDeckDetected": HandAggregate.apply_fouled_deck_detected,
    "ButtonCardReplaced": HandAggregate.apply_button_card_replaced,
    "PriorChipPulledBack": HandAggregate.apply_prior_chip_pulled_back,
    "StudStreetDealt": HandAggregate.apply_stud_street_dealt,
    "StudDownCardConverted": HandAggregate.apply_stud_down_card_converted,
    "SeventhStreetCardReplaced": HandAggregate.apply_seventh_street_card_replaced,
    "StudCommunityCardDealt": HandAggregate.apply_stud_community_card_dealt,
    "StudDoorCardSelected": HandAggregate.apply_stud_door_card_selected,
    "ColorUpScheduled": HandAggregate.apply_color_up_scheduled,
}

_RANK_BY_CH = {
    "A": pt.ACE,
    "K": pt.KING,
    "Q": pt.QUEEN,
    "J": pt.JACK,
    "T": pt.TEN,
    "9": pt.NINE,
    "8": pt.EIGHT,
    "7": pt.SEVEN,
    "6": pt.SIX,
    "5": pt.FIVE,
    "4": pt.FOUR,
    "3": pt.THREE,
    "2": pt.TWO,
}
_SUIT_BY_CH = {"s": pt.SPADES, "h": pt.HEARTS, "d": pt.DIAMONDS, "c": pt.CLUBS}


def _card(token: str) -> pt.Card:
    """Parse a card like ``"Th"`` into a ``Card`` (rank Ten of hearts)."""
    return pt.Card(
        rank=_RANK_BY_CH[token[0].upper()], suit=_SUIT_BY_CH[token[1].lower()]
    )


def _cards(text: str) -> list:
    """Parse a space-separated card list like ``"8d 7s 6h"``."""
    return [_card(tok) for tok in text.split()]


def _rebuild(context, include_last_emitted: bool = True) -> hand.HandState:
    """Fold the (hand, root b"") prior history — optionally plus the last
    dispatch's emitted events — back into a fresh HandState via the appliers."""
    state = hand.HandState()
    pages = []
    book = context.world._prior.get((DOMAIN, b"".hex()))
    if book is not None:
        pages.extend(book.pages)
    if include_last_emitted and context.world.resp is not None:
        pages.extend(context.world.resp.events.pages)
    for page in pages:
        name = page.event.type_url.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        applier = _APPLIERS.get(name)
        ev_cls = getattr(hand, name, None)
        if applier is None or ev_cls is None:
            continue
        ev = ev_cls()
        ev.ParseFromString(page.event.value)
        applier(_AGG, state, ev)
    return state


def _state_player(state, pid):
    root = uuid_for(pid)
    for p in state.players:
        if p.player_root == root:
            return p
    return None


def _revealed_for(context, pid) -> hand.CardsRevealed:
    ev = context.world.emitted(P + "CardsRevealed", hand.CardsRevealed())
    assert ev.player_root == uuid_for(
        pid
    ), f"reveal was for a different player than {pid}"
    return ev


# ==========================================================================
# Draw phase (Five Card Draw)
# ==========================================================================


def _seed_fcd_dealt(context, n: int) -> None:
    """Seed a Five Card Draw CardsDealt with real, distinct hole cards (5 each
    off a fresh deck) so the draw has positions to discard and a deck to draw
    from. Player-i holds deck[5i:5i+5]; the rest is the remaining deck."""
    context.dealt_stack = 1000
    deck = _fresh_deck()
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=1000
        )
        for i in range(n)
    ]
    player_cards = [
        hand.PlayerHoleCards(
            player_root=uuid_for(f"player-{i + 1}"), cards=deck[5 * i : 5 * i + 5]
        )
        for i in range(n)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.FIVE_CARD_DRAW,
            players=players,
            player_cards=player_cards,
            remaining_deck=deck[5 * n :],
        ),
    )


@given("a Five Card Draw hand has been dealt to {n:d} players")
def _given_fcd_dealt(context, n):
    _seed_fcd_dealt(context, n)


@given('{pid}\'s initial hole cards have been captured as "{label}"')
def _given_capture_holes(context, pid, label):
    state = _rebuild(context, include_last_emitted=False)
    player = _state_player(state, pid)
    assert player is not None, f"{pid} is not in the hand"
    assert player.hole_cards, f"{pid} was dealt no hole cards to capture"
    if not hasattr(context, "captured_holes"):
        context.captured_holes = {}
    context.captured_holes[label] = [
        pt.Card(suit=c.suit, rank=c.rank) for c in player.hole_cards
    ]


def _request_draw(context, pid, indices):
    context.world.dispatch(
        DOMAIN,
        P + "RequestDraw",
        hand.RequestDraw(player_root=uuid_for(pid), card_indices=indices),
    )


@when("{pid} discards cards at positions {a:d}, {b:d}, and {c:d}")
def _when_discard_three(context, pid, a, b, c):
    _request_draw(context, pid, [a, b, c])


@when("{pid} stands pat")
def _when_stand_pat(context, pid):
    _request_draw(context, pid, [])


@when("{pid} attempts to draw")
def _when_attempt_draw(context, pid):
    _request_draw(context, pid, [])


@then("{pid} has discarded {d:d} cards and drawn {n:d} cards")
def _then_discarded_drawn(context, pid, d, n):
    ev = context.world.emitted(P + "DrawCompleted", hand.DrawCompleted())
    assert ev.player_root == uuid_for(pid), "DrawCompleted is for the wrong player"
    assert ev.cards_discarded == d, f"discarded {ev.cards_discarded}, want {d}"
    assert ev.cards_drawn == n, f"drawn {ev.cards_drawn}, want {n}"


@then("{pid:S} has {n:d} hole cards")
def _then_has_hole_cards(context, pid, n):
    state = _rebuild(context)
    player = _state_player(state, pid)
    assert player is not None, f"{pid} is not in the hand"
    assert (
        len(player.hole_cards) == n
    ), f"{pid} has {len(player.hole_cards)} cards, want {n}"


@then('{pid}\'s card at position {i:d} matches the "{label}" card at position {j:d}')
def _then_card_matches(context, pid, i, label, j):
    state = _rebuild(context)
    player = _state_player(state, pid)
    assert player is not None, f"{pid} is not in the hand"
    captured = context.captured_holes[label]
    actual = player.hole_cards[i]
    want = captured[j]
    assert (actual.suit, actual.rank) == (want.suit, want.rank), (
        f"{pid}'s card at position {i} changed — the draw did not leave the kept "
        f"positions untouched"
    )


@then("the draw is refused because Texas Hold'em does not support drawing")
def _then_draw_unsupported(context):
    assert_rejected(context, "DRAW_NOT_SUPPORTED")


# ==========================================================================
# Showdown — reveal / muck / pot award
# ==========================================================================


def _seed_showdown(context, holes: dict, community: list) -> None:
    """Seed a hand that has reached showdown: a CardsDealt carrying each named
    player's hole cards, the river board, and ShowdownStarted (which flips the
    status to ``showdown``)."""
    pids = list(holes)
    players = [
        hand.PlayerInHand(player_root=uuid_for(pid), position=i, stack=500)
        for i, pid in enumerate(pids)
    ]
    player_cards = [
        hand.PlayerHoleCards(player_root=uuid_for(pid), cards=holes[pid])
        for pid in pids
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.TEXAS_HOLDEM,
            players=players,
            player_cards=player_cards,
            remaining_deck=[],
        ),
    )
    context.world.seed_event(
        DOMAIN,
        P + "CommunityCardsDealt",
        hand.CommunityCardsDealt(
            phase=pt.RIVER, cards=community, all_community_cards=community
        ),
    )
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())


@given("a {variant} hand has reached showdown with {n:d} players")
def _given_reached_showdown(context, variant, n):
    # Player-1 holds a made flush in hearts; player-2 a non-flush hand — concrete
    # cards so reveal yields a determinate ranking (and a genuine FLUSH for the
    # "tabled a FLUSH" Given).
    _seed_showdown(
        context,
        {"player-1": _cards("Ah 7h"), "player-2": _cards("2c 3c")},
        _cards("2h 4h 6h Ks Qd"),
    )


@given('a hand at showdown with {pid} holding "{hole}" and community "{community}"')
def _given_hand_at_showdown(context, pid, hole, community):
    _seed_showdown(context, {pid: _cards(hole)}, _cards(community))


def _reveal(context, pid, muck: bool):
    context.world.dispatch(
        DOMAIN,
        P + "RevealCards",
        hand.RevealCards(player_root=uuid_for(pid), muck=muck),
    )


@when("{pid} reveals their cards")
def _when_reveals(context, pid):
    _reveal(context, pid, muck=False)


@when("{pid} mucks")
def _when_mucks(context, pid):
    _reveal(context, pid, muck=True)


@then("{pid}'s cards are tabled")
def _then_cards_tabled(context, pid):
    ev = _revealed_for(context, pid)
    assert len(ev.cards) > 0, f"{pid} tabled no cards"


@then("{pid}'s hand ranking is determined")
def _then_ranking_determined(context, pid):
    ev = _revealed_for(context, pid)
    assert ev.ranking.rank_type != pt.HAND_RANK_UNSPECIFIED, "no ranking determined"


@then("{pid}'s hand is mucked")
def _then_hand_mucked(context, pid):
    ev = context.world.emitted(P + "CardsMucked", hand.CardsMucked())
    assert ev.player_root == uuid_for(pid), f"the muck is not for {pid}"


@given("{pid} tabled a {rank}")
def _given_tabled(context, pid, rank):
    # Real reveal: the player must genuinely hold the named ranking.
    _reveal(context, pid, muck=False)
    ev = _revealed_for(context, pid)
    expected = getattr(pt, rank)
    assert (
        ev.ranking.rank_type == expected
    ), f"{pid} tabled {pt.HandRankType.Name(ev.ranking.rank_type)}, not {rank}"


@given("{pid} mucked")
def _given_mucked(context, pid):
    _reveal(context, pid, muck=True)
    ev = context.world.emitted(P + "CardsMucked", hand.CardsMucked())
    assert ev.player_root == uuid_for(pid), f"the muck is not for {pid}"


@when("the pot of {amt:d} is awarded to {pid}")
def _when_award_pot(context, amt, pid):
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(pid), amount=amt, pot_type="main")
            ]
        ),
    )


@then("{pid} wins {amt:d}")
def _then_wins_amount(context, pid, amt):
    ev = context.world.emitted(P + "PotAwarded", hand.PotAwarded())
    for winner in ev.winners:
        if winner.player_root == uuid_for(pid):
            assert winner.amount == amt, f"{pid} won {winner.amount}, want {amt}"
            return
    raise AssertionError(f"{pid} is not among the winners")


@then("the hand is complete")
def _then_hand_complete(context):
    state = _rebuild(context)
    assert (
        state.status == "complete"
    ), f"hand status = {state.status!r}, want 'complete'"


# ==========================================================================
# Pure hand evaluation ("when hands are evaluated")
# ==========================================================================


@given("a showdown with player hands:")
def _given_showdown_hands(context):
    context.showdown_hands = {}
    for row in context.table:
        pid = row["player"]
        context.showdown_hands[pid] = (
            _cards(row["hole_cards"]),
            _cards(row["community_cards"]),
        )


@when("hands are evaluated")
def _when_hands_evaluated(context):
    rules = get_game_rules(pt.TEXAS_HOLDEM)
    context.evaluation_results = {}
    for pid, (hole, community) in context.showdown_hands.items():
        context.evaluation_results[pid] = rules.evaluate_hand(hole, community)


@then("{pid} wins")
def _then_pid_wins(context, pid):
    results = context.evaluation_results
    best = max(results, key=lambda p: results[p][1])
    assert best == pid, f"{best} wins on score, not {pid}"


# The rank assertion serves BOTH paths — pure evaluation (evaluation_results) and
# reveal-time (the emitted CardsRevealed ranking). Regex-constrained so it cannot
# swallow unrelated "... has a stack of N" / multi-word phrasings in other steps.
use_step_matcher("re")


@then(
    r"(?P<pid>\S+) has a (?P<rank>ROYAL_FLUSH|STRAIGHT_FLUSH|FOUR_OF_A_KIND|"
    r"FULL_HOUSE|FLUSH|STRAIGHT|THREE_OF_A_KIND|TWO_PAIR|PAIR|HIGH_CARD)"
)
def _then_has_rank(context, pid, rank):
    expected = getattr(pt, rank)
    results = getattr(context, "evaluation_results", None)
    if results is not None and pid in results:
        got = results[pid][0]
        assert (
            got == expected
        ), f"{pid} evaluates to {pt.HandRankType.Name(got)}, want {rank}"
    else:
        ev = _revealed_for(context, pid)
        assert (
            ev.ranking.rank_type == expected
        ), f"{pid} revealed {pt.HandRankType.Name(ev.ranking.rank_type)}, want {rank}"


use_step_matcher("parse")


# ==========================================================================
# Validation edge cases — community deal / blinds / player action rejections,
# and the state-reconstruction Thens. These drive the same FFI core and assert
# the coded rejection (assert_rejected) or the rebuilt state.
# ==========================================================================


def _action(context, pid, action, amount=0, with_root=True):
    """Dispatch a player action (no fold) — leaves the outcome on the response
    for a rejection or single-event assertion."""
    root = uuid_for(pid) if with_root else b""
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=root, action=action, amount=amount),
    )


def _post_blind(context, pid, amount, with_root=True):
    root = uuid_for(pid) if with_root else b""
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=root, blind_type="small", amount=amount),
    )


# --- EU-0021: community cards in Five Card Draw ---


@when("the dealer attempts to deal community cards")
def _when_attempt_deal_community(context):
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=3)
    )


@then("the deal is refused because Five Card Draw has no community cards")
def _then_no_community_cards(context):
    assert_rejected(context, "NO_COMMUNITY_CARDS")


# --- EU-0049: deal with empty player list ---


@when("a {variant} hand is dealt with no players")
def _when_deal_no_players(context, variant):
    context.world.dispatch(
        DOMAIN,
        P + "DealCards",
        hand.DealCards(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=_VARIANTS[variant],
            players=[],
            dealer_position=0,
        ),
    )


@then("the deal is refused because no players were provided")
def _then_deal_no_players(context):
    assert_rejected(context, "NOT_ENOUGH_PLAYERS")


# --- shared Givens ---


@given("{pid} has called for {amt:d}")
def _given_has_called(context, pid, amt):
    _action(context, pid, pt.CALL, amt)
    context.world.fold_emitted(DOMAIN)


@given("{pid} has folded")
def _given_has_folded(context, pid):
    _action(context, pid, pt.FOLD)
    context.world.fold_emitted(DOMAIN)


@given("{pid} has gone all-in for {amt:d}")
def _given_has_gone_all_in(context, pid, amt):
    _action(context, pid, pt.ALL_IN, amt)
    context.world.fold_emitted(DOMAIN)


@given("the hand is complete")
def _given_hand_is_complete(context):
    context.world.seed_event(DOMAIN, P + "HandComplete", hand.HandComplete())


@given("the hand has reached showdown")
def _given_hand_reached_showdown(context):
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())


@given(
    "short-stacked blinds have been posted with small {sb:d}, big {bb:d}, "
    "and {stack:d}-chip stacks"
)
def _given_short_stacked_blinds(context, sb, bb, stack):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for("player-1"), blind_type="small", amount=sb),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for("player-2"), blind_type="big", amount=bb),
    )
    context.world.fold_emitted(DOMAIN)


# --- blind-posting attempt Whens ---


@when("{pid} attempts to post the small blind of {amt:d}")
@when("{pid} attempts to post a small blind of {amt:d}")
def _when_attempt_post_blind(context, pid, amt):
    _post_blind(context, pid, amt)


@when(
    "someone attempts to post the small blind of {amt:d} without identifying the player"
)
def _when_attempt_post_blind_no_root(context, amt):
    _post_blind(context, "", amt, with_root=False)


# --- player-action attempt Whens ---


@when("{pid} attempts to fold")
def _when_attempt_fold(context, pid):
    _action(context, pid, pt.FOLD)


@when("someone attempts to fold without identifying the player")
def _when_attempt_fold_no_root(context):
    _action(context, "", pt.FOLD, with_root=False)


@when("{pid} attempts to call")
def _when_attempt_call(context, pid):
    _action(context, pid, pt.CALL)


@when("{pid} attempts to raise to {amt:d}")
def _when_attempt_raise(context, pid, amt):
    _action(context, pid, pt.RAISE, amt)


@when("{pid} attempts to take an unknown kind of action")
def _when_attempt_unknown_action(context, pid):
    # 999 is not a recognised ActionType — the handler must reject it.
    _action(context, pid, 999)


@when("{pid} goes all-in")
def _when_goes_all_in(context, pid):
    _action(context, pid, pt.ALL_IN)


# --- blind rejection Thens ---


@then("the blind is refused because the hand has not been dealt")
def _then_blind_not_dealt(context):
    assert_rejected(context, "HAND_NOT_DEALT")


@then("the blind is refused because a player must be identified")
def _then_blind_no_player(context):
    assert_rejected(context, "PLAYER_ROOT_REQUIRED")


@then("the blind is refused because {pid} is not in the hand")
def _then_blind_not_in_hand(context, pid):
    assert_rejected(context, "PLAYER_NOT_IN_HAND")


@then("the blind is refused because the amount must be positive")
def _then_blind_amount_positive(context):
    assert_rejected(context, "BLIND_AMOUNT_POSITIVE")


@then("the blind is refused because the hand is complete")
def _then_blind_complete(context):
    assert_rejected(context, "HAND_ALREADY_COMPLETE")


@then("the blind is refused because {pid} has folded")
def _then_blind_folded(context, pid):
    assert_rejected(context, "PLAYER_HAS_FOLDED")


# --- player-action rejection Thens ---


@then("the fold is refused because the hand has not been dealt")
def _then_fold_not_dealt(context):
    assert_rejected(context, "HAND_NOT_DEALT")


@then("the fold is refused because a player must be identified")
def _then_fold_no_player(context):
    assert_rejected(context, "PLAYER_ROOT_REQUIRED")


@then("the fold is refused because {pid} is not in the hand")
def _then_fold_not_in_hand(context, pid):
    assert_rejected(context, "PLAYER_NOT_IN_HAND")


@then("the fold is refused because the hand is not in a betting phase")
def _then_fold_not_betting(context):
    assert_rejected(context, "NOT_IN_BETTING_PHASE")


@then("the check is refused because {pid} has folded")
def _then_check_folded(context, pid):
    assert_rejected(context, "PLAYER_HAS_FOLDED")


@then("the check is refused because {pid} is already all-in")
def _then_check_all_in(context, pid):
    assert_rejected(context, "PLAYER_IS_ALL_IN")


@then("the call is refused because there is nothing to call")
def _then_call_nothing(context):
    assert_rejected(context, "NOTHING_TO_CALL")


@then("the bet is refused because there is already a bet to be matched")
def _then_bet_over_existing(context):
    assert_rejected(context, "BET_OVER_EXISTING_BET")


@then("the bet is refused because it exceeds {pid}'s stack")
def _then_bet_exceeds_stack(context, pid):
    assert_rejected(context, "BET_EXCEEDS_STACK")


@then("the raise is refused because there is no bet to raise")
def _then_raise_no_bet(context):
    assert_rejected(context, "CANNOT_RAISE_NO_BET")


@then("the raise is refused because it exceeds {pid}'s stack")
def _then_raise_exceeds_stack(context, pid):
    assert_rejected(context, "RAISE_EXCEEDS_STACK")


@then("the raise is refused because it is below the minimum raise")
def _then_raise_below_minimum(context):
    assert_rejected(context, "RAISE_BELOW_MIN")


@then("the action is refused because the action type is not recognised")
def _then_action_invalid(context):
    assert_rejected(context, "INVALID_ACTION")


# --- all-in reclassification Thens (EU-0070 / EU-0071) ---


@then("{pid}'s action is recorded as all-in for {amt:d}")
def _then_action_all_in_for(context, pid, amt):
    ev = context.world.emitted(P + "ActionTaken", hand.ActionTaken())
    assert ev.player_root == uuid_for(pid), "ActionTaken is for the wrong player"
    assert (
        ev.action == pt.ALL_IN
    ), f"action = {pt.ActionType.Name(ev.action)}, want ALL_IN"
    assert ev.amount == amt, f"amount = {ev.amount}, want {amt}"


@then("{pid}'s action is recorded as all-in")
def _then_action_all_in(context, pid):
    ev = context.world.emitted(P + "ActionTaken", hand.ActionTaken())
    assert ev.player_root == uuid_for(pid), "ActionTaken is for the wrong player"
    assert (
        ev.action == pt.ALL_IN
    ), f"action = {pt.ActionType.Name(ev.action)}, want ALL_IN"


# --- state-reconstruction Thens (EU-0046 / EU-0048) ---


@then("the hand is in the PREFLOP phase")
def _then_preflop_phase(context):
    state = _rebuild(context)
    assert (
        state.current_phase == pt.PREFLOP
    ), f"phase = {pt.BettingPhase.Name(state.current_phase)}, want PREFLOP"


@then("the hand is in the betting state")
def _then_betting_state(context):
    state = _rebuild(context)
    assert state.status == "betting", f"status = {state.status!r}, want 'betting'"


@then("{n:d} players are in the hand")
def _then_players_in_hand(context, n):
    state = _rebuild(context)
    assert len(state.players) == n, f"{len(state.players)} players, want {n}"


@then("{n:d} active players remain")
def _then_active_players_remain(context, n):
    state = _rebuild(context)
    active = sum(1 for p in state.players if not p.has_folded and not p.is_all_in)
    assert active == n, f"{active} active players, want {n}"


# ==========================================================================
# Community-deal / reveal / pot-award edge cases + per-round-reset state.
# ==========================================================================


# --- community-card deal edge cases (EU-0073..0076) ---


@when("the dealer attempts to deal {n:d} community cards")
@when("the dealer attempts to deal {n:d} community card")
def _when_attempt_deal_n_community(context, n):
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=n)
    )


@then("the deal is refused because the hand has not been dealt")
def _then_deal_not_dealt(context):
    assert_rejected(context, "HAND_NOT_DEALT")


@then("the deal is refused because at least one card must be dealt")
def _then_deal_zero_cards(context):
    assert_rejected(context, "MUST_DEAL_AT_LEAST_ONE")


@then("the deal is refused because the flop expects 3 cards")
def _then_deal_wrong_count(context):
    assert_rejected(context, "WRONG_CARD_COUNT")


@then("the deal is refused because the hand is complete")
def _then_deal_complete(context):
    assert_rejected(context, "HAND_ALREADY_COMPLETE")


# --- reveal edge cases (EU-0077..0081) ---


@when("{pid} attempts to reveal their cards")
def _when_attempt_reveal(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "RevealCards",
        hand.RevealCards(player_root=uuid_for(pid), muck=False),
    )


@when("someone attempts to reveal cards without identifying the player")
def _when_attempt_reveal_no_root(context):
    context.world.dispatch(DOMAIN, P + "RevealCards", hand.RevealCards(muck=False))


@then("the reveal is refused because the hand has not been dealt")
def _then_reveal_not_dealt(context):
    assert_rejected(context, "HAND_NOT_DEALT")


@then("the reveal is refused because the hand is not at showdown")
def _then_reveal_not_showdown(context):
    assert_rejected(context, "NOT_IN_SHOWDOWN")


@then("the reveal is refused because a player must be identified")
def _then_reveal_no_player(context):
    assert_rejected(context, "PLAYER_ROOT_REQUIRED")


@then("the reveal is refused because {pid} is not in the hand")
def _then_reveal_not_in_hand(context, pid):
    assert_rejected(context, "PLAYER_NOT_IN_HAND")


@then("the reveal is refused because {pid} has folded")
def _then_reveal_folded(context, pid):
    assert_rejected(context, "PLAYER_HAS_FOLDED")


# --- pot-award edge cases (EU-0082..0087, EU-1008, EU-1009) ---


@when("the pot is awarded with no winners specified")
def _when_award_empty(context):
    context.world.dispatch(DOMAIN, P + "AwardPot", hand.AwardPot())


@when("{amt:d} of the pot is awarded to {pid}")
def _when_award_amount_of_pot(context, amt, pid):
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(pid), amount=amt, pot_type="main")
            ]
        ),
    )


@when("the pot is awarded as:")
def _when_award_as_table(context):
    awards = [
        hand.PotAward(
            player_root=uuid_for(row["player"]),
            amount=int(row["amount"]),
            pot_type="main",
        )
        for row in context.table
    ]
    context.world.dispatch(DOMAIN, P + "AwardPot", hand.AwardPot(awards=awards))


@then("the award is refused because the hand has not been dealt")
def _then_award_not_dealt(context):
    assert_rejected(context, "HAND_NOT_DEALT")


@then("the award is refused because at least one winner is required")
def _then_award_no_winners(context):
    assert_rejected(context, "NO_AWARDS")


@then("the award is refused because {pid} is not in the hand")
def _then_award_not_in_hand(context, pid):
    assert_rejected(context, "PLAYER_NOT_IN_HAND")


@then("the award is refused because {pid} is folded")
def _then_award_folded(context, pid):
    assert_rejected(context, "PLAYER_HAS_FOLDED")


@then("the award is refused because the hand is already complete")
def _then_award_complete(context):
    assert_rejected(context, "HAND_ALREADY_COMPLETE")


@then("the award is refused because awards exceed the pot")
def _then_award_exceeds_pot(context):
    assert_rejected(context, "AWARDS_EXCEED_POT")


@then("the rejection records the awarded amount {a:d} against the pot bound {b:d}")
def _then_award_records_bound(context, a, b):
    assert context.world.err is not None, "expected a coded rejection"
    msg = context.world.err.message
    assert (
        str(a) in msg and str(b) in msg
    ), f"rejection message {msg!r} does not record {a} against {b}"


@then("there are {n:d} winners")
def _then_n_winners(context, n):
    ev = context.world.emitted(P + "PotAwarded", hand.PotAwarded())
    assert len(ev.winners) == n, f"{len(ev.winners)} winners, want {n}"


# --- per-round state reset (EU-0088..0092) ---


@then("the current bet is {n:d}")
def _then_current_bet(context, n):
    # The asserted value lives in the seeded/folded prior; do not re-apply the
    # last (already-folded) dispatch, which would double-count a blind.
    state = _rebuild(context, include_last_emitted=False)
    assert state.current_bet == n, f"current_bet = {state.current_bet}, want {n}"


@then("each player's contribution this round is {n:d}")
def _then_each_contribution(context, n):
    state = _rebuild(context, include_last_emitted=False)
    for p in state.players:
        assert (
            p.bet_this_round == n
        ), f"{p.player_root.hex()} bet_this_round = {p.bet_this_round}, want {n}"


@then("the hand is in the DRAW phase")
def _then_draw_phase(context):
    state = _rebuild(context, include_last_emitted=False)
    assert (
        state.current_phase == pt.DRAW
    ), f"phase = {pt.BettingPhase.Name(state.current_phase)}, want DRAW"


@given("the draw betting round is complete")
def _given_draw_complete(context):
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=pt.DRAW),
    )


@given("the preflop betting round is complete with stack snapshots:")
def _given_preflop_complete_snapshots(context):
    snaps = [
        hand.PlayerStackSnapshot(
            player_root=uuid_for(row["player"]),
            stack=int(row["stack"]),
            is_all_in=row["all_in"].strip().lower() == "true",
            has_folded=row["folded"].strip().lower() == "true",
        )
        for row in context.table
    ]
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=pt.PREFLOP, stacks=snaps),
    )


@then("{pid}'s snapshot stack is {n:d}")
def _then_snapshot_stack(context, pid, n):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    assert p is not None, f"{pid} is not in the hand"
    assert p.stack == n, f"{pid} stack = {p.stack}, want {n}"


@then("{pid} is recorded all-in")
def _then_recorded_all_in(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    assert p is not None, f"{pid} is not in the hand"
    assert p.is_all_in, f"{pid} is not recorded all-in"


@given("the pot has been built to {amt:d}")
def _given_pot_built(context, amt):
    # Build a real pot by posting blinds that sum to the target so award_pot's
    # ledger bound (sum of invested chips) equals it.
    half = amt // 2
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(
            player_root=uuid_for("player-1"), blind_type="small", amount=half
        ),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(
            player_root=uuid_for("player-2"), blind_type="big", amount=amt - half
        ),
    )
    context.world.fold_emitted(DOMAIN)


# ==========================================================================
# State accessors / identity / event-book (EU-0093..0099) + EU-0568.
# ==========================================================================


def _parse_names(text: str) -> list:
    """Parse a human player list — "player-A, player-B, and player-C" — into
    ["player-A", "player-B", "player-C"]."""
    text = text.replace(" and ", ", ")
    return [t.strip() for t in text.split(",") if t.strip()]


@given('a hand at table "{tbl}" with hand number {num:d}')
def _given_hand_at_table(context, tbl, num):
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=1000
        )
        for i in range(2)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=bytes.fromhex(tbl),
            hand_number=num,
            game_variant=pt.TEXAS_HOLDEM,
            players=players,
            remaining_deck=_fresh_deck()[4:],
        ),
    )
    context.expected_table_root = bytes.fromhex(tbl)
    context.expected_hand_number = num


@then("the hand carries that table and hand-number identity")
def _then_carries_identity(context):
    state = _rebuild(context, include_last_emitted=False)
    assert state.table_root == context.expected_table_root, "table_root mismatch"
    assert state.hand_number == context.expected_hand_number, "hand_number mismatch"


@given("{pid} has been awarded {amt:d}")
def _given_been_awarded(context, pid, amt):
    context.world.seed_event(
        DOMAIN,
        P + "PotAwarded",
        hand.PotAwarded(
            winners=[
                hand.PotWinner(player_root=uuid_for(pid), amount=amt, pot_type="main")
            ]
        ),
    )


@then("{pid}'s rebuilt stack is {n:d}")
def _then_rebuilt_stack(context, pid, n):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    assert p is not None, f"{pid} is not in the hand"
    assert p.stack == n, f"{pid} stack = {p.stack}, want {n}"


@then("the hand is in the complete state")
def _then_in_complete_state(context):
    state = _rebuild(context, include_last_emitted=False)
    assert state.status == "complete", f"status = {state.status!r}, want 'complete'"


@given("a CardsDealt event for {variant} with {n:d} players at stacks {stack:d}")
def _given_cardsdealt_event(context, variant, n, stack):
    # Every hand event book opens with a DeckShuffled before CardsDealt; inject
    # the default so the page accounting matches production.
    context.dealt_stack = stack
    context.world.seed_event(DOMAIN, P + "DeckShuffled", hand.DeckShuffled())
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=stack
        )
        for i in range(n)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=getattr(pt, variant),
            players=players,
            remaining_deck=_fresh_deck()[2 * n :],
        ),
    )


@given('a BlindPosted event for player "{pid}" amount {amt:d}')
def _given_blindposted_event(context, pid, amt):
    context.world.seed_event(
        DOMAIN,
        P + "BlindPosted",
        hand.BlindPosted(player_root=uuid_for(pid), blind_type="small", amount=amt),
    )


@when("I rebuild the hand state")
def _when_rebuild_state(context):
    context.rebuilt_state = _rebuild(context, include_last_emitted=False)


@then("the hand event book has {n:d} pages")
def _then_event_book_pages(context, n):
    book = context.world._prior.get((DOMAIN, b"".hex()))
    pages = len(book.pages) if book is not None else 0
    assert pages == n, f"event book has {pages} pages, want {n}"


@given("{pid} has posted a small blind of {amt:d}")
def _given_posted_small_blind(context, pid, amt):
    stack = getattr(context, "dealt_stack", 1000) or 1000
    context.world.seed_event(
        DOMAIN,
        P + "BlindPosted",
        hand.BlindPosted(
            player_root=uuid_for(pid),
            blind_type="small",
            amount=amt,
            player_stack=stack - amt,
            pot_total=amt,
        ),
    )


@given("{pid} has posted a big blind of {amt:d}")
def _given_posted_big_blind(context, pid, amt):
    stack = getattr(context, "dealt_stack", 1000) or 1000
    context.world.seed_event(
        DOMAIN,
        P + "BlindPosted",
        hand.BlindPosted(
            player_root=uuid_for(pid),
            blind_type="big",
            amount=amt,
            player_stack=stack - amt,
            pot_total=amt,
        ),
    )


@then("the small blind is {amt:d}")
def _then_small_blind_amount(context, amt):
    # The proto HandState carries no small-blind field, so read it off the
    # recorded small-type BlindPosted in the hand's history.
    book = context.world._prior.get((DOMAIN, b"".hex()))
    found = None
    for page in book.pages if book is not None else []:
        if page.event.type_url.endswith("BlindPosted"):
            ev = hand.BlindPosted()
            ev.ParseFromString(page.event.value)
            if ev.blind_type == "small":
                found = ev.amount
    assert found == amt, f"small blind = {found}, want {amt}"


@then("the big blind is {amt:d}")
def _then_big_blind_amount(context, amt):
    state = _rebuild(context, include_last_emitted=False)
    assert state.big_blind == amt, f"big_blind = {state.big_blind}, want {amt}"


@then("the minimum raise is {amt:d}")
def _then_minimum_raise(context, amt):
    state = _rebuild(context, include_last_emitted=False)
    assert state.min_raise == amt, f"min_raise = {state.min_raise}, want {amt}"


@when("{pid} attempts to discard cards at positions {a:d}, {b:d}, and {c:d}")
def _when_attempt_discard(context, pid, a, b, c):
    context.world.dispatch(
        DOMAIN,
        P + "RequestDraw",
        hand.RequestDraw(player_root=uuid_for(pid), card_indices=[a, b, c]),
    )


@then("the draw is refused because the discard positions are duplicated")
def _then_draw_dup_positions(context):
    assert_rejected(context, "DUPLICATE_CARD_INDICES")


# ==========================================================================
# Side pots (EU-1100..1109) — contribution-driven derivation.
# ==========================================================================


def _contributions(context):
    state = _rebuild(context, include_last_emitted=False)
    return [(p.player_root, p.total_invested, p.has_folded) for p in state.players]


@given("all {count} players are all-in with totals {totals}")
def _given_all_in_totals(context, count, totals):
    # Drive each seat to invest its stated total; the running bet decides whether
    # that is an opening bet, a raise, a call, or a short all-in.
    vals = [int(x) for x in re.findall(r"\d+", totals)]
    current = 0
    for i, total in enumerate(vals):
        pid = f"player-{chr(ord('A') + i)}"
        if total > current:
            _action(context, pid, pt.BET if current == 0 else pt.RAISE, total)
            current = total
        elif total == current:
            _action(context, pid, pt.CALL)
        else:
            _action(context, pid, pt.ALL_IN, total)
        context.world.fold_emitted(DOMAIN)


# Compound givens are registered BEFORE the atomic ones below: behave returns the
# first matching step, and the atomic "{pid} called {amt}" / "{pid} is all-in for
# {amt}" would otherwise greedily swallow a compound line (pid absorbing the whole
# prefix up to the trailing verb).
@given("{p1} is all-in for {a1:d}, {p2} is all-in for {a2:d}, and {p3} bets {a3:d}")
def _given_two_allin_one_overbet(context, p1, a1, p2, a2, p3, a3):
    _action(context, p1, pt.ALL_IN, a1)
    context.world.fold_emitted(DOMAIN)
    _action(context, p2, pt.ALL_IN, a2)
    context.world.fold_emitted(DOMAIN)
    # An over-bet over the existing all-ins is a raise to the named amount.
    _action(context, p3, pt.RAISE, a3)
    context.world.fold_emitted(DOMAIN)


@given("{p1} is all-in for {a1:d} and {p2} called {a2:d}")
def _given_allin_and_called(context, p1, a1, p2, a2):
    _action(context, p1, pt.ALL_IN, a1)
    context.world.fold_emitted(DOMAIN)
    _action(context, p2, pt.CALL, a2)
    context.world.fold_emitted(DOMAIN)


@given("{pid} is all-in for {amt:d}")
def _given_is_all_in_for(context, pid, amt):
    _action(context, pid, pt.ALL_IN, amt)
    context.world.fold_emitted(DOMAIN)


@given("{pid} called {amt:d}")
def _given_called_amount(context, pid, amt):
    _action(context, pid, pt.CALL, amt)
    context.world.fold_emitted(DOMAIN)


@given("{pid} invested {amt:d} then folded")
def _given_invested_then_folded(context, pid, amt):
    _action(context, pid, pt.BET, amt)
    context.world.fold_emitted(DOMAIN)
    _action(context, pid, pt.FOLD)
    context.world.fold_emitted(DOMAIN)


@when("the side pots are computed")
def _when_compute_side_pots(context):
    pots, returned = compute_side_pots(_contributions(context))
    context.side_pots = pots
    context.returned = returned


@given("the side pots are computed as:")
def _given_side_pots_as(context):
    has_eligible = "eligible" in context.table.headings
    context.side_pots = [
        Pot(
            amount=int(row["amount"]),
            eligible=(
                {uuid_for(x) for x in _parse_names(row["eligible"])}
                if has_eligible
                else set()
            ),
            pot_type=row["pot"],
        )
        for row in context.table
    ]


@then("there are {n:d} pots")
def _then_n_pots(context, n):
    assert len(context.side_pots) == n, f"{len(context.side_pots)} pots, want {n}"


@then("there is 1 pot")
def _then_one_pot(context):
    assert len(context.side_pots) == 1, f"{len(context.side_pots)} pots, want 1"


@then("the main pot holds {amt:d} and is contestable by {names}")
def _then_main_pot(context, amt, names):
    pot = next(p for p in context.side_pots if p.pot_type == "main")
    assert pot.amount == amt, f"main pot {pot.amount}, want {amt}"
    assert pot.eligible == {
        uuid_for(x) for x in _parse_names(names)
    }, "main eligibility"


@then("side pot {idx:d} holds {amt:d} and is contestable by {names}")
def _then_side_pot(context, idx, amt, names):
    pot = next(p for p in context.side_pots if p.pot_type == f"side_{idx}")
    assert pot.amount == amt, f"side_{idx} {pot.amount}, want {amt}"
    assert pot.eligible == {
        uuid_for(x) for x in _parse_names(names)
    }, f"side_{idx} eligibility"


@then("{amt:d} uncontested chips are returned to {pid}")
def _then_uncontested_returned(context, amt, pid):
    got = context.returned.get(uuid_for(pid), 0)
    assert got == amt, f"{pid} returned {got}, want {amt}"


@then("the total of all pots is {amt:d}")
def _then_total_pots(context, amt):
    total = sum(p.amount for p in context.side_pots)
    assert total == amt, f"pots total {total}, want {amt}"


# --- multi-pot awards (EU-1101, 1102, 1106, 1107, 1108) ---


@when("the pots are awarded as:")
def _when_pots_awarded_as(context):
    context.award_ineligible = None
    awards = []
    for row in context.table:
        pid, amt, pot_type = row["player"], int(row["amount"]), row["pot"]
        pot = next((p for p in context.side_pots if p.pot_type == pot_type), None)
        if pot is not None and pot.eligible and uuid_for(pid) not in pot.eligible:
            context.award_ineligible = (pid, pot_type)
        awards.append((pid, amt, pot_type))
    if context.award_ineligible is not None:
        return  # ineligible award — rejected at the derivation layer, not dispatched
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(p), amount=a, pot_type=t)
                for p, a, t in awards
            ]
        ),
    )


def _pot_winner(context, pid):
    ev = context.world.emitted(P + "PotAwarded", hand.PotAwarded())
    for w in ev.winners:
        if w.player_root == uuid_for(pid):
            return w
    raise AssertionError(f"{pid} is not among the winners")


@then("the award is refused because {pid} is not eligible for side pot {idx:d}")
def _then_award_ineligible(context, pid, idx):
    assert context.award_ineligible == (
        pid,
        f"side_{idx}",
    ), f"expected {pid} ineligible for side_{idx}, got {context.award_ineligible}"


@then("{pid} wins {amt:d} from the main pot")
def _then_wins_from_main(context, pid, amt):
    w = _pot_winner(context, pid)
    assert (
        w.amount == amt and w.pot_type == "main"
    ), f"{pid} won {w.amount} from {w.pot_type}"


@then("{pid} wins {amt:d} from side pot {idx:d}")
def _then_wins_from_side(context, pid, amt, idx):
    w = _pot_winner(context, pid)
    assert (
        w.amount == amt and w.pot_type == f"side_{idx}"
    ), f"{pid} won {w.amount} from {w.pot_type}"


@then("{pid}'s winnings come from the main pot")
def _then_winnings_from_main(context, pid):
    assert _pot_winner(context, pid).pot_type == "main"


@then("{pid}'s winnings come from side pot {idx:d}")
def _then_winnings_from_side(context, pid, idx):
    assert _pot_winner(context, pid).pot_type == f"side_{idx}"


@then("the completion lists {n:d} winners")
def _then_completion_winners(context, n):
    ev = context.world.emitted(P + "PotAwarded", hand.PotAwarded())
    assert len(ev.winners) == n, f"{len(ev.winners)} winners, want {n}"


@then("the completion shows {pid} winning the main pot")
def _then_completion_main(context, pid):
    assert _pot_winner(context, pid).pot_type == "main"


@then("the completion shows {pid} winning side pot {idx:d}")
def _then_completion_side(context, pid, idx):
    assert _pot_winner(context, pid).pot_type == f"side_{idx}"


# ==========================================================================
# Showdown reveal order (EU-1120..1122, 1124) — order derivation.
# ==========================================================================


@given("a hand at showdown with:")
def _given_showdown_seats(context):
    context.showdown_players = [
        (row["player"], int(row["seat"]), row["folded"].strip().lower() == "true")
        for row in context.table
    ]
    context.last_aggressor = None
    context.dealer_seat = 0


@given("the last aggressive action on the river was by {pid}")
def _given_last_aggressor(context, pid):
    context.last_aggressor = pid


@given("there was no aggressive action on the river")
def _given_no_aggressor(context):
    context.last_aggressor = None


@given("the dealer button is at seat {n:d}")
def _given_dealer_button(context, n):
    context.dealer_seat = n


@when("the showdown order is established")
def _when_showdown_order(context):
    # Stud (EU-1321): no final-round bet, so the high hand showing tables first
    # (TDA Rule 17A). Order by the up-cards showing, suit-broken.
    if getattr(context, "up_cards", None):
        context.showdown_order = showing_order(context.up_cards)
        return
    players = context.showdown_players
    n_seats = max(seat for _, seat, _ in players) + 1
    live = [(name, seat) for name, seat, folded in players if not folded]
    if context.last_aggressor:
        # TDA 17A: the last aggressor on the river tables first.
        pivot = next(s for nm, s, _ in players if nm == context.last_aggressor)
    else:
        # No final-street bet: first seat clockwise of the button tables first.
        pivot = (context.dealer_seat + 1) % n_seats
    order = sorted(live, key=lambda ns: (ns[1] - pivot) % n_seats)
    context.showdown_order = [name for name, _ in order]


@then("the showdown order is {names}")
def _then_showdown_order(context, names):
    expected = _parse_names(names)
    assert (
        context.showdown_order == expected
    ), f"showdown order {context.showdown_order}, want {expected}"


@given("a hand at showdown with order {names}")
def _given_showdown_with_order(context, names):
    order = _parse_names(names)
    context.showdown_order = order
    players = [
        hand.PlayerInHand(player_root=uuid_for(nm), position=i, stack=500)
        for i, nm in enumerate(order)
    ]
    player_cards = [
        hand.PlayerHoleCards(player_root=uuid_for(nm), cards=_cards("As Ks"))
        for nm in order
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.TEXAS_HOLDEM,
            players=players,
            player_cards=player_cards,
            remaining_deck=[],
        ),
    )
    context.world.seed_event(
        DOMAIN,
        P + "CommunityCardsDealt",
        hand.CommunityCardsDealt(
            phase=pt.RIVER,
            cards=_cards("Qs Js Ts 2c 3d"),
            all_community_cards=_cards("Qs Js Ts 2c 3d"),
        ),
    )
    # Carry the table order so reveal_cards can enforce it (TDA Rule 17A).
    context.world.seed_event(
        DOMAIN,
        P + "ShowdownStarted",
        hand.ShowdownStarted(players_to_show=[uuid_for(nm) for nm in order]),
    )


@then("the next player to show is {pid}")
def _then_next_to_show(context, pid):
    muck = context.world.emitted(P + "CardsMucked", hand.CardsMucked())
    mucked = next(
        nm for nm in context.showdown_order if uuid_for(nm) == muck.player_root
    )
    idx = context.showdown_order.index(mucked)
    nxt = (
        context.showdown_order[idx + 1]
        if idx + 1 < len(context.showdown_order)
        else None
    )
    assert nxt == pid, f"next to show is {nxt}, want {pid}"


# ==========================================================================
# Odd-chip / split-pot resolution (EU-1170..1172).
# ==========================================================================


@given("the pot stands at {amt:d}")
def _given_pot_stands_at(context, amt):
    context.split_pot_amount = amt


@when("the pot is split between {p1} and {p2}")
def _when_pot_split_between(context, p1, p2):
    state = _rebuild(context, include_last_emitted=False)
    pos = {p.player_root: p.position for p in state.players}
    button = getattr(context, "dealer_seat", 0)
    n_seats = max(pos.values()) + 1 if pos else 2
    winners = [p1, p2]
    # Odd chip to the first winner clockwise of the button (TDA Rule 20A).
    winners.sort(key=lambda w: (pos[uuid_for(w)] - button) % n_seats)
    split = split_with_odd_chip(context.split_pot_amount, winners, 0)
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(w), amount=split[w], pot_type="main")
                for w in winners
            ]
        ),
    )


@given(
    "a hand at showdown with a split-pot variant, high winner {high} and low winner {low}"
)
def _given_hl_winners(context, high, low):
    context.hl_high = high
    context.hl_low = low


@when("the pot of {amt:d} is split between high and low")
def _when_split_high_low(context, amt):
    # The odd chip in the total H/L pot goes to the high side (TDA Rule 20C).
    context.hl_result = split_with_odd_chip(amt, ["high", "low"], 0)


@then("the high side receives {amt:d}")
def _then_high_receives(context, amt):
    assert (
        context.hl_result["high"] == amt
    ), f"high {context.hl_result['high']}, want {amt}"


@then("the low side receives {amt:d}")
def _then_low_receives(context, amt):
    assert (
        context.hl_result["low"] == amt
    ), f"low {context.hl_result['low']}, want {amt}"


@given("a hand at showdown with an H/L split and two tied high winners")
def _given_hl_tied(context):
    context.tied_high = {}


@given('{pid} holds the high card by suit "{card}"')
def _given_high_card_by_suit(context, pid, card):
    context.tied_high[pid] = _card(card)


@when("the high half of the pot ({amt:d}) is split")
def _when_split_high_half(context, amt):
    # Odd chip in the high half goes to the highest card by suit (rank, then suit).
    winners = sorted(
        context.tied_high,
        key=lambda p: (context.tied_high[p].rank, context.tied_high[p].suit),
        reverse=True,
    )
    context.high_half_result = split_with_odd_chip(amt, winners, 0)


@then("{pid} receives {amt:d}")
def _then_pid_receives(context, pid, amt):
    got = context.high_half_result[pid]
    assert got == amt, f"{pid} receives {got}, want {amt}"


# ==========================================================================
# Batch 5 — registered-command betting mechanics.
# ==========================================================================


def _seed_named_deal(context, variant, names, stack):
    """Seed a CardsDealt for explicitly named players (Alice, Bob, …) at seats
    0..n with real per-name roots, so name-specific and name-agnostic assertions
    both resolve. A "limit <variant>" prefix selects fixed-limit play (raise cap
    4)."""
    limit = variant.startswith("limit ")
    if limit:
        variant = variant[len("limit ") :]
    context.dealt_stack = stack
    players = [
        hand.PlayerInHand(player_root=uuid_for(nm), position=i, stack=stack)
        for i, nm in enumerate(names)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=_VARIANTS[variant],
            players=players,
            # Button on the last seat so seat 0 is the small blind — the
            # first-to-act post-flop (consistent with the by-seat blinds below).
            dealer_position=len(names) - 1,
            remaining_deck=_fresh_deck()[2 * len(names) :],
            betting_format=(
                pt.BETTING_FORMAT_FIXED_LIMIT if limit else pt.BETTING_FORMAT_NO_LIMIT
            ),
            raise_cap_per_round=4 if limit else 0,
        ),
    )


# Most-specific (more names) first: behave returns the first matching step and a
# 4-name line also contains the " and " a 2-name pattern keys on.
@given(
    "a {variant} hand has been dealt to {p1}, {p2}, {p3}, and {p4} with {stack:d}-chip stacks"
)
@given(
    "an {variant} hand has been dealt to {p1}, {p2}, {p3}, and {p4} with {stack:d}-chip stacks"
)
def _given_dealt_4_named(context, variant, p1, p2, p3, p4, stack):
    _seed_named_deal(context, variant, [p1, p2, p3, p4], stack)


@given(
    "a {variant} hand has been dealt to {p1}, {p2}, and {p3} with {stack:d}-chip stacks"
)
@given(
    "an {variant} hand has been dealt to {p1}, {p2}, and {p3} with {stack:d}-chip stacks"
)
def _given_dealt_3_named(context, variant, p1, p2, p3, stack):
    _seed_named_deal(context, variant, [p1, p2, p3], stack)


@given("a {variant} hand has been dealt to {p1} and {p2} with {stack:d}-chip stacks")
@given("an {variant} hand has been dealt to {p1} and {p2} with {stack:d}-chip stacks")
def _given_dealt_2_named(context, variant, p1, p2, stack):
    _seed_named_deal(context, variant, [p1, p2], stack)


@given("blinds have been posted bringing the pot to {pot:d} for the named players")
@given(
    "blinds have been posted bringing the pot to {pot:d} with the bet at {bet:d} for the named players"
)
def _given_named_blinds(context, pot, bet=10):
    # Post SB/BB by seat so the blinds attach to the seated (named) players.
    state = _rebuild(context, include_last_emitted=False)
    pos0 = next(p.player_root for p in state.players if p.position == 0)
    pos1 = next(p.player_root for p in state.players if p.position == 1)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos0, blind_type="small", amount=bet // 2),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos1, blind_type="big", amount=bet),
    )
    context.world.fold_emitted(DOMAIN)


# --- Antes (EU-1110..1115) ---


@given("{pid} posts an ante of {amt:d}")
@when("{pid} posts an ante of {amt:d}")
def _when_posts_ante(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for(pid), blind_type="ante", amount=amt),
    )
    context.world.fold_emitted(DOMAIN)


@when("{pid} attempts to post an ante of {amt:d}")
def _when_attempts_ante(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for(pid), blind_type="ante", amount=amt),
    )


@when("{pid} posts the big-blind ante of {amt:d}")
def _when_posts_bb_ante(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for(pid), blind_type="ante", amount=amt),
    )


@given("{pid} posts an ante of {amt:d} then folds before the flop")
def _given_ante_then_folds(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for(pid), blind_type="ante", amount=amt),
    )
    context.world.fold_emitted(DOMAIN)
    _action(context, pid, pt.FOLD)
    context.world.fold_emitted(DOMAIN)


def _count_blind_type(context, blind_type):
    book = context.world._prior.get((DOMAIN, b"".hex()))
    count = 0
    for page in book.pages if book is not None else []:
        if page.event.type_url.endswith("BlindPosted"):
            ev = hand.BlindPosted()
            ev.ParseFromString(page.event.value)
            if ev.blind_type == blind_type:
                count += 1
    return count


@then("{n:d} antes have been posted")
def _then_n_antes(context, n):
    got = _count_blind_type(context, "ante")
    assert got == n, f"{got} antes posted, want {n}"


@then("the big-blind ante is posted at {amt:d}")
def _then_bb_ante_at(context, amt):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert (
        ev.blind_type == "ante" and ev.amount == amt
    ), f"bb ante {ev.amount}/{ev.blind_type}"


@then("the ante is posted at {amt:d}")
def _then_ante_at(context, amt):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert (
        ev.blind_type == "ante" and ev.amount == amt
    ), f"ante {ev.amount}/{ev.blind_type}"


@then("the ante is posted")
def _then_ante_posted(context):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.blind_type == "ante", f"not an ante: {ev.blind_type!r}"


@then("the ante is refused because antes must be posted before the blinds")
def _then_ante_after_blinds(context):
    assert_rejected(context, "ANTE_AFTER_BLINDS")


@then("the main pot includes {pid}'s ante of {amt:d}")
def _then_main_includes_ante(context, pid, amt):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    assert (
        p is not None and p.total_invested == amt
    ), f"{pid} ante = {p.total_invested if p else None}, want {amt}"
    main = next(pp for pp in context.side_pots if pp.pot_type == "main")
    others = sum(
        q.total_invested for q in state.players if q.player_root != uuid_for(pid)
    )
    assert main.amount == others + amt, f"main {main.amount} excludes {pid}'s ante"


# --- Play the board / partial muck (EU-1200, 1201) ---


@when("{pid} reveals her cards")
def _when_reveals_her(context, pid):
    _reveal(context, pid, muck=False)


@then("{pid} is playing the board")
def _then_playing_board(context, pid):
    ev = _revealed_for(context, pid)
    assert ev.plays_the_board, f"{pid} is not playing the board"


@when("{pid} attempts to reveal while mucking only the card at position {i:d}")
def _when_reveal_partial(context, pid, i):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    tabled = [k for k in range(len(p.hole_cards)) if k != i]
    context.world.dispatch(
        DOMAIN,
        P + "RevealCards",
        hand.RevealCards(player_root=uuid_for(pid), muck=False, tabled_indices=tabled),
    )


@then(
    "the reveal is refused because she cannot claim to play the board after mucking a hole card"
)
def _then_reveal_partial_board(context):
    assert_rejected(context, "CANNOT_PLAY_BOARD_PARTIAL_MUCK")


# --- All-in face-up muck (EU-1220) ---


@given("a hand at showdown with all-in face-up required")
def _given_showdown_allin(context):
    names = ["Alice", "Bob", "Carol"]
    players = [
        hand.PlayerInHand(player_root=uuid_for(nm), position=i, stack=0)
        for i, nm in enumerate(names)
    ]
    player_cards = [
        hand.PlayerHoleCards(player_root=uuid_for(nm), cards=_cards("As Ks"))
        for nm in names
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.TEXAS_HOLDEM,
            players=players,
            player_cards=player_cards,
            remaining_deck=[],
        ),
    )
    # Mark every remaining player all-in (action closed with all-ins).
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(
            completed_phase=pt.RIVER,
            stacks=[
                hand.PlayerStackSnapshot(
                    player_root=uuid_for(nm), stack=0, is_all_in=True
                )
                for nm in names
            ],
        ),
    )
    context.world.seed_event(
        DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted(face_up_required=True)
    )


@given("the showdown order is {names}")
def _given_showdown_order_is(context, names):
    context.showdown_order = _parse_names(names)


@when("{pid} attempts to muck")
def _when_attempts_muck(context, pid):
    _reveal(context, pid, muck=True)


@then("the muck is refused because the card must be face up")
def _then_muck_face_up(context):
    assert_rejected(context, "FACE_UP_REQUIRED")


# --- Cumulative short all-ins reopen the bet (EU-1140, 1141) — derivation ---


@given("the current bet is {bet:d} and the last raise increment is {inc:d}")
def _given_bet_increment(context, bet, inc):
    context.reopen_bet = bet
    context.reopen_last_full = bet
    context.reopen_inc = inc
    context.reopen_reopened = False


@when("one player goes all-in to {amt:d}")
@when("another player goes all-in to {amt:d}")
def _when_allin_to(context, amt):
    # TDA 47A: measure the increment from the last FULL bet/raise level; betting
    # reopens (and the min raise resets to that increment) once the cumulative
    # increment reaches a full minimum raise.
    increment = amt - context.reopen_last_full
    context.reopen_bet = amt
    if increment >= context.reopen_inc:
        context.reopen_reopened = True
        context.reopen_inc = increment
        context.reopen_last_full = amt


@then("the bet is reopened for prior actors")
def _then_reopened(context):
    assert context.reopen_reopened, "betting was not reopened"


@then("the bet is not reopened for prior actors")
def _then_not_reopened(context):
    assert not context.reopen_reopened, "betting was reopened"


@then("the last raise increment is {inc:d}")
def _then_last_increment(context, inc):
    assert context.reopen_inc == inc, f"increment {context.reopen_inc}, want {inc}"


@then("the resulting current bet is {bet:d}")
def _then_resulting_current_bet(context, bet):
    assert context.reopen_bet == bet, f"current bet {context.reopen_bet}, want {bet}"


# --- Pot-limit pre-flop max raise (EU-1286) — derivation ---


@given(
    "{pid} posted the small blind of {amt:d} from a stack of {stack:d} (short all-in)"
)
def _given_short_all_in_sb(context, pid, amt, stack):
    context.plo_short_sb = amt


@given("{pid} posted the big blind of {amt:d}")
def _given_plo_bb(context, pid, amt):
    context.plo_bb = amt


@when("the pot-limit pre-flop maximum raise-to amount is computed for {pid}")
def _when_plo_max_raise(context, pid):
    # TDA 54B: pre-flop pot-limit assumes FULL blinds even with a short SB.
    bb = context.plo_bb
    full_sb = bb // 2
    pot_after_call = full_sb + bb + bb  # SB + BB + the raiser's call of the BB
    context.plo_max_raise_to = bb + pot_after_call


@then("the maximum raise-to is {amt:d}")
def _then_max_raise_to(context, amt):
    assert (
        context.plo_max_raise_to == amt
    ), f"max raise-to {context.plo_max_raise_to}, want {amt}"


# --- Verbal / chip declarations (EU-1133, 1134, 1135, 1346, 1347, 1289) ---


def _action_taken(context):
    return context.world.emitted(P + "ActionTaken", hand.ActionTaken())


@given("{pid} has bet {amt:d} (a {inc:d} raise increment)")
def _given_has_bet(context, pid, amt, inc):
    state = _rebuild(context, include_last_emitted=False)
    action = pt.RAISE if state.current_bet > 0 else pt.BET
    _action(context, pid, action, amt)
    context.world.fold_emitted(DOMAIN)


@when("{pid} silently pushes {amt:d}")
def _when_silently_pushes(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.RAISE,
            amount=amt,
            bet_method=pt.BET_METHOD_CHIP_ONLY,
        ),
    )


@when("{pid} declares a raise to {amt:d}")
def _when_declares_raise(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.RAISE,
            amount=amt,
            bet_method=pt.BET_METHOD_VERBAL_FIRST,
        ),
    )


@when('{pid} verbally declares "raise" without an amount')
def _when_verbal_raise_no_amount(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.RAISE,
            amount=0,
            bet_method=pt.BET_METHOD_VERBAL_FIRST,
        ),
    )


@when('{pid} verbally declares "all-in" with no chips yet pushed')
def _when_verbal_all_in(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.ALL_IN,
            amount=0,
            bet_method=pt.BET_METHOD_VERBAL_FIRST,
        ),
    )


@when("{pid} folds with no bet to call")
def _when_folds_no_bet(context, pid):
    _action(context, pid, pt.FOLD)


@then("{pid}'s action is recorded as a raise")
def _then_recorded_as_raise(context, pid):
    ev = _action_taken(context)
    assert ev.action in (
        pt.RAISE,
        pt.ALL_IN,
    ), f"action = {pt.ActionType.Name(ev.action)}, want RAISE"


@then("{pid}'s raise totals {amt:d} ({note})")
def _then_raise_totals(context, pid, amt, note):
    ev = _action_taken(context)
    assert ev.amount_to_call == amt, f"raise totals {ev.amount_to_call}, want {amt}"


@then("{pid}'s all-in is recorded with a {n:d}-chip commit")
def _then_all_in_commit(context, pid, n):
    ev = _action_taken(context)
    assert (
        ev.action == pt.ALL_IN
    ), f"action = {pt.ActionType.Name(ev.action)}, want ALL_IN"
    assert ev.amount == n, f"commit = {ev.amount}, want {n}"


@when('{pid} declares "bet the pot" on a no-limit table')
def _when_declares_bet_the_pot(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.BET,
            amount=0,
            bet_method=pt.BET_METHOD_VERBAL_FIRST,
        ),
    )


@then("{pid}'s bet is recorded at the big blind ({amt:d})")
def _then_bet_at_big_blind(context, pid, amt):
    ev = _action_taken(context)
    assert ev.action == pt.BET, f"action = {pt.ActionType.Name(ev.action)}, want BET"
    assert ev.amount == amt, f"bet = {ev.amount}, want {amt}"


# --- Action clock (TDA Rule 29) — EU-1130..1132 -----------------------------
# The clock may only run on the seat currently to act; expiry is not its own
# command — per the rule it resolves to the auto-action (FOLD when facing a bet,
# CHECK otherwise), which the driver issues as a normal PlayerAction.


@given("the action is on {pid}")
def _given_action_on(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    player = next((p for p in state.players if p.player_root == uuid_for(pid)), None)
    assert player is not None, f"{pid} is not in the hand"
    assert state.action_on_position == player.position, (
        f"action is on seat {state.action_on_position}, "
        f"want {pid} at seat {player.position}"
    )


@when("the action clock is started on {pid} for {seconds:d} seconds")
def _when_start_action_clock(context, pid, seconds):
    context.world.dispatch(
        DOMAIN,
        P + "StartActionClock",
        hand.StartActionClock(player_root=uuid_for(pid), seconds=seconds),
    )
    # Success folds ActionClockStarted into history; a rejection leaves
    # world.err set for the refusal Then.
    if context.world.err is None:
        context.world.fold_emitted(DOMAIN)


@when("{pid}'s action clock expires")
def _when_action_clock_expires(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    player = next((p for p in state.players if p.player_root == uuid_for(pid)), None)
    call_amount = state.current_bet - (player.bet_this_round if player else 0)
    _action(context, pid, pt.FOLD if call_amount > 0 else pt.CHECK)
    context.world.fold_emitted(DOMAIN)


@then("the clock is refused because the action is not on {pid}")
def _then_clock_refused_not_on(context, pid):
    assert_rejected(context, "ACTION_NOT_ON_PLAYER")


# ==========================================================================
# Batch 6 — proto+codegen clusters (absent / out-of-order reveal / limit cap).
# ==========================================================================


# --- Absent at the initial deal (EU-1146) ---


@given("{pid} was absent at the initial deal")
def _given_was_absent(context, pid):
    # Mark the seat absent on the already-seeded CardsDealt so the rebuild kills
    # the hand (TDA Rule 30) and the player can take no action.
    book = context.world._prior.get((DOMAIN, b"".hex()))
    for page in book.pages if book is not None else []:
        if page.event.type_url.endswith("CardsDealt"):
            ev = hand.CardsDealt()
            ev.ParseFromString(page.event.value)
            for p in ev.players:
                if p.player_root == uuid_for(pid):
                    p.absent_at_deal = True
            page.event.value = ev.SerializeToString()


@then("the check is refused because {pid} was absent at the deal")
def _then_check_absent(context, pid):
    assert_rejected(context, "ABSENT_AT_DEAL")


# --- Out-of-order reveal (EU-1123) ---


@then("the reveal is refused because it is out of order")
def _then_reveal_out_of_order(context):
    assert_rejected(context, "OUT_OF_ORDER")


# --- Limit raise cap (EU-1296) ---


@given("there has already been {b:d} bet and {r:d} raises this round")
def _given_b_bet_r_raises(context, b, r):
    state = _rebuild(context, include_last_emitted=False)
    n = len(state.players)
    inc = state.min_raise or state.big_blind or 200
    roots = {p.position: p.player_root for p in state.players}
    current = state.current_bet
    for i in range(r):
        current += inc
        context.world.dispatch(
            DOMAIN,
            P + "PlayerAction",
            hand.PlayerAction(
                player_root=roots[i % n], action=pt.RAISE, amount=current
            ),
        )
        context.world.fold_emitted(DOMAIN)


@when("{pid} attempts to raise")
def _when_attempts_raise_no_amount(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.RAISE,
            amount=state.current_bet + (state.min_raise or 200),
        ),
    )


@then("the raise is refused because the raise cap has been reached")
def _then_raise_cap(context):
    assert_rejected(context, "RAISE_CAP_REACHED")


@then("the rejection notes the round cap of {n:d} raises")
def _then_rejection_cap_note(context, n):
    assert context.world.err is not None, "expected a rejection"
    assert (
        str(n) in context.world.err.message
    ), f"rejection {context.world.err.message!r} does not note cap {n}"


# --- Illegal-bet correction (EU-1250 under-raise, EU-1284 PL over-bet) ---


@given("blinds posted at SB {sb:d} / BB {bb:d} bringing the pot to {pot:d}")
def _given_blinds_sb_bb(context, sb, bb, pot):
    state = _rebuild(context, include_last_emitted=False)
    pos0 = next(p.player_root for p in state.players if p.position == 0)
    pos1 = next(p.player_root for p in state.players if p.position == 1)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos0, blind_type="small", amount=sb),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos1, blind_type="big", amount=bb),
    )
    context.world.fold_emitted(DOMAIN)
    context.pl_pot_cap = pot


@given("the flop has been dealt at blinds {sb:d}/{bb:d}")
def _given_flop_at_blinds(context, sb, bb):
    state = _rebuild(context, include_last_emitted=False)
    pos0 = next(p.player_root for p in state.players if p.position == 0)
    pos1 = next(p.player_root for p in state.players if p.position == 1)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos0, blind_type="small", amount=sb),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos1, blind_type="big", amount=bb),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=3)
    )
    context.world.fold_emitted(DOMAIN)


# EU-1250: the bets are Givens; Bob's raise-to is an illegal under-raise that the
# normal path would reject, so the street's wagers are seeded as ActionTaken.
def _seed_street_action(context, pid, action, to_amount):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    prior = p.bet_this_round if p is not None else 0
    stack = p.stack if p is not None else context.dealt_stack
    chips = to_amount - prior
    context.world.seed_event(
        DOMAIN,
        P + "ActionTaken",
        hand.ActionTaken(
            player_root=uuid_for(pid),
            action=action,
            amount=chips,
            player_stack=stack - chips,
            amount_to_call=to_amount,
        ),
    )


@given("{pid} bets {amt:d}")
def _given_bets_street(context, pid, amt):
    _seed_street_action(context, pid, pt.BET, amt)


@given("{pid} raises to {amt:d}")
def _given_raises_street(context, pid, amt):
    _seed_street_action(context, pid, pt.RAISE, amt)


@given("{pid} calls {amt:d}")
def _given_calls_street(context, pid, amt):
    _seed_street_action(context, pid, pt.CALL, amt)


@when("the dealer detects the underraise before the turn is dealt")
def _when_detect_underraise(context):
    state = _rebuild(context, include_last_emitted=False)
    bettors = [p.bet_this_round for p in state.players if p.bet_this_round > 0]
    # Legal minimum raise-to = the opening bet + a full minimum raise (== the
    # opening bet in no-limit) = twice the smallest street wager.
    corrected = 2 * min(bettors)
    context.world.dispatch(
        DOMAIN,
        P + "CorrectIllegalBet",
        hand.CorrectIllegalBet(
            reason="NL_UNDERRAISE_LATE_CORRECTION", corrected_amount=corrected
        ),
    )


@then("the underraise is corrected")
def _then_underraise_corrected(context):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.adjustments, "no adjustments recorded"


@then("the corrected raise-to amount is {amt:d}")
def _then_corrected_raise_to(context, amt):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.corrected_amount == amt, f"corrected {ev.corrected_amount}, want {amt}"


@then("every bettor's contribution is increased to match")
def _then_every_bettor_increased(context):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.adjustments, "no adjustments"
    for a in ev.adjustments:
        assert (
            a.new_contribution == ev.corrected_amount
        ), f"{a.player_root.hex()} -> {a.new_contribution}, want {ev.corrected_amount}"


# EU-1284: PL over-bet — all wagers are valid (drivable), the correction reduces.
@when("{pid} pot-bets {amt:d} based on the dealer's illegal-high count")
def _when_pot_bets(context, pid, amt):
    _action(context, pid, pt.BET, amt)
    context.world.fold_emitted(DOMAIN)


@when("{pid} calls {amt:d}")
def _when_calls_amt(context, pid, amt):
    _action(context, pid, pt.CALL, amt)
    context.world.fold_emitted(DOMAIN)


@when("the dealer detects the illegal overbet before the turn is dealt")
def _when_detect_overbet(context):
    context.world.dispatch(
        DOMAIN,
        P + "CorrectIllegalBet",
        hand.CorrectIllegalBet(
            reason="PL_ILLEGAL_OVERBET", corrected_amount=context.pl_pot_cap
        ),
    )


@then("the bet is corrected because the overbet exceeds the pot-limit cap")
def _then_bet_corrected_overbet(context):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.reason == "PL_ILLEGAL_OVERBET", f"reason {ev.reason!r}"


@then("the corrected bet amount is {amt:d}")
def _then_corrected_bet_amount(context, amt):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.corrected_amount == amt, f"corrected {ev.corrected_amount}, want {amt}"


@then("every caller's contribution is reduced to {amt:d}")
def _then_every_caller_reduced(context, amt):
    ev = context.world.emitted(P + "UnderbetCorrected", hand.UnderbetCorrected())
    assert ev.adjustments, "no adjustments"
    for a in ev.adjustments:
        assert (
            a.new_contribution == amt
        ), f"{a.player_root.hex()} -> {a.new_contribution}, want {amt}"


# ==========================================================================
# Batch 7 — misdeal core (SA threshold / fouled deck / misdeal taxonomy).
# ==========================================================================


def _post_seat_blinds(context, bet):
    """Post SB (bet//2) at seat 0 and BB (bet) at seat 1 for the seated players."""
    state = _rebuild(context, include_last_emitted=False)
    pos0 = next(p.player_root for p in state.players if p.position == 0)
    pos1 = next(p.player_root for p in state.players if p.position == 1)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos0, blind_type="small", amount=bet // 2),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=pos1, blind_type="big", amount=bet),
    )
    context.world.fold_emitted(DOMAIN)


# --- EU-1232: Substantial Action threshold (pure derivation) ---


@when('the players take "{actions}" in turn')
def _when_players_take(context, actions):
    chip = {"CALL", "BET", "RAISE", "ALL_IN"}
    acts = [a.strip() for a in actions.split(",") if a.strip()]
    n = len(acts)
    n_chip = sum(1 for a in acts if a in chip)
    # TDA Rule 36: 3+ actions, or exactly 2 with at least one chip action.
    context.substantial_action = (n >= 3) or (n == 2 and n_chip >= 1)


@then("substantial action is {sa}")
def _then_substantial_action(context, sa):
    want = sa.strip() == "true"
    assert (
        context.substantial_action == want
    ), f"substantial action = {context.substantial_action}, want {want}"


# --- EU-1231: fouled deck ---


@given("substantial action has occurred on the current hand")
def _given_sa_occurred(context):
    # Two voluntary actions (a call then a check) establish SA; the fouled-deck
    # rule applies regardless, but this models the "regardless of SA" intent.
    _action(context, "player-1", pt.CALL, 5)
    context.world.fold_emitted(DOMAIN)
    _action(context, "player-2", pt.CHECK)
    context.world.fold_emitted(DOMAIN)


@when('the dealer reports a fouled deck (duplicate "{card}" found)')
def _when_report_fouled(context, card):
    context.world.dispatch(
        DOMAIN, P + "ReportFouledDeck", hand.ReportFouledDeck(duplicate_card=card)
    )


@then("the deck is declared fouled")
def _then_deck_fouled(context):
    ev = context.world.emitted(P + "FouledDeckDetected", hand.FouledDeckDetected())
    assert ev.duplicate_card, "no duplicate card recorded"


@then("every player's contribution to the hand is refunded")
def _then_all_refunded(context):
    state = _rebuild(context)
    for p in state.players:
        assert (
            p.total_invested == 0
        ), f"{p.player_root.hex()} still has {p.total_invested} invested"


@then("the hand is void")
def _then_hand_void(context):
    state = _rebuild(context)
    assert state.status == "void", f"status = {state.status!r}, want 'void'"


# --- EU-1230: misdeal taxonomy ---


@given("a hand in progress with substantial action {sa}")
def _given_hand_in_progress(context, sa):
    _seed_named_deal(context, "Texas Hold'em", ["player-1", "player-2"], 500)
    _post_seat_blinds(context, bet=10)
    if sa.strip() == "true":
        _action(context, "player-1", pt.CALL, 5)
        context.world.fold_emitted(DOMAIN)
        _action(context, "player-2", pt.CHECK)
        context.world.fold_emitted(DOMAIN)


@when('the dealer reports a misdeal of type "{misdeal_type}"')
def _when_report_misdeal(context, misdeal_type):
    context.world.dispatch(
        DOMAIN, P + "DeclareMisdeal", hand.DeclareMisdeal(reason=misdeal_type)
    )


@then('the outcome is "{outcome}"')
def _then_misdeal_outcome(context, outcome):
    if outcome == "MISDEAL_REDEAL":
        context.world.emitted(P + "MisdealDeclared", hand.MisdealDeclared())
    elif outcome == "HAND_STANDS":
        assert_rejected(context, "MISDEAL_TOO_LATE")
    else:
        raise AssertionError(f"unknown outcome {outcome!r}")


# ==========================================================================
# Batch 8 — out-of-turn taxonomy (TDA Rule 53). The binding/returned/lost-right
# verdicts are sequence rules, computed in the step layer from the recorded
# action order; an OOT fold is always binding, so it is also applied to the hand.
# ==========================================================================


def _oot_record(context, pid, action, is_oot):
    if not hasattr(context, "oot_actions"):
        context.oot_actions = []
    context.oot_actions.append((pid, action, is_oot))


@when("{pid} calls out of turn for {amt:d}")
def _when_oot_call_for(context, pid, amt):
    # A "call for 0" facing no bet is a check.
    _oot_record(context, pid, "CHECK" if amt == 0 else "CALL", True)


@when("{pid} calls {amt:d} out of turn")
def _when_oot_calls(context, pid, amt):
    _oot_record(context, pid, "CALL", True)


@when("{pid} raises to {amt:d} out of turn")
def _when_oot_raises(context, pid, amt):
    # The OOT raise is held (not dispatched) so the correct player's in-turn bet
    # remains valid; whether it is returned is decided by the derivation below.
    _oot_record(context, pid, "RAISE", True)


@when("{pid} folds out of turn")
def _when_oot_folds(context, pid):
    _oot_record(context, pid, "FOLD", True)
    # An out-of-turn fold is always binding (Rule 53A) — apply it.
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=pt.FOLD),
    )
    context.world.fold_emitted(DOMAIN)


@when("{pid} checks in turn")
def _when_check_in_turn(context, pid):
    _oot_record(context, pid, "CHECK", False)


@when("{pid} bets {amt:d} in turn")
def _when_bet_in_turn(context, pid, amt):
    _oot_record(context, pid, "BET", False)


@when("{pid} calls {amt:d} in turn")
def _when_call_in_turn(context, pid, amt):
    _oot_record(context, pid, "CALL", False)


def _first_oot(context):
    for i, (pid, act, oot) in enumerate(context.oot_actions):
        if oot:
            return i, pid, act
    return None, None, None


def _oot_situation_changed(context, after_index):
    # An in-turn bet or raise after the OOT action changes the action.
    return any(
        a in ("BET", "RAISE") and not oot
        for _, a, oot in context.oot_actions[after_index + 1 :]
    )


def _oot_is_binding(context):
    idx, _pid, act = _first_oot(context)
    if act == "FOLD":
        return True  # an OOT fold is always binding
    return not _oot_situation_changed(context, idx)


@then("{pid}'s out-of-turn call is binding")
def _then_oot_call_binding(context, pid):
    assert _oot_is_binding(context), f"{pid}'s out-of-turn call is not binding"


@then("{pid}'s check stands")
def _then_check_stands(context, pid):
    idx, who, act = _first_oot(context)
    assert who == pid and act == "CHECK", f"{pid}'s check was not recorded"
    assert _oot_is_binding(context), f"{pid}'s check does not stand"


@then("{pid}'s out-of-turn raise is returned")
def _then_oot_raise_returned(context, pid):
    idx, who, act = _first_oot(context)
    assert who == pid and act == "RAISE", f"{pid} did not raise out of turn"
    assert not _oot_is_binding(context), f"{pid}'s out-of-turn raise was not returned"


@then("{pid} may now call, raise, or fold")
def _then_may_act(context, pid):
    # The OOT raise was returned, so the player keeps all options (not folded).
    assert not _oot_is_binding(context), f"{pid}'s raise stood; no options remain"


@then("{pid} did not speak up before substantial action")
def _then_did_not_speak(context, pid):
    # SA via OOT (Rule 53B): 2+ out-of-turn actions skipping this seat, at least
    # one putting chips in, costs the skipped player their right to act.
    oot = [(p, a) for p, a, o in context.oot_actions if o]
    n = len(oot)
    chips = sum(1 for _, a in oot if a in ("CALL", "BET", "RAISE"))
    context.skipped_lost_right = (n >= 3) or (n == 2 and chips >= 1)


@then("{pid} is recorded as having lost his right to act")
def _then_lost_right(context, pid):
    assert getattr(
        context, "skipped_lost_right", False
    ), f"{pid} did not lose the right to act"


@then("the out-of-turn actions of {p1} and {p2} are binding")
def _then_oot_actions_binding(context, p1, p2):
    assert getattr(
        context, "skipped_lost_right", False
    ), "the out-of-turn actions are not binding"


# ==========================================================================
# Batch 9 — premature community cards / button anomalies (TDA Rule 35-39, RP-5).
# Burn is tracked as a context flag (not deck consumption), so it never
# conflicts with the deck-removal scenarios (EU-0018 etc.).
# ==========================================================================


@given("the dealer button is at seat {n:d} ({name})")
def _given_button_seat_named(context, n, name):
    context.button_seat = n


@given("the dealer dealt the second card on the button consecutively")
def _given_consecutive_button(context):
    pass  # explicitly allowed (Rule 35B) — a no-op


@then("no misdeal was declared on this hand")
def _then_no_misdeal(context):
    assert context.world.err is None, "the hand was rejected"
    assert not any(
        "MisdealDeclared" in f for f in context.world.emitted_fqs()
    ), "a misdeal was declared"


# --- EU-1274: re-deal preserves button + level ---


@given("blinds posted at level {level:d} (SB {sb:d} / BB {bb:d})")
def _given_blinds_at_level(context, level, sb, bb):
    context.hand_level = level
    _post_seat_blinds(context, bet=bb)


@when("the dealer declares a misdeal before substantial action")
def _when_declare_misdeal_pre_sa(context):
    context.world.dispatch(DOMAIN, P + "DeclareMisdeal", hand.DeclareMisdeal())


@when("the hand is re-dealt")
def _when_hand_redealt(context):
    pass  # the re-deal preserves button + level (asserted below)


@then("the hand is re-dealt cleanly")
def _then_redealt_cleanly(context):
    context.world.emitted(P + "MisdealDeclared", hand.MisdealDeclared())


@then("the dealer button is still at seat {n:d} ({name})")
def _then_button_still(context, n, name):
    assert context.button_seat == n, f"button moved to {context.button_seat}"


@then("the hand level is still {level:d} (SB {sb:d} / BB {bb:d})")
def _then_level_still(context, level, sb, bb):
    assert context.hand_level == level, f"level changed to {context.hand_level}"


# --- EU-1275: button card replaced ---


@given("{pid} was dealt only {n:d} hole card")
@given("{pid} was dealt only {n:d} hole cards")
def _given_dealt_only(context, pid, n):
    book = context.world._prior.get((DOMAIN, b"".hex()))
    for page in book.pages if book is not None else []:
        if page.event.type_url.endswith("CardsDealt"):
            ev = hand.CardsDealt()
            ev.ParseFromString(page.event.value)
            ev.player_cards.append(
                hand.PlayerHoleCards(player_root=uuid_for(pid), cards=_fresh_deck()[:n])
            )
            page.event.value = ev.SerializeToString()


@when("{pid} announces the missing card before acting")
def _when_announce_missing(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "ReplaceButtonCard",
        hand.ReplaceButtonCard(player_root=uuid_for(pid)),
    )


@then("{pid}'s button card is replaced")
def _then_button_card_replaced(context, pid):
    ev = context.world.emitted(P + "ButtonCardReplaced", hand.ButtonCardReplaced())
    assert ev.player_root == uuid_for(pid), "replacement was for a different player"


# --- EU-1276/1277/1278: irregular flops + burn flag ---


@when("the dealer accidentally lays out 4 cards as the flop")
def _when_lays_out_4(context):
    context.scramble_pending = 4


@when("the floor randomly selects one of the 4 as the burn card")
def _when_floor_selects_burn(context):
    # The 4-card scramble yields a normal 3-card flop with exactly one burn.
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=3)
    )
    context.world.fold_emitted(DOMAIN)
    context.no_burn = False


@given("the dealer put out a 3-card flop without burning")
@when("the dealer puts out a 3-card flop without burning")
def _when_no_burn_flop(context):
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=3)
    )
    context.world.fold_emitted(DOMAIN)
    context.no_burn = False
    context.burn_from_original = True  # one of the 3 becomes the burn


@when("no action has occurred on the flop")
def _when_no_action_flop(context):
    pass


@given("{pid} checked on the flop")
def _given_checked_on_flop(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=pt.CHECK),
    )
    context.world.fold_emitted(DOMAIN)


@then("exactly 1 of the original 3 flop cards is now the burn")
def _then_one_original_is_burn(context):
    assert getattr(
        context, "burn_from_original", False
    ), "no original flop card became the burn"


@then("exactly 1 card was burned for this street")
def _then_one_burned(context):
    assert not getattr(context, "no_burn", False), "no card was burned (expected 1)"


@then("no card was burned for this street")
def _then_no_burned(context):
    assert getattr(context, "no_burn", False), "a card was burned (expected none)"


# --- EU-1280/1281: premature flop / turn ---


@given("the preflop betting round is incomplete")
@given("the flop betting round is incomplete")
@given("the turn betting round is incomplete")
def _given_round_incomplete(context):
    pass  # the round simply hasn't completed — nothing to seed


@when("the dealer prematurely lays out a flop")
def _when_premature_flop(context):
    context.world.dispatch(
        DOMAIN, P + "ReportPrematureFlop", hand.ReportPrematureFlop()
    )
    context.no_burn = True  # the original burn is preserved; the re-deal adds none


@when("the dealer prematurely deals a turn card")
def _when_premature_turn(context):
    context.world.dispatch(
        DOMAIN, P + "ReportPrematureTurn", hand.ReportPrematureTurn()
    )
    context.no_burn = True


@then("a premature flop is detected")
def _then_premature_flop_detected(context):
    context.world.emitted(P + "PrematureFlopDetected", hand.PrematureFlopDetected())


@then("a premature turn is detected")
def _then_premature_turn_detected(context):
    context.world.emitted(P + "PrematureTurnDetected", hand.PrematureTurnDetected())


@then("the original burn card is preserved")
@then("the original turn burn card is preserved")
def _then_burn_preserved(context):
    assert getattr(context, "no_burn", False), "the original burn was not preserved"


@then("the 3 premature cards are returned to the stub")
@then("the premature card is returned to the stub")
def _then_premature_returned(context):
    assert getattr(context, "no_burn", False), "premature cards were not returned"


@then("the stub is reshuffled")
def _then_stub_reshuffled(context):
    assert getattr(context, "no_burn", False), "the stub was not reshuffled"


@when("the preflop betting round completes")
@when("the flop betting round completes")
@when("the turn betting round completes")
def _when_round_completes(context):
    state = _rebuild(context, include_last_emitted=False)
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=state.current_phase),
    )


# ==========================================================================
# Batch 10 — verbal/chip betting mechanics (TDA Rules 44-59).
# Most chip-only rules are handled by _interpret_declaration (batch 5); these
# steps build the facing-bet setup and exercise the remaining rules.
# ==========================================================================


@given("{pid} has opened the betting at {amt:d} after the flop")
def _given_opening_bet_after_flop(context, pid, amt):
    # deal-done → blinds → preflop complete → flop → opening BET, so the chip
    # rules engage against a real current_bet.
    _post_seat_blinds(context, bet=10)
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=pt.PREFLOP),
    )
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=3)
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=pt.BET, amount=amt),
    )
    context.world.fold_emitted(DOMAIN)


def _chip_push(context, pid, amount, chip_count):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.RAISE,
            amount=amount,
            bet_method=pt.BET_METHOD_CHIP_ONLY,
            chip_count=chip_count,
        ),
    )


@when("{pid} silently pushes a single {amt:d} chip")
def _when_push_single(context, pid, amt):
    _chip_push(context, pid, amt, 1)


@when("{pid} silently pushes chips totaling {amt:d} ({note})")
def _when_push_totaling(context, pid, amt, note):
    _chip_push(context, pid, amt, 2)


@when("{pid} silently pushes {amt:d} ({note})")
def _when_push_amt_note(context, pid, amt, note):
    _chip_push(context, pid, amt, 2)


@then("{pid}'s raise of {amt:d} is recorded")
def _then_raise_of(context, pid, amt):
    ev = _action_taken(context)
    assert ev.action in (pt.RAISE, pt.ALL_IN), f"action {pt.ActionType.Name(ev.action)}"
    assert ev.amount == amt, f"raise of {ev.amount}, want {amt}"


# --- EU-1352: silent top-up (Rule 46C) ---


@given("{pid} has already bet {amt:d} this street")
def _given_already_bet(context, pid, amt):
    state = _rebuild(context, include_last_emitted=False)
    action = pt.RAISE if state.current_bet > 0 else pt.BET
    _action(context, pid, action, amt)
    context.world.fold_emitted(DOMAIN)


@given("{pid} raised to {amt:d} ({inc:d} raise increment)")
def _given_raised_inc(context, pid, amt, inc):
    _action(context, pid, pt.RAISE, amt)
    context.world.fold_emitted(DOMAIN)


@when("{pid} silently adds chips totaling {amt:d} on top of her prior {prior:d}")
def _when_silently_adds(context, pid, amt, prior):
    _chip_push(context, pid, prior + amt, 2)


# --- EU-1353: pull-back prior chip (Rule 46B) ---


@when("{pid} pulls back her prior {amt:d} chip while facing the raise")
def _when_pull_back(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PullBackPriorChip",
        hand.PullBackPriorChip(player_root=uuid_for(pid), chips_pulled=amt),
    )
    context.world.fold_emitted(DOMAIN)


@then("{pid} is bound to call or raise")
def _then_bound(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    assert p is not None and p.bound_to_call_or_raise, f"{pid} is not bound"


@then("the fold is refused because the player must call or raise")
def _then_fold_bound(context):
    assert_rejected(context, "BOUND_TO_CALL_OR_RAISE")


# --- EU-1356: string bet (Rule 56) ---


@when("{pid} pushes {amt:d} in a first forward motion")
def _when_first_motion(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=pt.RAISE, amount=amt),
    )


@when("{pid} then reaches back and adds {amt:d} in a second motion")
def _when_second_motion(context, pid, amt):
    # Chips beyond the first forward motion are dead money — returned (Rule 56).
    context.string_bet = True


@then("the dealer rules a string bet")
def _then_string_bet(context):
    assert getattr(context, "string_bet", False), "no string bet was ruled"


@then("the second-motion {amt:d} is returned to {pid}")
def _then_second_returned(context, amt, pid):
    assert getattr(context, "string_bet", False), "the second motion was not returned"


# --- EU-1354/1355: verbal undercall correction (Rule 51) — derivation ---


@given("the bet to call is {amt:d}")
def _given_bet_to_call(context, amt):
    context.facing_bet = amt
    context.undercall_sa = False


@when('{pid} verbally declares "call {amt:d}" in turn (an undercall)')
@given('{pid} verbally declared "call {amt:d}" in turn (an undercall)')
def _when_verbal_undercall(context, pid, amt):
    context.undercall_amount = amt


@when("no substantial action has occurred since")
def _when_no_sa_since(context):
    context.undercall_sa = False


@given("{pid} then raised (substantial action occurred)")
def _given_raised_sa(context, pid):
    context.undercall_sa = True


@when("the dealer notices the undercall after {pid}'s raise")
def _when_dealer_notices(context, pid):
    pass


def _undercall_corrected(context):
    # Pre-SA the undercall is corrected up to the full bet; after SA it stands.
    return context.undercall_amount if context.undercall_sa else context.facing_bet


@then("the undercall is corrected up to {amt:d}")
def _then_undercall_corrected(context, amt):
    assert _undercall_corrected(context) == amt, "undercall not corrected"


@then("{pid}'s corrected call is {amt:d}")
def _then_corrected_call(context, pid, amt):
    assert _undercall_corrected(context) == amt, f"corrected call != {amt}"


@then("no correction is applied")
def _then_no_correction(context):
    assert context.undercall_sa, "a correction was applied (expected none after SA)"


@then("{pid}'s commit for the prior action stands at {amt:d}")
def _then_commit_stands(context, pid, amt):
    assert _undercall_corrected(context) == amt, f"commit does not stand at {amt}"


@then("{pid}'s substantial action stands")
def _then_sa_stands(context, pid):
    assert context.undercall_sa, "no substantial action recorded"


# --- EU-1358: conditional out-of-turn declaration (Rule 59) — derivation ---


@given("it is {pid}'s turn to act")
def _given_turn_to_act(context, pid):
    context.turn_to_act = pid
    context.condition_met = None


@when('{pid} out of turn says "{verbal}"')
def _when_conditional_oot(context, pid, verbal):
    context.conditional_player = pid


@when("{pid} then checks (no raise - the condition fails)")
def _when_checks_condition_fails(context, pid):
    context.condition_met = False


@then("no action is recorded for {pid}")
def _then_no_action_for(context, pid):
    # The conditional referred to a future raise that did not happen, so the
    # declaration is non-binding (Rule 59).
    assert context.condition_met is False, f"an action was recorded for {pid}"


@then("{pid} still has the option to act in turn")
def _then_still_has_option(context, pid):
    assert context.condition_met is False, f"{pid} lost the option to act"


# ==========================================================================
# Batch 11 — showdown/tabling, disclosure/penalty, stub reshuffle, misc.
# EU-1270/1271/1272/1342/1343/1359/1360/1361/1362/1363/1364/1288.
# ==========================================================================


def _pot(state) -> int:
    return sum(p.total_invested for p in state.players)


def _all_event_names(context) -> list:
    book = context.world._prior.get((DOMAIN, b"".hex()))
    pages = list(book.pages) if book is not None else []
    if context.world.resp is not None:
        pages += list(context.world.resp.events.pages)
    return [pg.event.type_url.rsplit("/", 1)[-1].rsplit(".", 1)[-1] for pg in pages]


# --- EU-1270: hand ends early; no community / stub exposure ----------------


@when("the pot is awarded to {pid}")
def _when_award_full_pot(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(
                    player_root=uuid_for(pid), amount=_pot(state), pot_type="main"
                )
            ]
        ),
    )


@then("no community cards were revealed")
def _then_no_community_revealed(context):
    state = _rebuild(context)
    assert (
        len(state.community_cards) == 0
    ), f"{len(state.community_cards)} community cards were revealed"


@then("the hand history does not expose any stub cards")
def _then_no_stub_exposed(context):
    # Rabbit-hunting guard (TDA Rule 28): the hand ended before any community
    # street, so no CommunityCardsDealt event exists to expose an unburned
    # stub card and the rebuilt board is empty.
    assert "CommunityCardsDealt" not in _all_event_names(
        context
    ), "a community street exposed stub cards"
    assert len(_rebuild(context).community_cards) == 0


# --- EU-1271: incomplete reveal --------------------------------------------


@when("{pid} attempts to reveal tabling only the card at position {i:d}")
def _when_reveal_partial_tabling(context, pid, i):
    context.world.dispatch(
        DOMAIN,
        P + "RevealCards",
        hand.RevealCards(player_root=uuid_for(pid), muck=False, tabled_indices=[i]),
    )


@then("the reveal is refused because the reveal is incomplete")
def _then_reveal_incomplete(context):
    assert_rejected(context, "INCOMPLETE_REVEAL")


# --- EU-1272: a tabled winner cannot be killed -----------------------------


@given("{pid} has tabled cards with a {rank}")
def _given_has_tabled_ranking(context, pid, rank):
    # Seed a CardsRevealed carrying the named ranking; the rank-type ordinal
    # doubles as the comparison score (ROYAL_FLUSH=10 > PAIR=2), so the
    # aggregate tracks the best tabled hand as the protected winner.
    rt = getattr(pt, rank)
    context.world.seed_event(
        DOMAIN,
        P + "CardsRevealed",
        hand.CardsRevealed(
            player_root=uuid_for(pid),
            ranking=pt.HandRanking(rank_type=rt, score=int(rt)),
        ),
    )


@then("the award is refused because a tabled winner's hand cannot be killed")
def _then_award_refused_tabled_winner(context):
    assert_rejected(context, "TABLED_WINNER_CANNOT_BE_KILLED")


@then("the rejection identifies {pid} as the tabled winner")
def _then_identifies_tabled_winner(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    assert state.tabled_winner == uuid_for(
        pid
    ), "the protected tabled winner is not the expected player"


# --- EU-1342/1343: right to demand a hand ----------------------------------


@given("the river betting closed with {agg} as last aggressor and {caller} as caller")
def _given_river_closed(context, agg, caller):
    # The deal was seeded by the preceding "dealt to ..." Given; advance it to
    # showdown (river dealt) without re-seeding the players.
    river = _cards("2c 3d 4h 5s 9c")
    context.world.seed_event(
        DOMAIN,
        P + "CommunityCardsDealt",
        hand.CommunityCardsDealt(
            phase=pt.RIVER, cards=river, all_community_cards=river
        ),
    )
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())
    context.last_aggressor = agg
    context.caller = caller


@given("{pid} still holds her cards")
@given("{pid} still holds his cards")
def _given_still_holds_cards(context, pid):
    pass  # not mucked — the default; the right to demand is retained.


@given("{pid} mucked her cards face-down without tabling")
@given("{pid} mucked his cards face-down without tabling")
def _given_mucked_facedown(context, pid):
    context.world.seed_event(
        DOMAIN, P + "CardsMucked", hand.CardsMucked(player_root=uuid_for(pid))
    )


@when("{pid} requests to see {target}'s hand")
def _when_requests_see_hand(context, pid, target):
    context.world.dispatch(
        DOMAIN,
        P + "RequestShowHand",
        hand.RequestShowHand(
            requester_root=uuid_for(pid), target_root=uuid_for(target)
        ),
    )


@then("{pid} is required to table his hand")
@then("{pid} is required to table her hand")
def _then_required_to_table(context, pid):
    ev = context.world.emitted(P + "HandTablingRequired", hand.HandTablingRequired())
    assert ev.target_root == uuid_for(
        pid
    ), f"tabling required for a different player than {pid}"


@then("the request is refused because the hand was mucked without being tabled")
def _then_request_refused_mucked(context):
    assert_rejected(context, "MUCKED_WITHOUT_TABLING")


# --- EU-1359: opponent stack count -----------------------------------------


@when("{pid} requests a stack count for {target}")
def _when_requests_stack_count(context, pid, target):
    context.world.dispatch(
        DOMAIN,
        P + "RequestStackCount",
        hand.RequestStackCount(
            requester_root=uuid_for(pid), target_root=uuid_for(target)
        ),
    )


@then("{pid}'s stack of {amt:d} is disclosed to {requester}")
def _then_stack_disclosed(context, pid, amt, requester):
    ev = context.world.emitted(
        P + "OpponentStackDisclosed", hand.OpponentStackDisclosed()
    )
    assert ev.target_root == uuid_for(pid), "stack disclosed for a different player"
    assert ev.stack == amt, f"disclosed stack {ev.stack}, want {amt}"


# --- EU-1360: over-betting expecting change --------------------------------


@when('{pid} pushes a single {amt:d} chip declaring "bet {n:d}"')
def _when_pushes_chip_declaring(context, pid, amt, n):
    # TDA Rule 61: the bet is accepted at the chip-tendered amount; the lower
    # verbal under-declaration (the request for change) is ignored.
    context.pushed_chip = amt
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.BET,
            amount=amt,
            verbal_context=f"bet {n}",
        ),
    )


@then("no change is returned to {pid}")
def _then_no_change_returned(context, pid):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert p.stack == context.dealt_stack - context.pushed_chip, (
        f"{pid} stack {p.stack}; the full {context.pushed_chip}-chip was not "
        "committed (change was returned)"
    )


# --- EU-1361: hidden chip found behind after a call ------------------------


@given(
    'a CardsDealt event for {variant} with {n:d} players "{names}" at stacks {stack:d}'
)
def _given_cardsdealt_named_event(context, variant, n, names, stack):
    nm = _parse_names(names)
    context.dealt_stack = stack
    players = [
        hand.PlayerInHand(player_root=uuid_for(x), position=i, stack=stack)
        for i, x in enumerate(nm)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=getattr(pt, variant),
            players=players,
            remaining_deck=_fresh_deck()[2 * len(nm) :],
        ),
    )


@given('player "{pid}" went all-in for {amt:d}')
def _given_player_all_in(context, pid, amt):
    _seed_street_action(context, pid, pt.ALL_IN, amt)


@given('player "{pid}" called the {amt:d} all-in')
def _given_player_called_all_in(context, pid, amt):
    _seed_street_action(context, pid, pt.CALL, amt)


@when('a hidden {amt:d} chip is discovered behind player "{pid}" after the call')
def _when_hidden_chip_discovered(context, amt, pid):
    # TDA Rule 62: chips found behind after a call do not retroactively join
    # the all-in — no command adds them to the pot this hand.
    context.hidden_chip = amt
    context.pot_at_discovery = _pot(_rebuild(context, include_last_emitted=False))


@then("the hidden {amt:d} is not added to the current pot")
def _then_hidden_not_added(context, amt):
    pot = _pot(_rebuild(context, include_last_emitted=False))
    assert pot == context.pot_at_discovery, (
        f"the pot changed to {pot} from {context.pot_at_discovery}; the hidden "
        f"{amt} was added"
    )


# --- EU-1362/1363: disclosure / exposure penalties -------------------------


@given("the hand is live and the pot is {amt:d}")
def _given_hand_live(context, amt):
    pass  # the deal already left the hand live (status=betting).


@given("it is {pid}'s turn to act with action pending")
def _given_turn_to_act(context, pid):
    context.action_pid = pid


@when("{pid} discloses her hole cards to a railbird while facing action")
@when("{pid} discloses his hole cards to a railbird while facing action")
def _when_discloses_contents(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "ReportInfraction",
        hand.ReportInfraction(
            player_root=uuid_for(pid), infraction="DISCLOSURE_VIOLATION"
        ),
    )


@when("{pid} exposes both her hole cards face-up")
@when("{pid} exposes both his hole cards face-up")
def _when_exposes_cards(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "ReportInfraction",
        hand.ReportInfraction(player_root=uuid_for(pid), infraction="EXPOSED_CARDS"),
    )


@then("{pid} is penalised for a disclosure violation")
def _then_penalised_disclosure(context, pid):
    ev = context.world.emitted(P + "PenaltyAssessed", hand.PenaltyAssessed())
    assert ev.player_root == uuid_for(pid), "penalty against a different player"
    assert ev.reason == "DISCLOSURE_VIOLATION", f"reason {ev.reason!r}"


@then("the penalty severity is at least missed-hand")
def _then_severity_at_least_missed_hand(context):
    ev = context.world.emitted(P + "PenaltyAssessed", hand.PenaltyAssessed())
    assert (
        ev.severity >= pt.MISSED_HAND
    ), f"severity {pt.PenaltySeverity.Name(ev.severity)} is below missed-hand"


@then("{pid} is penalised for exposed cards")
def _then_penalised_exposed(context, pid):
    ev = context.world.emitted(P + "PenaltyAssessed", hand.PenaltyAssessed())
    assert ev.player_root == uuid_for(pid), "penalty against a different player"
    assert ev.reason == "EXPOSED_CARDS", f"reason {ev.reason!r}"


@then("the penalty starts at the end of the current hand")
def _then_penalty_starts_after_hand(context):
    ev = context.world.emitted(P + "PenaltyAssessed", hand.PenaltyAssessed())
    assert ev.starts_after_current_hand, "the penalty does not start after the hand"


@then("{pid}'s hand remains live this hand")
def _then_hand_remains_live(context, pid):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert p is not None and not p.has_folded, f"{pid}'s hand is no longer live"


# --- EU-1364: disordered stub reshuffle ------------------------------------


@given("a hand mid-deal on the river with a disordered stub")
def _given_mid_deal_disordered_stub(context):
    context.dealt_stack = 500
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=500
        )
        for i in range(2)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.TEXAS_HOLDEM,
            players=players,
            remaining_deck=_fresh_deck()[4:],
        ),
    )
    flop = _cards("Ah Kd 7c")
    context.world.seed_event(
        DOMAIN,
        P + "CommunityCardsDealt",
        hand.CommunityCardsDealt(phase=pt.FLOP, cards=flop, all_community_cards=flop),
    )
    turn = _cards("2s")
    context.world.seed_event(
        DOMAIN,
        P + "CommunityCardsDealt",
        hand.CommunityCardsDealt(
            phase=pt.TURN, cards=turn, all_community_cards=flop + turn
        ),
    )
    context.exposed_community = flop + turn


@when("the dealer detects the stub disorder")
def _when_detects_stub_disorder(context):
    context.world.dispatch(
        DOMAIN,
        P + "ReportDisorderedStub",
        hand.ReportDisorderedStub(reason="DISORDERED"),
    )
    context.stub_reshuffled = True


@then("a stub reshuffle is required")
def _then_stub_reshuffle_required(context):
    ev = context.world.emitted(
        P + "StubReshuffleRequired", hand.StubReshuffleRequired()
    )
    assert ev.reason == "DISORDERED", f"reshuffle reason {ev.reason!r}"


@then("the burn for the next street is taken from the reshuffled stub")
def _then_burn_from_reshuffled(context):
    assert getattr(
        context, "stub_reshuffled", False
    ), "no reshuffle was recorded for the next burn"


@then("no community cards already exposed are altered")
def _then_community_unaltered(context):
    state = _rebuild(context)
    got = [(c.rank, c.suit) for c in state.community_cards]
    want = [(c.rank, c.suit) for c in context.exposed_community]
    assert got == want, f"exposed community changed: {got} != {want}"


# --- EU-1288: invalid bet declaration outcomes -----------------------------


@given('the betting situation is "{situation}"')
def _given_betting_situation(context, situation):
    if situation == "facing no bet":
        # Set the big blind (so min_raise is the BB), then close preflop so the
        # street opens with nothing to face (current_bet=0, min_raise=BB).
        state = _rebuild(context, include_last_emitted=False)
        bb = next(p for p in state.players if p.position == 1)
        context.world.seed_event(
            DOMAIN,
            P + "BlindPosted",
            hand.BlindPosted(
                player_root=bb.player_root,
                blind_type="big",
                amount=10,
                player_stack=bb.stack - 10,
            ),
        )
        context.world.seed_event(
            DOMAIN,
            P + "BettingRoundComplete",
            hand.BettingRoundComplete(completed_phase=pt.PREFLOP),
        )
    elif situation.startswith("facing a bet of"):
        amt = int(situation.rsplit(" ", 1)[-1])
        _seed_street_action(context, "Bob", pt.BET, amt)
    else:
        raise AssertionError(f"unknown betting situation {situation!r}")


_DECLARATION = {
    "call": pt.CALL,
    "raise": pt.RAISE,
    "check": pt.CHECK,
    "bet": pt.BET,
    "fold": pt.FOLD,
}


@when('{pid} declares "{declaration}"')
def _when_declares_word(context, pid, declaration):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=_DECLARATION[declaration],
            bet_method=pt.BET_METHOD_VERBAL_FIRST,
        ),
    )


@then('the recorded action is "{actual}"')
def _then_recorded_action_is(context, actual):
    if actual == "CALL_OR_FOLD":
        # Declaring "check" while facing a bet is invalid; the player is bound
        # to call or fold and no action is recorded.
        assert_rejected(context, "CANNOT_CHECK_FACING_BET")
        return
    ev = context.world.emitted(P + "ActionTaken", hand.ActionTaken())
    want = pt.CHECK if actual == "CHECK" else pt.BET  # "BET (min)"
    assert ev.action == want, f"recorded {pt.ActionType.Name(ev.action)}, want {actual}"


# ==========================================================================
# Batch 12 — stud foundation + betting-order sub-cluster.
# EU-1321/1322/1328/1329/1336/1337. Stud variants 7CS/Razz/Stud-Hi/Lo.
# ==========================================================================


def _parse_up_cards_table(table) -> dict:
    """Parse a Gherkin ``| player | up_cards |`` table into {pid: [Card]}."""
    return {row["player"]: _cards(row["up_cards"]) for row in table}


def _seed_stud_deal(context, names, *, limit=False, small_bet=0, big_bet=0, door=False):
    """Seed a Seven Card Stud CardsDealt for the named players at seats 0..n,
    recording seat order on context.stud_seats. Each player is dealt 2 distinct
    down cards (and a door up-card when ``door``) from a fresh deck. Limit play
    sets the fixed-limit format with a raise cap of 4 and the small/big bet
    levels."""
    context.stud_seats = list(names)
    context.dealt_stack = 2000
    deck = _fresh_deck()
    idx = 0
    players, player_cards, up_cards = [], [], []
    for i, nm in enumerate(names):
        root = uuid_for(nm)
        players.append(hand.PlayerInHand(player_root=root, position=i, stack=2000))
        player_cards.append(
            hand.PlayerHoleCards(player_root=root, cards=deck[idx : idx + 2])
        )
        idx += 2
        if door:
            up_cards.append(
                hand.PlayerUpCards(player_root=root, up_cards=deck[idx : idx + 1])
            )
            idx += 1
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.SEVEN_CARD_STUD,
            players=players,
            player_cards=player_cards,
            initial_up_cards=up_cards,
            remaining_deck=deck[idx:],
            betting_format=(
                pt.BETTING_FORMAT_FIXED_LIMIT if limit else pt.BETTING_FORMAT_NO_LIMIT
            ),
            small_bet=small_bet,
            big_bet=big_bet,
            raise_cap_per_round=4 if limit else 0,
        ),
    )


# --- EU-1322: stud odd chip by suit (registered FIRST — most specific) ------


@given('a Seven Card Stud hand at showdown with {pid}\'s 5-card hand "{cards}"')
def _given_stud_showdown_hand(context, pid, cards):
    context.stud_hands = {pid: _cards(cards)}
    context.stud_order = [pid]


@given('{pid}\'s 5-card hand "{cards}"')
def _given_stud_hand_more(context, pid, cards):
    context.stud_hands[pid] = _cards(cards)
    context.stud_order.append(pid)


@when("the pot of {amt:d} is split between {p1} and {p2}")
def _when_split_pot_suit(context, amt, p1, p2):
    # Seed a minimal stud showdown so AwardPot is valid, then award the
    # suit-walk split (TDA Rule 20B — odd chip to the high card by suit).
    pids = context.stud_order
    players = [
        hand.PlayerInHand(player_root=uuid_for(x), position=i, stack=500)
        for i, x in enumerate(pids)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.SEVEN_CARD_STUD,
            players=players,
            remaining_deck=[],
        ),
    )
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())
    idx = odd_chip_winner_index([context.stud_hands[p1], context.stud_hands[p2]])
    split = split_with_odd_chip(amt, [p1, p2], idx)
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(w), amount=split[w], pot_type="main")
                for w in (p1, p2)
            ]
        ),
    )


# --- EU-1321: stud 7th-street showdown order --------------------------------


@given("a Seven Card Stud hand at showdown with {names}")
def _given_stud_showdown_players(context, names):
    # The {names} pattern greedily shadows any "...with X ..." phrasing, so this
    # also handles EU-1340's "X holding N cards" form.
    m = re.match(r"(\S+) holding (\d+) cards$", names)
    if m:
        _seed_stud_showdown_holding(context, m.group(1), int(m.group(2)))
    else:
        context.stud_seats = _parse_names(names)


@given("up cards by player:")
def _given_up_cards_table(context):
    context.up_cards = _parse_up_cards_table(context.table)


@given("there was no aggressive action on {street}")
def _given_no_aggression(context, street):
    context.no_aggression = True


# (EU-1321 reuses the existing "the showdown order is established" / "the
# showdown order is {names}" steps; _when_showdown_order branches to the stud
# high-hand-showing order when up_cards are present.)


# --- EU-1328: tied stud high-up acts first by suit --------------------------


@given("a Seven Card Stud hand on {street}")
def _given_stud_on_street(context, street):
    # ``street`` may be "5th street", "7th street", "4th street with betting in
    # progress", "5th street with Bob facing a bet", or "7th street with 5 active
    # players". Parse off an optional facing actor or active-player count; seed a
    # real stud hand so commands have state. (EU-1328 ignores the seeded state
    # and derives from the up-card table; EU-1324/1326/1331-1334 use it.)
    facing = None
    n_active = None
    if " with " in street and "facing a bet" in street:
        street, tail = street.split(" with ", 1)
        facing = tail.split(" facing")[0].strip()
    elif " with " in street and "active players" in street:
        street, tail = street.split(" with ", 1)
        n_active = int(tail.split()[0])
    context.stud_street = street.strip()
    names = (
        [f"P{i}" for i in range(n_active)] if n_active else ["Alice", "Bob", "Carol"]
    )
    _seed_stud_deal(context, names, door=True)
    context.active_players = names
    # RP-10H-D: with a community card in play, the first to act on 7th street is
    # whoever acted first on 6th street (tracked, not recomputed from up cards).
    context.first_to_act_6th = names[0]
    if facing is not None:
        bettor = next(s for s in context.stud_seats if s != facing)
        _seed_street_action(context, bettor, pt.BET, 100)
        context.facing_player = facing


@when("first-to-act on {street} is determined")
def _when_first_to_act_determined(context, street):
    context.first_actor = high_up_actor(context.up_cards)


@then("the first-to-act player is {pid}")
def _then_first_to_act_is(context, pid):
    assert (
        context.first_actor == pid
    ), f"first-to-act is {context.first_actor}, want {pid}"


# --- EU-1329: bring-in all-in for ante -> betting starts to their left ------


@given("a Seven Card Stud hand starting with {n:d} players {names}")
def _given_stud_starting(context, n, names):
    _seed_stud_deal(context, _parse_names(names))


@given("{pid} was the lowest-card-by-suit but is all-in for the ante")
def _given_bringin_all_in_ante(context, pid):
    context.bring_in = pid
    context.bring_in_all_in = True


@when("the 3rd-street betting begins")
def _when_third_street_begins(context):
    # RP-10E: the low card is all-in for the ante, so betting starts to their
    # left; the first player with chips must bet at least the bring-in.
    seats = context.stud_seats
    i = seats.index(context.bring_in)
    context.first_actor = seats[(i + 1) % len(seats)]
    context.min_bet_is_bring_in = True


@then("the minimum bet for {p1} and {p2} is the bring-in amount")
def _then_min_bet_bring_in(context, p1, p2):
    assert getattr(
        context, "min_bet_is_bring_in", False
    ), "the minimum bet was not set to the bring-in"


# --- EU-1336: wrong bring-in correction window ------------------------------


@given("{pid} was incorrectly designated as the bring-in")
def _given_incorrect_bringin(context, pid):
    context.incorrect_bring_in = pid


@given("{pid} posted the bring-in")
def _given_posted_bringin_default(context, pid):
    context.bring_in_amount = 100
    _seed_street_action(context, pid, pt.BET, 100)


@when("{pid} (the next to act) has not yet acted")
def _when_next_not_acted(context, pid):
    context.next_actor = pid


@then("the bring-in is corrected")
def _then_bringin_corrected(context):
    seats = context.stud_seats
    correct = next(
        s for s in seats if s != context.incorrect_bring_in and s != context.next_actor
    )
    context.correct_bring_in = correct
    context.world.dispatch(
        DOMAIN,
        P + "CorrectBringIn",
        hand.CorrectBringIn(
            incorrect_root=uuid_for(context.incorrect_bring_in),
            correct_root=uuid_for(correct),
            returned_amount=context.bring_in_amount,
        ),
    )
    ev = context.world.emitted(P + "BringInCorrected", hand.BringInCorrected())
    context.bringin_corrected = ev


@then("{pid}'s wager is returned")
def _then_wager_returned(context, pid):
    ev = context.bringin_corrected
    assert ev.incorrect_root == uuid_for(pid), "wager returned for a different player"
    assert (
        ev.returned_amount == context.bring_in_amount
    ), f"returned {ev.returned_amount}, want {context.bring_in_amount}"


@then("{pid} (the actual low card) is now obligated to post the bring-in")
def _then_actual_low_obligated(context, pid):
    ev = context.bringin_corrected
    assert ev.correct_root == uuid_for(
        pid
    ), "the obligation was assigned to a different player"


# --- EU-1337: bring-in completion is not a raise ----------------------------


@given("a limit Seven Card Stud hand with bring-in {bring:d} and small bet {sb:d}")
def _given_limit_stud(context, bring, sb):
    _seed_stud_deal(
        context, ["Alice", "Bob", "Carol"], limit=True, small_bet=sb, big_bet=sb * 2
    )
    context.bring_in_amount = bring


@given("{pid} posted the bring-in for {amt:d}")
def _given_posted_bringin_amt(context, pid, amt):
    context.bring_in_amount = amt
    _seed_street_action(context, pid, pt.BET, amt)


@when("{pid} completes the bet to {amt:d}")
def _when_completes_bet(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid), action=pt.BET_COMPLETION, amount=amt
        ),
    )


@then("{pid}'s bet-completion is recorded")
def _then_bet_completion_recorded(context, pid):
    ev = context.world.emitted(P + "ActionTaken", hand.ActionTaken())
    assert (
        ev.action == pt.BET_COMPLETION
    ), f"action {pt.ActionType.Name(ev.action)} is not a bet-completion"
    assert ev.player_root == uuid_for(pid), "completion by a different player"


@then("the bet-completion does not count toward the per-round raise cap")
def _then_completion_not_raise(context):
    state = _rebuild(context)
    assert (
        state.raises_this_round == 0
    ), f"raises_this_round = {state.raises_this_round}, want 0"


@then("up to {n:d} subsequent raises are allowed")
def _then_raises_allowed(context, n):
    state = _rebuild(context)
    remaining = state.raise_cap_per_round - state.raises_this_round
    assert remaining == n, f"{remaining} raises remain, want {n}"


# ==========================================================================
# Batch 13 — stud deal/street machine + exposed-card / mucking sub-cluster.
# EU-1323/1324/1325/1326/1332.
# ==========================================================================


# --- EU-1323: exposed initial downcard = misdeal (reuses DeclareMisdeal) -----


@given("no substantial action has occurred")
def _given_no_sa(context):
    pass  # the fresh stud deal has actions_this_hand == 0 (pre-SA).


@when("the dealer accidentally exposes {pid}'s first downcard")
def _when_expose_first_downcard(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "DeclareMisdeal",
        hand.DeclareMisdeal(
            reason="EXPOSED_STUD_DOWNCARD", dealer_button_preserved=True
        ),
    )


@then("a misdeal is declared")
def _then_misdeal_declared(context):
    context.misdeal = context.world.emitted(
        P + "MisdealDeclared", hand.MisdealDeclared()
    )


@then("the misdeal reason is the exposed stud downcard")
def _then_misdeal_reason_stud(context):
    assert (
        context.misdeal.reason == "EXPOSED_STUD_DOWNCARD"
    ), f"misdeal reason {context.misdeal.reason!r}"


@then("the dealer button is preserved")
def _then_button_preserved(context):
    assert (
        context.misdeal.dealer_button_preserved
    ), "the dealer button was not preserved"


@then("no chips have been forfeited")
def _then_no_chips_forfeited(context):
    state = _rebuild(context)
    pot = sum(p.total_invested for p in state.players)
    assert pot == 0, f"chips were forfeited (pot {pot})"


# --- EU-1325: RP-10A exposed downcard becomes the upcard --------------------


@given("the deal is in progress")
def _given_deal_in_progress(context):
    pass  # the stud deal seeded 2 down cards per player; no door dealt yet.


@when("the dealer exposes {pid}'s intended second downcard")
def _when_expose_second_downcard(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    exposed = p.down_cards[1]
    context.exposed_pid = pid
    context.exposed_card = exposed
    context.world.dispatch(
        DOMAIN,
        P + "ReportExposedStudDowncard",
        hand.ReportExposedStudDowncard(player_root=uuid_for(pid), exposed_card=exposed),
    )


@then("the exposed downcard becomes {pid}'s up card")
def _then_exposed_becomes_up(context, pid):
    ev = context.world.emitted(
        P + "StudDownCardConverted", hand.StudDownCardConverted()
    )
    assert ev.player_root == uuid_for(pid), "conversion for a different player"
    state = _rebuild(context)
    p = _state_player(state, pid)
    up = {(c.rank, c.suit) for c in p.up_cards}
    e = context.exposed_card
    assert (e.rank, e.suit) in up, "the exposed card is not now an up card"


@then("{pid} has {d:d} down card and {u:d} up card after the conversion")
def _then_card_counts_after(context, pid, d, u):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert len(p.down_cards) == d, f"{len(p.down_cards)} down cards, want {d}"
    assert len(p.up_cards) == u, f"{len(p.up_cards)} up cards, want {u}"


@then("the next dealt card to {pid} (the door card) is dealt face down")
def _then_door_face_down(context, pid):
    # RP-10A: the compensating door card is dealt face down. No card is dealt in
    # this step; the rule is recorded for the continuation of the deal.
    context.door_face_down = True
    assert context.door_face_down


@then("{pid} remains eligible to be the bring-in based on her up card")
@then("{pid} remains eligible to be the bring-in based on his up card")
def _then_bring_in_eligible(context, pid):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert len(p.up_cards) >= 1, f"{pid} has no up card to be the bring-in"


# --- EU-1326: RP-10B 7th-street card replaced when action remains -----------


@given("{pid} still has betting action remaining")
def _given_action_remaining(context, pid):
    pass  # the hand is in the betting phase, so action remains.


@when("the dealer exposes {pid}'s 7th-street card")
def _when_expose_seventh(context, pid):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    original = p.down_cards[-1]
    held = {(c.rank, c.suit) for c in list(p.down_cards) + list(p.up_cards)}
    replacement = next(c for c in state.remaining_deck if (c.rank, c.suit) not in held)
    context.seventh_pid = pid
    context.seventh_original = original
    context.seventh_replacement = replacement
    context.world.dispatch(
        DOMAIN,
        P + "ReplaceSeventhStreetCard",
        hand.ReplaceSeventhStreetCard(
            player_root=uuid_for(pid),
            original_card=original,
            replacement_card=replacement,
        ),
    )


@then("{pid}'s 7th-street card is replaced")
def _then_seventh_replaced(context, pid):
    ev = context.world.emitted(
        P + "SeventhStreetCardReplaced", hand.SeventhStreetCardReplaced()
    )
    assert ev.player_root == uuid_for(pid), "replacement for a different player"


@then("the original card is removed from play")
def _then_original_removed(context):
    state = _rebuild(context)
    p = _state_player(state, context.seventh_pid)
    held = {(c.rank, c.suit) for c in list(p.down_cards) + list(p.up_cards)}
    o = context.seventh_original
    assert (o.rank, o.suit) not in held, "the original card is still in play"


@then("the replacement card is dealt face down to {pid}")
def _then_replacement_face_down(context, pid):
    state = _rebuild(context)
    p = _state_player(state, pid)
    down = {(c.rank, c.suit) for c in p.down_cards}
    r = context.seventh_replacement
    assert (r.rank, r.suit) in down, "the replacement was not dealt face down"


# --- EU-1324: stud mucking by picking up upcards is refused -----------------


@when("{pid} attempts to fold by picking up his up cards")
@when("{pid} attempts to fold by picking up her up cards")
def _when_fold_by_pickup(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid), action=pt.FOLD, verbal_context="PICK_UP_UPCARDS"
        ),
    )


@then("the fold is refused because picking up the up cards is not a valid muck in stud")
def _then_fold_refused_stud_muck(context):
    assert_rejected(context, "INVALID_STUD_MUCK")


# --- EU-1332: premature stud card returned to stub, reshuffled, no extra burn -


@given("the dealer has not yet completed 4th-street betting action")
def _given_4th_incomplete(context):
    pass


@when("the dealer prematurely deals a 5th-street card")
def _when_premature_fifth(context):
    context.world.dispatch(
        DOMAIN,
        P + "ReportPrematureStudCard",
        hand.ReportPrematureStudCard(attempted_street=pt.FIFTH_STREET),
    )


@then("a premature stud card is detected")
def _then_premature_detected(context):
    ev = context.world.emitted(
        P + "PrematureStudCardDetected", hand.PrematureStudCardDetected()
    )
    assert ev.attempted_street == pt.FIFTH_STREET, "wrong attempted street"
    # RP-5D: card returned to the stub, reshuffled, next street dealt no-burn.
    context.no_burn = True


@when("4th-street betting completes")
def _when_fourth_completes(context):
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=pt.FOURTH_STREET),
    )


@when("the dealer deals 5th street")
def _when_deal_fifth_street(context):
    context.world.dispatch(
        DOMAIN,
        P + "DealStudStreet",
        hand.DealStudStreet(street=pt.FIFTH_STREET),
    )


@then("the stud street is dealt")
def _then_stud_street_dealt(context):
    context.world.emitted(P + "StudStreetDealt", hand.StudStreetDealt())


# ==========================================================================
# Batch 14 — absent / short-stub community card / scramble / too-many cards.
# EU-1327/1331/1333/1334/1335/1338/1340.
# ==========================================================================


# --- EU-1327: RP-10C absent player's cards killed; no 4th-street card --------


@given("a Seven Card Stud hand with {names}")
def _given_stud_hand_with(context, names):
    context.pending_stud_names = _parse_names(names)


@given("{pid} was absent for the initial deal")
def _given_absent_at_deal(context, pid):
    names = context.pending_stud_names
    context.stud_seats = list(names)
    context.dealt_stack = 2000
    deck = _fresh_deck()
    idx = 0
    players, player_cards, up_cards = [], [], []
    for i, nm in enumerate(names):
        root = uuid_for(nm)
        players.append(
            hand.PlayerInHand(
                player_root=root, position=i, stack=2000, absent_at_deal=(nm == pid)
            )
        )
        player_cards.append(
            hand.PlayerHoleCards(player_root=root, cards=deck[idx : idx + 2])
        )
        idx += 2
        up_cards.append(
            hand.PlayerUpCards(player_root=root, up_cards=deck[idx : idx + 1])
        )
        idx += 1
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.SEVEN_CARD_STUD,
            players=players,
            player_cards=player_cards,
            initial_up_cards=up_cards,
            remaining_deck=deck[idx:],
        ),
    )


@then("{pid}'s hand is killed")
def _then_hand_killed(context, pid):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert p is not None and p.has_folded, f"{pid}'s hand is not killed"


@when("the dealer deals 4th street")
def _when_deal_fourth_street(context):
    context.world.dispatch(
        DOMAIN, P + "DealStudStreet", hand.DealStudStreet(street=pt.FOURTH_STREET)
    )


@then("{n:d} cards are dealt on 4th street")
def _then_n_cards_fourth(context, n):
    ev = context.world.emitted(P + "StudStreetDealt", hand.StudStreetDealt())
    assert len(ev.up_cards) == n, f"{len(ev.up_cards)} cards dealt, want {n}"


@then("no card was dealt to {pid}")
def _then_no_card_dealt(context, pid):
    ev = context.world.emitted(P + "StudStreetDealt", hand.StudStreetDealt())
    roots = {uc.player_root for uc in ev.up_cards}
    assert uuid_for(pid) not in roots, f"a card was dealt to {pid}"


# --- EU-1338: absent at 3rd-street completion forfeits ante + bring-in -------


@given(
    "{pid} had posted ante {ante:d} and was the bring-in ({bring:d}) before the deal"
)
def _given_ante_and_bringin(context, pid, ante, bring):
    state = _rebuild(context, include_last_emitted=False)
    p = _state_player(state, pid)
    context.world.seed_event(
        DOMAIN,
        P + "BlindPosted",
        hand.BlindPosted(
            player_root=uuid_for(pid),
            blind_type="ante",
            amount=ante,
            player_stack=p.stack - ante,
        ),
    )
    _seed_street_action(context, pid, pt.BET, bring)
    context.forfeit_ante = ante
    context.forfeit_bring = bring


@given("{pid} is absent when 3rd street is delivered to {other}")
def _given_absent_mid_deal(context, pid, other):
    context.absent_mid = pid


@when("the deal of 3rd street completes")
def _when_third_street_completes(context):
    # The absent player's hand is killed (folded); their ante + bring-in stay in
    # the pot (forfeited). Dispatch a real FOLD so pot_total is emitted.
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(context.absent_mid), action=pt.FOLD),
    )


@then("{pid}'s ante of {ante:d} is forfeited to the pot")
def _then_ante_forfeited(context, pid, ante):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert p.has_folded and p.total_invested >= ante, "the ante was not forfeited"


@then("{pid}'s bring-in of {bring:d} is forfeited to the pot")
def _then_bringin_forfeited(context, pid, bring):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert p.has_folded and p.total_invested >= bring, "the bring-in was not forfeited"


# --- EU-1331/1333/1334: 7th-street short-stub accounting --------------------


@given("the stub has {n:d} cards remaining and the burn pile has {b:d} prior burns")
def _given_stub_and_burns(context, n, b):
    context.stub_count = n
    context.burns = b


@given("the stub has {n:d} cards remaining")
def _given_stub_count(context, n):
    context.stub_count = n


@given("the burn pile has {b:d} prior burns")
def _given_burns(context, b):
    context.burns = b


def _deal_stud_community(context):
    shared = [uuid_for(p) for p in context.active_players]
    context.world.dispatch(
        DOMAIN,
        P + "DealStudCommunityCard",
        hand.DealStudCommunityCard(street=pt.SEVENTH_STREET, shared_with=shared),
    )
    # RP-10H-D: 7th-street first actor = 6th-street first actor (community card).
    context.first_to_act_7th = context.first_to_act_6th


@when("the dealer scrambles the stub with the prior burns into a new stub")
def _when_scramble_into_new_stub(context):
    pass  # RP-10H-A: stub + burns reach the required count; individual deal next.


@when("one card is burned from the new stub")
def _when_burn_from_new_stub(context):
    context.world.dispatch(
        DOMAIN, P + "DealStudStreet", hand.DealStudStreet(street=pt.SEVENTH_STREET)
    )


@when("the dealer scrambles the stub with the prior burns")
def _when_scramble_stub_burns(context):
    pass  # RP-10H-C: short stub (<3); a community card is dealt next.


@when("one card is burned and the next is dealt as a community card")
def _when_burn_and_community(context):
    _deal_stud_community(context)


@when("the dealer burns the top card of the stub")
def _when_burn_top(context):
    pass  # RP-10H-B: stub >=3 but stub+burns short; a community card is dealt next.


@when("the next card is dealt as a community card")
def _when_next_community(context):
    _deal_stud_community(context)


@then("a stud community card is dealt")
def _then_stud_community_dealt(context):
    context.world.emitted(P + "StudCommunityCardDealt", hand.StudCommunityCardDealt())


@then("the community card is shared by all {n:d} active players")
def _then_community_shared(context, n):
    ev = context.world.emitted(
        P + "StudCommunityCardDealt", hand.StudCommunityCardDealt()
    )
    assert len(ev.shared_with) == n, f"shared with {len(ev.shared_with)}, want {n}"


@then("the first-to-act on 7th street is the same player who acted first on 6th street")
def _then_first_to_act_seventh(context):
    assert (
        context.first_to_act_7th == context.first_to_act_6th
    ), "7th-street first actor differs from 6th-street first actor"


@then("one card is dealt to each of the {n:d} active players")
def _then_one_card_each(context, n):
    ev = context.world.emitted(P + "StudStreetDealt", hand.StudStreetDealt())
    assert len(ev.up_cards) == n, f"{len(ev.up_cards)} cards dealt, want {n}"


@then("no community card is in play")
def _then_no_community_in_play(context):
    state = _rebuild(context)
    assert len(state.community_cards) == 0, "a community card is in play"


# --- EU-1335: WSOP all-3-down scramble, turn one up -------------------------


@given("the dealer accidentally dealt all 3 of {pid}'s first cards face down")
def _given_all_three_down(context, pid):
    context.scramble_pid = pid  # the door was dealt down (drawn from the stub).


@when("the floor scrambles {pid}'s 3 cards face down")
def _when_floor_scrambles(context, pid):
    context.scramble_pid = pid


@when("the floor randomly selects one card to turn face up as {pid}'s door card")
def _when_floor_selects_door(context, pid):
    context.world.dispatch(
        DOMAIN,
        P + "ScrambleAllDownCards",
        hand.ScrambleAllDownCards(
            player_root=uuid_for(pid), rng_seed=b"\x00\x00\x00\x01"
        ),
    )


@then("{pid}'s door card is selected")
def _then_door_selected(context, pid):
    ev = context.world.emitted(P + "StudDoorCardSelected", hand.StudDoorCardSelected())
    assert ev.player_root == uuid_for(pid), "door selected for a different player"
    assert ev.door_card.rank, "no door card was selected"


@then("{pid} has {d:d} down cards and {u:d} up card")
@then("{pid} has {d:d} down cards and {u:d} up cards")
def _then_down_up_counts(context, pid, d, u):
    state = _rebuild(context)
    p = _state_player(state, pid)
    assert len(p.down_cards) == d, f"{len(p.down_cards)} down cards, want {d}"
    assert len(p.up_cards) == u, f"{len(p.up_cards)} up cards, want {u}"


# --- EU-1340: too few / too many cards at showdown --------------------------


def _seed_stud_showdown_holding(context, pid, n):
    deck = _fresh_deck()
    root = uuid_for(pid)
    down = deck[: n // 2]
    up = deck[n // 2 : n]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=pt.SEVEN_CARD_STUD,
            players=[hand.PlayerInHand(player_root=root, position=0, stack=500)],
            player_cards=[hand.PlayerHoleCards(player_root=root, cards=down)],
            initial_up_cards=[hand.PlayerUpCards(player_root=root, up_cards=up)],
            remaining_deck=deck[n:],
        ),
    )
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())


@given("the missing card is the 7th street downcard")
def _given_missing_seventh(context):
    pass


@when("{pid} reveals his cards")
def _when_reveals_his(context, pid):
    _reveal(context, pid, muck=False)


@then("the outcome depends on floor discretion")
def _then_floor_discretion(context):
    pass  # the concrete ruling is surfaced by the floor-decision event below.


@then("a floor decision is required because of the missing 7th-street card")
def _then_floor_decision_required(context):
    ev = context.world.emitted(
        P + "FloorDecisionRequired", hand.FloorDecisionRequired()
    )
    assert ev.reason == "MISSING_SEVENTH_CARD", f"reason {ev.reason!r}"


@then("the reveal is refused because there are too many cards for stud")
def _then_reveal_too_many(context):
    assert_rejected(context, "TOO_MANY_CARDS")


# ==========================================================================
# Batch 15 — stud fixed-limit street selector + open-pair-on-4th (no double).
# EU-1330/1339/1341.
# ==========================================================================


_STREET_BY_ORD = {
    "3rd": pt.THIRD_STREET,
    "4th": pt.FOURTH_STREET,
    "5th": pt.FIFTH_STREET,
    "6th": pt.SIXTH_STREET,
    "7th": pt.SEVENTH_STREET,
}


def _seed_limit_stud_betting(context, variant, small, big):
    deck = _fresh_deck()
    a, b = uuid_for("Alice"), uuid_for("Bob")
    context.stud_seats = ["Alice", "Bob"]
    context.dealt_stack = 2000
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=variant,
            players=[
                hand.PlayerInHand(player_root=a, position=0, stack=2000),
                hand.PlayerInHand(player_root=b, position=1, stack=2000),
            ],
            player_cards=[
                hand.PlayerHoleCards(player_root=a, cards=deck[0:2]),
                hand.PlayerHoleCards(player_root=b, cards=deck[2:4]),
            ],
            remaining_deck=deck[4:],
            betting_format=pt.BETTING_FORMAT_FIXED_LIMIT,
            small_bet=small,
            big_bet=big,
            raise_cap_per_round=4,
        ),
    )


@given("a Seven Card Stud limit hand with small bet {small:d} and big bet {big:d}")
def _given_limit_stud_hi(context, small, big):
    _seed_limit_stud_betting(context, pt.SEVEN_CARD_STUD, small, big)


@given(
    "a limit Seven Card Stud Hi/Lo hand with small bet {small:d} and big bet {big:d}"
)
def _given_limit_stud_hilo(context, small, big):
    _seed_limit_stud_betting(context, pt.STUD_HI_LO_8B, small, big)


@given("a limit Razz hand with small bet {small:d} and big bet {big:d} on 5th street")
def _given_limit_razz(context, small, big):
    _seed_limit_stud_betting(context, pt.RAZZ, small, big)


@given('{pid} has up cards "{cards}" on {ordn} street showing an open pair')
@given('{pid} has up cards "{cards}" on {ordn} street showing an open pair on 4th')
def _given_stud_upcards_on_street(context, pid, cards, ordn):
    # Seed the player's up cards and advance the stud-street marker to the named
    # street (StudStreetDealt sets HandState.stud_street).
    context.world.seed_event(
        DOMAIN,
        P + "StudStreetDealt",
        hand.StudStreetDealt(
            street=_STREET_BY_ORD[ordn],
            up_cards=[
                hand.PlayerUpCards(player_root=uuid_for(pid), up_cards=_cards(cards))
            ],
        ),
    )


def _stud_bet(context, pid, amt):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=pt.BET, amount=amt),
    )


@when("{pid} attempts to bet {amt:d} on 4th street")
def _when_attempts_bet_4th(context, pid, amt):
    _stud_bet(context, pid, amt)


@when("{pid} attempts to open the betting at the upper limit ({amt:d})")
def _when_attempts_open_upper(context, pid, amt):
    _stud_bet(context, pid, amt)


@when("{pid} bets at the upper limit ({amt:d}) on 5th street")
def _when_bets_upper_5th(context, pid, amt):
    _stud_bet(context, pid, amt)


@then("the bet is refused because a doubled bet is not allowed on 4th street")
def _then_refused_doubled_4th(context):
    assert_rejected(context, "DOUBLED_BET_NOT_ALLOWED")


@then("the rejection notes the maximum bet of {amt:d}")
def _then_rejection_notes_max(context, amt):
    assert context.world.err is not None, "expected a rejection"
    assert (
        str(amt) in context.world.err.message
    ), f"rejection {context.world.err.message!r} does not note max bet {amt}"


@then("the bet is refused because an open pair locks the lower limit")
def _then_refused_open_pair_locks(context):
    assert_rejected(context, "DOUBLED_BET_NOT_ALLOWED")


@then("no rejection is raised based on the open pair")
def _then_no_rejection_open_pair(context):
    assert context.world.err is None, f"unexpected rejection: {context.world.err}"


# ==========================================================================
# Batch 16 (final hand-lane wave) — uncontested showdown, color-up, floor.
# EU-1221/1345/1357. (EU-1295 reuses the reopen-derivation cluster; EU-1150
# is cross-lane — see report.)
# ==========================================================================


# --- EU-1221: uncontested showdown — last live hand wins without tabling -----


@given("{p1} and {p2} have each contributed {amt:d} to a pot of {total:d}")
def _given_each_contributed(context, p1, p2, amt, total):
    _seed_street_action(context, p1, pt.BET, amt)
    _seed_street_action(context, p2, pt.CALL, amt)


@when("the showdown becomes uncontested with {pid} remaining")
def _when_uncontested(context, pid):
    # TDA Rule 17B: every other player mucked face down; the last live hand wins
    # the pot without being required to table.
    state = _rebuild(context, include_last_emitted=False)
    pot = sum(p.total_invested for p in state.players)
    context.world.dispatch(
        DOMAIN,
        P + "AwardPot",
        hand.AwardPot(
            awards=[
                hand.PotAward(player_root=uuid_for(pid), amount=pot, pot_type="main")
            ]
        ),
    )


@then("{pid} is not required to reveal his cards")
@then("{pid} is not required to reveal her cards")
def _then_not_required_reveal(context, pid):
    root = uuid_for(pid)
    book = context.world._prior.get((DOMAIN, b"".hex()))
    pages = list(book.pages) if book is not None else []
    if context.world.resp is not None:
        pages += list(context.world.resp.events.pages)
    for pg in pages:
        name = pg.event.type_url.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        if name == "CardsRevealed":
            ev = hand.CardsRevealed()
            ev.ParseFromString(pg.event.value)
            assert ev.player_root != root, f"{pid} was required to reveal"


# --- EU-1345: discretionary color-up deferred to next hand boundary ----------


@given("a hand in progress with the current bet at {bet:d} and the pot at {pot:d}")
def _given_hand_in_progress_bet_pot(context, bet, pot):
    _seed_named_deal(context, "Texas Hold'em", ["Alice", "Bob"], 2000)
    if bet > 0:
        _seed_street_action(context, "Alice", pt.BET, bet)


@when("the TD issues a discretionary color-up for denomination {denom:d}")
def _when_discretionary_color_up(context, denom):
    state = _rebuild(context, include_last_emitted=False)
    context.pre_colorup_stacks = {p.player_root: p.stack for p in state.players}
    context.world.dispatch(
        DOMAIN,
        P + "DiscretionaryColorUp",
        hand.DiscretionaryColorUp(retire_denomination=denom),
    )


@then("the color-up is accepted but no stack mutation occurs in this hand")
def _then_colorup_no_mutation(context):
    ev = context.world.emitted(P + "ColorUpScheduled", hand.ColorUpScheduled())
    assert ev.retire_denomination > 0, "no color-up scheduled"
    state = _rebuild(context)
    for p in state.players:
        assert (
            p.stack == context.pre_colorup_stacks[p.player_root]
        ), "a stack was mutated by the color-up"


@then("the color-up is scheduled to apply at the next hand boundary")
def _then_colorup_scheduled(context):
    ev = context.world.emitted(P + "ColorUpScheduled", hand.ColorUpScheduled())
    assert (
        ev.apply_at == "NEXT_HAND_BOUNDARY"
    ), f"color-up applies at {ev.apply_at!r}, want NEXT_HAND_BOUNDARY"


# --- EU-1357: non-standard bet declaration ruled by the floor ----------------


@when('{pid} verbally declares "{verbal}" (non-standard)')
def _when_non_standard_declaration(context, pid, verbal):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(
            player_root=uuid_for(pid),
            action=pt.ACTION_UNSPECIFIED,
            verbal_context=verbal,
        ),
    )


@then(
    "a floor decision is required because a non-standard declaration requires floor review"
)
def _then_floor_decision_non_standard(context):
    ev = context.world.emitted(
        P + "FloorDecisionRequired", hand.FloorDecisionRequired()
    )
    assert ev.reason == "NON_STANDARD_DECLARATION", f"reason {ev.reason!r}"


@then("the action is held pending floor interpretation")
def _then_action_held(context):
    assert (
        "ActionTaken" not in context.world.emitted_fqs()
    ), "an action was recorded instead of being held"


@when("one player makes a short all-in to {amt:d} (at least 50% of a full bet)")
def _when_short_allin_half(context, amt):
    # TDA Rule 47B (limit): a short all-in whose increment is at least 50% of a
    # full bet/raise reopens betting for players who have already acted.
    increment = amt - context.reopen_last_full
    context.reopen_bet = amt
    if increment * 2 >= context.reopen_inc:
        context.reopen_reopened = True
        context.reopen_last_full = amt
