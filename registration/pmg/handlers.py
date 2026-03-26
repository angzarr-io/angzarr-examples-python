"""Registration PM handlers.

Coordinates registration flows across Player <-> Tournament:
1. Player emits RegistrationRequested
2. PM validates Tournament state (registration open, not full, player not already registered)
3. PM emits EnrollPlayer to Tournament
4. Tournament emits TournamentPlayerEnrolled or TournamentEnrollmentRejected
5. PM emits ConfirmRegistrationFee or ReleaseRegistrationFee to Player
"""

from angzarr_client import now
from angzarr_client.process_manager import (
    ProcessManager,
    applies,
    handles,
    output_domain,
    prepares,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import RegistrationState
from tournament_state import TournamentStateHelper, tournament_state_router


class RegistrationPM(ProcessManager[RegistrationState]):
    """Registration process manager.

    Coordinates the registration flow between Player and Tournament aggregates.
    """

    name = "pmg-registration"

    # Register StateRouters for destination domains
    # Handlers with dict[str, ...] type hints receive auto-rebuilt state
    _destination_routers = {
        "tournament": tournament_state_router,
    }

    def _create_empty_state(self) -> RegistrationState:
        return RegistrationState()

    # --- State appliers ---

    @applies(registration.RegistrationInitiated)
    def apply_initiated(
        self, state: RegistrationState, event: registration.RegistrationInitiated
    ) -> None:
        state.phase = event.phase
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root

    @applies(registration.RegistrationPhaseChanged)
    def apply_phase_changed(
        self, state: RegistrationState, event: registration.RegistrationPhaseChanged
    ) -> None:
        state.phase = event.to_phase

    @applies(registration.RegistrationCompleted)
    def apply_completed(
        self, state: RegistrationState, event: registration.RegistrationCompleted
    ) -> None:
        state.phase = orch.RegistrationPhase.REGISTRATION_COMPLETED
        state.starting_stack = event.starting_stack

    @applies(registration.RegistrationFailed)
    def apply_failed(
        self, state: RegistrationState, _event: registration.RegistrationFailed
    ) -> None:
        state.phase = orch.RegistrationPhase.REGISTRATION_FAILED

    # --- Prepare handlers ---

    @prepares(registration.RegistrationRequested)
    def prepare_registration_requested(
        self, event: registration.RegistrationRequested
    ) -> list[types.Cover]:
        """RegistrationRequested from Player -> need Tournament state."""
        return [
            types.Cover(
                domain="tournament",
                root=types.UUID(value=event.tournament_root),
            ),
        ]

    @prepares(tournament.TournamentPlayerEnrolled)
    def prepare_player_enrolled(
        self, event: tournament.TournamentPlayerEnrolled
    ) -> list[types.Cover]:
        """TournamentPlayerEnrolled from Tournament -> need Player state."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            ),
        ]

    @prepares(tournament.TournamentEnrollmentRejected)
    def prepare_enrollment_rejected(
        self, event: tournament.TournamentEnrollmentRejected
    ) -> list[types.Cover]:
        """TournamentEnrollmentRejected from Tournament -> need Player state."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            ),
        ]

    # --- Event handlers ---

    @output_domain("tournament")
    @handles(registration.RegistrationRequested, input_domain="player")
    def handle_registration_requested(
        self,
        event: registration.RegistrationRequested,
        destinations: dict[str, TournamentStateHelper],
        root: bytes,
    ) -> tournament.EnrollPlayer | None:
        """Handle RegistrationRequested from Player domain.

        Validates Tournament state and emits EnrollPlayer if valid.

        Args:
            event: The RegistrationRequested event
            destinations: Rebuilt destination states by domain (auto-built via StateRouter)
            root: The player_root from the trigger's Cover
        """
        tournament_state = destinations.get("tournament")
        if tournament_state is None:
            self._emit_failure(
                root,
                event.tournament_root,
                event.reservation_id,
                "MISSING_DESTINATIONS",
                "Missing tournament destination",
            )
            return None

        player_root = root

        # Validate registration is open
        if not tournament_state.registration_open:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "REGISTRATION_CLOSED",
                "Tournament registration is closed",
            )
            return None

        # Validate tournament is not full
        if (
            tournament_state.max_players > 0
            and tournament_state.registered_count >= tournament_state.max_players
        ):
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "TOURNAMENT_FULL",
                f"Tournament is full ({tournament_state.max_players} players)",
            )
            return None

        # Validate player is not already registered
        player_hex = player_root.hex()
        if player_hex in tournament_state.registered_players:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "ALREADY_REGISTERED",
                "Player is already registered for this tournament",
            )
            return None

        # Emit PM event for tracking
        fee = event.fee.amount if event.HasField("fee") else 0
        self._apply_and_record(
            registration.RegistrationInitiated(
                player_root=player_root,
                tournament_root=event.tournament_root,
                reservation_id=event.reservation_id,
                fee=poker.Currency(amount=fee, currency_code="USD"),
                phase=orch.RegistrationPhase.REGISTRATION_ENROLLING,
                initiated_at=now(),
            )
        )

        # Return EnrollPlayer command to Tournament
        return tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=event.reservation_id,
        )

    @output_domain("player")
    @handles(tournament.TournamentPlayerEnrolled, input_domain="tournament")
    def handle_player_enrolled(
        self,
        event: tournament.TournamentPlayerEnrolled,
        destinations: list[types.EventBook],
    ) -> registration.ConfirmRegistrationFee:
        """Handle TournamentPlayerEnrolled from Tournament domain.

        Emits ConfirmRegistrationFee to Player.
        """
        # Emit PM completion event
        self._apply_and_record(
            registration.RegistrationCompleted(
                player_root=event.player_root,
                tournament_root=self.state.tournament_root,
                reservation_id=event.reservation_id,
                fee=poker.Currency(amount=self.state.fee, currency_code="USD"),
                starting_stack=event.starting_stack,
                completed_at=now(),
            )
        )

        return registration.ConfirmRegistrationFee(
            reservation_id=event.reservation_id,
        )

    @output_domain("player")
    @handles(tournament.TournamentEnrollmentRejected, input_domain="tournament")
    def handle_enrollment_rejected(
        self,
        event: tournament.TournamentEnrollmentRejected,
        destinations: list[types.EventBook],
    ) -> registration.ReleaseRegistrationFee:
        """Handle TournamentEnrollmentRejected from Tournament domain.

        Emits ReleaseRegistrationFee to Player.
        """
        # Emit PM failure event
        self._apply_and_record(
            registration.RegistrationFailed(
                player_root=event.player_root,
                tournament_root=self.state.tournament_root,
                reservation_id=event.reservation_id,
                failure=orch.OrchestrationFailure(
                    code="ENROLLMENT_REJECTED",
                    message=event.reason,
                    failed_at_phase="ENROLLING",
                    failed_at=now(),
                ),
            )
        )

        return registration.ReleaseRegistrationFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

    def _emit_failure(
        self,
        player_root: bytes,
        tournament_root: bytes,
        reservation_id: bytes,
        code: str,
        message: str,
    ) -> None:
        """Record a failure event (no commands)."""
        self._apply_and_record(
            registration.RegistrationFailed(
                player_root=player_root,
                tournament_root=tournament_root,
                reservation_id=reservation_id,
                failure=orch.OrchestrationFailure(
                    code=code,
                    message=message,
                    failed_at_phase="VALIDATION",
                    failed_at=now(),
                ),
            )
        )
