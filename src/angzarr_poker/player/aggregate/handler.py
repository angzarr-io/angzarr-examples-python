"""Player aggregate business seam — bankroll primitives.

Implements ``PlayerAggregateHandler`` on the angzarr-cli generated seam. The
player is the source of truth for a bankroll and its table reservations:
``register_player`` creates the account, the fund primitives move money between
the available and reserved buckets, and ``deduct_reserved_funds`` settles a
reserved amount the reservation PM has confirmed. State is the proto
``PlayerState`` (``bankroll`` and ``reserved_funds`` are ``Currency`` totals;
``table_reservations`` maps a reservation key's hex to its locked amount); the
appliers fold each emitted event back into it.

Available balance is always ``bankroll - reserved_funds`` — reserving locks
money without spending it, so a reservation lowers what can be withdrawn while
leaving the total bankroll unchanged. The buy-in / rebuy / tournament-
registration lifecycles are NOT handled here; they live on the reservation
aggregate after the reservation refactor.
"""

from __future__ import annotations

from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as _player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.player_aggregate_angzarr import (
    PlayerAggregateHandler,
)

# Rejections that express a state precondition cross the FFI as
# FAILED_PRECONDITION; pure input-validation rejections as INVALID_ARGUMENT.
# (Mirrors the poker error-shape hierarchy: PreconditionError vs ValidationError.)
_PRECONDITION_CODES = {
    "PLAYER_ALREADY_EXISTS",
    "PLAYER_NOT_FOUND",
    "INSUFFICIENT_AVAILABLE_BALANCE",
    "INSUFFICIENT_FUNDS",
    "FUNDS_ALREADY_RESERVED_FOR_TABLE",
    "NO_FUNDS_RESERVED_FOR_TABLE",
    "AMOUNT_EXCEEDS_RESERVED_FUNDS",
}


def _reject(code: str, message: str, **extras: str) -> _az.CodedError:
    grpc = (
        _az.GrpcCode.FAILED_PRECONDITION
        if code in _PRECONDITION_CODES
        else _az.GrpcCode.INVALID_ARGUMENT
    )
    return _az.CodedError(code=code, message=message, grpc=grpc, extras=extras or None)


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


def _exists(state: _player.PlayerState) -> bool:
    return bool(state.status)


def _available(state: _player.PlayerState) -> int:
    return state.bankroll.amount - state.reserved_funds.amount


