"""The player's wallet as pure functions.

Every command is ``guard(state)`` → ``validate(cmd, state)`` →
``compute(cmd, state, effect)``. ``validate`` returns the command's
:class:`Effect`: ``APPLY``, or ``ALREADY_APPLIED`` when the same request was
recorded before (redelivery is harmless, so ``compute`` then emits nothing).
Appliers fold each event into ``PlayerState``.

A hold earmarks part of the bankroll; it never moves money. ``available`` is
the bankroll minus open holds. Invariant L1 after every event:
``bankroll >= sum(open holds) >= 0``, every open hold is positive, and
``bankroll = deposited - withdrawn - to_tables + from_tables``.
"""

from __future__ import annotations

import enum

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack.errors import invalid, precondition

Hold = _p.Hold
OPEN = Hold.Status.STATUS_OPEN
BUY_IN = Hold.Purpose.PURPOSE_BUY_IN
TOP_UP = Hold.Purpose.PURPOSE_TOP_UP

# Anomaly recorded on a TopUpSettled fact that matches no open top-up hold.
NO_MATCHING_HOLD = "NO_MATCHING_HOLD"


class Effect(enum.Enum):
    APPLY = "apply"
    ALREADY_APPLIED = "already_applied"


# --- reading state ------------------------------------------------------------


def hold_key(hold_id: bytes) -> str:
    return hold_id.hex()


def result_key(table_root: bytes, round_number: int) -> str:
    return f"{table_root.hex()}/{round_number}"


def held(state: _p.PlayerState) -> int:
    """Sum of open holds."""
    return sum(h.amount for h in state.holds.values() if h.status == OPEN)


def available(state: _p.PlayerState) -> int:
    return state.bankroll - held(state)


def open_hold(state: _p.PlayerState, hold_id: bytes, purpose) -> Hold | None:
    hold = state.holds.get(hold_key(hold_id))
    if hold is not None and hold.status == OPEN and hold.purpose == purpose:
        return hold
    return None


def ledger_balances(state: _p.PlayerState) -> bool:
    """Invariant L1."""
    open_amounts = [h.amount for h in state.holds.values() if h.status == OPEN]
    return (
        state.bankroll >= sum(open_amounts) >= 0
        and all(amount > 0 for amount in open_amounts)
        and state.bankroll
        == state.total_deposited
        - state.total_withdrawn
        - state.total_to_tables
        + state.total_from_tables
    )


# --- shared guards and validations -------------------------------------------


def guard_registered(state: _p.PlayerState) -> None:
    if not state.registered:
        raise precondition("PLAYER_NOT_FOUND", "the player is not registered")


def guard_not_registered(state: _p.PlayerState) -> None:
    if state.registered:
        raise precondition("PLAYER_ALREADY_EXISTS", "the player already exists")


def validate_positive(amount: int) -> None:
    if amount <= 0:
        raise invalid("AMOUNT_NOT_POSITIVE", f"amount must be positive, got {amount}")


def validate_identity(display_name: str, email: str) -> None:
    if not display_name:
        raise invalid("DISPLAY_NAME_REQUIRED", "a display name is required")
    if not email:
        raise invalid("EMAIL_REQUIRED", "an email is required")


def validate_affordable(amount: int, state: _p.PlayerState) -> None:
    if amount > available(state):
        raise precondition(
            "INSUFFICIENT_AVAILABLE_FUNDS",
            f"requested {amount} but only {available(state)} is available",
        )


def validate_new_hold(
    hold_id: bytes, table_root: bytes, amount: int, purpose, state
) -> Effect:
    """A hold id already used for the identical request is a repeat; used for
    anything else it conflicts. A new hold must be affordable."""
    existing = state.holds.get(hold_key(hold_id))
    if existing is not None:
        if (
            existing.purpose == purpose
            and existing.amount == amount
            and existing.table_root == table_root
        ):
            return Effect.ALREADY_APPLIED
        raise precondition(
            "HOLD_CONFLICT",
            f"hold {hold_key(hold_id)} is already used for a different request",
        )
    validate_affordable(amount, state)
    return Effect.APPLY


