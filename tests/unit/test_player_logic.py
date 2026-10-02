"""The wallet's pure functions: exact rejection codes, gRPC classes and
messages, every guard/validate/compute triple, and the appliers.

Codes are part of the cross-language contract (player.proto); FAILED_PRECONDITION
marks a state-dependent refusal, INVALID_ARGUMENT a malformed request.
"""

import angzarr_client.router as _az
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack.player.agg import logic as L
from angzarr_blackjack.player.agg.logic import Effect

FP = _az.GrpcCode.FAILED_PRECONDITION
IA = _az.GrpcCode.INVALID_ARGUMENT
TABLE = b"\x01" * 16
OTHER_TABLE = b"\x02" * 16
H1 = b"\x11" * 16
H2 = b"\x12" * 16


def wallet(bankroll=0, **holds) -> _p.PlayerState:
    state = _p.PlayerState(registered=True, display_name="Alice", email="a@x")
    if bankroll:
        L.apply_deposited(state, _p.FundsDeposited(amount=bankroll))
    return state


def held(state, hold_id=H1, amount=300, purpose=L.BUY_IN, table=TABLE):
    if purpose == L.BUY_IN:
        L.apply_funds_held(
            state, _p.FundsHeld(hold_id=hold_id, table_root=table, amount=amount)
        )
    else:
        L.apply_top_up_requested(
            state, _p.TopUpRequested(hold_id=hold_id, table_root=table, amount=amount)
        )
    return state


def refused(fn, *args):
    with pytest.raises(_az.CodedError) as info:
        fn(*args)
    return info.value


# --- identity ------------------------------------------------------------------------


def test_registration_needs_a_new_wallet():
    err = refused(L.guard_not_registered, wallet())
    assert (err.code, err.grpc, err.message) == (
        "PLAYER_ALREADY_EXISTS",
        FP,
        "the player already exists",
    )
    L.guard_not_registered(_p.PlayerState())


def test_most_commands_need_a_registered_wallet():
    err = refused(L.guard_registered, _p.PlayerState())
    assert (err.code, err.grpc, err.message) == (
        "PLAYER_NOT_FOUND",
        FP,
        "the player is not registered",
    )
    L.guard_registered(wallet())


def test_identity_needs_a_name_then_an_email():
    err = refused(L.validate_register, _p.RegisterPlayer(email="a@x"), _p.PlayerState())
    assert (err.code, err.grpc, err.message) == (
        "DISPLAY_NAME_REQUIRED",
        IA,
        "a display name is required",
    )
    err = refused(
        L.validate_import, _p.ImportPlayer(display_name="A"), _p.PlayerState()
    )
    assert (err.code, err.grpc, err.message) == (
        "EMAIL_REQUIRED",
        IA,
        "an email is required",
    )
    assert (
        L.validate_register(_p.RegisterPlayer(display_name="A", email="a@x"), None)
        is Effect.APPLY
    )


def test_register_and_import_record_identity():
    (registered,) = L.compute_register(
        _p.RegisterPlayer(display_name="A", email="a@x"), None, Effect.APPLY
    )
    assert registered == _p.PlayerRegistered(display_name="A", email="a@x")
    (imported,) = L.compute_import(
        _p.ImportPlayer(display_name="C", email="c@x", legacy_id="L-77"),
        None,
        Effect.APPLY,
    )
    state = _p.PlayerState()
    L.apply_imported(state, imported)
    assert (
        state.registered,
        state.display_name,
        state.email,
        state.legacy_id,
        state.bankroll,
    ) == (
        True,
        "C",
        "c@x",
        "L-77",
        0,
    )


def test_profile_update_needs_a_name():
    err = refused(L.validate_update_profile, _p.UpdateProfile(), wallet())
    assert err.code == "DISPLAY_NAME_REQUIRED"
    (event,) = L.compute_update_profile(
        _p.UpdateProfile(display_name="Ace"), wallet(), Effect.APPLY
    )
    state = wallet()
    L.apply_profile_updated(state, event)
    assert state.display_name == "Ace"


# --- money ---------------------------------------------------------------------------


