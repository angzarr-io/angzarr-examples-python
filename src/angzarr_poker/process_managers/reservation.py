# Scaffolded ONCE by angzarr codegen python — this file is YOURS.
#
# Regeneration will NOT overwrite this file. It is your responsibility to
# keep the generated <Component>Handler interface implemented: when a
# command or event is added to the proto, the handler will be missing a
# method until you add it here.
#
# Reservation process manager — single PM for the buy-in, rebuy, and
# tournament-registration lifecycles. It is stateful and event-sourced: it
# folds its OWN *Initiated / *Completed / *Failed events into
# ``ReservationProcessManagerState`` (via the appliers) and reacts to triggers
# from the reservation / table / tournament domains, translating each lifecycle
# event into the matching player-funds primitive and coordinating the non-funds
# side with table / tournament / reservation.
#
#   Buy-in:
#     reservation.BuyInRequested        -> player.ReserveFunds + table.SeatPlayer
#                                          (own event: BuyInInitiated)
#     table.PlayerSeated                -> reservation.ConfirmBuyIn
#                                          (own event: BuyInCompleted)
#     reservation.BuyInConfirmed        -> player.DeductReservedFunds
#     table.SeatingRejected             -> reservation.ReleaseBuyIn
#                                          (own event: BuyInFailed)
#     reservation.BuyInReservationReleased -> player.ReleaseFunds
#
#   Rebuy:
#     reservation.RebuyRequested        -> player.ReserveFunds + tournament.ProcessRebuy
#                                          (own event: RebuyInitiated)
#     tournament.RebuyProcessed         -> table.AddRebuyChips
#     table.RebuyChipsAdded             -> reservation.ConfirmRebuyFee
#                                          (own event: RebuyCompleted)
#     reservation.RebuyFeeConfirmed     -> player.DeductReservedFunds
#     tournament.RebuyDenied            -> reservation.ReleaseRebuyFee
#                                          (own event: RebuyFailed)
#     reservation.RebuyFeeReleased      -> player.ReleaseFunds
#
#   Registration:
#     reservation.RegistrationRequested -> player.ReserveFunds + tournament.EnrollPlayer
#                                          (own event: RegistrationInitiated)
#     tournament.TournamentPlayerEnrolled -> reservation.ConfirmRegistrationFee
#                                          (own event: RegistrationCompleted)
#     reservation.RegistrationFeeConfirmed -> player.DeductReservedFunds
#     tournament.TournamentEnrollmentRejected -> reservation.ReleaseRegistrationFee
#                                          (own event: RegistrationFailed)
#     reservation.RegistrationFeeReleased -> player.ReleaseFunds
#
# Reframed-model note: there is NO QueryClient seam here, so the pre-validation
# the baseline performed against synchronously-read table / tournament state
# (amount in range, seat free, registration open, capacity, rebuy window, player
# seated) is NOT reconstructable and is therefore omitted. Decisions are driven
# off the trigger event's fields plus the PM's own event-sourced state. The
# orchestration aggregates remain the authority that rejects an invalid request.

import angzarr_router_ffi as _az
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as _buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as _rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as _registration
from angzarr_poker._gen.io.angzarr.examples.v1 import reservation_pb2 as _reservation
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _tournament
from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as _player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _poker
from angzarr_poker._gen.io.angzarr.examples.v1 import orchestration_pb2 as _orch
from angzarr_poker._gen.io.angzarr.examples.v1.reservation_process_manager_angzarr import (
    ReservationProcessManagerHandler,
)

# state.kind discriminators (mirrors the proto string field).
_KIND_BUY_IN = "buy_in"
_KIND_REBUY = "rebuy"
_KIND_REGISTRATION = "registration"

# Own events land on a dedicated PM stream keyed by reservation_id.
_PM_DOMAIN = "reservation"


def _currency(amount: int) -> _poker.Currency:
    return _poker.Currency(amount=amount, currency_code="CHIPS")


