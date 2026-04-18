"""Unit tests for tournament aggregate handlers."""

import pytest

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import tournament_pb2 as tournament

from .handlers import Tournament


def _make_valid_create_cmd(**overrides):
    """Helper to build a valid CreateTournament command."""
    defaults = dict(
        name="Test Tournament",
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=100,
        starting_stack=1000,
        max_players=100,
        min_players=10,
    )
    defaults.update(overrides)
    return tournament.CreateTournament(**defaults)


def _make_tournament_with_registration():
    """Create a tournament with registration open."""
    t = Tournament()
    t.handle_create_tournament(_make_valid_create_cmd())
    t.handle_open_registration(tournament.OpenRegistration())
    return t


class TestCreateTournament:
    """Tests for handle_create_tournament."""

    def test_create_tournament(self) -> None:
        """Create a tournament successfully."""
        t = Tournament()
        event = t.handle_create_tournament(_make_valid_create_cmd())
        assert t.exists
        assert event.name == "Test Tournament"
        assert event.buy_in == 100
        assert event.starting_stack == 1000

    def test_rejects_existing_tournament(self) -> None:
        """Cannot create tournament that already exists."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd())
        with pytest.raises(CommandRejectedError, match="already exists"):
            t.handle_create_tournament(_make_valid_create_cmd())

    def test_requires_name(self) -> None:
        """Name is required."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="name is required"):
            t.handle_create_tournament(_make_valid_create_cmd(name=""))

    def test_requires_positive_buy_in(self) -> None:
        """buy_in must be positive."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="buy_in must be positive"):
            t.handle_create_tournament(_make_valid_create_cmd(buy_in=0))

    def test_requires_positive_starting_stack(self) -> None:
        """starting_stack must be positive."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="starting_stack must be positive"):
            t.handle_create_tournament(_make_valid_create_cmd(starting_stack=0))

    def test_requires_min_players_at_least_2(self) -> None:
        """min_players must be at least 2."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="min_players must be at least 2"):
            t.handle_create_tournament(_make_valid_create_cmd(min_players=1))

    def test_min_players_cannot_exceed_max(self) -> None:
        """min_players cannot exceed max_players."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="min_players cannot exceed"):
            t.handle_create_tournament(
                _make_valid_create_cmd(max_players=5, min_players=10)
            )


class TestOpenRegistration:
    """Tests for handle_open_registration."""

    def test_open_registration(self) -> None:
        """Open registration successfully."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd())
        t.handle_open_registration(tournament.OpenRegistration())
        assert t.is_registration_open

    def test_rejects_nonexistent_tournament(self) -> None:
        """Cannot open registration for nonexistent tournament."""
        t = Tournament()
        with pytest.raises(CommandRejectedError, match="does not exist"):
            t.handle_open_registration(tournament.OpenRegistration())

    def test_rejects_already_open(self) -> None:
        """Cannot open registration that is already open."""
        t = _make_tournament_with_registration()
        with pytest.raises(CommandRejectedError, match="already open"):
            t.handle_open_registration(tournament.OpenRegistration())


class TestCloseRegistration:
    """Tests for handle_close_registration."""

    def test_close_registration(self) -> None:
        """Close registration successfully."""
        t = _make_tournament_with_registration()
        t.handle_close_registration(tournament.CloseRegistration())

    def test_rejects_if_not_open(self) -> None:
        """Cannot close registration that is not open."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd())
        with pytest.raises(CommandRejectedError, match="not open"):
            t.handle_close_registration(tournament.CloseRegistration())


