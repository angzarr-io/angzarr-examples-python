"""Small rendering helpers used by behave step defs.

Kept separate from :mod:`main` so tests can import utilities without pulling
in the gRPC service wiring.
"""

from __future__ import annotations

from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types

_RANK_CHAR = {
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "T",
    11: "J",
    12: "Q",
    13: "K",
    14: "A",
}

_SUIT_CHAR = {
    poker_types.CLUBS: "c",
    poker_types.DIAMONDS: "d",
    poker_types.HEARTS: "h",
    poker_types.SPADES: "s",
}


def format_card(card) -> str:
    """Format a :class:`poker_types.Card` as a short string like ``"As"`` or ``"Th"``.

    Unknown ranks/suits render as ``"?"`` so callers see a placeholder instead of
    crashing on malformed input.
    """
    rank = _RANK_CHAR.get(card.rank, "?")
    suit = _SUIT_CHAR.get(card.suit, "?")
    return rank + suit