@pytest.mark.parametrize("amount", [0, -1, -50])
def test_amounts_must_be_positive(amount):
    err = refused(L.validate_positive, amount)
    assert (err.code, err.grpc, err.message) == (
        "AMOUNT_NOT_POSITIVE",
        IA,
        f"amount must be positive, got {amount}",
    )


def test_one_chip_is_positive():
    L.validate_positive(1)


def test_deposit_raises_bankroll_and_deposited_total():
    state = wallet()
    (event,) = L.compute_deposit(_p.DepositFunds(amount=250), state, Effect.APPLY)
    L.apply_deposited(state, event)
    assert (state.bankroll, state.total_deposited) == (250, 250)


def test_withdrawal_is_limited_to_available():
    state = held(wallet(1000), amount=700)
    err = refused(L.validate_withdraw, _p.WithdrawFunds(amount=301), state)
    assert (err.code, err.grpc, err.message) == (
        "INSUFFICIENT_AVAILABLE_FUNDS",
        FP,
        "requested 301 but only 300 is available",
    )
    assert L.validate_withdraw(_p.WithdrawFunds(amount=300), state) is Effect.APPLY
    (event,) = L.compute_withdraw(_p.WithdrawFunds(amount=300), state, Effect.APPLY)
    L.apply_withdrawn(state, event)
    assert (state.bankroll, state.total_withdrawn, L.available(state)) == (700, 300, 0)


# --- holds ---------------------------------------------------------------------------------


def test_hold_reduces_available_not_bankroll():
    state = wallet(1000)
    cmd = _p.HoldFunds(hold_id=H1, table_root=TABLE, amount=400)
    assert L.validate_hold_funds(cmd, state) is Effect.APPLY
    (event,) = L.compute_hold_funds(cmd, state, Effect.APPLY)
    assert event == _p.FundsHeld(hold_id=H1, table_root=TABLE, amount=400)
    L.apply_funds_held(state, event)
    assert (state.bankroll, L.held(state), L.available(state)) == (1000, 400, 600)
    assert state.holds[H1.hex()] == _p.Hold(
        table_root=TABLE, amount=400, purpose=L.BUY_IN, status=L.OPEN
    )


def test_identical_hold_is_a_repeat_whatever_its_status():
    state = held(wallet(1000), amount=400)
    cmd = _p.HoldFunds(hold_id=H1, table_root=TABLE, amount=400)
    assert L.validate_hold_funds(cmd, state) is Effect.ALREADY_APPLIED
    assert L.compute_hold_funds(cmd, state, Effect.ALREADY_APPLIED) == []
    L.apply_funds_captured(
        state, _p.FundsCaptured(hold_id=H1, table_root=TABLE, amount=400)
    )
    assert L.validate_hold_funds(cmd, state) is Effect.ALREADY_APPLIED


@pytest.mark.parametrize(
    "cmd",
    [
        _p.HoldFunds(hold_id=H1, table_root=TABLE, amount=300),
        _p.HoldFunds(hold_id=H1, table_root=OTHER_TABLE, amount=400),
    ],
)
def test_reusing_a_hold_id_for_another_request_conflicts(cmd):
    state = held(wallet(1000), amount=400)
    err = refused(L.validate_hold_funds, cmd, state)
    assert (err.code, err.grpc, err.message) == (
        "HOLD_CONFLICT",
        FP,
        f"hold {H1.hex()} is already used for a different request",
    )


def test_a_top_up_hold_id_cannot_be_reused_for_a_buy_in():
    state = held(wallet(1000), amount=400, purpose=L.TOP_UP)
    err = refused(
        L.validate_hold_funds,
        _p.HoldFunds(hold_id=H1, table_root=TABLE, amount=400),
        state,
    )
    assert err.code == "HOLD_CONFLICT"


def test_hold_must_be_affordable_and_positive():
    state = held(wallet(1000), amount=700)
    err = refused(
        L.validate_hold_funds,
        _p.HoldFunds(hold_id=H2, table_root=TABLE, amount=301),
        state,
    )
    assert err.code == "INSUFFICIENT_AVAILABLE_FUNDS"
    assert (
        L.validate_hold_funds(
            _p.HoldFunds(hold_id=H2, table_root=TABLE, amount=300), state
        )
        is Effect.APPLY
    )
    err = refused(
        L.validate_hold_funds,
        _p.HoldFunds(hold_id=H2, table_root=TABLE, amount=0),
        state,
    )
    assert err.code == "AMOUNT_NOT_POSITIVE"