# --- identity -----------------------------------------------------------------


def validate_register(cmd: _p.RegisterPlayer, state) -> Effect:
    validate_identity(cmd.display_name, cmd.email)
    return Effect.APPLY


def compute_register(cmd: _p.RegisterPlayer, state, effect: Effect) -> list:
    return [_p.PlayerRegistered(display_name=cmd.display_name, email=cmd.email)]


def validate_import(cmd: _p.ImportPlayer, state) -> Effect:
    validate_identity(cmd.display_name, cmd.email)
    return Effect.APPLY


def compute_import(cmd: _p.ImportPlayer, state, effect: Effect) -> list:
    return [
        _p.PlayerImported(
            display_name=cmd.display_name, email=cmd.email, legacy_id=cmd.legacy_id
        )
    ]


def validate_update_profile(cmd: _p.UpdateProfile, state) -> Effect:
    if not cmd.display_name:
        raise invalid("DISPLAY_NAME_REQUIRED", "a display name is required")
    return Effect.APPLY


def compute_update_profile(cmd: _p.UpdateProfile, state, effect: Effect) -> list:
    return [_p.ProfileUpdated(display_name=cmd.display_name)]


# --- deposits and withdrawals -------------------------------------------------


def validate_deposit(cmd: _p.DepositFunds, state) -> Effect:
    validate_positive(cmd.amount)
    return Effect.APPLY


def compute_deposit(cmd: _p.DepositFunds, state, effect: Effect) -> list:
    return [_p.FundsDeposited(amount=cmd.amount)]


def validate_withdraw(cmd: _p.WithdrawFunds, state) -> Effect:
    validate_positive(cmd.amount)
    validate_affordable(cmd.amount, state)
    return Effect.APPLY


def compute_withdraw(cmd: _p.WithdrawFunds, state, effect: Effect) -> list:
    return [_p.FundsWithdrawn(amount=cmd.amount)]


# --- buy-in holds (from the buy-in process) ------------------------------------


# region hold_funds
def validate_hold_funds(cmd: _p.HoldFunds, state: _p.PlayerState) -> Effect:
    validate_positive(cmd.amount)
    return validate_new_hold(cmd.hold_id, cmd.table_root, cmd.amount, BUY_IN, state)


def compute_hold_funds(
    cmd: _p.HoldFunds, state: _p.PlayerState, effect: Effect
) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    return [
        _p.FundsHeld(hold_id=cmd.hold_id, table_root=cmd.table_root, amount=cmd.amount)
    ]


# endregion hold_funds


def validate_capture(cmd: _p.CaptureFunds, state: _p.PlayerState) -> Effect:
    hold = state.holds.get(hold_key(cmd.hold_id))
    if hold is not None and hold.purpose == BUY_IN:
        if hold.status == Hold.Status.STATUS_CAPTURED:
            return Effect.ALREADY_APPLIED
        if hold.status == OPEN:
            return Effect.APPLY
    raise precondition(
        "HOLD_NOT_FOUND", f"there is no open buy-in hold {hold_key(cmd.hold_id)}"
    )


def compute_capture(
    cmd: _p.CaptureFunds, state: _p.PlayerState, effect: Effect
) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    hold = state.holds[hold_key(cmd.hold_id)]
    return [
        _p.FundsCaptured(
            hold_id=cmd.hold_id, table_root=hold.table_root, amount=hold.amount
        )
    ]


def validate_release(cmd: _p.ReleaseHold, state: _p.PlayerState) -> Effect:
    hold = state.holds.get(hold_key(cmd.hold_id))
    if hold is None:
        raise precondition(
            "HOLD_NOT_FOUND", f"there is no hold {hold_key(cmd.hold_id)}"
        )
    return Effect.APPLY if hold.status == OPEN else Effect.ALREADY_APPLIED


