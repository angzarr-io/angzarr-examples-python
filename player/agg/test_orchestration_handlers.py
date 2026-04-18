"""Unit tests for player orchestration command handlers + state appliers.

Covers the buy-in / registration / rebuy flows ported from the Rust
reference (``examples-rust/main/player/agg/src/handlers/``).
"""

import pytest

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration

from .handlers import (
    handle_confirm_buy_in,
    handle_confirm_rebuy_fee,
    handle_confirm_registration_fee,
    handle_initiate_buy_in,
    handle_initiate_rebuy,
    handle_initiate_tournament_registration,
    handle_release_buy_in,
    handle_release_rebuy_fee,
    handle_release_registration_fee,
)
from .state import (
    PendingBuyIn,
    PendingRebuy,
    PendingRegistration,
    PlayerState,
    apply_buy_in_confirmed,
    apply_buy_in_released,
    apply_buy_in_requested,
    apply_rebuy_confirmed,
    apply_rebuy_released,
    apply_rebuy_requested,
    apply_registration_confirmed,
    apply_registration_released,
    apply_registration_requested,
)

TABLE_ROOT = b"\x10" * 16
TOURNAMENT_ROOT = b"\x11" * 16
RESERVATION_ID = b"\x12" * 16


def _existing_player(bankroll: int = 1000) -> PlayerState:
    return PlayerState(player_id="player_test@example.com", bankroll=bankroll)


# --------------------------------------------------------------------------
# Buy-in
# --------------------------------------------------------------------------


class TestBuyInHandlers:
    def test_initiate_buy_in_emits_requested(self):
        state = _existing_player(bankroll=5000)
        cmd = buy_in.InitiateBuyIn(
            table_root=TABLE_ROOT,
            seat=0,
            amount=poker_types.Currency(amount=500, currency_code="CHIPS"),
        )
        event = handle_initiate_buy_in(cmd, state)
        assert event.table_root == TABLE_ROOT
        assert event.amount.amount == 500
        assert event.reservation_id  # auto-generated UUID

    def test_initiate_buy_in_rejects_nonexistent_player(self):
        state = PlayerState()
        cmd = buy_in.InitiateBuyIn(
            table_root=TABLE_ROOT,
            amount=poker_types.Currency(amount=500),
        )
        with pytest.raises(CommandRejectedError):
            handle_initiate_buy_in(cmd, state)

    def test_initiate_buy_in_rejects_insufficient_funds(self):
        state = _existing_player(bankroll=100)
        cmd = buy_in.InitiateBuyIn(
            table_root=TABLE_ROOT,
            amount=poker_types.Currency(amount=500),
        )
        with pytest.raises(CommandRejectedError):
            handle_initiate_buy_in(cmd, state)

    def test_confirm_buy_in_requires_pending(self):
        state = _existing_player()
        cmd = buy_in.ConfirmBuyIn(reservation_id=RESERVATION_ID)
        with pytest.raises(CommandRejectedError):
            handle_confirm_buy_in(cmd, state)

    def test_confirm_buy_in_emits_confirmed(self):
        state = _existing_player()
        state.pending_buy_ins[RESERVATION_ID.hex()] = PendingBuyIn(
            table_root=TABLE_ROOT, seat=2, amount=500
        )
        cmd = buy_in.ConfirmBuyIn(reservation_id=RESERVATION_ID)
        event = handle_confirm_buy_in(cmd, state)
        assert event.table_root == TABLE_ROOT
        assert event.seat == 2
        assert event.amount.amount == 500

    def test_release_buy_in_emits_released(self):
        state = _existing_player()
        state.pending_buy_ins[RESERVATION_ID.hex()] = PendingBuyIn(
            table_root=TABLE_ROOT, seat=0, amount=500
        )
        cmd = buy_in.ReleaseBuyIn(reservation_id=RESERVATION_ID, reason="timeout")
        event = handle_release_buy_in(cmd, state)
        assert event.reason == "timeout"