def test_capture_spends_an_open_buy_in_hold():
    state = held(wallet(1000), amount=400)
    cmd = _p.CaptureFunds(hold_id=H1)
    assert L.validate_capture(cmd, state) is Effect.APPLY
    (event,) = L.compute_capture(cmd, state, Effect.APPLY)
    assert event == _p.FundsCaptured(hold_id=H1, table_root=TABLE, amount=400)
    L.apply_funds_captured(state, event)
    assert (state.bankroll, state.total_to_tables, L.held(state)) == (600, 400, 0)
    assert state.holds[H1.hex()].status == _p.Hold.Status.STATUS_CAPTURED
    assert L.validate_capture(cmd, state) is Effect.ALREADY_APPLIED
    assert L.compute_capture(cmd, state, Effect.ALREADY_APPLIED) == []


@pytest.mark.parametrize("setup", ["none", "released", "top-up"])
def test_capture_needs_an_open_buy_in_hold(setup):
    state = wallet(1000)
    if setup == "released":
        held(state)
        L.apply_hold_released(state, _p.HoldReleased(hold_id=H1, amount=300))
    elif setup == "top-up":
        held(state, purpose=L.TOP_UP)
    err = refused(L.validate_capture, _p.CaptureFunds(hold_id=H1), state)
    assert (err.code, err.grpc, err.message) == (
        "HOLD_NOT_FOUND",
        FP,
        f"there is no open buy-in hold {H1.hex()}",
    )


def test_release_closes_an_open_hold_once():
    state = held(wallet(1000), amount=400)
    cmd = _p.ReleaseHold(hold_id=H1, reason="seat refused")
    assert L.validate_release(cmd, state) is Effect.APPLY
    (event,) = L.compute_release(cmd, state, Effect.APPLY)
    assert event == _p.HoldReleased(hold_id=H1, amount=400, reason="seat refused")
    L.apply_hold_released(state, event)
    assert (state.bankroll, L.available(state)) == (1000, 1000)
    assert state.holds[H1.hex()].status == _p.Hold.Status.STATUS_RELEASED
    assert L.validate_release(cmd, state) is Effect.ALREADY_APPLIED
    assert L.compute_release(cmd, state, Effect.ALREADY_APPLIED) == []


def test_release_of_an_unknown_hold_is_refused():
    err = refused(L.validate_release, _p.ReleaseHold(hold_id=H2), wallet(10))
    assert (err.code, err.message) == ("HOLD_NOT_FOUND", f"there is no hold {H2.hex()}")


# --- top-ups ---------------------------------------------------------------------------


def test_top_up_request_holds_for_the_table():
    state = wallet(1000)
    cmd = _p.RequestTopUp(table_root=TABLE, amount=200, request_id=H1)
    assert L.validate_request_top_up(cmd, state) is Effect.APPLY
    (event,) = L.compute_request_top_up(cmd, state, Effect.APPLY)
    assert event == _p.TopUpRequested(hold_id=H1, table_root=TABLE, amount=200)
    L.apply_top_up_requested(state, event)
    assert L.open_hold(state, H1, L.TOP_UP).amount == 200
    assert L.open_hold(state, H1, L.BUY_IN) is None
    assert L.validate_request_top_up(cmd, state) is Effect.ALREADY_APPLIED
    assert L.compute_request_top_up(cmd, state, Effect.ALREADY_APPLIED) == []


def test_top_up_must_be_affordable():
    err = refused(
        L.validate_request_top_up,
        _p.RequestTopUp(table_root=TABLE, amount=101, request_id=H1),
        wallet(100),
    )
    assert err.code == "INSUFFICIENT_AVAILABLE_FUNDS"


