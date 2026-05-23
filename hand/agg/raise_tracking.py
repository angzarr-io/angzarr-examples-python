"""Raise-tracking arithmetic helpers — Python mirror of the Rust module.

Pure-math helpers used by the production handler when validating raises.
The server's ``min_raise`` tracking must agree with these functions or
clients will submit raises the server rejects.

This module mirrors ``examples-rust/main/hand/agg/src/raise_tracking.rs``;
keeping the two in lockstep is enforced by the cross-language behave
scenarios in ``features/example/unit/raise_tracking.feature``.
"""

from dataclasses import dataclass


def min_raise_to(current_bet: int, last_raise_increment: int) -> int:
    """Return the minimum raise *target* (the min RaiseTo amount).

    Equals ``current_bet + last_raise_increment``. After SB/BB are posted in
    no-limit Hold'em, ``current_bet == last_raise_increment == BB``, so the
    first legal raise is to ``2 * BB``.
    """
    return current_bet + last_raise_increment


def next_last_raise_increment(
    current_bet: int, last_raise_increment: int, new_bet: int
) -> int:
    """Return the updated ``last_raise_increment`` after a RAISE to ``new_bet``.

    Implements ``max(old, new_increment)`` semantics: a raise that exceeds
    the previous increment grows the tracker; a (legal) raise that doesn't
    leaves it intact unless the new increment is larger.

    ``new_bet`` must be the absolute target the player raised TO, not the
    delta.
    """
    increment = new_bet - current_bet
    return max(last_raise_increment, increment)


def all_in_to(stack: int, current_bet_for_player: int) -> int:
    """Return the absolute amount a player goes all-in TO.

    Adds the player's remaining stack to whatever they've already committed
    this round.
    """
    return stack + current_bet_for_player


@dataclass(frozen=True)
class ShortAllInOutcome:
    """Outcome of feeding one or more short all-ins through the tracker.

    Per TDA Rule 47A second sentence: "If multiple short all-ins re-open
    the betting, the minimum raise is always the last full valid bet or
    raise of the round." The cumulative increment of consecutive short
    all-ins is compared against the existing ``last_raise_increment``; if
    it reaches or exceeds the threshold, betting reopens for prior actors
    and ``last_raise_increment`` is updated to the cumulative amount.
    """

    current_bet: int
    last_raise_increment: int
    cumulative_short: int
    action_reopened: bool


def short_all_in_initial(
    current_bet: int, last_raise_increment: int
) -> ShortAllInOutcome:
    """Return the initial tracker state (no short all-ins applied yet)."""
    return ShortAllInOutcome(
        current_bet=current_bet,
        last_raise_increment=last_raise_increment,
        cumulative_short=0,
        action_reopened=False,
    )


@dataclass(frozen=True)
class StreetResetState:
    """Per-round betting state at the start of a new street.

    Per TDA Rule 47A "current betting round" wording: at the start of
    every new street (post-flop, post-turn, post-river-redeal), the
    minimum bet is the big blind and ``current_bet`` resets to 0.
    Carrying preflop's last_raise_increment forward is a real-rule
    violation — see ``raise_tracking.feature`` EU-1006/1011/1013.
    """

    current_bet: int
    last_raise_increment: int


def reset_per_round(big_blind: int) -> StreetResetState:
    """Compute the per-round betting state at the start of a new street.

    Per TDA Rule 47A: the minimum bet on a new street is the big blind,
    and ``current_bet`` resets to 0. ``last_raise_increment`` becomes
    the BB so the first BET must be at least the BB (matching the EU-1010
    invariant "first bet on a new street establishes the new
    last_raise_increment"). The first RAISE must be at least 2*BB.

    Args:
        big_blind: The current big blind amount. Must be non-negative —
            ``0`` is permitted as a degenerate case (no BB established
            yet, e.g. variant-specific transitions before any blinds
            have been posted).

    Returns:
        StreetResetState with ``current_bet=0`` and
        ``last_raise_increment=big_blind``.

    Raises:
        ValueError: if ``big_blind`` is negative.
    """
    if big_blind < 0:
        raise ValueError(f"big_blind must be non-negative, got {big_blind}")
    return StreetResetState(current_bet=0, last_raise_increment=big_blind)


def apply_short_all_in(prior: ShortAllInOutcome, new_bet: int) -> ShortAllInOutcome:
    """Apply a single short all-in (whose absolute target is ``new_bet``) to a
    running tracker. The tracker carries ``cumulative_short`` across calls
    to detect when consecutive shorts cumulatively reach a full raise.

    Per TDA Rule 47A: if ``new_bet - current_bet < last_raise_increment``
    the all-in is "short". Otherwise the all-in is itself a full raise
    and the tracker is updated normally (``cumulative_short`` is reset).
    """
    increment = new_bet - prior.current_bet
    if increment >= prior.last_raise_increment:
        # Full raise — reopens action, resets cumulative tracker.
        return ShortAllInOutcome(
            current_bet=new_bet,
            last_raise_increment=increment,
            cumulative_short=0,
            action_reopened=True,
        )
    cumulative = prior.cumulative_short + increment
    if cumulative >= prior.last_raise_increment:
        return ShortAllInOutcome(
            current_bet=new_bet,
            last_raise_increment=cumulative,
            cumulative_short=0,
            action_reopened=True,
        )
    return ShortAllInOutcome(
        current_bet=new_bet,
        last_raise_increment=prior.last_raise_increment,
        cumulative_short=cumulative,
        action_reopened=False,
    )
