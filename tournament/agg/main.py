"""Tournament bounded context gRPC server - functional pattern.

This module implements the tournament aggregate using:
- CommandRouter for command dispatch
- StateRouter for state reconstruction
- @command_handler decorated functions
"""

import structlog
from state import (
    TournamentState,
    apply_blind_advanced,
    apply_completed,
    apply_created,
    apply_enrollment_rejected,
    apply_paused,
    apply_player_eliminated,
    apply_player_enrolled,
    apply_rebuy_denied,
    apply_rebuy_processed,
    apply_registration_closed,
    apply_registration_opened,
    apply_resumed,
    apply_started,
)

from angzarr_client import CommandRouter, StateRouter, run_command_handler_server
from angzarr_client.proto.examples import tournament_pb2 as tournament
from handlers import (
    handle_advance_blind_level,
    handle_close_registration,
    handle_create_tournament,
    handle_eliminate_player,
    handle_enroll_player,
    handle_open_registration,
    handle_pause_tournament,
    handle_process_rebuy,
    handle_resume_tournament,
    handle_start_tournament,
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# State router for event-to-state application
state_router = (
    StateRouter(TournamentState)
    .on(tournament.TournamentCreated, apply_created)
    .on(tournament.RegistrationOpened, apply_registration_opened)
    .on(tournament.RegistrationClosed, apply_registration_closed)
    .on(tournament.TournamentPlayerEnrolled, apply_player_enrolled)
    .on(tournament.TournamentEnrollmentRejected, apply_enrollment_rejected)
    .on(tournament.RebuyProcessed, apply_rebuy_processed)
    .on(tournament.RebuyDenied, apply_rebuy_denied)
    .on(tournament.BlindLevelAdvanced, apply_blind_advanced)
    .on(tournament.PlayerEliminated, apply_player_eliminated)
    .on(tournament.TournamentPaused, apply_paused)
    .on(tournament.TournamentResumed, apply_resumed)
    .on(tournament.TournamentStarted, apply_started)
    .on(tournament.TournamentCompleted, apply_completed)
)

# Command router with state composition
router = (
    CommandRouter[TournamentState]("tournament")
    .with_state(state_router)
    .on(tournament.CreateTournament, handle_create_tournament)
    .on(tournament.OpenRegistration, handle_open_registration)
    .on(tournament.CloseRegistration, handle_close_registration)
    .on(tournament.EnrollPlayer, handle_enroll_player)
    .on(tournament.ProcessRebuy, handle_process_rebuy)
    .on(tournament.AdvanceBlindLevel, handle_advance_blind_level)
    .on(tournament.EliminatePlayer, handle_eliminate_player)
    .on(tournament.PauseTournament, handle_pause_tournament)
    .on(tournament.ResumeTournament, handle_resume_tournament)
    .on(tournament.StartTournament, handle_start_tournament)
)


if __name__ == "__main__":
    run_command_handler_server(router, "50304", logger=logger)