class ReservationProcessManager:
    """Implements ReservationProcessManagerHandler."""

    # ------------------------------------------------------------------ #
    # Plumbing helpers
    # ------------------------------------------------------------------ #

    def _seq(self, dests: _az.Destinations, domain: str) -> int:
        if dests is None:
            return 0
        seq = dests.sequence_for(domain)
        return seq if seq is not None else 0

    def _command_book(
        self, dests: _az.Destinations, domain: str, root: bytes, cmd
    ) -> _t.CommandBook:
        book = _t.CommandBook()
        book.cover.domain = domain
        book.cover.root.value = root
        page = book.pages.add()
        page.header.sequence = self._seq(dests, domain)
        page.command.CopyFrom(_az.pack(cmd))
        return book

    def _response_with_own_event(
        self,
        reservation_id: bytes,
        own_event,
        applier,
        commands: list,
    ) -> _pm.ProcessManagerHandleResponse:
        """Build a response: emit the PM's own event (with a folded-state
        snapshot to augment rebuild) plus any downstream commands."""
        resp = _pm.ProcessManagerHandleResponse()
        for book in commands:
            resp.commands.append(book)
        book = resp.process_events.add()
        book.cover.domain = _PM_DOMAIN
        book.cover.root.value = reservation_id
        book.pages.add().event.CopyFrom(_az.pack(own_event))
        folded = _reservation.ReservationProcessManagerState()
        # Replay the existing trajectory isn't available here; the snapshot
        # carries the post-fold delta so the core can fast-path rebuild.
        applier(folded, own_event)
        book.snapshot.state.CopyFrom(_az.pack(folded))
        return resp

    def _response_commands_only(
        self, dests: _az.Destinations, commands: list
    ) -> _pm.ProcessManagerHandleResponse:
        resp = _pm.ProcessManagerHandleResponse()
        for book in commands:
            resp.commands.append(book)
        return resp

    # ------------------------------------------------------------------ #
    # Buy-in flow
    # ------------------------------------------------------------------ #

    def buy_in_requested(
        self,
        event: _buy_in.BuyInRequested,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        table_root = event.table_root
        amount = event.amount.amount if event.HasField("amount") else 0

        # Look-before-leap: if the table's buy-in range has been observed (folded
        # from table.TableCreated into the cross-domain read model), refuse an
        # out-of-range amount up front — no SeatPlayer is offered. An unobserved
        # range (max == 0) skips the check; the table aggregate stays the authority.
        if state.table_max_buy_in and not (
            state.table_min_buy_in <= amount <= state.table_max_buy_in
        ):
            failed = _buy_in.BuyInFailed(
                player_root=player_root,
                table_root=table_root,
                reservation_id=reservation_id,
                failure=_orch.OrchestrationFailure(
                    code="AMOUNT_OUT_OF_RANGE",
                    message="buy-in amount is outside the table's allowed range",
                    failed_at_phase="SEATING",
                ),
            )
            return self._response_with_own_event(
                reservation_id, failed, self.apply_buy_in_failed, []
            )

        # Look-before-leap: if the table's seating has been observed (folded from
        # table.PlayerSeated), refuse a buy-in at an already-occupied seat or once
        # the table is full — before asking the table to seat. Both checks are
        # conditional on the relevant fact being observed; an unseeded read model
        # skips them and the table aggregate stays the authority.
        if event.seat >= 0 and event.seat in state.occupied_seats:
            failed = _buy_in.BuyInFailed(
                player_root=player_root,
                table_root=table_root,
                reservation_id=reservation_id,
                failure=_orch.OrchestrationFailure(
                    code="SEAT_TAKEN",
                    message="the requested seat is already occupied",
                    failed_at_phase="SEATING",
                ),
            )
            return self._response_with_own_event(
                reservation_id, failed, self.apply_buy_in_failed, []
            )
        if state.table_max_players and (
            len(state.occupied_seats) >= state.table_max_players
        ):
            failed = _buy_in.BuyInFailed(
                player_root=player_root,
                table_root=table_root,
                reservation_id=reservation_id,
                failure=_orch.OrchestrationFailure(
                    code="TABLE_FULL",
                    message="the table is full",
                    failed_at_phase="SEATING",
                ),
            )
            return self._response_with_own_event(
                reservation_id, failed, self.apply_buy_in_failed, []
            )

        reserve_cmd = _player.ReserveFunds(amount=_currency(amount), key=table_root)
        seat_cmd = _buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=amount,
        )
        initiated = _buy_in.BuyInInitiated(
            player_root=player_root,
            table_root=table_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=_currency(amount),
            phase=_orch.BuyInPhase.BUY_IN_SEATING,
        )
        commands = [
            self._command_book(dests, "player", player_root, reserve_cmd),
            self._command_book(dests, "table", table_root, seat_cmd),
        ]
        return self._response_with_own_event(
            reservation_id, initiated, self.apply_buy_in_initiated, commands
        )

    def player_seated(
        self,
        event: _buy_in.PlayerSeated,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        confirm = _buy_in.ConfirmBuyIn(reservation_id=event.reservation_id)
        completed = _buy_in.BuyInCompleted(
            player_root=event.player_root or state.player_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            seat=event.seat_position,
            amount=_currency(event.stack),
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, confirm),
        ]
        return self._response_with_own_event(
            event.reservation_id, completed, self.apply_buy_in_completed, commands
        )

    def seating_rejected(
        self,
        event: _buy_in.SeatingRejected,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release = _buy_in.ReleaseBuyIn(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _buy_in.BuyInFailed(
            player_root=event.player_root or state.player_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            failure=_orch.OrchestrationFailure(
                code="SEATING_REJECTED",
                message=event.reason,
                failed_at_phase="SEATING",
            ),
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, release),
        ]
        return self._response_with_own_event(
            event.reservation_id, failed, self.apply_buy_in_failed, commands
        )

    def buy_in_confirmed(
        self,
        event: _buy_in.BuyInConfirmed,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        amount = event.amount.amount if event.HasField("amount") else state.amount
        deduct = _player.DeductReservedFunds(
            amount=_currency(amount),
            key=event.table_root or state.table_root,
            reservation_id=event.reservation_id,
        )
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, deduct
                )
            ],
        )

    def buy_in_reservation_released(
        self,
        event: _buy_in.BuyInReservationReleased,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release_cmd = _player.ReleaseFunds(key=event.table_root or state.table_root)
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, release_cmd
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # Rebuy flow
    # ------------------------------------------------------------------ #

    def rebuy_requested(
        self,
        event: _rebuy.RebuyRequested,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        tournament_root = event.tournament_root
        table_root = event.table_root
        fee = event.fee.amount if event.HasField("fee") else 0

        # Look-before-leap: when the tournament's status has been observed (folded
        # from tournament.TournamentStarted/Paused/Resumed), the rebuy window is
        # open only while the tournament is RUNNING; and the player must be seated
        # at a table (folded from table.PlayerSeated). Refuse before asking the
        # tournament to process the rebuy. Both checks gate on the status having
        # been observed; an unseeded read model skips them entirely.
        if state.tournament_status:
            if state.tournament_status != (
                _tournament.TournamentStatus.TOURNAMENT_RUNNING
            ):
                failed = _rebuy.RebuyFailed(
                    player_root=player_root,
                    tournament_root=tournament_root,
                    reservation_id=reservation_id,
                    failure=_orch.OrchestrationFailure(
                        code="REBUY_WINDOW_CLOSED",
                        message="the tournament is not currently running",
                        failed_at_phase="APPROVING",
                    ),
                )
                return self._response_with_own_event(
                    reservation_id, failed, self.apply_rebuy_failed, []
                )
            if not state.player_seated:
                failed = _rebuy.RebuyFailed(
                    player_root=player_root,
                    tournament_root=tournament_root,
                    reservation_id=reservation_id,
                    failure=_orch.OrchestrationFailure(
                        code="PLAYER_NOT_SEATED",
                        message="the player is not seated at a table",
                        failed_at_phase="APPROVING",
                    ),
                )
                return self._response_with_own_event(
                    reservation_id, failed, self.apply_rebuy_failed, []
                )

        reserve_cmd = _player.ReserveFunds(amount=_currency(fee), key=table_root)
        process_cmd = _tournament.ProcessRebuy(
            player_root=player_root,
            reservation_id=reservation_id,
        )
        initiated = _rebuy.RebuyInitiated(
            player_root=player_root,
            tournament_root=tournament_root,
            table_root=table_root,
            reservation_id=reservation_id,
            seat=event.seat,
            fee=_currency(fee),
            phase=_orch.RebuyPhase.REBUY_APPROVING,
        )
        commands = [
            self._command_book(dests, "player", player_root, reserve_cmd),
            self._command_book(dests, "tournament", tournament_root, process_cmd),
        ]
        return self._response_with_own_event(
            reservation_id, initiated, self.apply_rebuy_initiated, commands
        )

    def rebuy_processed(
        self,
        event: _tournament.RebuyProcessed,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        add_chips = _rebuy.AddRebuyChips(
            player_root=event.player_root or state.player_root,
            reservation_id=event.reservation_id,
            seat=state.seat,
            amount=event.chips_added,
        )
        return self._response_commands_only(
            dests,
            [self._command_book(dests, "table", state.table_root, add_chips)],
        )

    def rebuy_chips_added(
        self,
        event: _rebuy.RebuyChipsAdded,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        confirm = _rebuy.ConfirmRebuyFee(reservation_id=event.reservation_id)
        completed = _rebuy.RebuyCompleted(
            player_root=event.player_root or state.player_root,
            tournament_root=state.tournament_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            fee=_currency(state.fee),
            chips_added=event.amount,
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, confirm),
        ]
        return self._response_with_own_event(
            event.reservation_id, completed, self.apply_rebuy_completed, commands
        )

    def rebuy_denied(
        self,
        event: _tournament.RebuyDenied,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release = _rebuy.ReleaseRebuyFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _rebuy.RebuyFailed(
            player_root=event.player_root or state.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            failure=_orch.OrchestrationFailure(
                code="REBUY_DENIED",
                message=event.reason,
                failed_at_phase="APPROVING",
            ),
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, release),
        ]
        return self._response_with_own_event(
            event.reservation_id, failed, self.apply_rebuy_failed, commands
        )

    def rebuy_fee_confirmed(
        self,
        event: _rebuy.RebuyFeeConfirmed,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        fee = event.fee.amount if event.HasField("fee") else state.fee
        deduct = _player.DeductReservedFunds(
            amount=_currency(fee),
            key=event.table_root or state.table_root,
            reservation_id=event.reservation_id,
        )
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, deduct
                )
            ],
        )

    def rebuy_fee_released(
        self,
        event: _rebuy.RebuyFeeReleased,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release_cmd = _player.ReleaseFunds(key=event.table_root or state.table_root)
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, release_cmd
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # Registration flow
    # ------------------------------------------------------------------ #

    def registration_requested(
        self,
        event: _registration.RegistrationRequested,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        player_root = event.player_root or state.player_root
        reservation_id = event.reservation_id
        tournament_root = event.tournament_root
        fee = event.fee.amount if event.HasField("fee") else 0

        # Look-before-leap: when the tournament's registration state has been
        # observed (folded from tournament.RegistrationOpened/Closed +
        # TournamentCreated capacity + TournamentPlayerEnrolled), refuse a
        # registration that is closed or at capacity before asking the tournament
        # to enroll. Unobserved state skips the check; the tournament aggregate
        # stays the authority.
        full = state.tournament_max_players and (
            state.tournament_enrolled_count >= state.tournament_max_players
        )
        closed = state.tournament_registration_observed and not (
            state.tournament_registration_open
        )
        if full or closed:
            failed = _registration.RegistrationFailed(
                player_root=player_root,
                tournament_root=tournament_root,
                reservation_id=reservation_id,
                failure=_orch.OrchestrationFailure(
                    code="REGISTRATION_CLOSED",
                    message="tournament registration is closed",
                    failed_at_phase="ENROLLING",
                ),
            )
            return self._response_with_own_event(
                reservation_id, failed, self.apply_registration_failed, []
            )

        # Registration reserves against the tournament_root (no table yet).
        reserve_cmd = _player.ReserveFunds(amount=_currency(fee), key=tournament_root)
        enroll_cmd = _tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
        )
        initiated = _registration.RegistrationInitiated(
            player_root=player_root,
            tournament_root=tournament_root,
            reservation_id=reservation_id,
            fee=_currency(fee),
            phase=_orch.RegistrationPhase.REGISTRATION_ENROLLING,
        )
        commands = [
            self._command_book(dests, "player", player_root, reserve_cmd),
            self._command_book(dests, "tournament", tournament_root, enroll_cmd),
        ]
        return self._response_with_own_event(
            reservation_id, initiated, self.apply_registration_initiated, commands
        )

    def tournament_player_enrolled(
        self,
        event: _tournament.TournamentPlayerEnrolled,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        confirm = _registration.ConfirmRegistrationFee(
            reservation_id=event.reservation_id
        )
        completed = _registration.RegistrationCompleted(
            player_root=event.player_root or state.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            fee=_currency(state.fee),
            starting_stack=event.starting_stack,
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, confirm),
        ]
        return self._response_with_own_event(
            event.reservation_id, completed, self.apply_registration_completed, commands
        )

    def tournament_enrollment_rejected(
        self,
        event: _tournament.TournamentEnrollmentRejected,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release = _registration.ReleaseRegistrationFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )
        failed = _registration.RegistrationFailed(
            player_root=event.player_root or state.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            failure=_orch.OrchestrationFailure(
                code="ENROLLMENT_REJECTED",
                message=event.reason,
                failed_at_phase="ENROLLING",
            ),
        )
        commands = [
            self._command_book(dests, "reservation", event.reservation_id, release),
        ]
        return self._response_with_own_event(
            event.reservation_id, failed, self.apply_registration_failed, commands
        )

    def registration_fee_confirmed(
        self,
        event: _registration.RegistrationFeeConfirmed,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        fee = event.fee.amount if event.HasField("fee") else state.fee
        deduct = _player.DeductReservedFunds(
            amount=_currency(fee),
            key=event.tournament_root or state.tournament_root,
            reservation_id=event.reservation_id,
        )
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, deduct
                )
            ],
        )

    def registration_fee_released(
        self,
        event: _registration.RegistrationFeeReleased,
        state: _reservation.ReservationProcessManagerState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        release_cmd = _player.ReleaseFunds(
            key=event.tournament_root or state.tournament_root
        )
        return self._response_commands_only(
            dests,
            [
                self._command_book(
                    dests, "player", event.player_root or state.player_root, release_cmd
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # Appliers — fold the PM's OWN events into state. kind is set once on
    # *Initiated and carried through; completion / failure only move phase.
    # ------------------------------------------------------------------ #

    def apply_buy_in_initiated(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _buy_in.BuyInInitiated,
    ) -> None:
        state.kind = _KIND_BUY_IN
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.table_root = event.table_root
        state.seat = event.seat
        state.amount = event.amount.amount if event.HasField("amount") else 0
        state.phase = event.phase

    def apply_buy_in_completed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _buy_in.BuyInCompleted,
    ) -> None:
        state.phase = _orch.BuyInPhase.BUY_IN_COMPLETED

    def apply_buy_in_failed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _buy_in.BuyInFailed,
    ) -> None:
        state.phase = _orch.BuyInPhase.BUY_IN_FAILED

    def apply_rebuy_initiated(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _rebuy.RebuyInitiated,
    ) -> None:
        state.kind = _KIND_REBUY
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root
        state.table_root = event.table_root
        state.seat = event.seat
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.phase = event.phase

    def apply_rebuy_completed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _rebuy.RebuyCompleted,
    ) -> None:
        state.phase = _orch.RebuyPhase.REBUY_COMPLETED

    def apply_rebuy_failed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _rebuy.RebuyFailed,
    ) -> None:
        state.phase = _orch.RebuyPhase.REBUY_FAILED

    def apply_registration_initiated(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _registration.RegistrationInitiated,
    ) -> None:
        state.kind = _KIND_REGISTRATION
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.phase = event.phase

    def apply_registration_completed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _registration.RegistrationCompleted,
    ) -> None:
        state.phase = _orch.RegistrationPhase.REGISTRATION_COMPLETED

    def apply_registration_failed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _registration.RegistrationFailed,
    ) -> None:
        state.phase = _orch.RegistrationPhase.REGISTRATION_FAILED

    # ------------------------------------------------------------------ #
    # Cross-domain appliers — fold OTHER domains' events into the
    # orchestrator's read model (applies:true on a foreign-domain event), so a
    # look-before-leap decision can be made without a synchronous read.
    # ------------------------------------------------------------------ #

    def apply_table_created(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _table.TableCreated,
    ) -> None:
        state.table_min_buy_in = event.min_buy_in
        state.table_max_buy_in = event.max_buy_in
        state.table_max_players = event.max_players

    def apply_player_seated(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _buy_in.PlayerSeated,
    ) -> None:
        # Track which seats are occupied at the table (and that this player is now
        # seated) so a later buy-in for a taken seat / at a full table is refused
        # and a rebuy for a seated player is allowed. Idempotent on the seat.
        if event.seat_position not in state.occupied_seats:
            state.occupied_seats.append(event.seat_position)
        state.player_seated = True

    def apply_tournament_created(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.TournamentCreated,
    ) -> None:
        state.tournament_max_players = event.max_players

    def apply_registration_opened(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.RegistrationOpened,
    ) -> None:
        state.tournament_registration_open = True
        state.tournament_registration_observed = True

    def apply_registration_closed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.RegistrationClosed,
    ) -> None:
        state.tournament_registration_open = False
        state.tournament_registration_observed = True

    def apply_tournament_player_enrolled(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.TournamentPlayerEnrolled,
    ) -> None:
        state.tournament_enrolled_count += 1

    def apply_tournament_started(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.TournamentStarted,
    ) -> None:
        state.tournament_status = _tournament.TournamentStatus.TOURNAMENT_RUNNING

    def apply_tournament_paused(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.TournamentPaused,
    ) -> None:
        state.tournament_status = _tournament.TournamentStatus.TOURNAMENT_PAUSED

    def apply_tournament_resumed(
        self,
        state: _reservation.ReservationProcessManagerState,
        event: _tournament.TournamentResumed,
    ) -> None:
        state.tournament_status = _tournament.TournamentStatus.TOURNAMENT_RUNNING


_: ReservationProcessManagerHandler = ReservationProcessManager()
