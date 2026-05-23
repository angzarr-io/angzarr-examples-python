"""Pot-distribution helpers — odd-chip allocation per TDA Rule 20.

When a pot doesn't divide evenly among tied winners, real poker has
specific rules for allocating the odd chip(s):

  TDA Rule 20A — Board games (Hold'em / Omaha / Draw): odd chip goes to
    the first seat clockwise of the dealer button.
  TDA Rule 20B — Stud / Razz / Stud-Hi-Lo: odd chip goes to the high card
    by suit in the player's 5-card winning hand.
  TDA Rule 20C — High/Low split: the odd chip in the total pot goes to
    the high side. Within each side, additional odd-chip distribution
    applies recursively.
  Robert's §35-9 — When the high (or low) portion of an H/L split has
    multiple tied winners, the odd chip in that portion goes to the
    player with the high card by suit (low card by suit for the low half).

These are pure functions — no state, no events, no commands. The Hand
aggregate's AwardPot handler calls into these helpers to compute the
``awards`` list it then emits as a PotAwarded event.
"""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class WinnerWithSeat:
    """A tied winner and their seat position relative to the dealer button.

    ``seat`` is the absolute seat number (0..max_seats-1). Distance from
    the button is computed by the caller using the active-seat order.
    """

    player_root: str
    seat: int


@dataclass(frozen=True)
class WinnerWithSuit:
    """A tied winner and their high (or low) card-by-suit ranking value.

    ``suit_rank`` is a single integer where higher value = higher suit
    rank by the standard ordering (Spades > Hearts > Diamonds > Clubs).
    Convention: encode as ``card_rank * 4 + suit_index`` where suit_index
    is 0=clubs, 1=diamonds, 2=hearts, 3=spades. Two players cannot share
    a single rank-and-suit (it would be the same physical card), so this
    ordering produces a strict total ordering on the tied set.
    """

    player_root: str
    suit_rank: int


@dataclass(frozen=True)
class Award:
    """A single pot allocation: ``amount`` chips to ``player_root``."""

    player_root: str
    amount: int


def split_pot_clockwise_from_button(
    pot: int,
    winners: Sequence[WinnerWithSeat],
    dealer_button_seat: int,
    max_seats: int,
) -> list[Award]:
    """Split ``pot`` evenly among ``winners``; odd chips go to the first
    seat clockwise of the dealer button.

    Per TDA Rule 20A: in board games (Hold'em / Omaha / Draw), the odd
    chip goes to the first seat to the dealer's left (clockwise). When
    multiple odd chips remain (extremely rare with denominated tournament
    chips, but possible with mixed denominations), they continue to the
    next seat clockwise.

    Args:
        pot: Total chips to distribute.
        winners: All players tied for this pot, with their seat positions.
        dealer_button_seat: Absolute seat number where the button is.
        max_seats: The table's seat capacity (the modulus used to compute
            clockwise distance for sparse seat layouts). Must be > the
            highest seat used and > ``dealer_button_seat``.

    Returns:
        Awards summing to exactly ``pot``. Awards appear in the same
        order as ``winners``.

    Raises:
        ValueError: if ``winners`` is empty, ``pot`` is non-positive, or
            ``max_seats`` is too small to cover the seats in use.
    """
    if pot <= 0:
        raise ValueError(f"pot must be positive, got {pot}")
    if not winners:
        raise ValueError("winners must be non-empty")
    highest_seat = max(w.seat for w in winners)
    min_required = max(highest_seat, dealer_button_seat) + 1
    if max_seats < min_required:
        raise ValueError(
            f"max_seats ({max_seats}) must be at least {min_required} "
            f"to cover button seat {dealer_button_seat} and winner seats"
        )

    base_share = pot // len(winners)
    odd_chips = pot - base_share * len(winners)

    def distance_from_button(seat: int) -> int:
        # Clockwise distance from the seat immediately after the button.
        # Seat == button + 1 has distance 0 (or wraps to 0 if button is
        # the highest seat).
        return (seat - dealer_button_seat - 1) % max_seats

    ordered_winners = sorted(winners, key=lambda w: distance_from_button(w.seat))

    # First N winners (by clockwise distance from button) get one extra chip.
    extra_recipients = {ordered_winners[i].player_root for i in range(odd_chips)}

    return [
        Award(
            player_root=w.player_root,
            amount=base_share + (1 if w.player_root in extra_recipients else 0),
        )
        for w in winners
    ]


