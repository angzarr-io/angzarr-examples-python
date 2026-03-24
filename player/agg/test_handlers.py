"""Unit tests for player aggregate handlers.

Tests the guard/validate/compute functions and full handler flows.
"""

import pytest
from .state import (
    PlayerState,
    apply_deposited,
    apply_registered,
    apply_released,
    apply_reserved,
    apply_withdrawn,
    build_state,
)

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from .handlers import (
    deposit_compute,
    deposit_guard,
    deposit_validate,
    handle_deposit,
    handle_register,
    handle_release,
    handle_reserve,
    handle_withdraw,
)


def currency(amount: int) -> poker_types.Currency:
    """Helper to create Currency."""
    return poker_types.Currency(amount=amount, currency_code="CHIPS")


def make_registered_state(bankroll: int = 0, reserved: int = 0) -> PlayerState:
    """Create a registered player state."""
    state = PlayerState()
    state.player_id = "player_test@example.com"
    state.display_name = "Test Player"
    state.email = "test@example.com"
    state.bankroll = bankroll
    state.reserved_funds = reserved
    return state


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegisterPlayer:
    """Tests for handle_register."""

    def test_register_new_player(self) -> None:
        """Register a new player successfully."""
        state = PlayerState()
        cmd = player.RegisterPlayer(
            display_name="Alice",
            email="alice@example.com",
            player_type=poker_types.PlayerType.HUMAN,
        )

        event = handle_register(cmd, state, seq=0)

        assert event.display_name == "Alice"
        assert event.email == "alice@example.com"
        assert event.player_type == poker_types.PlayerType.HUMAN
        assert event.HasField("registered_at")

    def test_register_ai_player(self) -> None:
        """Register an AI player."""
        state = PlayerState()
        cmd = player.RegisterPlayer(
            display_name="Bot",
            email="bot@example.com",
            player_type=poker_types.PlayerType.AI,
            ai_model_id="gpt-4",
        )

        event = handle_register(cmd, state, seq=0)

        assert event.player_type == poker_types.PlayerType.AI
        assert event.ai_model_id == "gpt-4"

    def test_register_rejects_duplicate(self) -> None:
        """Cannot register a player that already exists."""
        state = make_registered_state()
        cmd = player.RegisterPlayer(
            display_name="Alice",
            email="alice@example.com",
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_register(cmd, state, seq=0)

        assert "already exists" in str(exc.value)

    def test_register_rejects_empty_name(self) -> None:
        """Cannot register without display_name."""
        state = PlayerState()
        cmd = player.RegisterPlayer(
            display_name="",
            email="alice@example.com",
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_register(cmd, state, seq=0)

        assert "display_name" in str(exc.value)

    def test_register_rejects_empty_email(self) -> None:
        """Cannot register without email."""
        state = PlayerState()
        cmd = player.RegisterPlayer(
            display_name="Alice",
            email="",
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_register(cmd, state, seq=0)

        assert "email" in str(exc.value)


# =============================================================================
# Deposit Tests
# =============================================================================


class TestDepositFunds:
    """Tests for deposit guard/validate/compute and handle_deposit."""

    def test_deposit_increases_bankroll(self) -> None:
        """Deposit correctly calculates new balance."""
        state = make_registered_state(bankroll=1000)
        cmd = player.DepositFunds(amount=currency(500))

        event = deposit_compute(cmd, state, 500)

        assert event.new_balance.amount == 1500

    def test_deposit_rejects_non_existent_player(self) -> None:
        """Deposit guard rejects non-existent player."""
        state = PlayerState()

        with pytest.raises(CommandRejectedError) as exc:
            deposit_guard(state)

        assert "does not exist" in str(exc.value)

    def test_deposit_rejects_zero_amount(self) -> None:
        """Deposit validate rejects zero amount."""
        cmd = player.DepositFunds(amount=currency(0))

        with pytest.raises(CommandRejectedError) as exc:
            deposit_validate(cmd)

        assert "positive" in str(exc.value)

    def test_deposit_rejects_negative_amount(self) -> None:
        """Deposit validate rejects negative amount."""
        cmd = player.DepositFunds(amount=currency(-100))

        with pytest.raises(CommandRejectedError) as exc:
            deposit_validate(cmd)

        assert "positive" in str(exc.value)

    def test_deposit_full_flow(self) -> None:
        """Full deposit handler flow."""
        state = make_registered_state(bankroll=1000)
        cmd = player.DepositFunds(amount=currency(500))

        event = handle_deposit(cmd, state, seq=1)

        assert event.amount.amount == 500
        assert event.new_balance.amount == 1500
        assert event.HasField("deposited_at")


# =============================================================================
# Withdraw Tests
# =============================================================================


class TestWithdrawFunds:
    """Tests for handle_withdraw."""

    def test_withdraw_decreases_bankroll(self) -> None:
        """Withdraw correctly calculates new balance."""
        state = make_registered_state(bankroll=1000)
        cmd = player.WithdrawFunds(amount=currency(400))

        event = handle_withdraw(cmd, state, seq=1)

        assert event.amount.amount == 400
        assert event.new_balance.amount == 600

    def test_withdraw_rejects_non_existent_player(self) -> None:
        """Cannot withdraw from non-existent player."""
        state = PlayerState()
        cmd = player.WithdrawFunds(amount=currency(100))

        with pytest.raises(CommandRejectedError) as exc:
            handle_withdraw(cmd, state, seq=0)

        assert "does not exist" in str(exc.value)

    def test_withdraw_rejects_zero_amount(self) -> None:
        """Cannot withdraw zero amount."""
        state = make_registered_state(bankroll=1000)
        cmd = player.WithdrawFunds(amount=currency(0))

        with pytest.raises(CommandRejectedError) as exc:
            handle_withdraw(cmd, state, seq=0)

        assert "positive" in str(exc.value)

    def test_withdraw_rejects_insufficient_funds(self) -> None:
        """Cannot withdraw more than available balance."""
        state = make_registered_state(bankroll=100)
        cmd = player.WithdrawFunds(amount=currency(500))

        with pytest.raises(CommandRejectedError) as exc:
            handle_withdraw(cmd, state, seq=0)

        assert "Insufficient" in str(exc.value)

    def test_withdraw_respects_reserved_funds(self) -> None:
        """Cannot withdraw reserved funds."""
        state = make_registered_state(bankroll=1000, reserved=800)
        # Available is 200, trying to withdraw 500
        cmd = player.WithdrawFunds(amount=currency(500))

        with pytest.raises(CommandRejectedError) as exc:
            handle_withdraw(cmd, state, seq=0)

        assert "Insufficient" in str(exc.value)

    def test_withdraw_full_available_balance(self) -> None:
        """Can withdraw exactly the available balance."""
        state = make_registered_state(bankroll=1000, reserved=600)
        cmd = player.WithdrawFunds(amount=currency(400))  # Available is 400

        event = handle_withdraw(cmd, state, seq=1)

        assert event.new_balance.amount == 600


# =============================================================================
# Reserve Funds Tests
# =============================================================================


class TestReserveFunds:
    """Tests for handle_reserve."""

    def test_reserve_funds_for_table(self) -> None:
        """Reserve funds for a table buy-in."""
        state = make_registered_state(bankroll=1000)
        table_root = b"table_123"
        cmd = player.ReserveFunds(
            table_root=table_root,
            amount=currency(500),
        )

        event = handle_reserve(cmd, state, seq=1)

        assert event.amount.amount == 500
        assert event.table_root == table_root
        assert event.new_available_balance.amount == 500
        assert event.new_reserved_balance.amount == 500

    def test_reserve_rejects_non_existent_player(self) -> None:
        """Cannot reserve for non-existent player."""
        state = PlayerState()
        cmd = player.ReserveFunds(
            table_root=b"table_123",
            amount=currency(500),
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_reserve(cmd, state, seq=0)

        assert "does not exist" in str(exc.value)

    def test_reserve_rejects_zero_amount(self) -> None:
        """Cannot reserve zero amount."""
        state = make_registered_state(bankroll=1000)
        cmd = player.ReserveFunds(
            table_root=b"table_123",
            amount=currency(0),
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_reserve(cmd, state, seq=0)

        assert "positive" in str(exc.value)

    def test_reserve_rejects_duplicate_reservation(self) -> None:
        """Cannot reserve twice for same table."""
        state = make_registered_state(bankroll=1000)
        table_root = b"table_123"
        state.table_reservations[table_root.hex()] = 500
        state.reserved_funds = 500

        cmd = player.ReserveFunds(
            table_root=table_root,
            amount=currency(200),
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_reserve(cmd, state, seq=0)

        assert "already reserved" in str(exc.value)

    def test_reserve_rejects_insufficient_funds(self) -> None:
        """Cannot reserve more than available balance."""
        state = make_registered_state(bankroll=100)
        cmd = player.ReserveFunds(
            table_root=b"table_123",
            amount=currency(500),
        )

        with pytest.raises(CommandRejectedError) as exc:
            handle_reserve(cmd, state, seq=0)

        assert "Insufficient" in str(exc.value)

    def test_reserve_multiple_tables(self) -> None:
        """Can reserve for multiple tables."""
        state = make_registered_state(bankroll=1000)

        # First reservation
        cmd1 = player.ReserveFunds(
            table_root=b"table_1",
            amount=currency(300),
        )
        event1 = handle_reserve(cmd1, state, seq=1)

        # Apply event to state
        apply_reserved(state, event1)

        # Second reservation
        cmd2 = player.ReserveFunds(
            table_root=b"table_2",
            amount=currency(400),
        )
        event2 = handle_reserve(cmd2, state, seq=2)

        assert event2.new_reserved_balance.amount == 700
        assert event2.new_available_balance.amount == 300


# =============================================================================
# Release Funds Tests
# =============================================================================


class TestReleaseFunds:
    """Tests for handle_release."""

    def test_release_reserved_funds(self) -> None:
        """Release reserved funds when leaving a table."""
        state = make_registered_state(bankroll=1000, reserved=500)
        table_root = b"table_123"
        state.table_reservations[table_root.hex()] = 500

        cmd = player.ReleaseFunds(table_root=table_root)

        event = handle_release(cmd, state, seq=1)

        assert event.amount.amount == 500
        assert event.table_root == table_root
        assert event.new_available_balance.amount == 1000
        assert event.new_reserved_balance.amount == 0

    def test_release_rejects_non_existent_player(self) -> None:
        """Cannot release for non-existent player."""
        state = PlayerState()
        cmd = player.ReleaseFunds(table_root=b"table_123")

        with pytest.raises(CommandRejectedError) as exc:
            handle_release(cmd, state, seq=0)

        assert "does not exist" in str(exc.value)

    def test_release_rejects_no_reservation(self) -> None:
        """Cannot release when no reservation exists."""
        state = make_registered_state(bankroll=1000)
        cmd = player.ReleaseFunds(table_root=b"table_123")

        with pytest.raises(CommandRejectedError) as exc:
            handle_release(cmd, state, seq=0)

        assert "No funds reserved" in str(exc.value)

    def test_release_partial_when_multiple_tables(self) -> None:
        """Release only affects the specified table."""
        state = make_registered_state(bankroll=1000, reserved=700)
        state.table_reservations[b"table_1".hex()] = 300
        state.table_reservations[b"table_2".hex()] = 400

        cmd = player.ReleaseFunds(table_root=b"table_1")
        event = handle_release(cmd, state, seq=1)

        assert event.amount.amount == 300
        assert event.new_reserved_balance.amount == 400


# =============================================================================
# State Applier Tests
# =============================================================================


class TestStateAppliers:
    """Tests for state applier functions."""

    def test_apply_registered(self) -> None:
        """Apply PlayerRegistered event."""
        state = PlayerState()
        event = player.PlayerRegistered(
            display_name="Alice",
            email="alice@example.com",
            player_type=poker_types.PlayerType.HUMAN,
        )

        apply_registered(state, event)

        assert state.exists
        assert state.display_name == "Alice"
        assert state.email == "alice@example.com"
        assert state.status == "active"
        assert state.bankroll == 0

    def test_apply_deposited(self) -> None:
        """Apply FundsDeposited event."""
        state = make_registered_state(bankroll=500)
        event = player.FundsDeposited(
            amount=currency(200),
            new_balance=currency(700),
        )

        apply_deposited(state, event)

        assert state.bankroll == 700

    def test_apply_withdrawn(self) -> None:
        """Apply FundsWithdrawn event."""
        state = make_registered_state(bankroll=1000)
        event = player.FundsWithdrawn(
            amount=currency(300),
            new_balance=currency(700),
        )

        apply_withdrawn(state, event)

        assert state.bankroll == 700

    def test_apply_reserved(self) -> None:
        """Apply FundsReserved event."""
        state = make_registered_state(bankroll=1000)
        table_root = b"table_123"
        event = player.FundsReserved(
            table_root=table_root,
            amount=currency(400),
            new_available_balance=currency(600),
            new_reserved_balance=currency(400),
        )

        apply_reserved(state, event)

        assert state.reserved_funds == 400
        assert table_root.hex() in state.table_reservations
        assert state.table_reservations[table_root.hex()] == 400

    def test_apply_released(self) -> None:
        """Apply FundsReleased event."""
        state = make_registered_state(bankroll=1000, reserved=400)
        table_root = b"table_123"
        state.table_reservations[table_root.hex()] = 400

        event = player.FundsReleased(
            table_root=table_root,
            amount=currency(400),
            new_available_balance=currency(1000),
            new_reserved_balance=currency(0),
        )

        apply_released(state, event)

        assert state.reserved_funds == 0
        assert table_root.hex() not in state.table_reservations


# =============================================================================
# Build State Integration Tests
# =============================================================================


class TestBuildState:
    """Tests for build_state function."""

    def test_build_state_from_events(self) -> None:
        """Build state from a sequence of events."""
        from google.protobuf.any_pb2 import Any as AnyProto

        events = []

        # Register
        reg = player.PlayerRegistered(
            display_name="Alice",
            email="alice@example.com",
        )
        reg_any = AnyProto()
        reg_any.Pack(reg, type_url_prefix="type.googleapis.com/")
        events.append(reg_any)

        # Deposit
        dep = player.FundsDeposited(
            amount=currency(1000),
            new_balance=currency(1000),
        )
        dep_any = AnyProto()
        dep_any.Pack(dep, type_url_prefix="type.googleapis.com/")
        events.append(dep_any)

        # Reserve
        res = player.FundsReserved(
            table_root=b"table_1",
            amount=currency(300),
            new_available_balance=currency(700),
            new_reserved_balance=currency(300),
        )
        res_any = AnyProto()
        res_any.Pack(res, type_url_prefix="type.googleapis.com/")
        events.append(res_any)

        state = build_state(PlayerState(), events)

        assert state.exists
        assert state.display_name == "Alice"
        assert state.bankroll == 1000
        assert state.reserved_funds == 300
        assert state.available_balance == 700


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_available_balance_property(self) -> None:
        """Available balance is bankroll minus reserved."""
        state = make_registered_state(bankroll=1000, reserved=300)
        assert state.available_balance == 700

    def test_exists_property(self) -> None:
        """exists is True when player_id is set."""
        state = PlayerState()
        assert not state.exists

        state.player_id = "player_1"
        assert state.exists

    def test_empty_table_reservations(self) -> None:
        """Table reservations start empty."""
        state = PlayerState()
        assert state.table_reservations == {}

    def test_reserve_and_release_cycle(self) -> None:
        """Full reserve/release cycle."""
        state = make_registered_state(bankroll=1000)
        table_root = b"table_abc"

        # Reserve
        reserve_cmd = player.ReserveFunds(
            table_root=table_root,
            amount=currency(500),
        )
        reserve_event = handle_reserve(reserve_cmd, state, seq=1)
        apply_reserved(state, reserve_event)

        assert state.available_balance == 500
        assert state.reserved_funds == 500

        # Release
        release_cmd = player.ReleaseFunds(table_root=table_root)
        release_event = handle_release(release_cmd, state, seq=2)
        apply_released(state, release_event)

        assert state.available_balance == 1000
        assert state.reserved_funds == 0
