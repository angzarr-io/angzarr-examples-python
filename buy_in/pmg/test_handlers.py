"""Unit tests for buy-in PM handlers."""

import sys
from pathlib import Path

import pytest

# Add buy_in/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import table_pb2 as table
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import BuyInPM, TableStateHelper, rebuild_table_state


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


class TestTableStateHelper:
    """Tests for TableStateHelper."""

    def test_find_seat_by_player_found(self) -> None:
        """Find seat when player is seated."""
        state = TableStateHelper(
            seats={0: b"player_a", 2: b"player_b"},
        )
        assert state.find_seat_by_player(b"player_b") == 2

    def test_find_seat_by_player_not_found(self) -> None:
        """Return None when player not seated."""
        state = TableStateHelper(
            seats={0: b"player_a"},
        )
        assert state.find_seat_by_player(b"player_c") is None

    def test_next_available_seat_found(self) -> None:
        """Find next available seat."""
        state = TableStateHelper(
            max_players=4,
            seats={0: b"p1", 2: b"p2"},
        )
        assert state.next_available_seat() == 1

    def test_next_available_seat_full(self) -> None:
        """Return None when table is full."""
        state = TableStateHelper(
            max_players=2,
            seats={0: b"p1", 1: b"p2"},
        )
        assert state.next_available_seat() is None


class TestRebuildTableState:
    """Tests for rebuild_table_state."""

    def test_rebuilds_from_table_created(self) -> None:
        """Rebuild state from TableCreated event."""
        created = table.TableCreated(
            table_name="Test Table",
            min_buy_in=100,
            max_buy_in=1000,
            max_players=6,
        )
        event_book = _make_event_book(
            [_pack_event(created, "TableCreated")], domain="table"
        )

        state = rebuild_table_state(event_book)

        assert state.table_name == "Test Table"
        assert state.min_buy_in == 100
        assert state.max_buy_in == 1000
        assert state.max_players == 6

    def test_rebuilds_with_player_joined(self) -> None:
        """Rebuild state with PlayerJoined events."""
        created = table.TableCreated(
            table_name="Test",
            min_buy_in=100,
            max_buy_in=1000,
            max_players=6,
        )
        joined = table.PlayerJoined(
            player_root=b"player_123",
            seat_position=2,
        )
        event_book = _make_event_book(
            [_pack_event(created, "TableCreated"), _pack_event(joined, "PlayerJoined")],
            domain="table",
        )

        state = rebuild_table_state(event_book)

        assert 2 in state.seats
        assert state.seats[2] == b"player_123"


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
    """Tests for BuyInPM event handlers."""

    def _make_table_event_book(
        self,
        min_buy_in: int = 100,
        max_buy_in: int = 1000,
        max_players: int = 6,
        occupied_seats: dict = None,
    ) -> types.EventBook:
        """Create a table EventBook for testing."""
        events = []

        # Table created event
        created = table.TableCreated(
            table_name="Test",
            min_buy_in=min_buy_in,
            max_buy_in=max_buy_in,
            max_players=max_players,
        )
        events.append(_pack_event(created, "TableCreated"))

        # Add occupied seats
        if occupied_seats:
            for pos, player_root in occupied_seats.items():
                joined = table.PlayerJoined(
                    player_root=player_root,
                    seat_position=pos,
                )
                events.append(_pack_event(joined, "PlayerJoined"))

        return _make_event_book(events, domain="table")

    def test_handle_buy_in_requested_valid(self) -> None:
        """Handle valid buy-in request."""
        pm = BuyInPM()
        player_root = b"player_123"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,
            amount=poker.Currency(amount=500),
        )
        table_eb = self._make_table_event_book()

        result = pm.handle_buy_in_requested(
            event, destinations=[table_eb], root=player_root
        )

        assert result is not None
        assert isinstance(result, buy_in.SeatPlayer)
        assert result.player_root == player_root
        assert result.seat == 2
        assert result.amount == 500

    def test_handle_buy_in_requested_amount_too_low(self) -> None:
        """Handle buy-in with amount below minimum."""
        pm = BuyInPM()
        player_root = b"player_123"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,
            amount=poker.Currency(amount=50),  # Below 100 min
        )
        table_eb = self._make_table_event_book(min_buy_in=100)

        result = pm.handle_buy_in_requested(
            event, destinations=[table_eb], root=player_root
        )

        assert result is None  # No command, failure event recorded
        # Check that failure was recorded
        process_events = pm.process_events()
        assert len(process_events.pages) == 1

    def test_handle_buy_in_requested_amount_too_high(self) -> None:
        """Handle buy-in with amount above maximum."""
        pm = BuyInPM()
        player_root = b"player_123"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,
            amount=poker.Currency(amount=2000),  # Above 1000 max
        )
        table_eb = self._make_table_event_book(max_buy_in=1000)

        result = pm.handle_buy_in_requested(
            event, destinations=[table_eb], root=player_root
        )

        assert result is None

    def test_handle_buy_in_requested_seat_occupied(self) -> None:
        """Handle buy-in when seat is occupied."""
        pm = BuyInPM()
        player_root = b"new_player"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=2,  # Same as occupied seat
            amount=poker.Currency(amount=500),
        )
        table_eb = self._make_table_event_book(
            occupied_seats={2: b"existing_player"},
        )

        result = pm.handle_buy_in_requested(
            event, destinations=[table_eb], root=player_root
        )

        assert result is None

    def test_handle_buy_in_requested_table_full(self) -> None:
        """Handle buy-in when table is full."""
        pm = BuyInPM()
        player_root = b"new_player"
        event = buy_in.BuyInRequested(
            table_root=b"table_456",
            reservation_id=b"res_789",
            seat=-1,  # Any seat
            amount=poker.Currency(amount=500),
        )
        table_eb = self._make_table_event_book(
            max_players=2,
            occupied_seats={0: b"p1", 1: b"p2"},
        )

        result = pm.handle_buy_in_requested(
            event, destinations=[table_eb], root=player_root
        )

        assert result is None

    def test_handle_player_seated_returns_confirm(self) -> None:
        """Handle PlayerSeated returns ConfirmBuyIn."""
        pm = BuyInPM()
        event = buy_in.PlayerSeated(
            player_root=b"player_123",
            reservation_id=b"res_789",
            seat_position=2,
            stack=500,
        )

        result = pm.handle_player_seated(event, destinations=[])

        assert isinstance(result, buy_in.ConfirmBuyIn)
        assert result.reservation_id == b"res_789"

    def test_handle_seating_rejected_returns_release(self) -> None:
        """Handle SeatingRejected returns ReleaseBuyIn."""
        pm = BuyInPM()
        event = buy_in.SeatingRejected(
            player_root=b"player_123",
            reservation_id=b"res_789",
            reason="Seat already taken",
        )

        result = pm.handle_seating_rejected(event, destinations=[])

        assert isinstance(result, buy_in.ReleaseBuyIn)
        assert result.reservation_id == b"res_789"
        assert result.reason == "Seat already taken"
