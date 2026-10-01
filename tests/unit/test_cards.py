"""The shoe and card values. The shuffle vectors are the cross-language golden
vectors from cards.proto / shoe.feature: every language must produce these
exact numbers and cards, so a change here is a parity break, not a refactor."""

from collections import Counter

import pytest

from angzarr_blackjack import cards
from angzarr_blackjack.cards import Card, Suit


def test_splitmix64_reference_values():
    # Published SplitMix64 reference outputs (cards.proto check vector).
    rng = cards.SplitMix64(1234567)
    assert [rng.next() for _ in range(3)] == [
        6457827717110365317,
        3203168211198807973,
        9817491932198370423,
    ]
    rng = cards.SplitMix64(1)
    assert [rng.next() for _ in range(3)] == [
        10451216379200822465,
        13757245211066428519,
        17911839290282890590,
    ]


def test_splitmix64_wraps_at_64_bits():
    # A seed at the top of the range must wrap, not grow past 64 bits.
    rng = cards.SplitMix64(2**64 - 1)
    value = rng.next()
    assert 0 <= value < 2**64
    assert rng.state == (2**64 - 1 + 0x9E3779B97F4A7C15) % 2**64


def test_bounded_draw_rejects_values_below_the_threshold():
    # With a bound just above 2^63 the 4th and 5th raw values of seed 1 fall
    # under the threshold and are redrawn (shoe.feature EU-1525).
    rng = cards.SplitMix64(1)
    assert [rng.below(9223372036854775809) for _ in range(5)] == [
        1227844342346046656,
        4533873174211652710,
        8688467253428114781,
        4849545566009754239,
        6960854651289091236,
    ]


def test_bounded_draw_of_one_is_always_zero():
    rng = cards.SplitMix64(99)
    assert {rng.below(1) for _ in range(10)} == {0}


@pytest.mark.parametrize(
    "seed, decks, first_twelve, last",
    [
        (1, 1, "7♦ 9♣ 4♦ 8♥ 8♦ 5♠ J♦ 6♦ 9♠ J♣ 5♦ K♦", "7♠"),
        (42, 1, "7♣ 3♥ K♣ A♠ 2♠ A♣ A♥ K♦ 10♦ 5♣ 8♠ J♥", "10♣"),
        (7, 1, "4♦ 5♣ J♥ 3♠ 4♥ 10♥ K♠ 6♦ 4♠ 7♥ 9♦ 2♣", "Q♣"),
        (1, 6, "6♠ A♣ 7♥ 3♣ 6♠ J♥ 3♥ Q♠ Q♣ 6♥ 6♦ 7♦", "7♠"),
        (42, 6, "7♠ K♠ 2♦ Q♣ 7♣ 7♥ 3♣ 7♥ 6♣ 7♦ 7♠ 4♦", "10♣"),
        (7, 6, "A♦ K♣ 4♦ 3♦ 9♣ 6♣ K♦ J♠ Q♠ J♦ A♥ 8♣", "Q♣"),
    ],
)
def test_golden_shoes(seed, decks, first_twelve, last):
    shoe = cards.shuffle(seed, decks)
    assert cards.format_cards(shoe[:12]) == first_twelve
    assert cards.format_card(shoe[-1]) == last
    assert len(shoe) == 52 * decks
    assert set(Counter(cards.card_index(c) for c in shoe).values()) == {decks}


def test_complete_one_deck_shoe_for_seed_1():
    assert cards.format_cards(cards.shuffle(1, 1)) == (
        "7♦ 9♣ 4♦ 8♥ 8♦ 5♠ J♦ 6♦ 9♠ J♣ 5♦ K♦ 3♣ "
        "2♦ J♥ 5♥ 7♥ 4♥ 2♣ A♦ 6♠ K♣ K♥ 10♥ 10♠ J♠ "
        "10♦ 8♠ Q♣ 4♠ 6♣ 7♣ A♠ 5♣ A♥ K♠ 6♥ Q♠ Q♥ "
        "Q♦ 9♦ 3♦ 3♠ A♣ 4♣ 2♥ 8♣ 10♣ 3♥ 2♠ 9♥ 7♠"
    )


@pytest.mark.parametrize(
    "seed, expected",
    [(1, 10451216379200822465), (42, 13679457532755275413), (7, 7191089600892374487)],
)
def test_next_seed_is_the_first_output(seed, expected):
    assert cards.next_seed(seed) == expected


def test_canonical_index():
    assert cards.card_from_index(0) == Card(rank=1, suit=Suit.CLUBS)
    assert cards.card_from_index(12) == Card(rank=13, suit=Suit.CLUBS)
    assert cards.card_from_index(13) == Card(rank=1, suit=Suit.DIAMONDS)
    assert cards.card_from_index(51) == Card(rank=13, suit=Suit.SPADES)
    assert all(cards.card_index(cards.card_from_index(i)) == i for i in range(52))


@pytest.mark.parametrize(
    "hand, total, soft",
    [
        ("K♣ Q♦", 20, False),
        ("A♣ 6♣", 17, True),
        ("A♣ A♦", 12, True),
        ("A♣ 6♣ 10♥", 17, False),
        ("A♣ A♦ 9♥", 21, True),
        ("A♣ K♦", 21, True),
        ("7♣ 4♦ K♥", 21, False),
        ("A♣ 10♦ K♥", 21, False),
        ("K♣ Q♦ 2♥", 22, False),
        ("5♣", 5, False),
    ],
)
def test_hand_value(hand, total, soft):
    assert cards.hand_value(cards.parse_cards(hand)) == (total, soft)


def test_blackjack_is_exactly_two_cards_of_21():
    assert cards.is_blackjack(cards.parse_cards("A♠ K♠"))
    assert cards.is_blackjack(cards.parse_cards("10♥ A♦"))
    assert not cards.is_blackjack(cards.parse_cards("7♣ 7♦ 7♥"))
    assert not cards.is_blackjack(cards.parse_cards("A♠ 9♠"))


def test_ten_or_ace_up_card():
    assert cards.is_ten_or_ace(cards.parse_card("A♣"))
    assert cards.is_ten_or_ace(cards.parse_card("J♦"))
    assert cards.is_ten_or_ace(cards.parse_card("10♥"))
    assert not cards.is_ten_or_ace(cards.parse_card("9♠"))


def test_points():
    assert [
        cards.points(cards.parse_card(t)) for t in ("A♣", "9♣", "10♣", "J♣", "Q♣", "K♣")
    ] == [
        1,
        9,
        10,
        10,
        10,
        10,
    ]


def test_notation_round_trips():
    text = "A♠ 2♣ 10♦ J♥ Q♣ K♠"
    assert cards.format_cards(cards.parse_cards(text)) == text


@pytest.mark.parametrize("bad", ["1♠", "14♣", "K?", "0♦"])
def test_notation_rejects_non_cards(bad):
    with pytest.raises(ValueError):
        cards.parse_card(bad)
