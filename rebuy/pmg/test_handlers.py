"""Unit tests for rebuy PM handlers."""

import sys
from pathlib import Path

import pytest

# Add rebuy/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import table_pb2 as table
from angzarr_client.proto.examples import tournament_pb2 as tourn
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import (
    RebuyPM,
    TableStateHelper,
    TournamentStateHelper,
    rebuild_table_state,
    rebuild_tournament_state,
)


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


class TestTournamentStateHelper:
    """Tests for TournamentStateHelper."""

    def test_rebuild_from_created(self) -> None:
        """Rebuild state from TournamentCreated event."""
        created = tourn.TournamentCreated(
            name="Test Tournament",
            rebuy_config=tourn.RebuyConfig(
                enabled=True,
                max_rebuys=2,
                rebuy_level_cutoff=4,
                stack_threshold=1000,
                rebuy_chips=1500,
                rebuy_cost=50,
            ),
        )
        event_book = _make_event_book(
            [_pack_event(created, "TournamentCreated")], domain="tournament"
        )

        state = rebuild_tournament_state(event_book)

        assert state.rebuy_enabled is True
        assert state.max_rebuys == 2
        assert state.rebuy_level_cutoff == 4
        assert state.rebuy_chips == 1500

    def test_rebuild_tracks_enrollments(self) -> None:
        """Rebuild state tracks player enrollments."""
        created = tourn.TournamentCreated(name="Test")
        enrolled = tourn.TournamentPlayerEnrolled(
            player_root=b"player_123",
            registration_number=1,
        )
        event_book = _make_event_book(
            [
                _pack_event(created, "TournamentCreated"),
                _pack_event(enrolled, "TournamentPlayerEnrolled"),
            ],
            domain="tournament",
        )

        state = rebuild_tournament_state(event_book)

        player_hex = b"player_123".hex()
        assert player_hex in state.registered_players
        assert state.registered_players[player_hex] == 0


