"""House rules as pure functions: configuration, turn order, dealer play and
settlement (AHR-1 .. AHR-13). No state, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack.cards import (
    BLACKJACK,
    MAX_CARDS_PER_HAND,
    Card,
    hand_value,
    is_blackjack,
)

Outcome = _table.SeatOutcome.Outcome
LOSE = Outcome.OUTCOME_LOSE
PUSH = Outcome.OUTCOME_PUSH
WIN = Outcome.OUTCOME_WIN
PLAYER_BLACKJACK = Outcome.OUTCOME_BLACKJACK

NO_TURN = -1
MAX_SEATS = 7
MAX_DECKS = 8
DEALER_STANDS_ON = 17


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


def cards_needed(wagered_seats: int) -> int:
    """AHR-4: enough cards for every wagered seat and the dealer to draw a
    full hand of 21 or less."""
    return MAX_CARDS_PER_HAND * (wagered_seats + 1)


def needs_reshuffle(remaining: int, wagered_seats: int) -> bool:
    return remaining < cards_needed(wagered_seats)


def is_busted(cards: Iterable[Card]) -> bool:
    return hand_value(cards)[0] > BLACKJACK


def next_turn(
    seats: Sequence[int], finished: dict[int, bool], after: int | None = None
) -> int:
    """AHR-9: the first wagered seat, ascending, after ``after`` (or from the
    start) whose hand is not finished; ``NO_TURN`` when none is left."""
    for seat in sorted(seats):
        if (after is None or seat > after) and not finished[seat]:
            return seat
    return NO_TURN


def dealer_must_draw(dealer_cards: Sequence[Card]) -> bool:
    """AHR-11: the dealer draws below 17 and stands on every 17, soft or hard."""
    return hand_value(dealer_cards)[0] < DEALER_STANDS_ON


def dealer_draws(
    dealer_cards: Sequence[Card], shoe: Sequence[Card], live_hand: bool
) -> list[Card]:
    """The cards the dealer draws from the top of ``shoe``. Nothing is drawn
    when no player hand is left that is neither busted nor a blackjack."""
    if not live_hand:
        return []
    hand = list(dealer_cards)
    drawn: list[Card] = []
    for card in shoe:
        if not dealer_must_draw(hand):
            break
        hand.append(card)
        drawn.append(card)
    return drawn


def outcome(player_cards: Sequence[Card], dealer_cards: Sequence[Card]) -> int:
    """AHR-7, AHR-8, AHR-12: a busted hand loses whatever the dealer holds;
    blackjacks beat everything but a dealer blackjack, which they push; a
    dealer blackjack beats every other hand; otherwise the higher total wins."""
    player_total = hand_value(player_cards)[0]
    dealer_total = hand_value(dealer_cards)[0]
    player_bj = is_blackjack(player_cards)
    dealer_bj = is_blackjack(dealer_cards)
    if player_total > BLACKJACK:
        return LOSE
    if player_bj:
        return PUSH if dealer_bj else PLAYER_BLACKJACK
    if dealer_bj:
        return LOSE
    if dealer_total > BLACKJACK or player_total > dealer_total:
        return WIN
    return PUSH if player_total == dealer_total else LOSE


def returned(result: int, wager: int) -> int:
    """AHR-12: a win returns twice the wager, a blackjack the wager plus 3/2
    of it, a push the wager, a loss nothing. Wagers are even, so 3:2 is exact."""
    if result == WIN:
        return 2 * wager
    if result == PLAYER_BLACKJACK:
        return wager + wager * 3 // 2
    if result == PUSH:
        return wager
    return 0


def ledger_balances(state: _table.TableState) -> bool:
    """Invariant L2: sum(stacks) + sum(wagers) + house_result = chips_in - chips_out."""
    on_table = sum(seat.stack + seat.wager for seat in state.seated.values())
    return on_table + state.house_result == state.chips_in - state.chips_out
