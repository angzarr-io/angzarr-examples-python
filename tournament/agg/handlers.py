"""Tournament aggregate command handlers - functional pattern.

This implements the tournament aggregate using the guard/validate/compute pattern.
All handlers are pure functions that take command, state, and sequence,
returning events to be persisted.

Handler signature (decorated):
    handler(cmd: ConcreteCommand, state: TournamentState, seq: int) -> Event

The decorator auto-unpacks the command and packs the returned event.
"""

from state import TournamentState

from angzarr_client import command_handler, now
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import tournament_pb2 as tournament


# --- CreateTournament ---


def create_guard(state: TournamentState) -> None:
    """Guard: Tournament must not exist."""
    if state.exists:
        raise CommandRejectedError("Tournament already exists")


def create_validate(cmd: tournament.CreateTournament) -> None:
    """Validate CreateTournament command."""
    if not cmd.name:
        raise CommandRejectedError("name is required")
    if cmd.buy_in <= 0:
        raise CommandRejectedError("buy_in must be positive")
    if cmd.starting_stack <= 0:
        raise CommandRejectedError("starting_stack must be positive")
    if cmd.max_players < 2:
        raise CommandRejectedError("max_players must be at least 2")
    if cmd.min_players < 2:
        raise CommandRejectedError("min_players must be at least 2")
    if cmd.min_players > cmd.max_players:
        raise CommandRejectedError("min_players cannot exceed max_players")


def create_compute(cmd: tournament.CreateTournament) -> tournament.TournamentCreated:
    """Compute TournamentCreated event."""
    return tournament.TournamentCreated(
        name=cmd.name,
        game_variant=cmd.game_variant,
        buy_in=cmd.buy_in,
        starting_stack=cmd.starting_stack,
        max_players=cmd.max_players,
        min_players=cmd.min_players,
        scheduled_start=cmd.scheduled_start,
        rebuy_config=cmd.rebuy_config if cmd.HasField("rebuy_config") else None,
        addon_config=cmd.addon_config if cmd.HasField("addon_config") else None,
        blind_structure=cmd.blind_structure,
        created_at=now(),
    )


@command_handler(tournament.CreateTournament)
def handle_create_tournament(
    cmd: tournament.CreateTournament,
    state: TournamentState,
    seq: int,
) -> tournament.TournamentCreated:
    """Handle CreateTournament command."""
    create_guard(state)
    create_validate(cmd)
    return create_compute(cmd)


# --- OpenRegistration ---


def open_registration_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and not already open."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if state.is_registration_open:
        raise CommandRejectedError("Registration is already open")


@command_handler(tournament.OpenRegistration)
def handle_open_registration(
    cmd: tournament.OpenRegistration,
    state: TournamentState,
    seq: int,
) -> tournament.RegistrationOpened:
    """Handle OpenRegistration command."""
    open_registration_guard(state)
    return tournament.RegistrationOpened(opened_at=now())


# --- CloseRegistration ---


def close_registration_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and registration must be open."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_registration_open:
        raise CommandRejectedError("Registration is not open")


@command_handler(tournament.CloseRegistration)
def handle_close_registration(
    cmd: tournament.CloseRegistration,
    state: TournamentState,
    seq: int,
) -> tournament.RegistrationClosed:
    """Handle CloseRegistration command."""
    close_registration_guard(state)
    return tournament.RegistrationClosed(closed_at=now())


# --- EnrollPlayer ---


def enroll_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")


def enroll_validate(
    cmd: tournament.EnrollPlayer, state: TournamentState
) -> str | None:
    """Validate enrollment. Returns rejection reason or None if valid."""
    if not cmd.player_root:
        return "player_root is required"
    if not state.is_registration_open:
        return "Registration is not open"
    if not state.has_capacity():
        return "Tournament is full"
    player_root_hex = cmd.player_root.hex()
    if state.is_player_registered(player_root_hex):
        return "Player is already registered"
    return None


@command_handler(tournament.EnrollPlayer)
def handle_enroll_player(
    cmd: tournament.EnrollPlayer,
    state: TournamentState,
    seq: int,
) -> tournament.TournamentPlayerEnrolled | tournament.TournamentEnrollmentRejected:
    """Handle EnrollPlayer command."""
    enroll_guard(state)

    rejection_reason = enroll_validate(cmd, state)
    if rejection_reason is not None:
        return tournament.TournamentEnrollmentRejected(
            player_root=cmd.player_root,
            reservation_id=cmd.reservation_id,
            reason=rejection_reason,
            rejected_at=now(),
        )

    return tournament.TournamentPlayerEnrolled(
        player_root=cmd.player_root,
        reservation_id=cmd.reservation_id,
        fee_paid=state.buy_in,
        starting_stack=state.starting_stack,
        registration_number=len(state.registered_players) + 1,
        enrolled_at=now(),
    )


# --- ProcessRebuy ---


def rebuy_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and be running."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_running:
        raise CommandRejectedError("Tournament is not running")


