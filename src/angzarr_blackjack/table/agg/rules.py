"""House rules as pure functions: the table configuration (AHR-1). No state,
no I/O.
"""

from __future__ import annotations

MAX_SEATS = 7
MAX_DECKS = 8


def config_is_valid(
    seats: int, decks: int, min_bet: int, max_bet: int, min_buy_in: int, max_buy_in: int
) -> bool:
    """AHR-1: 1–7 seats, 1–8 decks, even bets 0 < min <= max, buy-ins
    0 < min <= max, and the smallest buy-in covers the smallest bet."""
    return (
        1 <= seats <= MAX_SEATS
        and 1 <= decks <= MAX_DECKS
        and 0 < min_bet <= max_bet
        and min_bet % 2 == 0
        and max_bet % 2 == 0
        and 0 < min_buy_in <= max_buy_in
        and min_bet <= min_buy_in
    )