def compute_release(cmd: _p.ReleaseHold, state: _p.PlayerState, effect: Effect) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    hold = state.holds[hold_key(cmd.hold_id)]
    return [_p.HoldReleased(hold_id=cmd.hold_id, amount=hold.amount, reason=cmd.reason)]


# --- top-ups (requested by the player, carried out by the table) ---------------


def validate_request_top_up(cmd: _p.RequestTopUp, state: _p.PlayerState) -> Effect:
    validate_positive(cmd.amount)
    return validate_new_hold(cmd.request_id, cmd.table_root, cmd.amount, TOP_UP, state)


def compute_request_top_up(cmd: _p.RequestTopUp, state, effect: Effect) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    return [
        _p.TopUpRequested(
            hold_id=cmd.request_id, table_root=cmd.table_root, amount=cmd.amount
        )
    ]


def compute_top_up_refused(hold_id: bytes, reason: str, state: _p.PlayerState) -> list:
    """The table refused a top-up: release its hold if it is still open."""
    hold = open_hold(state, hold_id, TOP_UP)
    if hold is None:
        return []
    return [_p.TopUpRefused(hold_id=hold_id, amount=hold.amount, reason=reason)]


def check_top_up_settled(
    fact: _p.TopUpSettled, state: _p.PlayerState
) -> _p.TopUpSettled:
    """A settled top-up is a fact: it is recorded whatever the wallet holds,
    flagged when it matches no open top-up hold of that amount."""
    hold = open_hold(state, fact.hold_id, TOP_UP)
    checked = _p.TopUpSettled()
    checked.CopyFrom(fact)
    if hold is None or hold.amount != fact.amount:
        checked.anomaly = NO_MATCHING_HOLD
    return checked


# --- loyalty and round history ---------------------------------------------------


def validate_enroll(cmd: _p.EnrollLoyalty, state: _p.PlayerState) -> Effect:
    return Effect.ALREADY_APPLIED if state.loyalty_enrolled else Effect.APPLY


def compute_enroll(cmd: _p.EnrollLoyalty, state, effect: Effect) -> list:
    return [] if effect is Effect.ALREADY_APPLIED else [_p.LoyaltyEnrolled()]


def validate_award(cmd: _p.AwardLoyaltyPoints, state: _p.PlayerState) -> Effect:
    if not state.loyalty_enrolled:
        raise precondition("LOYALTY_NOT_ENROLLED", "the player is not a loyalty member")
    if result_key(cmd.table_root, cmd.round) in state.loyalty_awards:
        return Effect.ALREADY_APPLIED
    return Effect.APPLY


def compute_award(cmd: _p.AwardLoyaltyPoints, state, effect: Effect) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    return [
        _p.LoyaltyPointsAwarded(
            table_root=cmd.table_root, round=cmd.round, points=cmd.points
        )
    ]


def validate_record_result(cmd: _p.RecordRoundResult, state: _p.PlayerState) -> Effect:
    if result_key(cmd.table_root, cmd.round) in state.round_results:
        return Effect.ALREADY_APPLIED
    return Effect.APPLY


def compute_record_result(cmd: _p.RecordRoundResult, state, effect: Effect) -> list:
    if effect is Effect.ALREADY_APPLIED:
        return []
    return [
        _p.RoundResultRecorded(
            table_root=cmd.table_root, round=cmd.round, wager=cmd.wager, net=cmd.net
        )
    ]


def compute_retract_results(
    recorded: list[_p.RoundResultRecorded], state: _p.PlayerState
) -> list:
    """Withdraw exactly the round results ``recorded`` wrote, each only while
    it still stands."""
    out = []
    for event in recorded:
        result = state.round_results.get(result_key(event.table_root, event.round))
        if result is not None and not result.retracted:
            out.append(
                _p.RoundResultRetracted(
                    table_root=result.table_root, round=result.round, net=result.net
                )
            )
    return out


