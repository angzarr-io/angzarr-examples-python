"""Unit tests for rebuy PM handlers."""

import sys
from pathlib import Path

# Add rebuy/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client import Destinations
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import tournament_pb2 as tourn
from handlers import RebuyPM
from state import RebuyState


def _make_destinations(sequences: dict[str, int] | None = None) -> Destinations:
    return Destinations(sequences or {})


class TestRebuyPMHandlers:
    """Tests for RebuyPM event handlers."""

    def test_handle_rebuy_requested_emits_process_rebuy(self) -> None:
        """PM emits ProcessRebuy command - Tournament aggregate validates."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
            fee=poker.Currency(amount=50),
        )
        state = RebuyState(player_root=player_root)
        destinations = _make_destinations({"tournament": 5, "table": 3})

        result = pm.handle_rebuy_requested(event, state=state, destinations=destinations)

        assert result is not None
        assert len(result.commands) == 1
        process_rebuy = tourn.ProcessRebuy()
        result.commands[0].pages[0].command.Unpack(process_rebuy)
        assert process_rebuy.player_root == player_root
        assert process_rebuy.reservation_id == b"res_001"

    def test_handle_rebuy_requested_records_initiated_event(self) -> None:
        """PM records RebuyInitiated event for state tracking."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
            fee=poker.Currency(amount=50),
        )
        state = RebuyState(player_root=player_root)
        destinations = _make_destinations({"tournament": 5})

        result = pm.handle_rebuy_requested(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        initiated = rebuy.RebuyInitiated()
        result.process_events.pages[0].event.Unpack(initiated)
        assert initiated.player_root == player_root
        assert initiated.tournament_root == b"tournament_456"
        assert initiated.phase == orch.RebuyPhase.REBUY_APPROVING

    def test_handle_rebuy_processed_emits_add_chips(self) -> None:
        """PM emits AddRebuyChips when Tournament approves rebuy."""
        pm = RebuyPM()
        state = RebuyState(table_root=b"table_789", seat=2)

        event = tourn.RebuyProcessed(
            player_root=b"player_123",
            reservation_id=b"res_001",
            chips_added=1500,
            rebuy_count=1,
        )
        destinations = _make_destinations({"table": 3})

        result = pm.handle_rebuy_processed(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        add_chips = rebuy.AddRebuyChips()
        result.commands[0].pages[0].command.Unpack(add_chips)
        assert add_chips.player_root == b"player_123"
        assert add_chips.reservation_id == b"res_001"
        assert add_chips.seat == 2
        assert add_chips.amount == 1500

    def test_handle_rebuy_denied_returns_release(self) -> None:
        """PM emits ReleaseRebuyFee when Tournament denies rebuy."""
        pm = RebuyPM()
        state = RebuyState(tournament_root=b"tournament_456")

        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Rebuy limit reached",
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_rebuy_denied(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        release = rebuy.ReleaseRebuyFee()
        result.commands[0].pages[0].command.Unpack(release)
        assert release.reservation_id == b"res_001"
        assert release.reason == "Rebuy limit reached"

    def test_handle_rebuy_denied_records_failed_event(self) -> None:
        """PM records RebuyFailed event for state tracking."""
        pm = RebuyPM()
        state = RebuyState(tournament_root=b"tournament_456")

        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Rebuy limit reached",
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_rebuy_denied(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        failed = rebuy.RebuyFailed()
        result.process_events.pages[0].event.Unpack(failed)
        assert failed.player_root == b"player_123"
        assert failed.failure.code == "REBUY_DENIED"

    def test_handle_chips_added_returns_confirm(self) -> None:
        """PM emits ConfirmRebuyFee when Table adds chips."""
        pm = RebuyPM()
        state = RebuyState(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            fee=50,
        )

        event = rebuy.RebuyChipsAdded(
            player_root=b"player_123",
            reservation_id=b"res_001",
            seat=2,
            amount=1500,
            new_stack=2000,
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_chips_added(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        confirm = rebuy.ConfirmRebuyFee()
        result.commands[0].pages[0].command.Unpack(confirm)
        assert confirm.reservation_id == b"res_001"

    def test_handle_chips_added_records_completed_event(self) -> None:
        """PM records RebuyCompleted event for state tracking."""
        pm = RebuyPM()
        state = RebuyState(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            fee=50,
        )

        event = rebuy.RebuyChipsAdded(
            player_root=b"player_123",
            reservation_id=b"res_001",
            seat=2,
            amount=1500,
            new_stack=2000,
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_chips_added(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        completed = rebuy.RebuyCompleted()
        result.process_events.pages[0].event.Unpack(completed)
        assert completed.player_root == b"player_123"
        assert completed.chips_added == 1500
