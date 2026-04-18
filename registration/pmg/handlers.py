"""Registration PM handlers.

Coordinates registration flows across Player <-> Tournament:

1. Player emits ``RegistrationRequested``
2. PM synchronously queries Tournament state via ``QueryClient`` and
   validates: registration open, tournament not full, player not already
   registered.
3. If validation fails: emit ``RegistrationFailed`` with a failure code and
   no outbound commands.
4. If validation passes: emit ``EnrollPlayer`` command to Tournament and
   ``RegistrationInitiated`` process event. The emitted command is
   dispatched under ``SYNC_MODE_DECISION`` so a downstream reject surfaces
   synchronously and the PM can compensate on the next event cycle.
5. Later, Tournament emits ``TournamentPlayerEnrolled`` → PM emits
   ``ConfirmRegistrationFee`` / ``RegistrationCompleted``; or
   ``TournamentEnrollmentRejected`` → PM emits ``ReleaseRegistrationFee`` /
   ``RegistrationFailed``.
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
from tournament_state import TournamentStateHelper, tournament_state_from_event_book


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(
    domain: str, root: bytes, cmd, sequence: int = 0
) -> types.CommandBook:
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


def _fetch_tournament_state(
    query_client, tournament_root: bytes
) -> TournamentStateHelper:
    if query_client is None or not tournament_root:
        return TournamentStateHelper()
    try:
        book = query_client.query("tournament", tournament_root).get_event_book()
    except Exception:
        return TournamentStateHelper()
    return tournament_state_from_event_book(book)


def _fail(
    reservation_id: bytes,
    player_root: bytes,
    tournament_root: bytes,
    code: str,
    message: str,
    phase: str,
) -> ProcessManagerResponse:
    failed = registration.RegistrationFailed(
        player_root=player_root,
        tournament_root=tournament_root,
        reservation_id=reservation_id,
        failure=orch.OrchestrationFailure(
            code=code,
            message=message,
            failed_at_phase=phase,
            failed_at=now(),
        ),
    )
    return ProcessManagerResponse(
        process_events=_event_book("registration", reservation_id, failed),
    )


@process_manager(
    name="pmg-registration",
    pm_domain="registration",
    sources=["player", "tournament"],
    targets=["tournament", "player"],
    state=RegistrationState,
)
class RegistrationPM:
    """Registration process manager.

    Coordinates registration between Player and Tournament aggregates. The
    PM pre-validates against queried Tournament state (``registration_open``,
    capacity, already-registered) and emits ``EnrollPlayer`` for dispatch
    under ``SYNC_MODE_DECISION`` on pass or ``RegistrationFailed`` on fail.
    """

    def __init__(self, query_client=None):
        self.query = query_client

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

    @handles(registration.RegistrationRequested)
    def handle_registration_requested(
        self,
        event: registration.RegistrationRequested,
        state: RegistrationState,
        destinations: Destinations,
        source_cover: types.Cover = None,
    ) -> ProcessManagerResponse:
        """Handle RegistrationRequested from Player domain.

        Pre-validates against live Tournament state queried synchronously;
        emits ``EnrollPlayer`` on pass or ``RegistrationFailed`` on fail.
        """
        player_root = (
            source_cover.root.value if source_cover is not None else state.player_root
        )
        fee = event.fee.amount if event.HasField("fee") else 0
        reservation_id = event.reservation_id
        tournament_root = event.tournament_root

        tour_state = _fetch_tournament_state(self.query, tournament_root)

        # Only enforce state-based validation when the helper was seeded
        # from an actual TournamentCreated event.
        if tour_state.max_players > 0:
            if not tour_state.registration_open:
                return _fail(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "REGISTRATION_CLOSED",
                    "tournament is not accepting registrations",
                    "VALIDATING",
                )
            if tour_state.registered_count >= tour_state.max_players:
                return _fail(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "REGISTRATION_CLOSED",
                    "tournament is full",
                    "VALIDATING",
                )
            if player_root and player_root.hex() in tour_state.registered_players:
                return _fail(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "ALREADY_REGISTERED",
                    "player is already registered",
                    "VALIDATING",
                )

        initiated = registration.RegistrationInitiated(
            player_root=player_root,
            tournament_root=tournament_root,
            reservation_id=reservation_id,
            fee=poker.Currency(amount=fee, currency_code="USD"),
            phase=orch.RegistrationPhase.REGISTRATION_ENROLLING,
            initiated_at=now(),
        )

        enroll = tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
        )

        cmd_book = _command_book(
            "tournament",
            tournament_root,
            enroll,
            _seq(destinations, "tournament"),
        )

        pe_book = _event_book("registration", reservation_id, initiated)

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