def split_pot_by_suit(
    pot: int, winners: Sequence[WinnerWithSuit], high_wins: bool
) -> list[Award]:
    """Split ``pot`` evenly among ``winners``; odd chip goes to the
    highest (or lowest) card by suit.

    Per Robert's Rules §35-9: in stud games and the high/low halves of
    split-pot games, the odd chip goes to the player with the high card
    by suit (or low card by suit when this is the low side).

    Args:
        pot: Total chips to distribute.
        winners: Tied players with their suit-encoded card ranks.
        high_wins: If True (default), the highest ``suit_rank`` gets the
            odd chip. If False, the lowest gets it (low-side of H/L,
            razz, etc.).

    Returns:
        Awards summing to exactly ``pot``.

    Raises:
        ValueError: if ``winners`` is empty or ``pot`` is non-positive.
    """
    if pot <= 0:
        raise ValueError(f"pot must be positive, got {pot}")
    if not winners:
        raise ValueError("winners must be non-empty")

    base_share = pot // len(winners)
    odd_chips = pot - base_share * len(winners)

    # Sort by suit rank: descending for high, ascending for low.
    ordered = sorted(winners, key=lambda w: w.suit_rank, reverse=high_wins)
    extra_recipients = {ordered[i].player_root for i in range(odd_chips)}

    return [
        Award(
            player_root=w.player_root,
            amount=base_share + (1 if w.player_root in extra_recipients else 0),
        )
        for w in winners
    ]


@dataclass(frozen=True)
class WinnerWithCards:
    """A tied winner and the 5-card hand they're tabling for the tiebreak.

    ``cards`` is a sequence of (suit_index, rank) tuples where suit_index
    follows the canonical 0=clubs, 1=diamonds, 2=hearts, 3=spades order
    (same as ``WinnerWithSuit.suit_rank // 4`` decomposition) and rank is
    2..14 (Ace high). Used by ``split_pot_by_high_card_walk`` for the TDA
    Rule 20B "high card by suit in the player's 5-card winning hand"
    tiebreak — the rule walks the hand top-to-bottom rather than picking
    a single representative card.
    """

    player_root: str
    cards: tuple


def split_pot_by_high_card_walk(
    pot: int, winners: Sequence[WinnerWithCards]
) -> list[Award]:
    """Split ``pot`` evenly; odd chip goes to the player whose 5-card
    winning hand has the highest card by suit, walking top-to-bottom.

    Per TDA Rule 20B: in stud / razz / stud-Hi-Lo, the odd chip goes to
    "the high card by suit in the player's 5-card winning hand." This
    rule walks all 5 positions — the *highest* card decides first, with
    each position breaking ties from the previous. Two FULL_HOUSE Jacks-
    over-eights hands with disjoint suits will tie on rank alone but
    diverge as soon as a higher-suit card appears at any position.

    Args:
        pot: Total chips to distribute.
        winners: Tied players each carrying their 5-card winning hand
            as a tuple of (suit_index, rank) pairs. Suit indexing must
            follow 0=clubs, 1=diamonds, 2=hearts, 3=spades so a higher
            integer dominates by the canonical TDA ordering.

    Returns:
        Awards summing to exactly ``pot``. When ``odd_chips`` > 0 the
        first ``odd_chips`` winners ranked by suit-walk order each get
        one extra chip.

    Raises:
        ValueError: if ``winners`` is empty or ``pot`` is non-positive.
    """
    if pot <= 0:
        raise ValueError(f"pot must be positive, got {pot}")
    if not winners:
        raise ValueError("winners must be non-empty")

    base_share = pot // len(winners)
    odd_chips = pot - base_share * len(winners)

    def _walk_key(w: WinnerWithCards) -> tuple:
        # Sort cards by (rank desc, suit desc) so position 0 is the
        # highest card; the tuple compares lexicographically with higher
        # = stronger.
        return tuple(sorted(w.cards, key=lambda c: (c[1], c[0]), reverse=True))

    ordered = sorted(winners, key=_walk_key, reverse=True)
    extra_recipients = {ordered[i].player_root for i in range(odd_chips)}

    return [
        Award(
            player_root=w.player_root,
            amount=base_share + (1 if w.player_root in extra_recipients else 0),
        )
        for w in winners
    ]


@dataclass(frozen=True)
class HighLowSplit:
    """Result of splitting a pot between high and low sides."""

    high_share: int
    low_share: int


def split_high_low_total(pot: int) -> HighLowSplit:
    """Split a total pot between the high and low halves.

    Per TDA Rule 20C: the odd chip in the total pot goes to the high
    side. (The high side may then need to further distribute among tied
    high winners; same for low.)

    Args:
        pot: Total chips to split.

    Returns:
        HighLowSplit with high_share + low_share == pot, and high_share
        getting any odd chip.
    """
    if pot <= 0:
        raise ValueError(f"pot must be positive, got {pot}")
    low_share = pot // 2
    high_share = pot - low_share  # high gets any odd chip
    return HighLowSplit(high_share=high_share, low_share=low_share)
