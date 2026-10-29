"""The player's plain types: a turn as the table tells it, the moves, and
what the player remembers. Plain Python; nothing here imports angzarr_client
or the generated code (the adapter maps the framework's messages onto these
types and back)."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Suit(enum.Enum):
    CLUBS = "clubs"
    DIAMONDS = "diamonds"
    HEARTS = "hearts"
    SPADES = "spades"


@dataclass(frozen=True)
class Card:
    """A card: ``rank`` 1..13 (Ace 1, Jack 11, Queen 12, King 13)."""

    rank: int
    suit: Suit


class Move(enum.Enum):
    """What a seat does on its turn."""

    HIT = "hit"
    STAND = "stand"
    DOUBLE_DOWN = "double_down"


@dataclass(frozen=True)
class Turn:
    """A seat's turn, as the table tells it: the hand as it stands, the
    dealer's up-card and what doubling needs. Only what any player at the
    table sees."""

    table_root: bytes
    round: int
    seat: int
    cards: tuple[Card, ...]
    total: int
    soft: bool
    dealer_up: Card
    can_double: bool
    stack: int
    wager: int


@dataclass(frozen=True)
class Decision:
    """A move the player made: the turn it answered and the move.
    ``cards`` is how many cards the hand held when the move was made (2 on a
    hand's first decision)."""

    table_root: bytes
    round: int
    seat: int
    move: Move
    cards: int


@dataclass(frozen=True)
class Memory:
    """What the player remembers: ``decisions`` made, and ``hands_seen``,
    the hands it played (one per hand: the decisions taken on two cards)."""

    decisions: int = 0
    hands_seen: int = 0
