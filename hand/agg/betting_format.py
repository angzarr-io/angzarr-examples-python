"""Betting-format math — limit / pot-limit / no-limit interpretation.

Pure helpers used by ``handle_player_action`` to apply rules that vary
by ``BettingFormat``:

- TDA Rule 43A (50% silent-push rule, NL/PL only)
- TDA Rule 47B (limit-format short all-in 50% reopen)
- TDA Rule 48 (limit raise cap: 1 bet + 4 raises until heads-up)
- TDA Rule 52A (declared underraise correction)
- TDA Rule 52B (PL underbet correction)
- TDA Rule 54B (PL pre-flop full-blinds assumption)
- TDA Rule 54D ("bet the pot" in NL = at least minimum bet)

Mirrors the corresponding ``examples-rust/main/hand/agg/src/betting_format.rs``
module (to be added per cross-language unification) — keeping the two in
lockstep is enforced by the cross-language behave scenarios.
"""

from dataclasses import dataclass
from typing import NamedTuple

from angzarr_client.proto.examples import poker_types_pb2 as poker_types

# Default house raise cap per TDA Rule 48 (1 bet + 4 raises).
DEFAULT_LIMIT_RAISE_CAP = 4


class SilentPushOutcome(NamedTuple):
    """Result of interpreting a silent (chip-only) push under TDA Rule 43A.

    Per Rule 43A: in NL / PL, a silent push of >= 50% of the prior raise
    increment but < a full minimum raise is auto-promoted to a minimum
    raise. < 50% is treated as a CALL. >= a full minimum raise is just a
    legal raise (no promotion needed). For fixed-limit, see Rule 47B
    (which uses the same 50% threshold but for *short all-ins*, not
    silent pushes — silent pushes in limit are simpler since amounts
    are constrained to small_bet/big_bet anyway).
    """

    # The actual ActionType to record (CALL / BET / RAISE / ALL_IN).
    action: int
    # The absolute target amount the player commits to. For CALL this
    # is the matched current_bet; for RAISE this is the corrected
    # raise-to amount.
    target_amount: int
    # True if the original chip amount was promoted up to a full
    # minimum raise (used only for telemetry/logs).
    promoted: bool


def interpret_silent_push(
    *,
    pushed_amount: int,
    current_bet: int,
    prior_bet_on_street: int,
    last_raise_increment: int,
    player_stack: int,
    chip_count: int = 0,
) -> SilentPushOutcome:
    """Interpret a silent chip push under TDA Rule 43A.

    Args:
        pushed_amount: Total chips the player pushed in this action
            (includes any prior bet still on the table — i.e. the
            absolute "raise-to" the player intends if interpreted as
            a raise).
        current_bet: Current bet amount on the street.
        prior_bet_on_street: Player's existing bet this street (the
            chips already committed; ``pushed_amount`` includes these).
        last_raise_increment: The min legal raise increment (the
            largest prior raise on the street, or BB at street start).
        player_stack: Player's stack BEFORE this push (chips currently
            in the player's stack, not including any prior_bet_on_street).
        chip_count: Number of physical chips pushed. ``1`` triggers
            TDA Rule 44 (single oversized chip = call regardless of
            value). ``0`` (default) skips this branch.

    Returns:
        SilentPushOutcome with the resolved action and target_amount.
    """
    # TDA Rule 44 — a single oversized chip is a call.
    if chip_count == 1 and pushed_amount > current_bet:
        return SilentPushOutcome(
            action=poker_types.CALL,
            target_amount=current_bet,
            promoted=False,
        )

    # Chips the player added in this push. ``pushed_amount`` is the
    # total they intend on the table; subtract what's already there.
    chips_put_in = pushed_amount - prior_bet_on_street
    if chips_put_in < 0:
        # Pulling chips back is a different rule (Rule 46B); not a
        # silent push interpretation. Fall through to CALL by default.
        chips_put_in = 0

    call_amount = current_bet - prior_bet_on_street
    if call_amount < 0:
        call_amount = 0

    # All-in dominates: if the player puts in their entire stack,
    # the action is ALL_IN regardless of raise-vs-call interpretation.
    if chips_put_in >= player_stack:
        target = prior_bet_on_street + player_stack
        return SilentPushOutcome(
            action=poker_types.ALL_IN,
            target_amount=target,
            promoted=False,
        )

    if chips_put_in <= call_amount:
        # Less than a full call — treated as a call for the call_amount.
        # (The handler upstream of this should have already validated
        # that chips_put_in > 0; otherwise the push is degenerate.)
        return SilentPushOutcome(
            action=poker_types.CALL,
            target_amount=current_bet,
            promoted=False,
        )

    raise_increment = chips_put_in - call_amount
    min_raise_increment = last_raise_increment
    if min_raise_increment <= 0:
        # Degenerate (pre-blinds) — any raise is legal.
        return SilentPushOutcome(
            action=poker_types.RAISE,
            target_amount=prior_bet_on_street + chips_put_in,
            promoted=False,
        )

    # Rule 43A: 50% threshold determines promote vs treat-as-call.
    half_increment = (min_raise_increment + 1) // 2  # ceil(inc / 2)
    if raise_increment >= min_raise_increment:
        # Already a full legal raise — no promotion needed.
        return SilentPushOutcome(
            action=poker_types.RAISE,
            target_amount=prior_bet_on_street + chips_put_in,
            promoted=False,
        )
    if raise_increment >= half_increment:
        # Promote to full minimum raise.
        promoted_target = current_bet + min_raise_increment
        return SilentPushOutcome(
            action=poker_types.RAISE,
            target_amount=promoted_target,
            promoted=True,
        )
    # < 50% → treated as a call. Excess chips are returned upstream.
    return SilentPushOutcome(
        action=poker_types.CALL,
        target_amount=current_bet,
        promoted=False,
    )


