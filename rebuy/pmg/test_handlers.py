"""Unit tests for rebuy PM handlers.

Design Philosophy:
    PMs are coordinators, NOT decision makers. Business validation (rebuy
    eligibility, level cutoffs, stack thresholds) belongs in aggregates.
    PM tests verify:
    1. Commands are emitted correctly
    2. PM events are recorded for state tracking
    3. Destinations are used for sequence stamping

    Validation tests belong in Tournament and Table aggregate tests, not here.
"""

import sys
from pathlib import Path

import pytest

# Add rebuy/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client.destinations import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import tournament_pb2 as tourn
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import RebuyPM


def _pack_event(event, type_name: str) -> AnyProto:
    """Pack an event into Any."""
    any_pb = AnyProto()
    any_pb.Pack(event, type_url_prefix="type.googleapis.com/examples")
    return any_pb


def _make_event_book(events: list[AnyProto], domain: str = "test") -> types.EventBook:
    """Create an EventBook with pages."""
    pages = [types.EventPage(event=e) for e in events]
    return types.EventBook(
        cover=types.Cover(domain=domain),
        pages=pages,
    )


def _make_destinations(sequences: dict[str, int] | None = None) -> Destinations:
    """Create a Destinations context for testing."""
    return Destinations(sequences or {})


class TestRebuyPMPrepare:
    """Tests for RebuyPM prepare handlers."""

    def test_prepare_rebuy_requested_returns_two_covers(self) -> None:
        """Prepare returns tournament and table covers."""
        pm = RebuyPM()
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_123",
            table_root=b"table_456",
        )

        result = pm.prepare_rebuy_requested(event)

        assert len(result) == 2
        assert result[0].domain == "tournament"
        assert result[0].root.value == b"tournament_123"
        assert result[1].domain == "table"
        assert result[1].root.value == b"table_456"

    def test_prepare_rebuy_denied_returns_player_cover(self) -> None:
        """Prepare returns player cover for RebuyDenied."""
        pm = RebuyPM()
        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reason="Not allowed",
        )

        result = pm.prepare_rebuy_denied(event)

        assert len(result) == 1
        assert result[0].domain == "player"
        assert result[0].root.value == b"player_123"


class TestRebuyPMHandlers:
    """Tests for RebuyPM event handlers.

    Design Philosophy:
        PM always emits commands - aggregates validate.
        These tests verify commands are emitted correctly, not validation logic.
        Validation tests (rebuy eligibility, level cutoffs) belong in
        Tournament and Table aggregate tests.
    """

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
        destinations = _make_destinations({"tournament": 5, "table": 3})

        result = pm.handle_rebuy_requested(
            event, destinations=destinations, root=player_root
        )

        assert result is not None
        assert isinstance(result, tourn.ProcessRebuy)
        assert result.player_root == player_root
        assert result.reservation_id == b"res_001"

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
        destinations = _make_destinations({"tournament": 5})

        pm.handle_rebuy_requested(event, destinations=destinations, root=player_root)

        # Check that RebuyInitiated was recorded
        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        initiated = rebuy.RebuyInitiated()
        process_events.pages[0].event.Unpack(initiated)
        assert initiated.player_root == player_root
        assert initiated.tournament_root == b"tournament_456"
        assert initiated.phase == orch.RebuyPhase.REBUY_APPROVING

    def test_handle_rebuy_processed_emits_add_chips(self) -> None:
        """PM emits AddRebuyChips when Tournament approves rebuy."""
        pm = RebuyPM()
        # Initialize PM state (simulates prior RebuyInitiated)
        pm._state = pm._create_empty_state()
        pm._state.table_root = b"table_789"
        pm._state.seat = 2

        event = tourn.RebuyProcessed(
            player_root=b"player_123",
            reservation_id=b"res_001",
            chips_added=1500,
            rebuy_count=1,
        )
        destinations = _make_destinations({"table": 3})

        result = pm.handle_rebuy_processed(event, destinations=destinations)

        assert isinstance(result, rebuy.AddRebuyChips)
        assert result.player_root == b"player_123"
        assert result.reservation_id == b"res_001"
        assert result.seat == 2
        assert result.amount == 1500

    def test_handle_rebuy_denied_returns_release(self) -> None:
        """PM emits ReleaseRebuyFee when Tournament denies rebuy."""
        pm = RebuyPM()
        # Initialize PM state
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"

        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Rebuy limit reached",
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_rebuy_denied(event, destinations=destinations)

        assert isinstance(result, rebuy.ReleaseRebuyFee)
        assert result.reservation_id == b"res_001"
        assert result.reason == "Rebuy limit reached"

    def test_handle_rebuy_denied_records_failed_event(self) -> None:
        """PM records RebuyFailed event for state tracking."""
        pm = RebuyPM()
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"

        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Rebuy limit reached",
        )
        destinations = _make_destinations({"player": 5})

        pm.handle_rebuy_denied(event, destinations=destinations)

        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        failed = rebuy.RebuyFailed()
        process_events.pages[0].event.Unpack(failed)
        assert failed.player_root == b"player_123"
        assert failed.failure.code == "REBUY_DENIED"

    def test_handle_chips_added_returns_confirm(self) -> None:
        """PM emits ConfirmRebuyFee when Table adds chips."""
        pm = RebuyPM()
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"
        pm._state.table_root = b"table_789"
        pm._state.fee = 50

        event = rebuy.RebuyChipsAdded(
            player_root=b"player_123",
            reservation_id=b"res_001",
            seat=2,
            amount=1500,
            new_stack=2000,
        )
        destinations = _make_destinations({"player": 5})

        result = pm.handle_chips_added(event, destinations=destinations)

        assert isinstance(result, rebuy.ConfirmRebuyFee)
        assert result.reservation_id == b"res_001"

    def test_handle_chips_added_records_completed_event(self) -> None:
        """PM records RebuyCompleted event for state tracking."""
        pm = RebuyPM()
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"
        pm._state.table_root = b"table_789"
        pm._state.fee = 50

        event = rebuy.RebuyChipsAdded(
            player_root=b"player_123",
            reservation_id=b"res_001",
            seat=2,
            amount=1500,
            new_stack=2000,
        )
        destinations = _make_destinations({"player": 5})

        pm.handle_chips_added(event, destinations=destinations)

        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        completed = rebuy.RebuyCompleted()
        process_events.pages[0].event.Unpack(completed)
        assert completed.player_root == b"player_123"
        assert completed.chips_added == 1500
