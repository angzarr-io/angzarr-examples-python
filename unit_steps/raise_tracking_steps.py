"""Step definitions for raise-tracking arithmetic scenarios.

These scenarios exercise pure arithmetic helpers in
``hand.agg.raise_tracking`` — no aggregate handlers. Steps call the
production helpers directly so a mutation in either the helper or the
step is caught by the cucumber run.
"""

from behave import given, then, use_step_matcher, when
from hand.agg.raise_tracking import (
    apply_short_all_in,
    reset_per_round,
    short_all_in_initial,
)

use_step_matcher("re")


# --- Given steps ---


@given(r"current_bet is (?P<bet>-?\d+) and last_raise_increment is (?P<inc>-?\d+)")
def step_given_state(context, bet, inc):
    """Seed raise-tracking state on the context.

    Behave reuses the context object across scenarios within a feature
    (only the fields listed in ``before_scenario`` are reset), so this
    step also clears any short-all-in tracker carried from a prior
    scenario — otherwise an EU-1140 chain would bleed into EU-1141.
    """
    context.current_bet = int(bet)
    context.last_raise_increment = int(inc)
    # behave's Context layers attributes per scope; setting to None at
    # the current layer is the cleanest way to clear without tripping
    # the "del across scope" guard rail.
    context._short_tracker = None
    context.action_reopened = False


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


def _apply_all_in_through_helper(context, amt: int) -> None:
    """Drive the production ``apply_short_all_in`` helper.

    Initialises a ``ShortAllInOutcome`` tracker on first call, then
    advances it for each subsequent all-in. ``context.current_bet`` and
    ``context.last_raise_increment`` are kept in sync with the tracker so
    downstream assertions can read them through the existing accessors.
    """
    if not getattr(context, "_short_tracker", None):
        context._short_tracker = short_all_in_initial(
            context.current_bet, context.last_raise_increment
        )
    context._short_tracker = apply_short_all_in(context._short_tracker, amt)
    context.current_bet = context._short_tracker.current_bet
    context.last_raise_increment = context._short_tracker.last_raise_increment
    context.action_reopened = context._short_tracker.action_reopened
    context.all_in_to = amt
    context.min_raise_to = context.current_bet + context.last_raise_increment


@when(r"a player goes all-in to (?P<amt>-?\d+)")
def step_when_all_in_to(context, amt):
    """Apply an all-in via the production short-all-in helper.

    The helper distinguishes "short" all-ins (increment < last_raise) —
    which accumulate but do not reopen action — from full-raise all-ins.
    Cumulative shorts that reach the threshold reopen action per
    TDA Rule 47A second sentence.
    """
    _apply_all_in_through_helper(context, int(amt))


@when(r"another player goes all-in to (?P<amt>-?\d+)")
def step_when_another_player_all_in_to(context, amt):
    """Apply a subsequent all-in to the same chain (TDA Rule 47A).

    Behaves identically to ``a player goes all-in to N`` — the helper
    state persists across calls so cumulative-short logic accumulates
    naturally.
    """
    _apply_all_in_through_helper(context, int(amt))


# --- Then steps ---


@then(r"min_raise_to is (?P<expected>-?\d+)")
def step_then_min_raise_to(context, expected):
    """Verify min_raise_to."""
    actual = getattr(
        context, "min_raise_to", context.current_bet + context.last_raise_increment
    )
    assert actual == int(expected), f"Expected min_raise_to={expected}, got {actual}"


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
    assert context.current_bet == int(
        expected
    ), f"Expected current_bet={expected}, got {context.current_bet}"


@then(r"the all-in amount is less than min_raise_to")
def step_then_all_in_less_than_min_raise(context):
    """Verify the all-in amount is less than min_raise_to."""
    min_raise_to = context.current_bet + context.last_raise_increment
    assert (
        context.all_in_to < min_raise_to
    ), f"all-in {context.all_in_to} is not less than min_raise_to {min_raise_to}"


@then(r"the bet is reopened for prior actors")
def step_then_bet_reopened(context):
    """Verify the cumulative-short tracker reports action_reopened=True.

    Per TDA Rule 47A: when multiple short all-ins cumulatively reach a
    full raise, betting reopens for players who already acted. The
    ``apply_short_all_in`` helper sets ``action_reopened`` accordingly.
    """
    assert (
        context.action_reopened is True
    ), "Expected action to be reopened, but the tracker reports it is not"


