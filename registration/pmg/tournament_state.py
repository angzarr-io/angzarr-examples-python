"""Tournament state router for Registration PM destination state rebuilding.

This module defines a StateRouter that automatically rebuilds TournamentStateHelper
from EventBooks, eliminating manual rebuild_tournament_state() boilerplate.

Usage in PM:
    class RegistrationPM(ProcessManager[RegistrationState]):
        _destination_routers = {
            "tournament": tournament_state_router,
        }

        @handles(RegistrationRequested, input_domain="player")
        def handle_registration(self, event, destinations: dict[str, TournamentStateHelper], root):
            tournament_state = destinations["tournament"]  # Already rebuilt!
"""

from dataclasses import dataclass, field

from angzarr_client import StateRouter
from angzarr_client.proto.examples import tournament_pb2 as tournament


@dataclass
class TournamentStateHelper:
    """Minimal tournament state for PM validation."""

    status: int = tournament.TournamentStatus.TOURNAMENT_STATUS_UNSPECIFIED
    registration_open: bool = True
    max_players: int = 0
    registered_count: int = 0
    buy_in: int = 0
    starting_stack: int = 0
    registered_players: set[str] = field(default_factory=set)  # hex player roots


# --- State appliers (pure functions) ---


def apply_tournament_created(
    state: TournamentStateHelper, event: tournament.TournamentCreated
) -> None:
    """Apply TournamentCreated event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_CREATED
    state.max_players = event.max_players
    state.buy_in = event.buy_in
    state.starting_stack = event.starting_stack
    state.registration_open = True


def apply_registration_opened(
    state: TournamentStateHelper, event: tournament.RegistrationOpened
) -> None:
    """Apply RegistrationOpened event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_REGISTERING
    state.registration_open = True


def apply_registration_closed(
    state: TournamentStateHelper, event: tournament.RegistrationClosed
) -> None:
    """Apply RegistrationClosed event."""
    state.registration_open = False


def apply_tournament_started(
    state: TournamentStateHelper, event: tournament.TournamentStarted
) -> None:
    """Apply TournamentStarted event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    state.registration_open = False


def apply_player_enrolled(
    state: TournamentStateHelper, event: tournament.TournamentPlayerEnrolled
) -> None:
    """Apply TournamentPlayerEnrolled event."""
    state.registered_players.add(event.player_root.hex())
    state.registered_count = len(state.registered_players)


# --- StateRouter configuration ---

tournament_state_router: StateRouter[TournamentStateHelper] = (
    StateRouter(TournamentStateHelper)
    .on(tournament.TournamentCreated, apply_tournament_created)
    .on(tournament.RegistrationOpened, apply_registration_opened)
    .on(tournament.RegistrationClosed, apply_registration_closed)
    .on(tournament.TournamentStarted, apply_tournament_started)
    .on(tournament.TournamentPlayerEnrolled, apply_player_enrolled)
)
