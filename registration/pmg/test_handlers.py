"""Unit tests for registration PM handlers."""

import sys
from pathlib import Path

import pytest

# Add registration/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tourn
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import (
    RegistrationPM,
    TournamentStateHelper,
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
            max_players=100,
            buy_in=50,
            starting_stack=1500,
        )
        event_book = _make_event_book(
            [_pack_event(created, "TournamentCreated")], domain="tournament"
        )

        state = rebuild_tournament_state(event_book)

        assert state.registration_open is True
        assert state.max_players == 100
        assert state.buy_in == 50
        assert state.starting_stack == 1500
        assert state.registered_count == 0

    def test_rebuild_tracks_enrollments(self) -> None:
        """Rebuild state tracks player enrollments."""
        created = tourn.TournamentCreated(name="Test", max_players=50)
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
        assert state.registered_count == 1

    def test_rebuild_registration_closed_after_start(self) -> None:
        """Rebuild state closes registration after tournament starts."""
        created = tourn.TournamentCreated(name="Test")
        started = tourn.TournamentStarted()
        event_book = _make_event_book(
            [
                _pack_event(created, "TournamentCreated"),
                _pack_event(started, "TournamentStarted"),
            ],
            domain="tournament",
        )

        state = rebuild_tournament_state(event_book)

        assert state.registration_open is False
        assert state.status == tourn.TournamentStatus.TOURNAMENT_RUNNING


class TestRegistrationPMPrepare:
    """Tests for RegistrationPM prepare handlers."""

    def test_prepare_registration_requested_returns_tournament_cover(self) -> None:
        """Prepare returns tournament cover."""
        pm = RegistrationPM()
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_123",
            reservation_id=b"res_001",
        )

        result = pm.prepare_registration_requested(event)

        assert len(result) == 1
        assert result[0].domain == "tournament"
        assert result[0].root.value == b"tournament_123"

    def test_prepare_player_enrolled_returns_player_cover(self) -> None:
        """Prepare returns player cover for TournamentPlayerEnrolled."""
        pm = RegistrationPM()
        event = tourn.TournamentPlayerEnrolled(
            player_root=b"player_123",
            reservation_id=b"res_001",
        )

        result = pm.prepare_player_enrolled(event)

        assert len(result) == 1
        assert result[0].domain == "player"
        assert result[0].root.value == b"player_123"

    def test_prepare_enrollment_rejected_returns_player_cover(self) -> None:
        """Prepare returns player cover for TournamentEnrollmentRejected."""
        pm = RegistrationPM()
        event = tourn.TournamentEnrollmentRejected(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Tournament full",
        )

        result = pm.prepare_enrollment_rejected(event)

        assert len(result) == 1
        assert result[0].domain == "player"
        assert result[0].root.value == b"player_123"


class TestRegistrationPMHandlers:
    """Tests for RegistrationPM event handlers."""

    def _make_tournament_event_book(
        self,
        status: int = tourn.TournamentStatus.TOURNAMENT_CREATED,
        registration_open: bool = True,
        max_players: int = 100,
        buy_in: int = 50,
        starting_stack: int = 1500,
        enrolled_players: list[bytes] = None,
    ) -> types.EventBook:
        """Create a tournament EventBook for testing."""
        events = []

        # Tournament created
        created = tourn.TournamentCreated(
            name="Test Tournament",
            max_players=max_players,
            buy_in=buy_in,
            starting_stack=starting_stack,
        )
        events.append(_pack_event(created, "TournamentCreated"))

        # Started if running (closes registration)
        if status == tourn.TournamentStatus.TOURNAMENT_RUNNING or not registration_open:
            started = tourn.TournamentStarted()
            events.append(_pack_event(started, "TournamentStarted"))

        # Enrolled players
        if enrolled_players:
            for i, player_root in enumerate(enrolled_players):
                enrolled = tourn.TournamentPlayerEnrolled(
                    player_root=player_root,
                    registration_number=i + 1,
                    fee_paid=buy_in,
                    starting_stack=starting_stack,
                )
                events.append(_pack_event(enrolled, "TournamentPlayerEnrolled"))

        return _make_event_book(events, domain="tournament")

    def test_handle_registration_requested_valid(self) -> None:
        """Handle valid registration request."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
            fee=poker.Currency(amount=50),
        )
        tournament_eb = self._make_tournament_event_book()

        result = pm.handle_registration_requested(
            event, destinations=[tournament_eb], root=player_root
        )

        assert result is not None
        assert isinstance(result, tourn.EnrollPlayer)
        assert result.player_root == player_root
        assert result.reservation_id == b"res_001"

    def test_handle_registration_requested_registration_closed(self) -> None:
        """Handle registration when registration is closed."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
        )
        tournament_eb = self._make_tournament_event_book(registration_open=False)

        result = pm.handle_registration_requested(
            event, destinations=[tournament_eb], root=player_root
        )

        assert result is None

    def test_handle_registration_requested_tournament_full(self) -> None:
        """Handle registration when tournament is full."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
        )
        # Create tournament with 2 max players and 2 already enrolled
        tournament_eb = self._make_tournament_event_book(
            max_players=2,
            enrolled_players=[b"player_a", b"player_b"],
        )

        result = pm.handle_registration_requested(
            event, destinations=[tournament_eb], root=player_root
        )

        assert result is None

    def test_handle_registration_requested_already_registered(self) -> None:
        """Handle registration when player already registered."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
        )
        tournament_eb = self._make_tournament_event_book(
            enrolled_players=[player_root],  # Same player already enrolled
        )

        result = pm.handle_registration_requested(
            event, destinations=[tournament_eb], root=player_root
        )

        assert result is None

    def test_handle_registration_requested_missing_destinations(self) -> None:
        """Handle registration with missing destinations."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
        )

        result = pm.handle_registration_requested(
            event, destinations=[], root=player_root
        )

        assert result is None

    def test_handle_player_enrolled_returns_confirm(self) -> None:
        """Handle TournamentPlayerEnrolled returns ConfirmRegistrationFee."""
        pm = RegistrationPM()
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"
        pm._state.fee = 50

        event = tourn.TournamentPlayerEnrolled(
            player_root=b"player_123",
            reservation_id=b"res_001",
            fee_paid=50,
            starting_stack=1500,
        )

        result = pm.handle_player_enrolled(event, destinations=[])

        assert isinstance(result, registration.ConfirmRegistrationFee)
        assert result.reservation_id == b"res_001"

    def test_handle_enrollment_rejected_returns_release(self) -> None:
        """Handle TournamentEnrollmentRejected returns ReleaseRegistrationFee."""
        pm = RegistrationPM()
        pm._state = pm._create_empty_state()
        pm._state.tournament_root = b"tournament_456"

        event = tourn.TournamentEnrollmentRejected(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Tournament full",
        )

        result = pm.handle_enrollment_rejected(event, destinations=[])

        assert isinstance(result, registration.ReleaseRegistrationFee)
        assert result.reservation_id == b"res_001"
        assert result.reason == "Tournament full"
