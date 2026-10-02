"""Cards, hand values and the deterministic shoe (house rules AHR-2, AHR-3).

The shuffle is pinned byte for byte in ``cards.proto``: SplitMix64 from a
64-bit seed drives a descending Fisher–Yates shuffle through unbiased bounded
draws. Every language of the example must deal the same cards from the same
seed; the golden vectors live in ``features/example/blackjack/shoe.feature``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from angzarr_blackjack._gen.io.angzarr.examples.v1 import cards_pb2 as _cards

Card = _cards.Card
Suit = _cards.Suit

_MASK64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_1 = 0xBF58476D1CE4E5B9
_MIX_2 = 0x94D049BB133111EB

CARDS_PER_DECK = 52
ACE = 1
BLACKJACK = 21
# A hand of 21 or less never holds more than 11 cards (AHR-4).
MAX_CARDS_PER_HAND = 11


class SplitMix64:
    """The SplitMix64 generator, all arithmetic wrapping mod 2^64."""

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.state = seed & _MASK64

    def next(self) -> int:
        self.state = (self.state + _GOLDEN_GAMMA) & _MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * _MIX_1) & _MASK64
        z = ((z ^ (z >> 27)) * _MIX_2) & _MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """An unbiased draw in [0, n): raw values under 2^64 mod n are redrawn."""
        threshold = (1 << 64) % n
        while True:
            r = self.next()
            if r >= threshold:
                return r % n


def next_seed(seed: int) -> int:
    """The seed of the shoe that replaces a shoe shuffled with ``seed``."""
    return SplitMix64(seed).next()


def card_from_index(index: int) -> Card:
    """The card at canonical index ``13 * (suit - 1) + (rank - 1)``."""
    return Card(rank=index % 13 + 1, suit=index // 13 + 1)


def card_index(card: Card) -> int:
    return 13 * (card.suit - 1) + (card.rank - 1)


def shuffled_indices(seed: int, decks: int) -> list[int]:
    """Canonical indices of a shuffled shoe of ``decks`` decks, in deal order."""
    cards = [p % CARDS_PER_DECK for p in range(CARDS_PER_DECK * decks)]
    rng = SplitMix64(seed)
    for i in range(len(cards) - 1, 0, -1):
        j = rng.below(i + 1)
        cards[i], cards[j] = cards[j], cards[i]
    return cards


def shuffle(seed: int, decks: int) -> list[Card]:
    """A shuffled shoe of ``decks`` decks, in deal order."""
    return [card_from_index(i) for i in shuffled_indices(seed, decks)]


def points(card: Card) -> int:
    """Hard points of one card: Ace 1, Jack/Queen/King 10."""
    return min(card.rank, 10)


def hand_value(cards: Iterable[Card]) -> tuple[int, bool]:
    """(total, soft) of a hand: an Ace counts 11 unless that busts the hand."""
    hard = 0
    has_ace = False
    for card in cards:
        hard += points(card)
        has_ace = has_ace or card.rank == ACE
    if has_ace and hard + 10 <= BLACKJACK:
        return hard + 10, True
    return hard, False


def is_blackjack(cards: Sequence[Card]) -> bool:
    """Exactly two cards totalling 21."""
    return len(cards) == 2 and hand_value(cards)[0] == BLACKJACK


def is_ten_or_ace(card: Card) -> bool:
    """The dealer's up-card shows an Ace or a 10-point card (AHR-7 peek)."""
    return card.rank == ACE or points(card) == 10


# --- notation: rank then suit, e.g. "A♠", "10♦", "Q♣" -----------------------

_RANKS = {"A": 1, "J": 11, "Q": 12, "K": 13}
_RANK_NAMES = {v: k for k, v in _RANKS.items()}
_PIPS = {str(rank) for rank in range(2, 11)}
_SUITS = {"♣": Suit.CLUBS, "♦": Suit.DIAMONDS, "♥": Suit.HEARTS, "♠": Suit.SPADES}
_SUIT_NAMES = {v: k for k, v in _SUITS.items()}


def parse_card(text: str) -> Card:
    """Parse one card written rank then suit ("A♠", "10♦")."""
    rank_text, suit_text = text[:-1], text[-1]
    rank = _RANKS.get(rank_text) or (int(rank_text) if rank_text in _PIPS else None)
    if rank is None or suit_text not in _SUITS:
        raise ValueError(f"not a card: {text!r}")
    return Card(rank=rank, suit=_SUITS[suit_text])


def parse_cards(text: str) -> list[Card]:
    """Parse space-separated cards ("A♠ K♦ 9♣")."""
    return [parse_card(token) for token in text.split()]


def format_card(card: Card) -> str:
    return _RANK_NAMES.get(card.rank, str(card.rank)) + _SUIT_NAMES[card.suit]


def format_cards(cards: Iterable[Card]) -> str:
    return " ".join(format_card(card) for card in cards)
