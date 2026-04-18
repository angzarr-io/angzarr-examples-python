"""Unit tests for buy-in PM handlers."""

import sys
from pathlib import Path

# Add buy_in/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import BuyInPM
from state import BuyInState


def _pack_event(event) -> AnyProto:
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
    return Destinations(sequences or {})


class TestBuyInPMHandlers:
    """Tests for BuyInPM event handlers."""

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
        # State carries the player_root (seeded by the framework / cover in prod).
        state = BuyInState(player_root=player_root)
        destinations = _make_destinations({"table": 5})

        result = pm.handle_buy_in_requested(event, state=state, destinations=destinations)

        assert result is not None
        assert len(result.commands) == 1
        cmd_book = result.commands[0]
        assert cmd_book.cover.domain == "table"
        seat_cmd = buy_in.SeatPlayer()
        cmd_book.pages[0].command.Unpack(seat_cmd)
        assert seat_cmd.player_root == player_root
        assert seat_cmd.seat == 2
        assert seat_cmd.amount == 500
        assert seat_cmd.reservation_id == b"res_789"

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
        state = BuyInState(player_root=player_root)
        destinations = _make_destinations({"table": 5})

        result = pm.handle_buy_in_requested(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        initiated = buy_in.BuyInInitiated()
        result.process_events.pages[0].event.Unpack(initiated)
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
        state = BuyInState()
        destinations = _make_destinations({"player": 3})

        result = pm.handle_player_seated(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        confirm = buy_in.ConfirmBuyIn()
        result.commands[0].pages[0].command.Unpack(confirm)
        assert confirm.reservation_id == b"res_789"

    def test_handle_player_seated_records_completed_event(self) -> None:
        """PM records BuyInCompleted event for state tracking."""
        pm = BuyInPM()
        event = buy_in.PlayerSeated(
            player_root=b"player_123",
            reservation_id=b"res_789",
            seat_position=2,
            stack=500,
        )
        state = BuyInState()
        destinations = _make_destinations({"player": 3})

        result = pm.handle_player_seated(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        completed = buy_in.BuyInCompleted()
        result.process_events.pages[0].event.Unpack(completed)
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
        state = BuyInState()
        destinations = _make_destinations({"player": 3})

        result = pm.handle_seating_rejected(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        release = buy_in.ReleaseBuyIn()
        result.commands[0].pages[0].command.Unpack(release)
        assert release.reservation_id == b"res_789"
        assert release.reason == "Seat already taken"

    def test_handle_seating_rejected_records_failed_event(self) -> None:
        """PM records BuyInFailed event for state tracking."""
        pm = BuyInPM()
        event = buy_in.SeatingRejected(
            player_root=b"player_123",
            reservation_id=b"res_789",
            reason="Seat already taken",
        )
        state = BuyInState()
        destinations = _make_destinations({"player": 3})

        result = pm.handle_seating_rejected(event, state=state, destinations=destinations)

        assert result.process_events is not None
        assert len(result.process_events.pages) == 1
        failed = buy_in.BuyInFailed()
        result.process_events.pages[0].event.Unpack(failed)
        assert failed.player_root == b"player_123"
        assert failed.failure.code == "SEATING_REJECTED"