def test_refused_top_up_releases_its_open_hold_only():
    state = held(wallet(1000), amount=200, purpose=L.TOP_UP)
    (event,) = L.compute_top_up_refused(H1, "WAGER_IN_PLAY", state)
    assert event == _p.TopUpRefused(hold_id=H1, amount=200, reason="WAGER_IN_PLAY")
    L.apply_top_up_refused(state, event)
    assert state.holds[H1.hex()].status == _p.Hold.Status.STATUS_REFUSED
    assert L.compute_top_up_refused(H1, "WAGER_IN_PLAY", state) == []
    assert L.compute_top_up_refused(H2, "WAGER_IN_PLAY", state) == []
    buy_in = held(wallet(1000), amount=200)
    assert L.compute_top_up_refused(H1, "WAGER_IN_PLAY", buy_in) == []


def test_settled_top_up_fact_matches_its_open_hold():
    state = held(wallet(1000), amount=200, purpose=L.TOP_UP)
    fact = _p.TopUpSettled(hold_id=H1, table_root=TABLE, amount=200)
    checked = L.check_top_up_settled(fact, state)
    assert checked.anomaly == "" and checked == fact
    L.apply_top_up_settled(state, checked)
    assert (state.bankroll, state.total_to_tables, state.anomalies) == (800, 200, 0)
    assert state.holds[H1.hex()].status == _p.Hold.Status.STATUS_SETTLED


@pytest.mark.parametrize("hold_id, amount", [(H2, 200), (H1, 150)])
def test_unmatched_settlement_is_flagged_and_still_moves_money(hold_id, amount):
    state = held(wallet(1000), amount=200, purpose=L.TOP_UP)
    fact = _p.TopUpSettled(hold_id=hold_id, table_root=TABLE, amount=amount)
    checked = L.check_top_up_settled(fact, state)
    assert checked.anomaly == L.NO_MATCHING_HOLD == "NO_MATCHING_HOLD"
    assert fact.anomaly == ""
    L.apply_top_up_settled(state, checked)
    assert (state.bankroll, state.total_to_tables, state.anomalies) == (
        1000 - amount,
        amount,
        1,
    )
    assert state.holds[H1.hex()].status == L.OPEN


def test_cash_out_credit_raises_bankroll():
    state = wallet(100)
    L.apply_cash_out_credited(
        state, _p.CashOutCredited(cashout_id=H1, table_root=TABLE, amount=640)
    )
    assert (state.bankroll, state.total_from_tables) == (740, 640)


# --- loyalty and round history ---------------------------------------------------------


def test_enrolment_is_idempotent():
    state = wallet()
    assert L.validate_enroll(_p.EnrollLoyalty(), state) is Effect.APPLY
    assert L.compute_enroll(_p.EnrollLoyalty(), state, Effect.APPLY) == [
        _p.LoyaltyEnrolled()
    ]
    L.apply_loyalty_enrolled(state, _p.LoyaltyEnrolled())
    assert L.validate_enroll(_p.EnrollLoyalty(), state) is Effect.ALREADY_APPLIED
    assert L.compute_enroll(_p.EnrollLoyalty(), state, Effect.ALREADY_APPLIED) == []


def test_points_need_membership_and_are_awarded_once_per_round():
    cmd = _p.AwardLoyaltyPoints(table_root=TABLE, round=3, points=20)
    err = refused(L.validate_award, cmd, wallet())
    assert (err.code, err.grpc, err.message) == (
        "LOYALTY_NOT_ENROLLED",
        FP,
        "the player is not a loyalty member",
    )
    state = wallet()
    L.apply_loyalty_enrolled(state, _p.LoyaltyEnrolled())
    assert L.validate_award(cmd, state) is Effect.APPLY
    (event,) = L.compute_award(cmd, state, Effect.APPLY)
    L.apply_loyalty_points_awarded(state, event)
    L.apply_loyalty_points_awarded(
        state, _p.LoyaltyPointsAwarded(table_root=TABLE, round=4, points=5)
    )
    assert state.loyalty_points == 25
    assert L.validate_award(cmd, state) is Effect.ALREADY_APPLIED
    assert L.compute_award(cmd, state, Effect.ALREADY_APPLIED) == []


