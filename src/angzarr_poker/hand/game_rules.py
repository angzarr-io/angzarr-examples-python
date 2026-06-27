"""Poker hand evaluation for the hand aggregate's showdown.

``get_game_rules(variant)`` returns a rules object whose
``evaluate_hand(hole_cards, community_cards)`` finds the best five-card hand and
reports ``(rank_type, score, kickers)``: ``rank_type`` is a ``_pt.HandRankType``,
``score`` a single comparable integer (higher wins), and ``kickers`` a list of
``_pt.Rank`` for tie-breaks — exactly the shape a ``HandRanking`` packs.

Cards are ``_pt.Card`` objects; ``Card.rank`` carries the proto Rank values, which
run 2..14 (ACE high), so the straight / score arithmetic works on them directly.
Hold'em and Five Card Draw take the best five of all available cards; Omaha forces
exactly two hole cards plus three community cards (Robert's Rules section 1).
"""

from __future__ import annotations

from itertools import combinations

from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt


class StandardRules:
    """Standard high-poker ranking shared by Hold'em and Five Card Draw: the best
    five cards out of everything available."""

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        return _find_best_hand(list(hole_cards) + list(community_cards))


class OmahaRules(StandardRules):
    """Omaha: the best five-card hand using exactly two hole cards and three
    community cards."""

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        best = (_pt.HIGH_CARD, 0, [])
        for hole_combo in combinations(hole_cards, 2):
            for comm_combo in combinations(community_cards, 3):
                result = _evaluate_five(list(hole_combo) + list(comm_combo))
                if result[1] > best[1]:
                    best = result
        return best


# Dispatch table for the rules factory — avoids an if/elif chain. Unknown variants
# fall back to standard high-poker ranking.
_GAME_RULES = {
    _pt.TEXAS_HOLDEM: StandardRules,
    _pt.OMAHA: OmahaRules,
    _pt.FIVE_CARD_DRAW: StandardRules,
}


def get_game_rules(variant: int) -> StandardRules:
    """Return the evaluator for a game variant."""
    return _GAME_RULES.get(variant, StandardRules)()


def _find_best_hand(cards: list) -> tuple:
    """The best-scoring five-card hand out of the available cards."""
    if len(cards) < 5:
        return (_pt.HIGH_CARD, 0, [])
    best = (_pt.HIGH_CARD, 0, [])
    for combo in combinations(cards, 5):
        result = _evaluate_five(list(combo))
        if result[1] > best[1]:
            best = result
    return best


def _evaluate_five(cards: list) -> tuple:
    """Score exactly five ``_pt.Card`` objects into ``(rank_type, score, kickers)``.

    The score keeps the 10-rank hierarchy in its leading digit so a single
    comparison settles any two hands; kickers carry the remaining ranks for
    same-category tie-breaks (Robert's Rules section 31)."""
    suits = [c.suit for c in cards]
    ranks = sorted((c.rank for c in cards), reverse=True)

    is_flush = len(set(suits)) == 1
    is_straight = _is_straight(ranks)

    rank_counts: dict[int, int] = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    counts = sorted(rank_counts.values(), reverse=True)
    # Order the five ranks by group size, then by rank — so the quad/trip/pair
    # leads and the kickers follow. The wheel is the one exception: the ace plays
    # low, so the hand reads five-high (5-4-3-2-A) and must sort below a regular
    # six-high straight.
    if is_straight and ranks == [_pt.ACE, _pt.FIVE, _pt.FOUR, _pt.THREE, _pt.TWO]:
        ordered = [_pt.FIVE, _pt.FOUR, _pt.THREE, _pt.TWO, 1]
    else:
        ordered = sorted(ranks, key=lambda r: (rank_counts[r], r), reverse=True)

    if is_straight and is_flush:
        rank_type = (
            _pt.ROYAL_FLUSH
            if ranks == [_pt.ACE, _pt.KING, _pt.QUEEN, _pt.JACK, _pt.TEN]
            else _pt.STRAIGHT_FLUSH
        )
    elif counts == [4, 1]:
        rank_type = _pt.FOUR_OF_A_KIND
    elif counts == [3, 2]:
        rank_type = _pt.FULL_HOUSE
    elif is_flush:
        rank_type = _pt.FLUSH
    elif is_straight:
        rank_type = _pt.STRAIGHT
    elif counts == [3, 1, 1]:
        rank_type = _pt.THREE_OF_A_KIND
    elif counts == [2, 2, 1]:
        rank_type = _pt.TWO_PAIR
    elif counts == [2, 1, 1, 1]:
        rank_type = _pt.PAIR
    else:
        rank_type = _pt.HIGH_CARD

    # Total-order score: the category (HandRankType runs 1=HIGH_CARD .. 10=
    # ROYAL_FLUSH) leads, then the ordered ranks in base-15 positional notation
    # (each rank is 1..14 < 15). A single comparison settles any two hands,
    # kickers included — so the best-scoring five is the genuine best hand.
    score = rank_type
    for r in ordered:
        score = score * 15 + r
    # Kickers: the singleton ranks that break ties within a category, high first.
    kickers = [r for r in ordered if rank_counts.get(r, 0) == 1]
    return (rank_type, score, kickers)


def _is_straight(ranks: list) -> bool:
    """Whether five descending-sorted ranks form a straight, counting the wheel
    (A-2-3-4-5, where the ace plays low)."""
    if ranks == [_pt.ACE, _pt.FIVE, _pt.FOUR, _pt.THREE, _pt.TWO]:
        return True
    for i in range(len(ranks) - 1):
        if ranks[i] - ranks[i + 1] != 1:
            return False
    return True