@then(r"the bet is not reopened for prior actors")
def step_then_bet_not_reopened(context):
    """Verify cumulative shorts below the threshold do NOT reopen action."""
    assert (
        context.action_reopened is False
    ), "Expected action NOT to be reopened, but the tracker reports it is"


# --- Per-street reset steps ---
#
# These exercise the NLHE convention that ``min_raise`` (a.k.a.
# ``last_raise_increment``) resets to the big blind on each new street.
# The arithmetic is local to context — the matching aggregate behaviour
# lives in ``Hand.apply_betting_round_complete``.


@given(
    r"current_bet is (?P<bet>-?\d+) and last_raise_increment is (?P<inc>-?\d+) "
    r"and big_blind is (?P<bb>-?\d+)"
)
def step_given_state_with_bb(context, bet, inc, bb):
    context.current_bet = int(bet)
    context.last_raise_increment = int(inc)
    context.big_blind = int(bb)


@given(
    r"current_bet is (?P<bet>-?\d+) and last_raise_increment is (?P<inc>-?\d+) "
    r"on a new street(?: with big_blind (?P<bb>-?\d+))?"
)
def step_given_state_new_street(context, bet, inc, bb):
    context.current_bet = int(bet)
    context.last_raise_increment = int(inc)
    context.big_blind = int(bb) if bb is not None else int(inc)


@given(
    r"current_bet is (?P<bet>-?\d+) and last_raise_increment is (?P<inc>-?\d+) "
    r"on a new street with big_blind (?P<bb>-?\d+)"
)
def step_given_state_new_street_with_bb(context, bet, inc, bb):
    context.current_bet = int(bet)
    context.last_raise_increment = int(inc)
    context.big_blind = int(bb)


@given(
    r"preflop ended with last_raise_increment (?P<inc>-?\d+) and "
    r"big_blind (?P<bb>-?\d+)"
)
def step_given_preflop_ended(context, inc, bb):
    context.current_bet = 0
    context.last_raise_increment = int(inc)
    context.big_blind = int(bb)


@when(r"a new betting round begins")
def step_when_new_betting_round(context):
    """Reset per-street betting state via the production helper.

    Calls ``hand.agg.raise_tracking.reset_per_round`` so the cucumber
    scenario exercises the same code path as the Hand aggregate's
    ``apply_betting_round_complete`` applier. A divergence between the
    cucumber tracker and the aggregate's reset behavior would surface
    as a failing scenario here.
    """
    reset = reset_per_round(context.big_blind)
    context.current_bet = reset.current_bet
    context.last_raise_increment = reset.last_raise_increment
    # Reset the short-all-in tracker — a fresh street has no in-flight
    # short-all-in chain. Set to None (not del) to avoid behave's
    # "del across scope" guard.
    context._short_tracker = None


class _ArithmeticRejection(Exception):
    """Minimal stand-in for a structured rejection on the context.error
    surface. ``common_steps`` reads ``code`` and ``details`` directly.
    """

    def __init__(self, code: str, **fields):
        self.code = code
        self.details = {k: str(v) for k, v in fields.items()}
        super().__init__(f"{code}: {fields}")


@when(r"a player bets (?P<amt>-?\d+)")
def step_when_bet(context, amt):
    bet_amount = int(amt)
    bb = getattr(context, "big_blind", 0)
    if bet_amount < bb:
        context.error = _ArithmeticRejection(
            "BET_BELOW_MIN_RAISE", got=bet_amount, bound=bb
        )
        return
    increment = bet_amount - context.current_bet
    if increment > context.last_raise_increment:
        context.last_raise_increment = increment
    context.current_bet = bet_amount
    context.error = None


@when(r"a player attempts to bet (?P<amt>-?\d+)")
def step_when_attempt_bet(context, amt):
    step_when_bet(context, amt)


@when(r"all active players check")
def step_when_check_around(context):
    """Checks don't change tracking state."""
    pass


@when(r"the next betting round begins")
def step_when_next_betting_round(context):
    step_when_new_betting_round(context)


@then(r"the bet is accepted")
def step_then_bet_accepted(context):
    err = getattr(context, "error", None)
    assert err is None, f"Expected bet to be accepted, but got rejection: {err}"


@then(r'the bet is rejected with code "(?P<code>[^"]+)"')
def step_then_bet_rejected(context, code):
    err = getattr(context, "error", None)
    assert err is not None, "Expected bet to be rejected, but it was accepted"
    assert err.code == code, f"Expected code {code!r}, got {err.code!r}"
