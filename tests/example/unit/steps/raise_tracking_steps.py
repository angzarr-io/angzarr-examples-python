"""Step definitions for raise-tracking arithmetic scenarios.

These scenarios exercise pure arithmetic with no handlers involved. Each
step simply reads/writes integer fields on ``context`` and computes
``min_raise_to`` as ``current_bet + last_raise_increment``.

Kept deliberately small so the arithmetic is easy to inspect.
"""

from behave import given, then, use_step_matcher, when

use_step_matcher("re")


# --- Given steps ---


@given(
    r"current_bet is (?P<bet>-?\d+) and last_raise_increment is (?P<inc>-?\d+)"
)
def step_given_state(context, bet, inc):
    """Seed raise-tracking state on the context."""
    context.current_bet = int(bet)
    context.last_raise_increment = int(inc)


# --- When steps ---


@when(r"I compute the min_raise_to")
def step_when_compute_min_raise(context):
    """Compute min_raise_to into context."""
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a player raises to (?P<amt>-?\d+)")
def step_when_raise_to(context, amt):
    """Apply a raise TO ``amt``; update tracking using max() semantics."""
    raise_to = int(amt)
    increment = raise_to - context.current_bet
    if increment > context.last_raise_increment:
        context.last_raise_increment = increment
    context.current_bet = raise_to
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a player calls (?P<amt>-?\d+)")
def step_when_call(context, amt):
    """A call does not affect current_bet or last_raise_increment."""
    # Purely cosmetic on the tracker; recompute for assertions.
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a below-increment raise of increment (?P<inc>-?\d+) is applied")
def step_when_below_increment_raise(context, inc):
    """Apply a raise smaller than the current last_raise_increment."""
    candidate = int(inc)
    if candidate > context.last_raise_increment:
        context.last_raise_increment = candidate
    # current_bet unchanged (the real path would reject or treat as all-in);
    # the assertion is that tracking is max()-monotonic.
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a player bets (?P<amt>-?\d+) on a new round")
def step_when_bet_new_round(context, amt):
    """Opening bet on a new round updates tracking if increment is larger."""
    bet_amount = int(amt)
    # current_bet is 0 at the start of a new round; increment = bet_amount - 0
    increment = bet_amount - context.current_bet
    if increment > context.last_raise_increment:
        context.last_raise_increment = increment
    context.current_bet = bet_amount
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a player goes all-in to (?P<amt>-?\d+)")
def step_when_all_in_to(context, amt):
    """Record an all-in raise without necessarily updating the tracker."""
    context.all_in_to = int(amt)
    context.min_raise_to = context.current_bet + context.last_raise_increment


# --- Then steps ---


@then(r"min_raise_to is (?P<expected>-?\d+)")
def step_then_min_raise_to(context, expected):
    """Verify min_raise_to."""
    actual = getattr(
        context, "min_raise_to", context.current_bet + context.last_raise_increment
    )
    assert actual == int(expected), (
        f"Expected min_raise_to={expected}, got {actual}"
    )


@then(r"last_raise_increment is (?P<expected>-?\d+)")
def step_then_last_raise_increment(context, expected):
    """Verify last_raise_increment."""
    assert context.last_raise_increment == int(expected), (
        f"Expected last_raise_increment={expected}, got "
        f"{context.last_raise_increment}"
    )


@then(r"current_bet is (?P<expected>-?\d+)")
def step_then_current_bet(context, expected):
    """Verify current_bet."""
    assert context.current_bet == int(expected), (
        f"Expected current_bet={expected}, got {context.current_bet}"
    )


@then(r"the all-in amount is less than min_raise_to")
def step_then_all_in_less_than_min_raise(context):
    """Verify the all-in amount is less than min_raise_to."""
    min_raise_to = context.current_bet + context.last_raise_increment
    assert context.all_in_to < min_raise_to, (
        f"all-in {context.all_in_to} is not less than min_raise_to {min_raise_to}"
    )
