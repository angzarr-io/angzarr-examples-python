"""Unit tests for tournament aggregate handlers."""

import pytest

import sys
from pathlib import Path

# Add tournament/agg to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from state import TournamentState
from handlers import (
    create_guard,
    create_validate,
    create_compute,
    enroll_guard,
    enroll_validate,
    open_registration_guard,
    rebuy_validate,
)
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import tournament_pb2 as tournament


class TestCreateTournament:
    """Tests for CreateTournament handler."""

    def test_guard_rejects_existing_tournament(self) -> None:
        """Guard rejects if tournament already exists."""
        state = TournamentState(tournament_id="tournament_test")
        with pytest.raises(CommandRejectedError, match="already exists"):
            create_guard(state)

    def test_guard_allows_new_tournament(self) -> None:
        """Guard allows creating new tournament."""
        state = TournamentState()
        create_guard(state)  # Should not raise

    def test_validate_requires_name(self) -> None:
        """Validate rejects empty name."""
        cmd = tournament.CreateTournament(
            name="",
            buy_in=100,
            starting_stack=1000,
            max_players=100,
            min_players=10,
        )
        with pytest.raises(CommandRejectedError, match="name is required"):
            create_validate(cmd)

    def test_validate_requires_positive_buy_in(self) -> None:
        """Validate rejects non-positive buy_in."""
        cmd = tournament.CreateTournament(
            name="Test",
            buy_in=0,
            starting_stack=1000,
            max_players=100,
            min_players=10,
        )
        with pytest.raises(CommandRejectedError, match="buy_in must be positive"):
            create_validate(cmd)

    def test_validate_requires_positive_starting_stack(self) -> None:
        """Validate rejects non-positive starting_stack."""
        cmd = tournament.CreateTournament(
            name="Test",
            buy_in=100,
            starting_stack=0,
            max_players=100,
            min_players=10,
        )
        with pytest.raises(CommandRejectedError, match="starting_stack must be positive"):
            create_validate(cmd)

    def test_validate_requires_min_players_at_least_2(self) -> None:
        """Validate rejects min_players less than 2."""
        cmd = tournament.CreateTournament(
            name="Test",
            buy_in=100,
            starting_stack=1000,
            max_players=100,
            min_players=1,
        )
        with pytest.raises(CommandRejectedError, match="min_players must be at least 2"):
            create_validate(cmd)

    def test_validate_requires_min_not_exceed_max(self) -> None:
        """Validate rejects min_players > max_players."""
        cmd = tournament.CreateTournament(
            name="Test",
            buy_in=100,
            starting_stack=1000,
            max_players=5,
            min_players=10,
        )
        with pytest.raises(CommandRejectedError, match="min_players cannot exceed"):
            create_validate(cmd)

    def test_compute_creates_event(self) -> None:
        """Compute returns TournamentCreated event."""
        cmd = tournament.CreateTournament(
            name="Test Tournament",
            game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
            buy_in=100,
            starting_stack=1000,
            max_players=100,
            min_players=10,
        )
        event = create_compute(cmd)
        assert event.name == "Test Tournament"
        assert event.buy_in == 100
        assert event.starting_stack == 1000
        assert event.max_players == 100
        assert event.min_players == 10


class TestEnrollPlayer:
    """Tests for EnrollPlayer handler."""

    def test_guard_rejects_nonexistent_tournament(self) -> None:
        """Guard rejects if tournament doesn't exist."""
        state = TournamentState()
        with pytest.raises(CommandRejectedError, match="does not exist"):
            enroll_guard(state)

    def test_validate_requires_player_root(self) -> None:
        """Validate rejects empty player_root."""
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
            max_players=100,
        )
        cmd = tournament.EnrollPlayer(player_root=b"")
        reason = enroll_validate(cmd, state)
        assert reason == "player_root is required"

    def test_validate_requires_registration_open(self) -> None:
        """Validate rejects if registration not open."""
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_CREATED,
            max_players=100,
        )
        cmd = tournament.EnrollPlayer(player_root=b"player123")
        reason = enroll_validate(cmd, state)
        assert reason == "Registration is not open"

    def test_validate_rejects_full_tournament(self) -> None:
        """Validate rejects if tournament is full."""
        from state import PlayerRegistration

        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
            max_players=1,
            registered_players={"abc": PlayerRegistration()},
        )
        cmd = tournament.EnrollPlayer(player_root=b"newplayer")
        reason = enroll_validate(cmd, state)
        assert reason == "Tournament is full"

    def test_validate_rejects_duplicate_registration(self) -> None:
        """Validate rejects if player already registered."""
        from state import PlayerRegistration

        player_root = b"player123"
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
            max_players=100,
            registered_players={player_root.hex(): PlayerRegistration()},
        )
        cmd = tournament.EnrollPlayer(player_root=player_root)
        reason = enroll_validate(cmd, state)
        assert reason == "Player is already registered"

    def test_validate_accepts_valid_enrollment(self) -> None:
        """Validate accepts valid enrollment."""
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
            max_players=100,
        )
        cmd = tournament.EnrollPlayer(player_root=b"newplayer")
        reason = enroll_validate(cmd, state)
        assert reason is None


class TestRebuy:
    """Tests for ProcessRebuy handler."""

    def test_validate_requires_player_registered(self) -> None:
        """Validate rejects if player not registered."""
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_RUNNING,
        )
        cmd = tournament.ProcessRebuy(player_root=b"unknown")
        reason = rebuy_validate(cmd, state)
        assert reason == "Player is not registered"

    def test_validate_rejects_if_rebuy_not_allowed(self) -> None:
        """Validate rejects if rebuy not configured."""
        from state import PlayerRegistration

        player_root = b"player123"
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_RUNNING,
            rebuy_config=None,  # No rebuy config
            registered_players={player_root.hex(): PlayerRegistration()},
        )
        cmd = tournament.ProcessRebuy(player_root=player_root)
        reason = rebuy_validate(cmd, state)
        assert reason == "Rebuy not allowed"


class TestOpenRegistration:
    """Tests for OpenRegistration handler."""

    def test_guard_rejects_nonexistent_tournament(self) -> None:
        """Guard rejects if tournament doesn't exist."""
        state = TournamentState()
        with pytest.raises(CommandRejectedError, match="does not exist"):
            open_registration_guard(state)

    def test_guard_rejects_already_open(self) -> None:
        """Guard rejects if registration already open."""
        state = TournamentState(
            tournament_id="test",
            status=tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
        )
        with pytest.raises(CommandRejectedError, match="already open"):
            open_registration_guard(state)
