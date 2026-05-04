"""Reservation PM handlers — single PM for all three lifecycle flavors.

Replaces the former ``buy_in/pmg``, ``rebuy/pmg``, and ``registration/pmg``
PMs. Subscribes to the ``reservation`` topic (where Initiate*/Confirm*/
Release* now originate), plus ``table`` and ``tournament`` for downstream
confirmations. Translates each reservation lifecycle event into the
matching player primitive — ``ReserveFunds`` on request, ``DeductReservedFunds``
on confirm, ``ReleaseFunds`` on release — and coordinates with ``table`` /
``tournament`` for the non-funds side of the flow.

Sync decisioning: the PM queries target-domain state synchronously via
``QueryClient`` (cross-aggregate reads, not destination-state-in-request).
Downstream command dispatch uses ``SYNC_MODE_DECISION`` so a reject
surfaces immediately to the PM for compensation.

Event → action map (Initiate* land on ``reservation`` via separate RPC):

    Buy-in:
      reservation.BuyInRequested        -> player.ReserveFunds
                                           + table.SeatPlayer
      table.PlayerSeated                -> reservation.ConfirmBuyIn
      reservation.BuyInConfirmed        -> player.DeductReservedFunds
      table.SeatingRejected             -> reservation.ReleaseBuyIn
      reservation.BuyInReservationReleased
                                         -> player.ReleaseFunds

    Rebuy:
      reservation.RebuyRequested        -> (query tournament for fee)
                                           + player.ReserveFunds
                                           + tournament.ProcessRebuy
      tournament.RebuyProcessed         -> table.AddRebuyChips
      table.RebuyChipsAdded             -> reservation.ConfirmRebuyFee
      reservation.RebuyFeeConfirmed     -> player.DeductReservedFunds
      tournament.RebuyDenied            -> reservation.ReleaseRebuyFee
      reservation.RebuyFeeReleased      -> player.ReleaseFunds

    Registration:
      reservation.RegistrationRequested -> (query tournament for entry fee)
                                           + player.ReserveFunds
                                           + tournament.EnrollPlayer
      tournament.TournamentPlayerEnrolled
                                         -> reservation.ConfirmRegistrationFee
      reservation.RegistrationFeeConfirmed
                                         -> player.DeductReservedFunds
      tournament.TournamentEnrollmentRejected
                                         -> reservation.ReleaseRegistrationFee
      reservation.RegistrationFeeReleased
                                         -> player.ReleaseFunds
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import (
    Cover,
    Destinations,
    ProcessManagerResponse,
    applies,
    handles,
    now,
    process_manager,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import (
    KIND_BUY_IN,
    KIND_REBUY,
    KIND_REGISTRATION,
    ReservationPMState,
)
from table_state import TableStateHelper, table_state_from_event_book
from tournament_state import (
    TournamentStateHelper,
    tournament_state_from_event_book,
)

PM_DOMAIN = "pmg-reservation"


# -----------------------------------------------------------------------------
# Plumbing helpers
# -----------------------------------------------------------------------------


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(
    domain: str, root: bytes, cmd, sequence: int = 0
) -> types.CommandBook:
    # PM-emitted commands set ``sync_mode = SYNC_MODE_DECISION`` so the
    # PM gets the accept/reject answer synchronously while projectors
    # and sagas still run async. Honoured by the PM coordinator's
    # per-command override path
    # (`core/main/src/orchestration/process_manager/mod.rs`).
    return types.CommandBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.CommandPage(
                header=types.PageHeader(
                    sequence=sequence,
                    sync_mode=types.SYNC_MODE_DECISION,
                ),
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
        pages=[types.EventPage(event=_pack(event))],
    )


def _seq(destinations: Destinations | None, domain: str) -> int:
    if destinations is None:
        return 0
    seq = destinations.sequence_for(domain)
    return seq if seq is not None else 0


def _fetch_table_state(query_client, table_root: bytes) -> TableStateHelper:
    if query_client is None or not table_root:
        return TableStateHelper()
    try:
        book = query_client.query("table", table_root).get_event_book()
    except Exception:
        return TableStateHelper()
    return table_state_from_event_book(book)


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


def _currency(amount: int) -> poker.Currency:
    return poker.Currency(amount=amount, currency_code="CHIPS")


# -----------------------------------------------------------------------------
# Failure envelopes (per-flavor, since each carries a different proto event)
# -----------------------------------------------------------------------------


def _buy_in_failed_event(
    reservation_id: bytes,
    player_root: bytes,
    table_root: bytes,
    code: str,
    message: str,
    phase: str,
) -> buy_in.BuyInFailed:
    return buy_in.BuyInFailed(
        player_root=player_root,
        table_root=table_root,
        reservation_id=reservation_id,
        failure=orch.OrchestrationFailure(
            code=code, message=message, failed_at_phase=phase, failed_at=now()
        ),
    )


def _rebuy_failed_event(
    reservation_id: bytes,
    player_root: bytes,
    tournament_root: bytes,
    code: str,
    message: str,
    phase: str,
) -> rebuy.RebuyFailed:
    return rebuy.RebuyFailed(
        player_root=player_root,
        tournament_root=tournament_root,
        reservation_id=reservation_id,
        failure=orch.OrchestrationFailure(
            code=code, message=message, failed_at_phase=phase, failed_at=now()
        ),
    )


def _registration_failed_event(
    reservation_id: bytes,
    player_root: bytes,
    tournament_root: bytes,
    code: str,
    message: str,
    phase: str,
) -> registration.RegistrationFailed:
    return registration.RegistrationFailed(
        player_root=player_root,
        tournament_root=tournament_root,
        reservation_id=reservation_id,
        failure=orch.OrchestrationFailure(
            code=code, message=message, failed_at_phase=phase, failed_at=now()
        ),
    )


# -----------------------------------------------------------------------------
# PM class
# -----------------------------------------------------------------------------


@process_manager(
    name="pmg-reservation",
    pm_domain=PM_DOMAIN,
    sources=["reservation", "table", "tournament"],
    targets=["player", "reservation", "table", "tournament"],
    state=ReservationPMState,
)
class ReservationPM:
    """Consolidated reservation process manager.

    One PM instance per ``reservation_id``. Drives buy-in, rebuy, and
    tournament-registration flows by translating reservation-aggregate
    lifecycle events into player-fund primitives, and routing downstream
    confirmations / rejections from table and tournament back into the
    reservation aggregate.
    """

    def __init__(self, query_client=None):
        self.query = query_client

    # =========================================================================
    # State appliers — kind is set once on *Initiated and carried through the
    # flow. Completion / failure events don't change kind, just phase.
    # =========================================================================

    @applies(buy_in.BuyInInitiated)
    def _apply_buy_in_initiated(
        self, state: ReservationPMState, event: buy_in.BuyInInitiated
    ) -> None:
        state.kind = KIND_BUY_IN
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.table_root = event.table_root
        state.seat = event.seat
        state.amount = event.amount.amount if event.HasField("amount") else 0
        state.phase = event.phase

    @applies(buy_in.BuyInCompleted)
    def _apply_buy_in_completed(
        self, state: ReservationPMState, _event: buy_in.BuyInCompleted
    ) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_COMPLETED

    @applies(buy_in.BuyInFailed)
    def _apply_buy_in_failed(
        self, state: ReservationPMState, _event: buy_in.BuyInFailed
    ) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_FAILED

    @applies(rebuy.RebuyInitiated)
    def _apply_rebuy_initiated(
        self, state: ReservationPMState, event: rebuy.RebuyInitiated
    ) -> None:
        state.kind = KIND_REBUY
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root
        state.table_root = event.table_root
        state.seat = event.seat
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.phase = event.phase

    @applies(rebuy.RebuyCompleted)
    def _apply_rebuy_completed(
        self, state: ReservationPMState, _event: rebuy.RebuyCompleted
    ) -> None:
        state.phase = orch.RebuyPhase.REBUY_COMPLETED

    @applies(rebuy.RebuyFailed)
    def _apply_rebuy_failed(
        self, state: ReservationPMState, _event: rebuy.RebuyFailed
    ) -> None:
        state.phase = orch.RebuyPhase.REBUY_FAILED

    @applies(registration.RegistrationInitiated)
    def _apply_registration_initiated(
        self,
        state: ReservationPMState,
        event: registration.RegistrationInitiated,
    ) -> None:
        state.kind = KIND_REGISTRATION
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.phase = event.phase

    @applies(registration.RegistrationCompleted)
    def _apply_registration_completed(
        self,
        state: ReservationPMState,
        _event: registration.RegistrationCompleted,
    ) -> None:
        state.phase = orch.RegistrationPhase.REGISTRATION_COMPLETED

    @applies(registration.RegistrationFailed)
    def _apply_registration_failed(
        self,
        state: ReservationPMState,
        _event: registration.RegistrationFailed,
    ) -> None:
        state.phase = orch.RegistrationPhase.REGISTRATION_FAILED

    # =========================================================================
    # Buy-in event handlers
    # =========================================================================

    @handles(buy_in.BuyInRequested)
    def on_buy_in_requested(
        self,
        event: buy_in.BuyInRequested,
        state: ReservationPMState,
        destinations: Destinations,
        source_cover: Cover | None = None,
    ) -> ProcessManagerResponse:
        """Reservation emitted BuyInRequested — reserve player funds and seat."""
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        table_root = event.table_root
        amount = event.amount.amount if event.HasField("amount") else 0

        # Pre-validate against live table state where available.
        tbl = _fetch_table_state(self.query, table_root)
        if tbl.max_players > 0:
            if amount < tbl.min_buy_in:
                return self._fail_buy_in(
                    reservation_id,
                    player_root,
                    table_root,
                    "INVALID_AMOUNT",
                    f"amount {amount} below minimum {tbl.min_buy_in}",
                    "VALIDATING",
                )
            if amount > tbl.max_buy_in:
                return self._fail_buy_in(
                    reservation_id,
                    player_root,
                    table_root,
                    "INVALID_AMOUNT",
                    f"amount {amount} exceeds maximum {tbl.max_buy_in}",
                    "VALIDATING",
                )
            if len(tbl.seats) >= tbl.max_players:
                return self._fail_buy_in(
                    reservation_id,
                    player_root,
                    table_root,
                    "TABLE_FULL",
                    "table has no available seats",
                    "VALIDATING",
                )
            if event.seat in tbl.seats:
                return self._fail_buy_in(
                    reservation_id,
                    player_root,
                    table_root,
                    "SEAT_OCCUPIED",
                    f"seat {event.seat} is occupied",
                    "VALIDATING",
                )

        reserve_cmd = player.ReserveFunds(
            amount=_currency(amount),
            key=table_root,
        )
        seat_cmd = buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=amount,
        )

        initiated = buy_in.BuyInInitiated(
            player_root=player_root,
            table_root=table_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=_currency(amount),
            phase=orch.BuyInPhase.BUY_IN_SEATING,
            initiated_at=now(),
        )

        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player", player_root, reserve_cmd, _seq(destinations, "player")
                ),
                _command_book(
                    "table", table_root, seat_cmd, _seq(destinations, "table")
                ),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, initiated),
        )

    @handles(buy_in.PlayerSeated)
    def on_player_seated(
        self,
        event: buy_in.PlayerSeated,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Table confirmed seating — tell reservation to confirm the buy-in."""
        confirm = buy_in.ConfirmBuyIn(reservation_id=event.reservation_id)
        completed = buy_in.BuyInCompleted(
            player_root=event.player_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            seat=event.seat_position,
            amount=_currency(event.stack),
            completed_at=now(),
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    confirm,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, completed),
        )

    @handles(buy_in.SeatingRejected)
    def on_seating_rejected(
        self,
        event: buy_in.SeatingRejected,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Table rejected seating — tell reservation to release and record failure."""
        release = buy_in.ReleaseBuyIn(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _buy_in_failed_event(
            event.reservation_id,
            event.player_root,
            state.table_root,
            "SEATING_REJECTED",
            event.reason,
            "SEATING",
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    release,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, failed),
        )

    @handles(buy_in.BuyInConfirmed)
    def on_buy_in_confirmed(
        self,
        event: buy_in.BuyInConfirmed,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation confirmed — deduct the reserved funds permanently."""
        amount = event.amount.amount if event.HasField("amount") else state.amount
        deduct = player.DeductReservedFunds(
            amount=_currency(amount),
            key=event.table_root or state.table_root,
            reservation_id=event.reservation_id,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    deduct,
                    _seq(destinations, "player"),
                ),
            ],
        )

    @handles(buy_in.BuyInReservationReleased)
    def on_buy_in_released(
        self,
        event: buy_in.BuyInReservationReleased,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation released — give the player's reserved funds back."""
        release_cmd = player.ReleaseFunds(
            key=event.table_root or state.table_root,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    release_cmd,
                    _seq(destinations, "player"),
                ),
            ],
        )

    # =========================================================================
    # Rebuy event handlers
    # =========================================================================

    @handles(rebuy.RebuyRequested)
    def on_rebuy_requested(
        self,
        event: rebuy.RebuyRequested,
        state: ReservationPMState,
        destinations: Destinations,
        source_cover: Cover | None = None,
    ) -> ProcessManagerResponse:
        """Reservation emitted RebuyRequested — look up fee, reserve, and process."""
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        tournament_root = event.tournament_root
        table_root = event.table_root

        tour = _fetch_tournament_state(self.query, tournament_root)
        tbl = _fetch_table_state(self.query, table_root)

        tournament_loaded = (
            tour.status != tournament.TournamentStatus.TOURNAMENT_STATUS_UNSPECIFIED
        )
        table_loaded = tbl.max_players > 0

        if tournament_loaded:
            running = tour.status == tournament.TournamentStatus.TOURNAMENT_RUNNING
            if not running or not tour.rebuy_allowed:
                return self._fail_rebuy(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "TOURNAMENT_NOT_RUNNING",
                    "tournament is not accepting rebuys",
                    "VALIDATING",
                )

        if table_loaded:
            seated_at = tbl.find_seat_by_player(player_root) if player_root else None
            if seated_at is None or seated_at != event.seat:
                return self._fail_rebuy(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "NOT_SEATED",
                    f"player is not seated at position {event.seat}",
                    "VALIDATING",
                )

        # Fee: prefer tournament config; fall back to event (tests without query).
        fee = tour.rebuy_cost or (event.fee.amount if event.HasField("fee") else 0)

        reserve_cmd = player.ReserveFunds(
            amount=_currency(fee),
            key=table_root,
        )
        process_cmd = tournament.ProcessRebuy(
            player_root=player_root,
            reservation_id=reservation_id,
        )

        initiated = rebuy.RebuyInitiated(
            player_root=player_root,
            tournament_root=tournament_root,
            table_root=table_root,
            reservation_id=reservation_id,
            seat=event.seat,
            fee=_currency(fee),
            chips_to_add=tour.rebuy_chips,
            phase=orch.RebuyPhase.REBUY_APPROVING,
            initiated_at=now(),
        )

        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player", player_root, reserve_cmd, _seq(destinations, "player")
                ),
                _command_book(
                    "tournament",
                    tournament_root,
                    process_cmd,
                    _seq(destinations, "tournament"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, initiated),
        )

    @handles(tournament.RebuyProcessed)
    def on_rebuy_processed(
        self,
        event: tournament.RebuyProcessed,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Tournament approved the rebuy — credit chips at the table."""
        add_chips = rebuy.AddRebuyChips(
            player_root=event.player_root,
            reservation_id=event.reservation_id,
            seat=state.seat,
            amount=event.chips_added,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "table",
                    state.table_root,
                    add_chips,
                    _seq(destinations, "table"),
                ),
            ],
        )

    @handles(rebuy.RebuyChipsAdded)
    def on_rebuy_chips_added(
        self,
        event: rebuy.RebuyChipsAdded,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Table credited chips — close out the reservation on the aggregate."""
        confirm = rebuy.ConfirmRebuyFee(reservation_id=event.reservation_id)
        completed = rebuy.RebuyCompleted(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            fee=_currency(state.fee),
            chips_added=event.amount,
            completed_at=now(),
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    confirm,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, completed),
        )

    @handles(tournament.RebuyDenied)
    def on_rebuy_denied(
        self,
        event: tournament.RebuyDenied,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Tournament denied — release the reservation on the aggregate."""
        release = rebuy.ReleaseRebuyFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _rebuy_failed_event(
            event.reservation_id,
            event.player_root,
            state.tournament_root,
            "REBUY_DENIED",
            event.reason,
            "APPROVING",
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    release,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, failed),
        )

    @handles(rebuy.RebuyFeeConfirmed)
    def on_rebuy_fee_confirmed(
        self,
        event: rebuy.RebuyFeeConfirmed,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation closed the rebuy — deduct reserved funds."""
        fee = event.fee.amount if event.HasField("fee") else state.fee
        deduct = player.DeductReservedFunds(
            amount=_currency(fee),
            key=event.table_root or state.table_root,
            reservation_id=event.reservation_id,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    deduct,
                    _seq(destinations, "player"),
                ),
            ],
        )

    @handles(rebuy.RebuyFeeReleased)
    def on_rebuy_fee_released(
        self,
        event: rebuy.RebuyFeeReleased,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation released — refund the player."""
        release_cmd = player.ReleaseFunds(
            key=event.table_root or state.table_root,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    release_cmd,
                    _seq(destinations, "player"),
                ),
            ],
        )

    # =========================================================================
    # Registration event handlers
    # =========================================================================

    @handles(registration.RegistrationRequested)
    def on_registration_requested(
        self,
        event: registration.RegistrationRequested,
        state: ReservationPMState,
        destinations: Destinations,
        source_cover: Cover | None = None,
    ) -> ProcessManagerResponse:
        """Reservation emitted RegistrationRequested — look up entry fee and enroll."""
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        tournament_root = event.tournament_root

        tour = _fetch_tournament_state(self.query, tournament_root)

        if tour.max_players > 0:
            if not tour.registration_open:
                return self._fail_registration(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "REGISTRATION_CLOSED",
                    "tournament is not accepting registrations",
                    "VALIDATING",
                )
            if tour.registered_count >= tour.max_players:
                return self._fail_registration(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "REGISTRATION_CLOSED",
                    "tournament is full",
                    "VALIDATING",
                )
            if player_root and player_root.hex() in tour.registered_players:
                return self._fail_registration(
                    reservation_id,
                    player_root,
                    tournament_root,
                    "ALREADY_REGISTERED",
                    "player is already registered",
                    "VALIDATING",
                )

        fee = tour.buy_in or (event.fee.amount if event.HasField("fee") else 0)

        reserve_cmd = player.ReserveFunds(
            amount=_currency(fee),
            key=tournament_root,  # registration uses tournament_root as its reservation key
        )
        enroll_cmd = tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
        )

        initiated = registration.RegistrationInitiated(
            player_root=player_root,
            tournament_root=tournament_root,
            reservation_id=reservation_id,
            fee=_currency(fee),
            phase=orch.RegistrationPhase.REGISTRATION_ENROLLING,
            initiated_at=now(),
        )

        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player", player_root, reserve_cmd, _seq(destinations, "player")
                ),
                _command_book(
                    "tournament",
                    tournament_root,
                    enroll_cmd,
                    _seq(destinations, "tournament"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, initiated),
        )

    @handles(tournament.TournamentPlayerEnrolled)
    def on_player_enrolled(
        self,
        event: tournament.TournamentPlayerEnrolled,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Tournament enrolled player — confirm the reservation."""
        confirm = registration.ConfirmRegistrationFee(
            reservation_id=event.reservation_id
        )
        completed = registration.RegistrationCompleted(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            fee=_currency(state.fee),
            starting_stack=event.starting_stack,
            completed_at=now(),
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    confirm,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, completed),
        )

    @handles(tournament.TournamentEnrollmentRejected)
    def on_enrollment_rejected(
        self,
        event: tournament.TournamentEnrollmentRejected,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Tournament rejected — release the reservation."""
        release = registration.ReleaseRegistrationFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _registration_failed_event(
            event.reservation_id,
            event.player_root,
            state.tournament_root,
            "ENROLLMENT_REJECTED",
            event.reason,
            "ENROLLING",
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "reservation",
                    event.reservation_id,
                    release,
                    _seq(destinations, "reservation"),
                ),
            ],
            process_events=_event_book(PM_DOMAIN, event.reservation_id, failed),
        )

    @handles(registration.RegistrationFeeConfirmed)
    def on_registration_confirmed(
        self,
        event: registration.RegistrationFeeConfirmed,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation confirmed — deduct reserved funds against the tournament."""
        fee = event.fee.amount if event.HasField("fee") else state.fee
        deduct = player.DeductReservedFunds(
            amount=_currency(fee),
            key=event.tournament_root or state.tournament_root,
            reservation_id=event.reservation_id,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    deduct,
                    _seq(destinations, "player"),
                ),
            ],
        )

    @handles(registration.RegistrationFeeReleased)
    def on_registration_released(
        self,
        event: registration.RegistrationFeeReleased,
        state: ReservationPMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Reservation released — refund the player against the tournament."""
        release_cmd = player.ReleaseFunds(
            key=event.tournament_root or state.tournament_root,
        )
        return ProcessManagerResponse(
            commands=[
                _command_book(
                    "player",
                    event.player_root or state.player_root,
                    release_cmd,
                    _seq(destinations, "player"),
                ),
            ],
        )

    # =========================================================================
    # Internal helpers for early-failure shortcuts
    # =========================================================================

    def _fail_buy_in(
        self,
        reservation_id: bytes,
        player_root: bytes,
        table_root: bytes,
        code: str,
        message: str,
        phase: str,
    ) -> ProcessManagerResponse:
        release = buy_in.ReleaseBuyIn(reservation_id=reservation_id, reason=message)
        failed = _buy_in_failed_event(
            reservation_id, player_root, table_root, code, message, phase
        )
        return ProcessManagerResponse(
            commands=[
                _command_book("reservation", reservation_id, release, 0),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, failed),
        )

    def _fail_rebuy(
        self,
        reservation_id: bytes,
        player_root: bytes,
        tournament_root: bytes,
        code: str,
        message: str,
        phase: str,
    ) -> ProcessManagerResponse:
        release = rebuy.ReleaseRebuyFee(reservation_id=reservation_id, reason=message)
        failed = _rebuy_failed_event(
            reservation_id, player_root, tournament_root, code, message, phase
        )
        return ProcessManagerResponse(
            commands=[
                _command_book("reservation", reservation_id, release, 0),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, failed),
        )

    def _fail_registration(
        self,
        reservation_id: bytes,
        player_root: bytes,
        tournament_root: bytes,
        code: str,
        message: str,
        phase: str,
    ) -> ProcessManagerResponse:
        release = registration.ReleaseRegistrationFee(
            reservation_id=reservation_id, reason=message
        )
        failed = _registration_failed_event(
            reservation_id, player_root, tournament_root, code, message, phase
        )
        return ProcessManagerResponse(
            commands=[
                _command_book("reservation", reservation_id, release, 0),
            ],
            process_events=_event_book(PM_DOMAIN, reservation_id, failed),
        )
