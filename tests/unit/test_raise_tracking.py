"""Unit tests for ``hand.agg.raise_tracking``.

Mirrors the Rust unit tests in ``examples-rust/main/hand/agg/src/raise_tracking.rs``
so the cross-language parity is enforced at the unit level too.
"""

import pytest

from hand.agg.raise_tracking import (
    StreetResetState,
    all_in_to,
    apply_short_all_in,
    min_raise_to,
    next_last_raise_increment,
    reset_per_round,
    short_all_in_initial,
)


def test_min_raise_to_after_blinds():
    assert min_raise_to(10, 10) == 20


def test_next_increment_grows_when_larger():
    assert next_last_raise_increment(10, 10, 30) == 20


def test_next_increment_holds_when_smaller():
    assert next_last_raise_increment(100, 50, 130) == 50


def test_all_in_to_sums_stack_and_committed():
    assert all_in_to(40, 0) == 40
    assert all_in_to(20, 30) == 50


# === ShortAllIn tracker ===


def test_initial_tracker_has_no_cumulative():
    s = short_all_in_initial(100, 50)
    assert s.current_bet == 100
    assert s.last_raise_increment == 50
    assert s.cumulative_short == 0
    assert s.action_reopened is False


def test_eu_1140_cumulative_shorts_reaching_full_raise_reopen_action():
    """EU-1140 — TDA Rule 47A: two cumulative shorts of +30 each reach 60,
    crossing the 50 threshold, so action reopens."""
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 130)
    assert s1.action_reopened is False
    assert s1.cumulative_short == 30
    assert s1.current_bet == 130
    assert s1.last_raise_increment == 50

    s2 = apply_short_all_in(s1, 160)
    assert s2.action_reopened is True
    assert s2.last_raise_increment == 60
    assert s2.current_bet == 160
    assert s2.cumulative_short == 0


def test_eu_1141_cumulative_shorts_below_threshold_do_not_reopen():
    """EU-1141 — TDA Rule 47A: two shorts of +20 and +10 reach 30, still
    below the 50 threshold, so action does not reopen."""
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 120)
    s2 = apply_short_all_in(s1, 130)
    assert s2.action_reopened is False
    assert s2.last_raise_increment == 50
    assert s2.current_bet == 130
    assert s2.cumulative_short == 30


def test_full_raise_after_short_resets_cumulative_tracker():
    """A full raise after a short all-in restarts the tracker."""
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 120)  # +20 short
    s2 = apply_short_all_in(s1, 200)  # +80 full raise
    assert s2.action_reopened is True
    assert s2.cumulative_short == 0
    assert s2.last_raise_increment == 80
    assert s2.current_bet == 200


def test_first_all_in_that_is_a_full_raise_reopens_immediately():
    """A single all-in whose increment >= last_raise_increment is a
    full raise (not a short); action reopens, cumulative stays 0."""
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 200)  # +100 full raise
    assert s1.action_reopened is True
    assert s1.cumulative_short == 0
    assert s1.last_raise_increment == 100
    assert s1.current_bet == 200


def test_exact_threshold_short_reopens():
    """A short whose cumulative increment equals (not exceeds) the
    threshold reopens action — boundary on the >= test."""
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 125)  # +25 short
    s2 = apply_short_all_in(s1, 150)  # +25 short, cumulative 50 == threshold
    assert s2.action_reopened is True
    assert s2.last_raise_increment == 50
    assert s2.current_bet == 150


def test_first_all_in_at_exact_threshold_is_a_full_raise():
    """Boundary: an all-in whose increment EQUALS the threshold (not
    exceeds it) is treated as a full raise, NOT a short. Reopens
    action and resets the cumulative tracker on the first call.

    Catches the >= → > mutation on the full-raise branch.
    """
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 150)  # increment exactly 50
    assert s1.action_reopened is True
    assert s1.cumulative_short == 0
    assert s1.last_raise_increment == 50
    assert s1.current_bet == 150


def test_reset_per_round_returns_zero_current_bet_and_bb_increment():
    """EU-1006 — TDA Rule 47A: at the start of every new street,
    ``current_bet`` resets to 0 and ``last_raise_increment`` resets to
    the big blind."""
    s = reset_per_round(big_blind=10)
    assert s == StreetResetState(current_bet=0, last_raise_increment=10)


def test_reset_per_round_works_with_various_big_blinds():
    """The reset always produces (0, big_blind) regardless of the BB
    amount. Pin three different BBs to catch a hardcoded constant."""
    assert reset_per_round(big_blind=1).last_raise_increment == 1
    assert reset_per_round(big_blind=25).last_raise_increment == 25
    assert reset_per_round(big_blind=10000).last_raise_increment == 10000


def test_reset_per_round_current_bet_is_always_zero():
    """current_bet is always zero — independent of big_blind."""
    for bb in (1, 10, 100, 1_000_000):
        assert reset_per_round(big_blind=bb).current_bet == 0


def test_reset_per_round_accepts_zero_big_blind_as_degenerate_case():
    """big_blind=0 is permitted (no BB established yet) and returns
    (0, 0). This matches the prior aggregate behavior; the Hand
    aggregate has internal transitions where state.big_blind is 0
    before any BlindPosted event has been applied."""
    s = reset_per_round(big_blind=0)
    assert s == StreetResetState(current_bet=0, last_raise_increment=0)


def test_reset_per_round_rejects_negative_big_blind():
    """Negative big_blind is invalid. Pin the exact message — guards
    against string-mutation testing."""
    with pytest.raises(ValueError) as exc:
        reset_per_round(big_blind=-5)
    assert str(exc.value) == "big_blind must be non-negative, got -5"
    with pytest.raises(ValueError) as exc:
        reset_per_round(big_blind=-1)
    assert str(exc.value) == "big_blind must be non-negative, got -1"


def test_reset_per_round_min_raise_to_after_reset_equals_big_blind():
    """On a NEW street, ``current_bet`` resets to 0 and the min legal
    BET is the big blind. ``min_raise_to(0, BB) == BB`` confirms the
    helper composes correctly with ``min_raise_to`` from the same
    module — and that the EU-1010 / EU-1012 invariant ("minimum bet on
    a new street is the big blind") is honoured.
    """
    s = reset_per_round(big_blind=10)
    assert min_raise_to(s.current_bet, s.last_raise_increment) == 10

    s2 = reset_per_round(big_blind=100)
    assert min_raise_to(s2.current_bet, s2.last_raise_increment) == 100


def test_full_raise_after_short_uses_increment_not_cumulative():
    """After a prior short (cumulative_short=20), an all-in whose
    increment equals the threshold (boundary case) MUST be classified
    as a full raise. The full-raise branch sets last_raise_increment=
    increment (50), NOT cumulative (20+50=70). This distinguishes the
    full-raise branch from the cumulative-reopen branch.

    Catches the >= → > mutation on the full-raise branch by forcing the
    two branches to produce different last_raise_increment values.
    """
    s0 = short_all_in_initial(100, 50)
    s1 = apply_short_all_in(s0, 120)  # +20 short, cumulative=20
    assert s1.cumulative_short == 20
    s2 = apply_short_all_in(s1, 170)  # increment=50 == prior.lri (boundary)
    assert s2.action_reopened is True
    assert s2.cumulative_short == 0
    # Full-raise branch returns lri=increment=50.
    # Mutated (>) would fall through to cumulative branch and return
    # lri=cumulative=70. So this test catches the mutation.
    assert s2.last_raise_increment == 50, (
        "boundary increment must use full-raise branch (lri=increment), "
        "not cumulative-reopen branch (lri=cumulative)"
    )
    assert s2.current_bet == 170