# --- appliers -------------------------------------------------------------------


def apply_registered(state: _p.PlayerState, event) -> None:
    state.registered = True
    state.display_name = event.display_name
    state.email = event.email


def apply_imported(state: _p.PlayerState, event: _p.PlayerImported) -> None:
    apply_registered(state, event)
    state.legacy_id = event.legacy_id


def apply_profile_updated(state: _p.PlayerState, event: _p.ProfileUpdated) -> None:
    state.display_name = event.display_name


def apply_deposited(state: _p.PlayerState, event: _p.FundsDeposited) -> None:
    state.bankroll += event.amount
    state.total_deposited += event.amount


def apply_withdrawn(state: _p.PlayerState, event: _p.FundsWithdrawn) -> None:
    state.bankroll -= event.amount
    state.total_withdrawn += event.amount


def _open(
    state: _p.PlayerState, hold_id: bytes, table_root: bytes, amount: int, purpose
) -> None:
    state.holds[hold_key(hold_id)].CopyFrom(
        Hold(table_root=table_root, amount=amount, purpose=purpose, status=OPEN)
    )


def _close(state: _p.PlayerState, hold_id: bytes, status) -> None:
    hold = state.holds.get(hold_key(hold_id))
    if hold is not None:
        hold.status = status


def _to_table(state: _p.PlayerState, amount: int) -> None:
    state.bankroll -= amount
    state.total_to_tables += amount


def apply_funds_held(state: _p.PlayerState, event: _p.FundsHeld) -> None:
    _open(state, event.hold_id, event.table_root, event.amount, BUY_IN)


def apply_funds_captured(state: _p.PlayerState, event: _p.FundsCaptured) -> None:
    _close(state, event.hold_id, Hold.Status.STATUS_CAPTURED)
    _to_table(state, event.amount)


def apply_hold_released(state: _p.PlayerState, event: _p.HoldReleased) -> None:
    _close(state, event.hold_id, Hold.Status.STATUS_RELEASED)


def apply_top_up_requested(state: _p.PlayerState, event: _p.TopUpRequested) -> None:
    _open(state, event.hold_id, event.table_root, event.amount, TOP_UP)


def apply_top_up_refused(state: _p.PlayerState, event: _p.TopUpRefused) -> None:
    _close(state, event.hold_id, Hold.Status.STATUS_REFUSED)


def apply_top_up_settled(state: _p.PlayerState, event: _p.TopUpSettled) -> None:
    if event.anomaly:
        state.anomalies += 1
    else:
        _close(state, event.hold_id, Hold.Status.STATUS_SETTLED)
    _to_table(state, event.amount)


def apply_cash_out_credited(state: _p.PlayerState, event: _p.CashOutCredited) -> None:
    state.bankroll += event.amount
    state.total_from_tables += event.amount


def apply_loyalty_enrolled(state: _p.PlayerState, event: _p.LoyaltyEnrolled) -> None:
    state.loyalty_enrolled = True


def apply_loyalty_points_awarded(
    state: _p.PlayerState, event: _p.LoyaltyPointsAwarded
) -> None:
    state.loyalty_points += event.points
    state.loyalty_awards[result_key(event.table_root, event.round)] = event.points


def apply_round_result_recorded(
    state: _p.PlayerState, event: _p.RoundResultRecorded
) -> None:
    state.round_results[result_key(event.table_root, event.round)].CopyFrom(
        _p.RoundResult(
            table_root=event.table_root,
            round=event.round,
            wager=event.wager,
            net=event.net,
        )
    )


def apply_round_result_retracted(
    state: _p.PlayerState, event: _p.RoundResultRetracted
) -> None:
    result = state.round_results.get(result_key(event.table_root, event.round))
    if result is not None:
        result.retracted = True
