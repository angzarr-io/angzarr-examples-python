"""Unit tests for ``hand.agg.pot_distribution``.

Mirrors the Rust unit tests in ``examples-rust/main/hand/agg/src/pot_distribution.rs``.
"""

import pytest

from hand.agg.pot_distribution import (
    Award,
    HighLowSplit,
    WinnerWithSeat,
    WinnerWithSuit,
    split_high_low_total,
    split_pot_by_suit,
    split_pot_clockwise_from_button,
)


# === split_pot_clockwise_from_button (TDA Rule 20A) ===


def test_eu_1170_odd_chip_to_first_seat_clockwise_of_button():
    """EU-1170 — TDA Rule 20A: pot=101, two-way tie; Alice at seat 1 is
    first clockwise of button at seat 0. Alice gets 51, Bob 50."""
    winners = [
        WinnerWithSeat(player_root="Alice", seat=1),
        WinnerWithSeat(player_root="Bob", seat=2),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=0, max_seats=9
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 51, "Bob": 50}
    assert sum(a.amount for a in awards) == 101


def test_even_pot_distributes_equally():
    """No odd chip — both winners get exactly half, button is irrelevant."""
    winners = [
        WinnerWithSeat(player_root="Alice", seat=1),
        WinnerWithSeat(player_root="Bob", seat=2),
    ]
    awards = split_pot_clockwise_from_button(
        pot=100, winners=winners, dealer_button_seat=0, max_seats=9
    )
    assert all(a.amount == 50 for a in awards)


def test_three_way_tie_with_one_odd_chip_goes_clockwise():
    """Pot=100 split 3 ways = 33 each + 1 odd chip. Odd goes to first
    seat clockwise of button (seat 0)."""
    winners = [
        WinnerWithSeat(player_root="Alice", seat=1),
        WinnerWithSeat(player_root="Bob", seat=2),
        WinnerWithSeat(player_root="Carol", seat=3),
    ]
    awards = split_pot_clockwise_from_button(
        pot=100, winners=winners, dealer_button_seat=0, max_seats=9
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 34, "Bob": 33, "Carol": 33}
    assert sum(a.amount for a in awards) == 100


def test_three_way_tie_with_two_odd_chips_continues_clockwise():
    """Pot=101 split 3 ways = 33 each + 2 odd chips. Odd chips to first
    two clockwise (Alice and Bob), Carol stays at base."""
    winners = [
        WinnerWithSeat(player_root="Alice", seat=1),
        WinnerWithSeat(player_root="Bob", seat=2),
        WinnerWithSeat(player_root="Carol", seat=3),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=0, max_seats=9
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 34, "Bob": 34, "Carol": 33}
    assert sum(a.amount for a in awards) == 101


def test_button_at_higher_seat_wraps_clockwise():
    """Button at seat 5; winners at seats 1 (Alice) and 8 (Bob).
    Clockwise from seat 5 goes 6, 7, 8, ... ; Bob at seat 8 is closer
    than Alice at seat 1 (which is at distance (1-5-1) mod 9 = 4 vs
    Bob's (8-5-1) mod 9 = 2). Bob gets the odd chip."""
    winners = [
        WinnerWithSeat(player_root="Alice", seat=1),
        WinnerWithSeat(player_root="Bob", seat=8),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=5, max_seats=9
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 50, "Bob": 51}


def test_split_pot_clockwise_rejects_empty_winners():
    with pytest.raises(ValueError) as exc:
        split_pot_clockwise_from_button(
            pot=100, winners=[], dealer_button_seat=0, max_seats=9
        )
    # Exact message check (defends against string-mutation testing).
    assert str(exc.value) == "winners must be non-empty"


def test_split_pot_clockwise_rejects_non_positive_pot():
    winners = [WinnerWithSeat(player_root="Alice", seat=1)]
    with pytest.raises(ValueError) as exc:
        split_pot_clockwise_from_button(
            pot=0, winners=winners, dealer_button_seat=0, max_seats=9
        )
    assert str(exc.value) == "pot must be positive, got 0"
    with pytest.raises(ValueError) as exc:
        split_pot_clockwise_from_button(
            pot=-1, winners=winners, dealer_button_seat=0, max_seats=9
        )
    assert str(exc.value) == "pot must be positive, got -1"


def test_split_pot_clockwise_rejects_max_seats_too_small():
    """Validation: max_seats must cover both the button and all winner
    seats. Catches a caller passing a too-small max_seats by accident."""
    winners = [WinnerWithSeat(player_root="Alice", seat=8)]
    with pytest.raises(ValueError) as exc:
        split_pot_clockwise_from_button(
            pot=100, winners=winners, dealer_button_seat=2, max_seats=5
        )
    assert "max_seats (5)" in str(exc.value)
    assert "at least 9" in str(exc.value)


