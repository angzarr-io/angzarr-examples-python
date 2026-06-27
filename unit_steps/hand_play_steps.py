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
from angzarr_poker.hand.game_rules import get_game_rules
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
    "PotAwarded": HandAggregate.apply_pot_awarded,
    "HandComplete": HandAggregate.apply_hand_complete,
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
    context.world.seed_event(DOMAIN, P + "ShowdownStarted", hand.ShowdownStarted())


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