class TestBuyInAppliers:
    def test_requested_reserves_funds(self):
        state = _existing_player(bankroll=1000)
        apply_buy_in_requested(
            state,
            buy_in.BuyInRequested(
                reservation_id=RESERVATION_ID,
                table_root=TABLE_ROOT,
                seat=0,
                amount=poker_types.Currency(amount=500),
            ),
        )
        assert state.reserved_funds == 500
        assert state.available_balance == 500
        assert RESERVATION_ID.hex() in state.pending_buy_ins

    def test_confirmed_deducts_bankroll(self):
        state = _existing_player(bankroll=1000)
        state.reserved_funds = 500
        state.pending_buy_ins[RESERVATION_ID.hex()] = PendingBuyIn(
            table_root=TABLE_ROOT, amount=500
        )
        apply_buy_in_confirmed(
            state, buy_in.BuyInConfirmed(reservation_id=RESERVATION_ID)
        )
        assert state.bankroll == 500
        assert state.reserved_funds == 0
        assert state.table_reservations[TABLE_ROOT.hex()] == 500
        assert RESERVATION_ID.hex() not in state.pending_buy_ins

    def test_released_returns_reserved(self):
        state = _existing_player(bankroll=1000)
        state.reserved_funds = 500
        state.pending_buy_ins[RESERVATION_ID.hex()] = PendingBuyIn(
            table_root=TABLE_ROOT, amount=500
        )
        apply_buy_in_released(
            state, buy_in.BuyInReservationReleased(reservation_id=RESERVATION_ID)
        )
        assert state.reserved_funds == 0
        assert state.bankroll == 1000
        assert RESERVATION_ID.hex() not in state.pending_buy_ins


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


class TestRegistrationHandlers:
    def test_initiate_emits_requested(self):
        state = _existing_player()
        cmd = registration.InitiateTournamentRegistration(
            tournament_root=TOURNAMENT_ROOT
        )
        event = handle_initiate_tournament_registration(cmd, state)
        assert event.tournament_root == TOURNAMENT_ROOT
        assert event.reservation_id

    def test_confirm_requires_pending(self):
        state = _existing_player()
        cmd = registration.ConfirmRegistrationFee(reservation_id=RESERVATION_ID)
        with pytest.raises(CommandRejectedError):
            handle_confirm_registration_fee(cmd, state)

    def test_confirm_emits_confirmed(self):
        state = _existing_player()
        state.pending_registrations[RESERVATION_ID.hex()] = PendingRegistration(
            tournament_root=TOURNAMENT_ROOT, fee=100
        )
        cmd = registration.ConfirmRegistrationFee(reservation_id=RESERVATION_ID)
        event = handle_confirm_registration_fee(cmd, state)
        assert event.tournament_root == TOURNAMENT_ROOT
        assert event.fee.amount == 100

    def test_release_emits_released(self):
        state = _existing_player()
        state.pending_registrations[RESERVATION_ID.hex()] = PendingRegistration(
            tournament_root=TOURNAMENT_ROOT, fee=100
        )
        cmd = registration.ReleaseRegistrationFee(
            reservation_id=RESERVATION_ID, reason="tournament full"
        )
        event = handle_release_registration_fee(cmd, state)
        assert event.reason == "tournament full"