class TestEnrollPlayer:
    """Tests for handle_enroll_player."""

    def test_enroll_player(self) -> None:
        """Enroll a player successfully."""
        t = _make_tournament_with_registration()
        event = t.handle_enroll_player(
            tournament.EnrollPlayer(player_root=b"player1", reservation_id=b"res1")
        )
        assert isinstance(event, tournament.TournamentPlayerEnrolled)
        assert event.player_root == b"player1"
        assert event.fee_paid == 100

    def test_rejects_empty_player_root(self) -> None:
        """Rejects enrollment with empty player_root."""
        t = _make_tournament_with_registration()
        event = t.handle_enroll_player(tournament.EnrollPlayer(player_root=b""))
        assert isinstance(event, tournament.TournamentEnrollmentRejected)
        assert "player_root" in event.reason

    def test_rejects_if_registration_not_open(self) -> None:
        """Rejects if registration is not open."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd())
        event = t.handle_enroll_player(
            tournament.EnrollPlayer(player_root=b"player1")
        )
        assert isinstance(event, tournament.TournamentEnrollmentRejected)
        assert "not open" in event.reason

    def test_rejects_full_tournament(self) -> None:
        """Rejects when tournament is full."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd(max_players=2, min_players=2))
        t.handle_open_registration(tournament.OpenRegistration())
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p1"))
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p2"))
        event = t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p3"))
        assert isinstance(event, tournament.TournamentEnrollmentRejected)
        assert "full" in event.reason

    def test_rejects_duplicate_registration(self) -> None:
        """Rejects duplicate player registration."""
        t = _make_tournament_with_registration()
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"player1"))
        event = t.handle_enroll_player(
            tournament.EnrollPlayer(player_root=b"player1")
        )
        assert isinstance(event, tournament.TournamentEnrollmentRejected)
        assert "already registered" in event.reason


class TestProcessRebuy:
    """Tests for handle_process_rebuy."""

    def test_rejects_if_not_running(self) -> None:
        """Cannot rebuy if tournament not running."""
        t = _make_tournament_with_registration()
        with pytest.raises(CommandRejectedError, match="not running"):
            t.handle_process_rebuy(tournament.ProcessRebuy(player_root=b"p1"))

    def test_rejects_unregistered_player(self) -> None:
        """Rebuy denied for unregistered player."""
        t = _make_tournament_with_registration()
        for i in range(10):
            t.handle_enroll_player(
                tournament.EnrollPlayer(player_root=f"p{i}".encode())
            )
        t.handle_start_tournament(tournament.StartTournament())
        event = t.handle_process_rebuy(
            tournament.ProcessRebuy(player_root=b"unknown")
        )
        assert isinstance(event, tournament.RebuyDenied)
        assert "not registered" in event.reason


class TestEliminatePlayer:
    """Tests for handle_eliminate_player."""

    def test_rejects_if_not_running(self) -> None:
        """Cannot eliminate if tournament not running."""
        t = _make_tournament_with_registration()
        with pytest.raises(CommandRejectedError, match="not running"):
            t.handle_eliminate_player(
                tournament.EliminatePlayer(player_root=b"p1")
            )


class TestPauseResume:
    """Tests for handle_pause_tournament and handle_resume_tournament."""

    def test_pause_rejects_if_not_running(self) -> None:
        """Cannot pause if tournament not running."""
        t = _make_tournament_with_registration()
        with pytest.raises(CommandRejectedError, match="not running"):
            t.handle_pause_tournament(tournament.PauseTournament(reason="break"))

    def test_resume_rejects_if_not_paused(self) -> None:
        """Cannot resume if tournament not paused."""
        t = _make_tournament_with_registration()
        with pytest.raises(CommandRejectedError, match="not paused"):
            t.handle_resume_tournament(tournament.ResumeTournament())


class TestStartTournament:
    """Tests for handle_start_tournament."""

    def test_start_tournament(self) -> None:
        """Start a tournament with enough players."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd(min_players=2, max_players=10))
        t.handle_open_registration(tournament.OpenRegistration())
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p1"))
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p2"))
        event = t.handle_start_tournament(tournament.StartTournament())
        assert t.is_running
        assert event.total_players == 2

    def test_rejects_not_enough_players(self) -> None:
        """Cannot start without enough players."""
        t = Tournament()
        t.handle_create_tournament(_make_valid_create_cmd(min_players=2, max_players=10))
        t.handle_open_registration(tournament.OpenRegistration())
        t.handle_enroll_player(tournament.EnrollPlayer(player_root=b"p1"))
        with pytest.raises(CommandRejectedError, match="Not enough players"):
            t.handle_start_tournament(tournament.StartTournament())