def test_split_pot_clockwise_with_pot_of_exactly_one_chip():
    """Boundary: pot=1 must succeed, not raise. Catches `<=0` → `<=1`
    boundary mutation on the validation guard."""
    winners = [WinnerWithSeat(player_root="Alice", seat=1)]
    awards = split_pot_clockwise_from_button(
        pot=1, winners=winners, dealer_button_seat=0, max_seats=9
    )
    assert awards == [Award(player_root="Alice", amount=1)]


def test_split_pot_clockwise_with_button_beyond_winner_seats():
    """Sparse layout: button at seat 10 (table holds 11 seats); winners
    at seats 0 and 5. Clockwise from button=10 wraps to seat 0 (next
    seat), then seat 5. Alice at seat 0 gets the odd chip.
    """
    winners = [
        WinnerWithSeat(player_root="Alice", seat=0),
        WinnerWithSeat(player_root="Bob", seat=5),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=10, max_seats=11
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 51, "Bob": 50}


def test_split_pot_clockwise_winner_at_button_seat_is_furthest():
    """The button's own seat is the LAST seat clockwise (distance =
    max_seats - 1), not the FIRST. With button=0, max_seats=11, a winner
    at seat 0 (the button) has distance 10; a winner at seat 10 has
    distance 9 — seat 10 gets the odd chip.

    Catches mutations that drop the `- 1` term: seat=button would map to
    distance 0 (the immediate next clockwise), flipping the outcome.
    """
    winners = [
        WinnerWithSeat(player_root="Alice", seat=10),
        WinnerWithSeat(player_root="Bob", seat=0),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=0, max_seats=11
    )
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 51, "Bob": 50}


def test_split_pot_clockwise_seat_just_before_button_is_furthest():
    """Boundary: the seat IMMEDIATELY before the button is the FURTHEST
    clockwise (distance = max_seats - 1, not 0).

    With button at seat 0 and a 9-seat table, seat 8 is one before the
    button and is furthest clockwise (distance 7). Seat 7 is one closer
    (distance 6). Alice@7 wins the odd chip over Bob@8.

    Catches mutations that shift the `-1` term in the distance formula:
    e.g. `-1` → `+1` would map seat 8 to distance 0 (wrapping), making
    Bob appear "first clockwise" when he is actually second-to-last.
    """
    winners = [
        WinnerWithSeat(player_root="Alice", seat=7),
        WinnerWithSeat(player_root="Bob", seat=8),
    ]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=0, max_seats=9
    )
    by_player = {a.player_root: a.amount for a in awards}
    # Alice (closer clockwise from button: distance 6) gets the odd chip.
    # Bob is at distance 7 — second-to-last possible position.
    assert by_player == {"Alice": 51, "Bob": 50}


def test_split_pot_clockwise_distance_is_modular_via_max_seats():
    """A 9-seat table with button at 8: seat 0 is the next clockwise
    (distance 0). With a 10-seat table and the same button position,
    seat 0 is two seats away (distance 1), so seat 9 (if occupied)
    would be closer. Pinning max_seats explicitly proves the modulus
    parameter actually affects ordering.
    """
    winners = [
        WinnerWithSeat(player_root="Alice", seat=0),
        WinnerWithSeat(player_root="Bob", seat=4),
    ]
    # 9-seat table: seat 0 distance=(0-8-1)%9=0, seat 4 distance=4. Alice first.
    awards_9 = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=8, max_seats=9
    )
    by_player_9 = {a.player_root: a.amount for a in awards_9}
    assert by_player_9 == {"Alice": 51, "Bob": 50}

    # 10-seat table: seat 0 distance=(0-8-1)%10=1, seat 4 distance=(4-8-1)%10=5.
    # Alice still first (1 < 5).
    awards_10 = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=8, max_seats=10
    )
    by_player_10 = {a.player_root: a.amount for a in awards_10}
    assert by_player_10 == {"Alice": 51, "Bob": 50}


def test_split_pot_clockwise_single_winner_takes_full_pot():
    """Sanity: one winner gets everything regardless of button."""
    winners = [WinnerWithSeat(player_root="Alice", seat=3)]
    awards = split_pot_clockwise_from_button(
        pot=101, winners=winners, dealer_button_seat=0, max_seats=9
    )
    assert awards == [Award(player_root="Alice", amount=101)]


# === split_pot_by_suit (Robert's §35-9) ===