class PlayerAggregate:
    """Implements ``PlayerAggregateHandler`` for the bankroll primitives."""

    # --- command handlers ---

    def register_player(
        self,
        cmd: _player.RegisterPlayer,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if _exists(state):
            raise _reject("PLAYER_ALREADY_EXISTS", "Player already exists")
        if not cmd.display_name:
            raise _reject("DISPLAY_NAME_REQUIRED", "display_name is required")
        if not cmd.email:
            raise _reject("EMAIL_REQUIRED", "email is required")
        return _book(
            _player.PlayerRegistered(
                display_name=cmd.display_name,
                email=cmd.email,
                player_type=cmd.player_type,
                ai_model_id=cmd.ai_model_id,
                registered_at=_now(),
            )
        )

    def deposit_funds(
        self,
        cmd: _player.DepositFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        amount = cmd.amount.amount
        if amount <= 0:
            raise _reject(
                "AMOUNT_MUST_BE_POSITIVE", f"Amount must be positive, got {amount}"
            )
        return _book(
            _player.FundsDeposited(
                amount=_chips(amount),
                new_balance=_chips(state.bankroll.amount + amount),
                deposited_at=_now(),
            )
        )

    def withdraw_funds(
        self,
        cmd: _player.WithdrawFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        amount = cmd.amount.amount
        if amount <= 0:
            raise _reject(
                "AMOUNT_MUST_BE_POSITIVE", f"Amount must be positive, got {amount}"
            )
        available = _available(state)
        if amount > available:
            raise _reject(
                "INSUFFICIENT_AVAILABLE_BALANCE",
                f"Insufficient available balance: requested {amount}, available {available}",
            )
        return _book(
            _player.FundsWithdrawn(
                amount=_chips(amount),
                new_balance=_chips(state.bankroll.amount - amount),
                withdrawn_at=_now(),
            )
        )

    def reserve_funds(
        self,
        cmd: _player.ReserveFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        amount = cmd.amount.amount
        if amount <= 0:
            raise _reject(
                "AMOUNT_MUST_BE_POSITIVE", f"Amount must be positive, got {amount}"
            )
        available = _available(state)
        if amount > available:
            raise _reject(
                "INSUFFICIENT_FUNDS",
                f"Insufficient funds: requested {amount}, available {available}",
            )
        bucket = cmd.key.hex()
        if bucket in state.table_reservations:
            raise _reject(
                "FUNDS_ALREADY_RESERVED_FOR_TABLE",
                f"Funds already reserved for table {bucket}",
                table_root_hex=bucket,
            )
        new_reserved = state.reserved_funds.amount + amount
        return _book(
            _player.FundsReserved(
                amount=_chips(amount),
                key=cmd.key,
                new_available_balance=_chips(state.bankroll.amount - new_reserved),
                new_reserved_balance=_chips(new_reserved),
                reserved_at=_now(),
            )
        )

    def release_funds(
        self,
        cmd: _player.ReleaseFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        if not cmd.key:
            raise _reject("TABLE_ROOT_REQUIRED", "table_root is required")
        bucket = cmd.key.hex()
        reserved_for_bucket = state.table_reservations.get(bucket, 0)
        if reserved_for_bucket == 0:
            raise _reject(
                "NO_FUNDS_RESERVED_FOR_TABLE",
                f"No funds reserved for table {bucket}",
                table_root_hex=bucket,
            )
        new_reserved = state.reserved_funds.amount - reserved_for_bucket
        return _book(
            _player.FundsReleased(
                amount=_chips(reserved_for_bucket),
                key=cmd.key,
                new_available_balance=_chips(state.bankroll.amount - new_reserved),
                new_reserved_balance=_chips(new_reserved),
                released_at=_now(),
            )
        )

    def transfer_funds(
        self,
        cmd: _player.TransferFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        amount = cmd.amount.amount
        if amount == 0:
            raise _reject("AMOUNT_MUST_BE_NON_ZERO", "Amount must be non-zero")
        to_root = state.player_id.encode() if state.player_id else b""
        return _book(
            _player.FundsTransferred(
                from_player_root=cmd.from_player_root,
                to_player_root=to_root,
                amount=cmd.amount,
                hand_root=cmd.hand_root,
                reason=cmd.reason,
                new_balance=_chips(state.bankroll.amount + amount),
                transferred_at=_now(),
            )
        )

    def deduct_reserved_funds(
        self,
        cmd: _player.DeductReservedFunds,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("PLAYER_NOT_FOUND", "Player does not exist")
        if not cmd.key:
            raise _reject("KEY_REQUIRED", "key is required")
        amount = cmd.amount.amount
        if amount <= 0:
            raise _reject(
                "AMOUNT_MUST_BE_POSITIVE", f"Amount must be positive, got {amount}"
            )
        reserved_for_key = state.table_reservations.get(cmd.key.hex(), 0)
        if amount > reserved_for_key:
            raise _reject(
                "AMOUNT_EXCEEDS_RESERVED_FUNDS",
                f"Amount exceeds reserved funds: requested {amount}, available {reserved_for_key}",
            )
        return _book(
            _player.FundsDeducted(
                amount=_chips(amount),
                key=cmd.key,
                reservation_id=cmd.reservation_id,
                new_balance=_chips(state.bankroll.amount - amount),
                new_reserved_balance=_chips(state.reserved_funds.amount - amount),
                deducted_at=_now(),
            )
        )

    # --- event appliers ---

    def apply_player_registered(
        self, state: _player.PlayerState, event: _player.PlayerRegistered
    ) -> None:
        state.display_name = event.display_name
        state.email = event.email
        state.player_type = event.player_type
        state.ai_model_id = event.ai_model_id
        state.status = "active"

    def apply_funds_deposited(
        self, state: _player.PlayerState, event: _player.FundsDeposited
    ) -> None:
        state.bankroll.CopyFrom(event.new_balance)

    def apply_funds_withdrawn(
        self, state: _player.PlayerState, event: _player.FundsWithdrawn
    ) -> None:
        state.bankroll.CopyFrom(event.new_balance)

    def apply_funds_reserved(
        self, state: _player.PlayerState, event: _player.FundsReserved
    ) -> None:
        state.reserved_funds.CopyFrom(event.new_reserved_balance)
        state.table_reservations[event.key.hex()] = event.amount.amount

    def apply_funds_released(
        self, state: _player.PlayerState, event: _player.FundsReleased
    ) -> None:
        state.reserved_funds.CopyFrom(event.new_reserved_balance)
        state.table_reservations.pop(event.key.hex(), None)

    def apply_funds_transferred(
        self, state: _player.PlayerState, event: _player.FundsTransferred
    ) -> None:
        state.bankroll.CopyFrom(event.new_balance)

    def apply_funds_deducted(
        self, state: _player.PlayerState, event: _player.FundsDeducted
    ) -> None:
        state.bankroll.CopyFrom(event.new_balance)
        state.reserved_funds.CopyFrom(event.new_reserved_balance)
        bucket = event.key.hex()
        remaining = state.table_reservations.get(bucket, 0) - event.amount.amount
        if remaining > 0:
            state.table_reservations[bucket] = remaining
        else:
            state.table_reservations.pop(bucket, None)


# Static guarantee that the class satisfies the generated Protocol.
_: PlayerAggregateHandler = PlayerAggregate()