def correct_declared_underraise(
    *,
    declared_amount: int,
    current_bet: int,
    last_raise_increment: int,
) -> int:
    """Correct a declared raise that's below the legal minimum (Rule 52A).

    Per TDA Rule 52A: a declared raise below the minimum legal amount is
    *corrected* (not rejected) anywhere on the current street before
    the next street is dealt. Returns the corrected absolute raise-to
    amount.

    A declared raise at or above the minimum is returned unchanged.
    """
    min_raise_to = current_bet + last_raise_increment
    if declared_amount < min_raise_to:
        return min_raise_to
    return declared_amount


def is_limit_raise_cap_reached(
    *,
    raises_this_round: int,
    raise_cap_per_round: int,
    is_heads_up: bool,
) -> bool:
    """Return True when the limit raise cap has been reached (Rule 48).

    TDA Rule 48: limit play caps raises per round (default 1 bet + 4
    raises = 4 in the cap counter). When the field is reduced to 2
    active players (heads-up), the cap is removed.

    Args:
        raises_this_round: Count of RAISE actions taken on the current
            street (the opening BET is *not* counted).
        raise_cap_per_round: House cap. 0 means use default
            (DEFAULT_LIMIT_RAISE_CAP). Negative means uncapped.
        is_heads_up: True if exactly 2 active (un-folded, un-busted)
            players remain. When True, cap is uncapped.
    """
    if is_heads_up:
        return False
    cap = raise_cap_per_round if raise_cap_per_round > 0 else DEFAULT_LIMIT_RAISE_CAP
    if cap < 0:
        return False
    return raises_this_round >= cap


@dataclass(frozen=True)
class LimitShortAllInOutcome:
    """Result of evaluating a fixed-limit short all-in under Rule 47B."""

    last_raise_increment: int
    action_reopened: bool


def apply_limit_short_all_in(
    *,
    current_bet: int,
    last_raise_increment: int,
    all_in_to: int,
) -> LimitShortAllInOutcome:
    """Apply Rule 47B: limit-format 50%-of-full-bet reopen threshold.

    In limit, an all-in increment of >= 50% of a full bet/raise reopens
    action for prior actors. Below 50% does not reopen. (Limit cumulative
    short all-ins follow the same 50% threshold but per-all-in, not
    cumulative — Rule 47B does not have the "cumulative" clause that
    Rule 47A NL/PL does.)
    """
    increment = all_in_to - current_bet
    if increment <= 0:
        return LimitShortAllInOutcome(
            last_raise_increment=last_raise_increment,
            action_reopened=False,
        )
    if increment >= last_raise_increment:
        # Full legal raise via all-in.
        return LimitShortAllInOutcome(
            last_raise_increment=increment,
            action_reopened=True,
        )
    half_increment = (last_raise_increment + 1) // 2
    if increment >= half_increment:
        return LimitShortAllInOutcome(
            last_raise_increment=increment,
            action_reopened=True,
        )
    return LimitShortAllInOutcome(
        last_raise_increment=last_raise_increment,
        action_reopened=False,
    )


def pot_limit_max_raise_to_preflop(
    *,
    small_blind: int,
    big_blind: int,
    sb_posted: int,
    bb_posted: int,
) -> int:
    """Pot-limit pre-flop max raise-to assuming full blinds (Rule 54B).

    "Pre-flop a dead or short all-in blind will not affect pot
    calculation. All pre-flop pot and re-pot bets will assume full
    blinds were posted." Returns the maximum legal first-action raise-to.

    The standard pot-limit formula for the first preflop raise is:
        max_raise_to = (call) + pot_after_call
                     = BB + (SB + BB + BB)        # full blinds, BB call
                     = SB + 3 × BB

    With a short SB or short BB, the actual chip count differs but the
    pot-limit calculation uses full blinds. ``sb_posted``/``bb_posted``
    are accepted for API symmetry with ``apply_blind_posted`` callers
    but ignored when computing this max — by Rule 54B's explicit
    mandate.
    """
    _ = (sb_posted, bb_posted)  # accepted for API symmetry; ignored per Rule 54B.
    return small_blind + 3 * big_blind


def bet_the_pot_in_no_limit_min(*, big_blind: int) -> int:
    """Resolve "I bet the pot" in NL to the minimum legal bet (Rule 54D).

    "'Bet the pot' is not a valid bet in no-limit but it does bind the
    player to making a valid bet (at least a minimum bet)." The minimum
    opening bet in NL Hold'em is the big blind.
    """
    return big_blind
