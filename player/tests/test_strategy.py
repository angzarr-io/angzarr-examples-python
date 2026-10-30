"""BasicStrategy's move for representative turns: hard and soft totals,
the dealer's up-card, and doubling allowed or not."""

from __future__ import annotations

import pytest

from angzarr_player.domain import Card, DecideMove, MoveAction, Suit
from angzarr_player.strategy import BasicStrategy

ACE, JACK, QUEEN, KING = 1, 11, 12, 13


def turn(
    ranks: tuple[int, ...],
    total: int,
    up: int,
    *,
    soft: bool = False,
    can_double: bool = False,
) -> DecideMove:
    return DecideMove(
        table_root=b"\x01" * 16,
        round=1,
        seat=0,
        cards=tuple(Card(rank=r, suit=Suit.CLUBS) for r in ranks),
        total=total,
        soft=soft,
        dealer_up=Card(rank=up, suit=Suit.DIAMONDS),
        can_double=can_double,
        stack=480,
        wager=20,
    )


@pytest.mark.parametrize(
    "hand, expected",
    [
        # Hard totals below 12 hit, except a doubleable 10 or 11.
        (turn((2, 4), 6, 9, can_double=True), MoveAction.HIT),
        (turn((2, 3), 5, 6, can_double=True), MoveAction.HIT),
        (turn((4, 5), 9, 3, can_double=True), MoveAction.HIT),
        (turn((2, 3, 4), 9, 6), MoveAction.HIT),
        (turn((6, 5), 11, 6, can_double=True), MoveAction.DOUBLE_DOWN),
        (turn((6, 4), 10, 9, can_double=True), MoveAction.DOUBLE_DOWN),
        (turn((6, 5), 11, ACE, can_double=True), MoveAction.DOUBLE_DOWN),
        # can_double false: a 10 or 11 hits instead.
        (turn((6, 5), 11, 6, can_double=False), MoveAction.HIT),
        (turn((6, 4), 10, 9, can_double=False), MoveAction.HIT),
        (turn((2, 3, 5), 10, 6, can_double=False), MoveAction.HIT),
        # Hard 12: stand against a dealer 4 to 6 only.
        (turn((10, 2), 12, 2), MoveAction.HIT),
        (turn((10, 2), 12, 3), MoveAction.HIT),
        (turn((10, 2), 12, 4), MoveAction.STAND),
        (turn((10, 2), 12, 6), MoveAction.STAND),
        (turn((10, 2), 12, 7), MoveAction.HIT),
        # Hard 13 to 16: stand against a dealer 2 to 6.
        (turn((10, 3), 13, 2), MoveAction.STAND),
        (turn((9, 7), 16, 6), MoveAction.STAND),
        (turn((9, 7), 16, 7), MoveAction.HIT),
        (turn((8, 6), 14, 9), MoveAction.HIT),
        (turn((10, 5), 15, KING), MoveAction.HIT),
        (turn((10, 6), 16, ACE), MoveAction.HIT),
        # Hard 17 and up stand, whatever the dealer shows.
        (turn((10, 7), 17, 10), MoveAction.STAND),
        (turn((10, 7), 17, ACE), MoveAction.STAND),
        (turn((QUEEN, JACK), 20, ACE, can_double=True), MoveAction.STAND),
        (turn((5, 6, 10), 21, 9), MoveAction.STAND),
        # Soft totals: 17 or less hit, 18 or more stand; never a soft double.
        (turn((ACE, 2), 13, 5, soft=True, can_double=True), MoveAction.HIT),
        (turn((ACE, 6), 17, 9, soft=True), MoveAction.HIT),
        (turn((ACE, 6), 17, 6, soft=True, can_double=True), MoveAction.HIT),
        (turn((ACE, 7), 18, 9, soft=True), MoveAction.STAND),
        (turn((ACE, 8), 19, ACE, soft=True), MoveAction.STAND),
        (turn((ACE, 2, 4, 3), 20, 10, soft=True), MoveAction.STAND),
        (turn((ACE, KING), 21, 10, soft=True), MoveAction.STAND),
    ],
)
def test_basic_strategy(hand, expected):
    assert BasicStrategy().choose(hand) == expected


def test_basic_strategy_never_doubles_when_it_may_not():
    for total in range(4, 22):
        for up in range(1, 14):
            for soft in (False, True):
                move = BasicStrategy().choose(turn((2, 2), total, up, soft=soft))
                assert move != MoveAction.DOUBLE_DOWN, (total, up, soft)