def rebuy_validate(
    cmd: tournament.ProcessRebuy, state: TournamentState
) -> str | None:
    """Validate rebuy. Returns rejection reason or None if valid."""
    if not cmd.player_root:
        return "player_root is required"
    player_root_hex = cmd.player_root.hex()
    if not state.is_player_registered(player_root_hex):
        return "Player is not registered"
    if not state.can_rebuy(player_root_hex):
        return "Rebuy not allowed"
    return None


@command_handler(tournament.ProcessRebuy)
def handle_process_rebuy(
    cmd: tournament.ProcessRebuy,
    state: TournamentState,
    seq: int,
) -> tournament.RebuyProcessed | tournament.RebuyDenied:
    """Handle ProcessRebuy command."""
    rebuy_guard(state)

    player_root_hex = cmd.player_root.hex()
    rejection_reason = rebuy_validate(cmd, state)

    if rejection_reason is not None:
        return tournament.RebuyDenied(
            player_root=cmd.player_root,
            reason=rejection_reason,
            denied_at=now(),
        )

    registration = state.registered_players.get(player_root_hex)
    rebuy_count = (registration.rebuys_used + 1) if registration else 1
    rebuy_cost = state.rebuy_config.rebuy_cost if state.rebuy_config else state.buy_in

    return tournament.RebuyProcessed(
        player_root=cmd.player_root,
        rebuy_count=rebuy_count,
        rebuy_cost=rebuy_cost,
        new_stack=state.starting_stack,
        processed_at=now(),
    )


# --- AdvanceBlindLevel ---


def advance_blind_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and be running."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_running:
        raise CommandRejectedError("Tournament is not running")


@command_handler(tournament.AdvanceBlindLevel)
def handle_advance_blind_level(
    cmd: tournament.AdvanceBlindLevel,
    state: TournamentState,
    seq: int,
) -> tournament.BlindLevelAdvanced:
    """Handle AdvanceBlindLevel command."""
    advance_blind_guard(state)

    new_level = state.current_level + 1
    # Get blind values from structure if available
    small_blind = 0
    big_blind = 0
    ante = 0
    if new_level <= len(state.blind_structure):
        level_config = state.blind_structure[new_level - 1]
        small_blind = level_config.small_blind
        big_blind = level_config.big_blind
        ante = level_config.ante

    return tournament.BlindLevelAdvanced(
        level=new_level,
        small_blind=small_blind,
        big_blind=big_blind,
        ante=ante,
        advanced_at=now(),
    )


# --- EliminatePlayer ---


def eliminate_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and be running."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_running:
        raise CommandRejectedError("Tournament is not running")


def eliminate_validate(
    cmd: tournament.EliminatePlayer, state: TournamentState
) -> None:
    """Validate EliminatePlayer command."""
    if not cmd.player_root:
        raise CommandRejectedError("player_root is required")
    player_root_hex = cmd.player_root.hex()
    if not state.is_player_registered(player_root_hex):
        raise CommandRejectedError("Player is not registered")


@command_handler(tournament.EliminatePlayer)
def handle_eliminate_player(
    cmd: tournament.EliminatePlayer,
    state: TournamentState,
    seq: int,
) -> tournament.PlayerEliminated:
    """Handle EliminatePlayer command."""
    eliminate_guard(state)
    eliminate_validate(cmd, state)

    finish_position = state.players_remaining

    return tournament.PlayerEliminated(
        player_root=cmd.player_root,
        finish_position=finish_position,
        payout=0,  # TODO: Calculate based on prize structure
        eliminated_at=now(),
    )


# --- PauseTournament ---


def pause_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and be running."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_running:
        raise CommandRejectedError("Tournament is not running")


@command_handler(tournament.PauseTournament)
def handle_pause_tournament(
    cmd: tournament.PauseTournament,
    state: TournamentState,
    seq: int,
) -> tournament.TournamentPaused:
    """Handle PauseTournament command."""
    pause_guard(state)
    return tournament.TournamentPaused(
        reason=cmd.reason,
        paused_at=now(),
    )


# --- ResumeTournament ---


def resume_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and be paused."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if state.status != tournament.TournamentStatus.TOURNAMENT_PAUSED:
        raise CommandRejectedError("Tournament is not paused")


@command_handler(tournament.ResumeTournament)
def handle_resume_tournament(
    cmd: tournament.ResumeTournament,
    state: TournamentState,
    seq: int,
) -> tournament.TournamentResumed:
    """Handle ResumeTournament command."""
    resume_guard(state)
    return tournament.TournamentResumed(resumed_at=now())


# --- StartTournament ---


def start_guard(state: TournamentState) -> None:
    """Guard: Tournament must exist and have enough players."""
    if not state.exists:
        raise CommandRejectedError("Tournament does not exist")
    if not state.is_registration_open:
        raise CommandRejectedError("Registration is not open")
    if len(state.registered_players) < state.min_players:
        raise CommandRejectedError("Not enough players to start")


@command_handler(tournament.StartTournament)
def handle_start_tournament(
    cmd: tournament.StartTournament,
    state: TournamentState,
    seq: int,
) -> tournament.TournamentStarted:
    """Handle StartTournament command."""
    start_guard(state)
    return tournament.TournamentStarted(
        total_entries=len(state.registered_players),
        total_prize_pool=state.total_prize_pool,
        started_at=now(),
    )
