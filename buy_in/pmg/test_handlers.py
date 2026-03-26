"""Unit tests for buy-in PM handlers.

Design Philosophy:
    PMs are coordinators, NOT decision makers. Business validation (seat
    availability, buy-in range) belongs in aggregates. PM tests verify:
    1. Commands are emitted correctly
    2. PM events are recorded for state tracking
    3. Destinations are used for sequence stamping

    Validation tests belong in Table aggregate tests, not here.
"""

import sys
from pathlib import Path

import pytest

# Add buy_in/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client.destinations import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import table_pb2 as table
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import BuyInPM


def _pack_event(event, type_name: str) -> AnyProto:
    """Pack an event into Any.

    Note: type_url_prefix should end with / for proper URL construction.
    The Pack method creates: type_url_prefix + descriptor.full_name
    """
    any_pb = AnyProto()
    any_pb.Pack(event, type_url_prefix="type.googleapis.com/")
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


class TestBuyInPMPrepare:
    """Tests for BuyInPM prepare handlers."""

    def test_prepare_buy_in_requested_returns_table_cover(self) -> None:
        """Prepare returns table cover for BuyInRequested."""
        pm = BuyInPM()
        event = buy_in.BuyInRequested(
            table_root=b"table_123",
        )

        result = pm.prepare_buy_in_requested(event)

        assert len(result) == 1
        assert result[0].domain == "table"
        assert result[0].root.value == b"table_123"

    def test_prepare_player_seated_returns_player_cover(self) -> None:
        """Prepare returns player cover for PlayerSeated."""
        pm = BuyInPM()
        event = buy_in.PlayerSeated(
            player_root=b"player_456",
            seat_position=3,
        )

        result = pm.prepare_player_seated(event)

        assert len(result) == 1
        assert result[0].domain == "player"
        assert result[0].root.value == b"player_456"


class TestBuyInPMHandlers:
    """Tests for BuyInPM event handlers.

    Design Philosophy:
        PM always emits commands - Table aggregate validates.
        These tests verify commands are emitted correctly, not validation logic.
        Validation tests (buy-in range, seat availability) belong in Table aggregate tests.
    """

    def test_handle_buy_in_requested_emits_seat_player(self) -> None:
        """PM emits SeatPlayer command - Table aggregate validates."""
        pm = BuyInPM()
        player_root = b"player_123"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,
            amount=poker.Currency(amount=500),
        )
        destinations = _make_destinations({"table": 5})

        result = pm.handle_buy_in_requested(
            event, destinations=destinations, root=player_root
        )

        assert result is not None
        assert isinstance(result, buy_in.SeatPlayer)
        assert result.player_root == player_root
        assert result.seat == 2
        assert result.amount == 500
        assert result.reservation_id == b"res_789"

    def test_handle_buy_in_requested_records_initiated_event(self) -> None:
        """PM records BuyInInitiated event for state tracking."""
        pm = BuyInPM()
        player_root = b"player_123"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,
            amount=poker.Currency(amount=500),
        )
        destinations = _make_destinations({"table": 5})

        pm.handle_buy_in_requested(event, destinations=destinations, root=player_root)

        # Check that BuyInInitiated was recorded
        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        initiated = buy_in.BuyInInitiated()
        process_events.pages[0].event.Unpack(initiated)
        assert initiated.player_root == player_root
        assert initiated.table_root == b"table_456"
        assert initiated.phase == orch.BuyInPhase.BUY_IN_SEATING

    def test_handle_player_seated_returns_confirm(self) -> None:
        """PM emits ConfirmBuyIn when Table accepts seating."""
        pm = BuyInPM()
        event = buy_in.PlayerSeated(
            player_root=b"player_123",
            reservation_id=b"res_789",
            seat_position=2,
            stack=500,
        )
        destinations = _make_destinations({"player": 3})

        result = pm.handle_player_seated(event, destinations=destinations)

        assert isinstance(result, buy_in.ConfirmBuyIn)
        assert result.reservation_id == b"res_789"

    def test_handle_player_seated_records_completed_event(self) -> None:
        """PM records BuyInCompleted event for state tracking."""
        pm = BuyInPM()
        event = buy_in.PlayerSeated(
            player_root=b"player_123",
            reservation_id=b"res_789",
            seat_position=2,
            stack=500,
        )
        destinations = _make_destinations({"player": 3})

        pm.handle_player_seated(event, destinations=destinations)

        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        completed = buy_in.BuyInCompleted()
        process_events.pages[0].event.Unpack(completed)
        assert completed.player_root == b"player_123"
        assert completed.seat == 2

    def test_handle_seating_rejected_returns_release(self) -> None:
        """PM emits ReleaseBuyIn when Table rejects seating."""
        pm = BuyInPM()
        event = buy_in.SeatingRejected(
            player_root=b"player_123",
            reservation_id=b"res_789",
            reason="Seat already taken",
        )
        destinations = _make_destinations({"player": 3})

        result = pm.handle_seating_rejected(event, destinations=destinations)

        assert isinstance(result, buy_in.ReleaseBuyIn)
        assert result.reservation_id == b"res_789"
        assert result.reason == "Seat already taken"

    def test_handle_seating_rejected_records_failed_event(self) -> None:
        """PM records BuyInFailed event for state tracking."""
        pm = BuyInPM()
        event = buy_in.SeatingRejected(
            player_root=b"player_123",
            reservation_id=b"res_789",
            reason="Seat already taken",
        )
        destinations = _make_destinations({"player": 3})

        pm.handle_seating_rejected(event, destinations=destinations)

        process_events = pm.process_events()
        assert len(process_events.pages) == 1
        failed = buy_in.BuyInFailed()
        process_events.pages[0].event.Unpack(failed)
        assert failed.player_root == b"player_123"
        assert failed.failure.code == "SEATING_REJECTED"
