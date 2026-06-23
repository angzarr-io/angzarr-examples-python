"""Reservation aggregate business seam — buy-in / rebuy / registration records.

Implements ``ReservationAggregateHandler`` on the angzarr-cli generated seam. The
aggregate owns one pending record per in-flight two-phase fund commitment:

  Initiate*  -> open a pending record, emit a *Requested event (with a generated
                reservation id)
  Confirm*   -> close the pending record on success, emit a *Confirmed event
  Release*   -> close the pending record on failure, emit a *Released event

State is the proto ``ReservationState`` (three maps keyed by reservation-id hex).
The appliers fold each event back into it.

It validates only its OWN inputs (the routing roots are present, the amount is
positive, the reservation id is supplied, the pending record exists). It does NOT
check player existence or funds: those are the player aggregate's invariant,
enforced when the reservation PM issues ``ReserveFunds`` / ``DeductReservedFunds``.
A buy-in that the player can't afford fails as an orchestration outcome (the PM's
``BuyInFailed``), not as a synchronous rejection here.
"""

from __future__ import annotations

import uuid
from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as _buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as _rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as _reg
from angzarr_poker._gen.io.angzarr.examples.v1 import reservation_pb2 as _res
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.reservation_aggregate_angzarr import (
    ReservationAggregateHandler,
)

# Missing-pending rejections are state preconditions; everything else here is
# input validation.
_PRECONDITION_CODES = {"NO_PENDING_BUY_IN", "NO_PENDING_REBUY", "NO_PENDING_REGISTRATION"}


def _reject(code: str, message: str) -> _az.CodedError:
    grpc = (
        _az.GrpcCode.FAILED_PRECONDITION
        if code in _PRECONDITION_CODES
        else _az.GrpcCode.INVALID_ARGUMENT
    )
    return _az.CodedError(code=code, message=message, grpc=grpc)


def _now() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _chips(amount: int) -> _pt.Currency:
    return _pt.Currency(amount=amount, currency_code="CHIPS")


def _book(*events) -> _t.EventBook:
    book = _t.EventBook()
    for ev in events:
        book.pages.add().event.CopyFrom(_az.pack(ev))
    return book


def _new_reservation_id() -> bytes:
    return uuid.uuid4().bytes