class TestTableStateHelper:
    """Tests for TableStateHelper."""

    def test_find_seat_by_player(self) -> None:
        """Find seat by player root."""
        state = TableStateHelper(
            seats={0: (b"player_a", 1000), 2: (b"player_b", 2000)},
        )
        assert state.find_seat_by_player(b"player_b") == 2
        assert state.find_seat_by_player(b"unknown") is None

    def test_get_stack(self) -> None:
        """Get player's stack."""
        state = TableStateHelper(
            seats={0: (b"player_a", 1000), 2: (b"player_b", 2000)},
        )
        assert state.get_stack(b"player_b") == 2000
        assert state.get_stack(b"unknown") is None


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
    """Tests for RebuyPM event handlers."""

    def _make_tournament_event_book(
        self,
        status: int = tourn.TournamentStatus.TOURNAMENT_RUNNING,
        rebuy_enabled: bool = True,
        max_rebuys: int = 3,
        rebuy_level_cutoff: int = 4,
        stack_threshold: int = 1000,
        rebuy_chips: int = 1500,
        current_level: int = 1,
        enrolled_players: dict = None,
    ) -> types.EventBook:
        """Create a tournament EventBook for testing."""
        events = []

        # Tournament created
        created = tourn.TournamentCreated(
            name="Test Tournament",
            rebuy_config=tourn.RebuyConfig(
                enabled=rebuy_enabled,
                max_rebuys=max_rebuys,
                rebuy_level_cutoff=rebuy_level_cutoff,
                stack_threshold=stack_threshold,
                rebuy_chips=rebuy_chips,
            ),
        )
        events.append(_pack_event(created, "TournamentCreated"))

        # Started if running
        if status == tourn.TournamentStatus.TOURNAMENT_RUNNING:
            started = tourn.TournamentStarted()
            events.append(_pack_event(started, "TournamentStarted"))

        # Enrolled players
        if enrolled_players:
            for player_root, rebuys_used in enrolled_players.items():
                enrolled = tourn.TournamentPlayerEnrolled(
                    player_root=player_root,
                    registration_number=len(events),
                )
                events.append(_pack_event(enrolled, "TournamentPlayerEnrolled"))

                # Add rebuy events if rebuys used
                for _ in range(rebuys_used):
                    processed = tourn.RebuyProcessed(
                        player_root=player_root,
                        rebuy_count=rebuys_used,
                    )
                    events.append(_pack_event(processed, "RebuyProcessed"))

        # Advance level if needed
        if current_level > 1:
            for level in range(2, current_level + 1):
                advanced = tourn.BlindLevelAdvanced(level=level)
                events.append(_pack_event(advanced, "BlindLevelAdvanced"))

        return _make_event_book(events, domain="tournament")

    def _make_table_event_book(
        self,
        seated_players: dict = None,  # seat -> (player_root, stack)
    ) -> types.EventBook:
        """Create a table EventBook for testing."""
        events = []

        # Table created
        created = table.TableCreated(
            table_name="Test Table",
            max_players=9,
        )
        events.append(_pack_event(created, "TableCreated"))

        # Seated players
        if seated_players:
            for seat, (player_root, stack) in seated_players.items():
                joined = table.PlayerJoined(
                    player_root=player_root,
                    seat_position=seat,
                    stack=stack,
                )
                events.append(_pack_event(joined, "PlayerJoined"))

        return _make_event_book(events, domain="table")

    def test_handle_rebuy_requested_valid(self) -> None:
        """Handle valid rebuy request."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
            fee=poker.Currency(amount=50),
        )
        tournament_eb = self._make_tournament_event_book(
            enrolled_players={player_root: 0},
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 500)},  # Stack below threshold
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is not None
        assert isinstance(result, tourn.ProcessRebuy)
        assert result.player_root == player_root

    def test_handle_rebuy_requested_tournament_not_running(self) -> None:
        """Handle rebuy when tournament not running."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
        )
        tournament_eb = self._make_tournament_event_book(
            status=tourn.TournamentStatus.TOURNAMENT_CREATED,
            enrolled_players={player_root: 0},
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 500)},
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is None

    def test_handle_rebuy_requested_rebuy_disabled(self) -> None:
        """Handle rebuy when rebuys not enabled."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
        )
        tournament_eb = self._make_tournament_event_book(
            rebuy_enabled=False,
            enrolled_players={player_root: 0},
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 500)},
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is None

    def test_handle_rebuy_requested_window_closed(self) -> None:
        """Handle rebuy when rebuy window has closed."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
        )
        tournament_eb = self._make_tournament_event_book(
            rebuy_level_cutoff=4,
            current_level=5,  # Past cutoff
            enrolled_players={player_root: 0},
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 500)},
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is None

    def test_handle_rebuy_requested_max_rebuys_reached(self) -> None:
        """Handle rebuy when max rebuys already used."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
        )
        tournament_eb = self._make_tournament_event_book(
            max_rebuys=2,
            enrolled_players={player_root: 2},  # Already used max
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 500)},
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is None

    def test_handle_rebuy_requested_stack_too_high(self) -> None:
        """Handle rebuy when stack exceeds threshold."""
        pm = RebuyPM()
        player_root = b"player_123"
        event = rebuy.RebuyRequested(
            tournament_root=b"tournament_456",
            table_root=b"table_789",
            reservation_id=b"res_001",
            seat=2,
        )
        tournament_eb = self._make_tournament_event_book(
            stack_threshold=1000,
            enrolled_players={player_root: 0},
        )
        table_eb = self._make_table_event_book(
            seated_players={2: (player_root, 1500)},  # Above threshold
        )

        result = pm.handle_rebuy_requested(
            event, destinations=[tournament_eb, table_eb], root=player_root
        )

        assert result is None

    def test_handle_rebuy_denied_returns_release(self) -> None:
        """Handle RebuyDenied returns ReleaseRebuyFee."""
        pm = RebuyPM()
        event = tourn.RebuyDenied(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Rebuy limit reached",
        )

        result = pm.handle_rebuy_denied(event, destinations=[])

        assert isinstance(result, rebuy.ReleaseRebuyFee)
        assert result.reservation_id == b"res_001"
        assert result.reason == "Rebuy limit reached"

    def test_handle_chips_added_returns_confirm(self) -> None:
        """Handle RebuyChipsAdded returns ConfirmRebuyFee."""
        # Initialize PM state first
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

        result = pm.handle_chips_added(event, destinations=[])

        assert isinstance(result, rebuy.ConfirmRebuyFee)
        assert result.reservation_id == b"res_001"