def test_round_result_recorded_once_and_retracted_exactly():
    state = wallet()
    for sequence, (round_number, net) in ((4, (1, 20)), (7, (2, -30))):
        cmd = _p.RecordRoundResult(
            table_root=TABLE, round=round_number, wager=30, net=net
        )
        assert L.validate_record_result(cmd, state) is Effect.APPLY
        (event,) = L.compute_record_result(cmd, state, Effect.APPLY)
        L.apply_round_result_recorded(state, event, sequence)
        assert L.validate_record_result(cmd, state) is Effect.ALREADY_APPLIED
        assert L.compute_record_result(cmd, state, Effect.ALREADY_APPLIED) == []
    (retracted,) = L.compute_retract_results([4], state)
    assert retracted == _p.RoundResultRetracted(table_root=TABLE, round=1, net=20)
    L.apply_round_result_retracted(state, retracted)
    assert not state.round_results[L.result_key(TABLE, 2)].retracted
    assert L.compute_retract_results([4], state) == []
    assert L.compute_retract_results([5, 6], state) == []
    (second,) = L.compute_retract_results([4, 7], state)
    assert second.round == 2


def test_result_keys_separate_tables_and_rounds():
    assert L.result_key(TABLE, 1) == f"{TABLE.hex()}/1"
    assert L.result_key(TABLE, 1) != L.result_key(OTHER_TABLE, 1)
    assert L.hold_key(H1) == H1.hex()


# --- L1 --------------------------------------------------------------------------------


def test_ledger_balances_detects_each_breach():
    state = held(wallet(1000), amount=300)
    assert L.ledger_balances(state)
    broken = _p.PlayerState()
    broken.CopyFrom(state)
    broken.bankroll += 1
    assert not L.ledger_balances(broken)
    over_held = _p.PlayerState()
    over_held.CopyFrom(state)
    over_held.holds[H1.hex()].amount = 2000
    assert not L.ledger_balances(over_held)
    empty_hold = _p.PlayerState()
    empty_hold.CopyFrom(state)
    empty_hold.holds[H1.hex()].amount = 0
    assert not L.ledger_balances(empty_hold)


def test_each_unmatched_settlement_is_counted():
    state = wallet(1000)
    for _ in range(2):
        L.apply_top_up_settled(
            state, _p.TopUpSettled(hold_id=H2, amount=10, anomaly=L.NO_MATCHING_HOLD)
        )
    assert state.anomalies == 2


def test_recorded_round_result_keeps_wager_and_net():
    state = wallet()
    L.apply_round_result_recorded(
        state,
        _p.RoundResultRecorded(table_root=TABLE, round=2, wager=30, net=-30),
        11,
    )
    assert state.round_results[L.result_key(TABLE, 2)] == _p.RoundResult(
        table_root=TABLE, round=2, wager=30, net=-30, sequence=11
    )


def test_profile_update_refusal_message():
    err = refused(L.validate_update_profile, _p.UpdateProfile(), wallet())
    assert (err.grpc, err.message) == (IA, "a display name is required")


def test_recorded_result_event_carries_the_wager():
    cmd = _p.RecordRoundResult(table_root=TABLE, round=3, wager=40, net=-40)
    (event,) = L.compute_record_result(cmd, wallet(), Effect.APPLY)
    assert event == _p.RoundResultRecorded(table_root=TABLE, round=3, wager=40, net=-40)


def test_a_one_chip_hold_balances():
    assert L.ledger_balances(held(wallet(1000), amount=1))


def test_withdrawals_accumulate():
    state = wallet(1000)
    for amount in (100, 50):
        L.apply_withdrawn(state, _p.FundsWithdrawn(amount=amount))
    assert (state.bankroll, state.total_withdrawn) == (850, 150)


def test_fact_handlers_record_settlements_and_credits():
    from angzarr_blackjack.player.agg.handler import PlayerAggregate

    wallet_ = PlayerAggregate()
    state = held(wallet(1000), amount=200, purpose=L.TOP_UP)
    matched = wallet_.on_top_up_settled_fact(
        _p.TopUpSettled(hold_id=H1, amount=200), state
    )
    assert (matched.fact.anomaly, matched.flags) == ("", ())
    unmatched = wallet_.on_top_up_settled_fact(
        _p.TopUpSettled(hold_id=H2, amount=200), state
    )
    assert (unmatched.fact.anomaly, unmatched.flags) == (L.NO_MATCHING_HOLD, ())
    assert (
        wallet_.on_cash_out_credited_fact(_p.CashOutCredited(amount=5), state) is None
    )