class ReservationAggregate:
    """Implements ``ReservationAggregateHandler`` for the three lifecycle flows."""

    # === buy-in ===

    def initiate_buy_in(
        self, cmd: _buy_in.InitiateBuyIn, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.player_root:
            raise _reject("PLAYER_ROOT_REQUIRED", "player_root is required")
        if not cmd.table_root:
            raise _reject("TABLE_ROOT_REQUIRED", "a table is required")
        amount = cmd.amount.amount
        if amount <= 0:
            raise _reject("AMOUNT_MUST_BE_POSITIVE", f"amount must be positive, got {amount}")
        return _book(
            _buy_in.BuyInRequested(
                reservation_id=_new_reservation_id(),
                player_root=cmd.player_root,
                table_root=cmd.table_root,
                seat=cmd.seat,
                amount=cmd.amount,
                requested_at=_now(),
            )
        )

    def confirm_buy_in(
        self, cmd: _buy_in.ConfirmBuyIn, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_buy_ins.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_BUY_IN", "no buy-in with that reservation is pending")
        return _book(
            _buy_in.BuyInConfirmed(
                reservation_id=cmd.reservation_id,
                player_root=pending.player_root,
                table_root=pending.table_root,
                seat=pending.seat,
                amount=_chips(pending.amount),
                confirmed_at=_now(),
            )
        )

    def release_buy_in(
        self, cmd: _buy_in.ReleaseBuyIn, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_buy_ins.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_BUY_IN", "no buy-in with that reservation is pending")
        return _book(
            _buy_in.BuyInReservationReleased(
                reservation_id=cmd.reservation_id,
                reason=cmd.reason,
                released_at=_now(),
                player_root=pending.player_root,
                table_root=pending.table_root,
                amount=_chips(pending.amount),
            )
        )

    def apply_buy_in_requested(
        self, state: _res.ReservationState, event: _buy_in.BuyInRequested
    ) -> None:
        state.pending_buy_ins[event.reservation_id.hex()].CopyFrom(
            _res.PendingBuyIn(
                player_root=event.player_root,
                table_root=event.table_root,
                seat=event.seat,
                amount=event.amount.amount,
            )
        )

    def apply_buy_in_confirmed(
        self, state: _res.ReservationState, event: _buy_in.BuyInConfirmed
    ) -> None:
        state.pending_buy_ins.pop(event.reservation_id.hex(), None)

    def apply_buy_in_reservation_released(
        self, state: _res.ReservationState, event: _buy_in.BuyInReservationReleased
    ) -> None:
        state.pending_buy_ins.pop(event.reservation_id.hex(), None)

    # === tournament registration ===

    def initiate_tournament_registration(
        self,
        cmd: _reg.InitiateTournamentRegistration,
        state: _res.ReservationState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not cmd.player_root:
            raise _reject("PLAYER_ROOT_REQUIRED", "player_root is required")
        if not cmd.tournament_root:
            raise _reject("TOURNAMENT_ROOT_REQUIRED", "a tournament is required")
        return _book(
            _reg.RegistrationRequested(
                reservation_id=_new_reservation_id(),
                player_root=cmd.player_root,
                tournament_root=cmd.tournament_root,
                requested_at=_now(),
            )
        )

    def confirm_registration_fee(
        self, cmd: _reg.ConfirmRegistrationFee, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_registrations.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_REGISTRATION", "no registration with that reservation is pending")
        return _book(
            _reg.RegistrationFeeConfirmed(
                reservation_id=cmd.reservation_id,
                player_root=pending.player_root,
                tournament_root=pending.tournament_root,
                fee=_chips(pending.fee),
                confirmed_at=_now(),
            )
        )

    def release_registration_fee(
        self, cmd: _reg.ReleaseRegistrationFee, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_registrations.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_REGISTRATION", "no registration with that reservation is pending")
        return _book(
            _reg.RegistrationFeeReleased(
                reservation_id=cmd.reservation_id,
                reason=cmd.reason,
                released_at=_now(),
                player_root=pending.player_root,
                tournament_root=pending.tournament_root,
                fee=_chips(pending.fee),
            )
        )

    def apply_registration_requested(
        self, state: _res.ReservationState, event: _reg.RegistrationRequested
    ) -> None:
        state.pending_registrations[event.reservation_id.hex()].CopyFrom(
            _res.PendingRegistration(
                player_root=event.player_root,
                tournament_root=event.tournament_root,
                fee=event.fee.amount,
            )
        )

    def apply_registration_fee_confirmed(
        self, state: _res.ReservationState, event: _reg.RegistrationFeeConfirmed
    ) -> None:
        state.pending_registrations.pop(event.reservation_id.hex(), None)

    def apply_registration_fee_released(
        self, state: _res.ReservationState, event: _reg.RegistrationFeeReleased
    ) -> None:
        state.pending_registrations.pop(event.reservation_id.hex(), None)

    # === rebuy ===

    def initiate_rebuy(
        self, cmd: _rebuy.InitiateRebuy, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.player_root:
            raise _reject("PLAYER_ROOT_REQUIRED", "player_root is required")
        if not cmd.tournament_root:
            raise _reject("TOURNAMENT_ROOT_REQUIRED", "a tournament is required")
        if not cmd.table_root:
            raise _reject("TABLE_ROOT_REQUIRED", "a table is required")
        return _book(
            _rebuy.RebuyRequested(
                reservation_id=_new_reservation_id(),
                player_root=cmd.player_root,
                tournament_root=cmd.tournament_root,
                table_root=cmd.table_root,
                seat=cmd.seat,
                requested_at=_now(),
            )
        )

    def confirm_rebuy_fee(
        self, cmd: _rebuy.ConfirmRebuyFee, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_rebuys.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_REBUY", "no rebuy with that reservation is pending")
        return _book(
            _rebuy.RebuyFeeConfirmed(
                reservation_id=cmd.reservation_id,
                player_root=pending.player_root,
                tournament_root=pending.tournament_root,
                table_root=pending.table_root,
                fee=_chips(pending.fee),
                chips_added=0,  # populated later by the tournament side
                confirmed_at=_now(),
            )
        )

    def release_rebuy_fee(
        self, cmd: _rebuy.ReleaseRebuyFee, state: _res.ReservationState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not cmd.reservation_id:
            raise _reject("RESERVATION_ID_REQUIRED", "a reservation identifier is required")
        pending = state.pending_rebuys.get(cmd.reservation_id.hex())
        if pending is None:
            raise _reject("NO_PENDING_REBUY", "no rebuy with that reservation is pending")
        return _book(
            _rebuy.RebuyFeeReleased(
                reservation_id=cmd.reservation_id,
                reason=cmd.reason,
                released_at=_now(),
                player_root=pending.player_root,
                tournament_root=pending.tournament_root,
                table_root=pending.table_root,
                fee=_chips(pending.fee),
            )
        )

    def apply_rebuy_requested(
        self, state: _res.ReservationState, event: _rebuy.RebuyRequested
    ) -> None:
        state.pending_rebuys[event.reservation_id.hex()].CopyFrom(
            _res.PendingRebuy(
                player_root=event.player_root,
                tournament_root=event.tournament_root,
                table_root=event.table_root,
                seat=event.seat,
                fee=event.fee.amount,
            )
        )

    def apply_rebuy_fee_confirmed(
        self, state: _res.ReservationState, event: _rebuy.RebuyFeeConfirmed
    ) -> None:
        state.pending_rebuys.pop(event.reservation_id.hex(), None)

    def apply_rebuy_fee_released(
        self, state: _res.ReservationState, event: _rebuy.RebuyFeeReleased
    ) -> None:
        state.pending_rebuys.pop(event.reservation_id.hex(), None)


# Static guarantee that the class satisfies the generated Protocol.
_: ReservationAggregateHandler = ReservationAggregate()