def test_eu_1172_multi_way_high_chip_goes_to_high_card_by_suit():
    """EU-1172 — Robert's §35-9: high half of H/L pot, two tied highs.
    Alice has Ah (suit_rank=50: ace=12, hearts=2, so 12*4+2=50);
    Bob has Kh (suit_rank=46). Pot=51 → Alice gets 26, Bob 25."""
    # Encode: card_rank * 4 + suit_index where suit: c=0,d=1,h=2,s=3.
    # Ace of hearts: 12*4 + 2 = 50; King of hearts: 11*4 + 2 = 46.
    winners = [
        WinnerWithSuit(player_root="Alice", suit_rank=50),
        WinnerWithSuit(player_root="Bob", suit_rank=46),
    ]
    awards = split_pot_by_suit(pot=51, winners=winners, high_wins=True)
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 26, "Bob": 25}


def test_split_by_suit_low_wins_gives_chip_to_lowest():
    """Low-side of H/L (or razz): odd chip goes to the LOW card by suit."""
    # Two of clubs (suit_rank=0*4+0=0); two of spades (0*4+3=3).
    winners = [
        WinnerWithSuit(player_root="Alice", suit_rank=0),
        WinnerWithSuit(player_root="Bob", suit_rank=3),
    ]
    awards = split_pot_by_suit(pot=51, winners=winners, high_wins=False)
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 26, "Bob": 25}


def test_split_by_suit_even_pot_distributes_equally():
    winners = [
        WinnerWithSuit(player_root="Alice", suit_rank=50),
        WinnerWithSuit(player_root="Bob", suit_rank=46),
    ]
    awards = split_pot_by_suit(pot=100, winners=winners, high_wins=True)
    assert all(a.amount == 50 for a in awards)


def test_split_by_suit_three_way_with_two_odd_chips():
    """Pot=101 among 3 tied; 33 each + 2 extras. Top two suit ranks
    each get +1; lowest stays at base."""
    winners = [
        WinnerWithSuit(player_root="Alice", suit_rank=50),  # Ah
        WinnerWithSuit(player_root="Bob", suit_rank=46),    # Kh
        WinnerWithSuit(player_root="Carol", suit_rank=42),  # Qh
    ]
    awards = split_pot_by_suit(pot=101, winners=winners, high_wins=True)
    by_player = {a.player_root: a.amount for a in awards}
    assert by_player == {"Alice": 34, "Bob": 34, "Carol": 33}


def test_split_by_suit_rejects_empty_or_non_positive():
    with pytest.raises(ValueError) as exc:
        split_pot_by_suit(pot=100, winners=[], high_wins=True)
    assert str(exc.value) == "winners must be non-empty"
    with pytest.raises(ValueError) as exc:
        split_pot_by_suit(
            pot=0,
            winners=[WinnerWithSuit(player_root="Alice", suit_rank=10)],
            high_wins=True,
        )
    assert str(exc.value) == "pot must be positive, got 0"


def test_split_by_suit_with_pot_of_exactly_one_chip():
    """Boundary: pot=1 succeeds. Catches `<=0` → `<=1` mutation."""
    winners = [WinnerWithSuit(player_root="Alice", suit_rank=50)]
    awards = split_pot_by_suit(pot=1, winners=winners, high_wins=True)
    assert awards == [Award(player_root="Alice", amount=1)]


def test_split_by_suit_high_wins_is_required():
    """``high_wins`` is a required parameter (no default). This guards
    against accidental misinterpretation of which side wins the odd chip.
    """
    winners = [WinnerWithSuit(player_root="Alice", suit_rank=50)]
    with pytest.raises(TypeError):
        split_pot_by_suit(pot=51, winners=winners)  # type: ignore[call-arg]


# === split_high_low_total (TDA Rule 20C) ===


def test_eu_1171_odd_chip_in_total_pot_goes_to_high_side():
    """EU-1171 — TDA Rule 20C: odd chip in total H/L pot goes to high."""
    result = split_high_low_total(pot=101)
    assert result == HighLowSplit(high_share=51, low_share=50)
    assert result.high_share + result.low_share == 101


def test_high_low_even_split():
    result = split_high_low_total(pot=100)
    assert result == HighLowSplit(high_share=50, low_share=50)


def test_high_low_split_rejects_non_positive_pot():
    with pytest.raises(ValueError, match="pot must be positive"):
        split_high_low_total(pot=0)
    with pytest.raises(ValueError, match="pot must be positive"):
        split_high_low_total(pot=-5)


def test_high_low_minimum_pot_of_one_chip_goes_entirely_to_high():
    """Boundary: pot=1 → high gets 1, low gets 0. Validates the floor
    division gives low_share=0 and high gets the lone chip."""
    result = split_high_low_total(pot=1)
    assert result == HighLowSplit(high_share=1, low_share=0)
