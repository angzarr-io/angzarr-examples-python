"""Registration PM handlers.

Coordinates registration flows across Player <-> Tournament:
1. Player emits RegistrationRequested
2. PM emits EnrollPlayer to Tournament (aggregate validates)
3. Tournament emits TournamentPlayerEnrolled or TournamentEnrollmentRejected
4. PM emits ConfirmRegistrationFee or ReleaseRegistrationFee to Player
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import (
    Destinations,
    ProcessManagerResponse,
    applies,
    handles,
    now,
    process_manager,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import RegistrationState


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(domain: str, root: bytes, cmd, sequence: int = 0) -> types.CommandBook:
    return types.CommandBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.CommandPage(
                header=types.PageHeader(sequence=sequence),
                command=_pack(cmd),
            )
        ],
    )


def _event_book(domain: str, root: bytes, event) -> types.EventBook:
    return types.EventBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.EventPage(event=_pack(event)),
        ],
    )


def _seq(destinations: Destinations | None, domain: str) -> int:
    if destinations is None:
        return 0
    seq = destinations.sequence_for(domain)
    return seq if seq is not None else 0


@process_manager(
    name="pmg-registration",
    pm_domain="registration",
    sources=["player", "tournament"],
    targets=["tournament", "player"],
    state=RegistrationState,
)
class RegistrationPM:
    """Registration process manager.

    Coordinates the registration flow between Player and Tournament aggregates.
    Validation (registration open, tournament full, player already registered)
    belongs in the Tournament aggregate — this PM just translates events to
    commands and handles rejection via Tournament's reject events.
    """

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

    # --- Event handlers ---

    # TODO(pm-source-context): new Router API doesn't expose source cover root
    # to handlers. Callers must seed state.player_root (or include player_root
    # in the event payload).
    @handles(registration.RegistrationRequested)
    def handle_registration_requested(
        self,
        event: registration.RegistrationRequested,
        state: RegistrationState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle RegistrationRequested from Player domain.

        Emits EnrollPlayer to Tournament - Tournament aggregate validates
        registration-open, tournament-full, and already-registered checks.
        """
        player_root = state.player_root
        fee = event.fee.amount if event.HasField("fee") else 0

        initiated = registration.RegistrationInitiated(
            player_root=player_root,
            tournament_root=event.tournament_root,
            reservation_id=event.reservation_id,
            fee=poker.Currency(amount=fee, currency_code="USD"),
            phase=orch.RegistrationPhase.REGISTRATION_ENROLLING,
            initiated_at=now(),
        )

        enroll = tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=event.reservation_id,
        )

        cmd_book = _command_book(
            "tournament",
            event.tournament_root,
            enroll,
            _seq(destinations, "tournament"),
        )

        pe_book = _event_book("registration", event.reservation_id, initiated)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(tournament.TournamentPlayerEnrolled)
    def handle_player_enrolled(
        self,
        event: tournament.TournamentPlayerEnrolled,
        state: RegistrationState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle TournamentPlayerEnrolled from Tournament domain."""
        completed = registration.RegistrationCompleted(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            fee=poker.Currency(amount=state.fee, currency_code="USD"),
            starting_stack=event.starting_stack,
            completed_at=now(),
        )

        confirm = registration.ConfirmRegistrationFee(
            reservation_id=event.reservation_id,
        )

        cmd_book = _command_book(
            "player", event.player_root, confirm, _seq(destinations, "player")
        )

        pe_book = _event_book("registration", event.reservation_id, completed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(tournament.TournamentEnrollmentRejected)
    def handle_enrollment_rejected(
        self,
        event: tournament.TournamentEnrollmentRejected,
        state: RegistrationState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle TournamentEnrollmentRejected from Tournament domain."""
        failed = registration.RegistrationFailed(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            failure=orch.OrchestrationFailure(
                code="ENROLLMENT_REJECTED",
                message=event.reason,
                failed_at_phase="ENROLLING",
                failed_at=now(),
            ),
        )

        release = registration.ReleaseRegistrationFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

        cmd_book = _command_book(
            "player", event.player_root, release, _seq(destinations, "player")
        )

        pe_book = _event_book("registration", event.reservation_id, failed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )
