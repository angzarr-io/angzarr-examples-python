"""Unit tests for registration PM handlers."""

import sys
from pathlib import Path

# Add registration/pmg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from angzarr_client import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tourn
from google.protobuf.any_pb2 import Any as AnyProto
from handlers import RegistrationPM
from state import RegistrationState
from tournament_state import (
    TournamentStateHelper,
    tournament_state_from_event_book,
    tournament_state_rebuild,
)


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


class TestTournamentStateRebuild:
    """Tests for tournament_state_rebuild / tournament_state_from_event_book."""

    def test_rebuild_from_created(self) -> None:
        """Rebuild state from TournamentCreated event."""
        created = tourn.TournamentCreated(
            name="Test Tournament",
            max_players=100,
            buy_in=50,
            starting_stack=1500,
        )
        event_book = _make_event_book(
            [_pack_event(created)], domain="tournament"
        )

        state = tournament_state_from_event_book(event_book)

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
                _pack_event(created),
                _pack_event(enrolled),
            ],
            domain="tournament",
        )

        state = tournament_state_from_event_book(event_book)

        player_hex = b"player_123".hex()
        assert player_hex in state.registered_players
        assert state.registered_count == 1

    def test_rebuild_registration_closed_after_start(self) -> None:
        """Rebuild state closes registration after tournament starts."""
        created = tourn.TournamentCreated(name="Test")
        started = tourn.TournamentStarted()
        event_book = _make_event_book(
            [
                _pack_event(created),
                _pack_event(started),
            ],
            domain="tournament",
        )

        state = tournament_state_from_event_book(event_book)

        assert state.registration_open is False
        assert state.status == tourn.TournamentStatus.TOURNAMENT_RUNNING

    def test_direct_rebuild_over_events(self) -> None:
        state = TournamentStateHelper()
        tournament_state_rebuild(
            state, tourn.TournamentCreated(name="T", max_players=4)
        )
        tournament_state_rebuild(
            state, tourn.TournamentPlayerEnrolled(player_root=b"p1")
        )
        assert state.registered_count == 1
        assert state.max_players == 4


class TestRegistrationPMHandlers:
    """Tests for RegistrationPM event handlers."""

    def test_handle_registration_requested_emits_enroll_player(self) -> None:
        """PM emits EnrollPlayer command - Tournament aggregate validates."""
        pm = RegistrationPM()
        player_root = b"player_123"
        event = registration.RegistrationRequested(
            tournament_root=b"tournament_456",
            reservation_id=b"res_001",
            fee=poker.Currency(amount=50),
        )
        state = RegistrationState(player_root=player_root)
        destinations = _make_destinations({"tournament": 5})

        result = pm.handle_registration_requested(
            event, state=state, destinations=destinations
        )

        assert result is not None
        assert len(result.commands) == 1
        enroll = tourn.EnrollPlayer()
        result.commands[0].pages[0].command.Unpack(enroll)
        assert enroll.player_root == player_root
        assert enroll.reservation_id == b"res_001"

    def test_handle_player_enrolled_returns_confirm(self) -> None:
        """Handle TournamentPlayerEnrolled returns ConfirmRegistrationFee."""
        pm = RegistrationPM()
        state = RegistrationState(tournament_root=b"tournament_456", fee=50)

        event = tourn.TournamentPlayerEnrolled(
            player_root=b"player_123",
            reservation_id=b"res_001",
            fee_paid=50,
            starting_stack=1500,
        )
        destinations = _make_destinations({"player": 3})

        result = pm.handle_player_enrolled(event, state=state, destinations=destinations)

        assert len(result.commands) == 1
        confirm = registration.ConfirmRegistrationFee()
        result.commands[0].pages[0].command.Unpack(confirm)
        assert confirm.reservation_id == b"res_001"

    def test_handle_enrollment_rejected_returns_release(self) -> None:
        """Handle TournamentEnrollmentRejected returns ReleaseRegistrationFee."""
        pm = RegistrationPM()
        state = RegistrationState(tournament_root=b"tournament_456")

        event = tourn.TournamentEnrollmentRejected(
            player_root=b"player_123",
            reservation_id=b"res_001",
            reason="Tournament full",
        )
        destinations = _make_destinations({"player": 3})

        result = pm.handle_enrollment_rejected(
            event, state=state, destinations=destinations
        )

        assert len(result.commands) == 1
        release = registration.ReleaseRegistrationFee()
        result.commands[0].pages[0].command.Unpack(release)
        assert release.reservation_id == b"res_001"
        assert release.reason == "Tournament full"