class TestRegistrationAppliers:
    def test_requested_reserves_fee(self):
        state = _existing_player(bankroll=500)
        apply_registration_requested(
            state,
            registration.RegistrationRequested(
                reservation_id=RESERVATION_ID,
                tournament_root=TOURNAMENT_ROOT,
                fee=poker_types.Currency(amount=100),
            ),
        )
        assert state.reserved_funds == 100

    def test_confirmed_deducts(self):
        state = _existing_player(bankroll=500)
        state.reserved_funds = 100
        state.pending_registrations[RESERVATION_ID.hex()] = PendingRegistration(
            tournament_root=TOURNAMENT_ROOT, fee=100
        )
        apply_registration_confirmed(
            state,
            registration.RegistrationFeeConfirmed(reservation_id=RESERVATION_ID),
        )
        assert state.bankroll == 400
        assert state.reserved_funds == 0

    def test_released_returns_reserved(self):
        state = _existing_player(bankroll=500)
        state.reserved_funds = 100
        state.pending_registrations[RESERVATION_ID.hex()] = PendingRegistration(
            tournament_root=TOURNAMENT_ROOT, fee=100
        )
        apply_registration_released(
            state,
            registration.RegistrationFeeReleased(reservation_id=RESERVATION_ID),
        )
        assert state.reserved_funds == 0
        assert state.bankroll == 500


# --------------------------------------------------------------------------
# Rebuy
# --------------------------------------------------------------------------


class TestRebuyHandlers:
    def test_initiate_emits_requested(self):
        state = _existing_player()
        cmd = rebuy.InitiateRebuy(
            tournament_root=TOURNAMENT_ROOT, table_root=TABLE_ROOT, seat=2
        )
        event = handle_initiate_rebuy(cmd, state)
        assert event.tournament_root == TOURNAMENT_ROOT
        assert event.table_root == TABLE_ROOT
        assert event.seat == 2

    def test_confirm_requires_pending(self):
        state = _existing_player()
        cmd = rebuy.ConfirmRebuyFee(reservation_id=RESERVATION_ID)
        with pytest.raises(CommandRejectedError):
            handle_confirm_rebuy_fee(cmd, state)

    def test_confirm_emits_confirmed(self):
        state = _existing_player()
        state.pending_rebuys[RESERVATION_ID.hex()] = PendingRebuy(
            tournament_root=TOURNAMENT_ROOT, fee=200, chips_to_add=500
        )
        cmd = rebuy.ConfirmRebuyFee(reservation_id=RESERVATION_ID)
        event = handle_confirm_rebuy_fee(cmd, state)
        assert event.tournament_root == TOURNAMENT_ROOT
        assert event.fee.amount == 200
        assert event.chips_added == 500

    def test_release_emits_released(self):
        state = _existing_player()
        state.pending_rebuys[RESERVATION_ID.hex()] = PendingRebuy(
            tournament_root=TOURNAMENT_ROOT, fee=200
        )
        cmd = rebuy.ReleaseRebuyFee(reservation_id=RESERVATION_ID, reason="denied")
        event = handle_release_rebuy_fee(cmd, state)
        assert event.reason == "denied"


class TestRebuyAppliers:
    def test_requested_reserves(self):
        state = _existing_player(bankroll=1000)
        apply_rebuy_requested(
            state,
            rebuy.RebuyRequested(
                reservation_id=RESERVATION_ID,
                tournament_root=TOURNAMENT_ROOT,
                table_root=TABLE_ROOT,
                seat=2,
                fee=poker_types.Currency(amount=200),
            ),
        )
        assert state.reserved_funds == 200

    def test_confirmed_deducts(self):
        state = _existing_player(bankroll=1000)
        state.reserved_funds = 200
        state.pending_rebuys[RESERVATION_ID.hex()] = PendingRebuy(fee=200)
        apply_rebuy_confirmed(
            state, rebuy.RebuyFeeConfirmed(reservation_id=RESERVATION_ID)
        )
        assert state.bankroll == 800
        assert state.reserved_funds == 0

    def test_released_returns_reserved(self):
        state = _existing_player(bankroll=1000)
        state.reserved_funds = 200
        state.pending_rebuys[RESERVATION_ID.hex()] = PendingRebuy(fee=200)
        apply_rebuy_released(
            state, rebuy.RebuyFeeReleased(reservation_id=RESERVATION_ID)
        )
        assert state.reserved_funds == 0
        assert state.bankroll == 1000
