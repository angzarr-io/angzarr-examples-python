"""pmg-buy-in: the BuyInProcessManager.

A buy-in needs a held seat at the table and held funds in the wallet. The
process holds the seat (the trigger), then the money, then confirms the seat,
then spends the money, and undoes whichever half went through when the other
is refused. It makes no business decisions: the table and the wallet decide.

Every handler first checks that the trigger belongs to this buy-in (its
buy_in_id or hold_id equals ``state.buy_in_id``) and that the buy-in is in the
phase that expects it; anything else is a no-op, so foreign and redelivered
news is harmless. Every command it sends is deferred, carries no correlation
id (core stamps the trigger's) and is decided synchronously
(SYNC_MODE_DECISION): each next step depends on the previous outcome.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import deferred_command, event_book, unpack
from angzarr_blackjack.errors import rejection_code

BuyInState = _b.BuyInState
Phase = BuyInState.Phase
PLAYER = "player"
TABLE = "table"
DECISION = _t.SyncMode.SYNC_MODE_DECISION


def _respond(event=None, *commands: _t.CommandBook) -> _pm.ProcessManagerHandleResponse:
    response = _pm.ProcessManagerHandleResponse(commands=list(commands))
    if event is not None:
        response.process_events.append(event_book(event))
    return response


def _belongs(state: BuyInState, buy_in_id: bytes, phase) -> bool:
    return state.phase == phase and state.buy_in_id == buy_in_id


def _to_player(state: BuyInState, command) -> _t.CommandBook:
    return deferred_command(PLAYER, state.player_root, command, DECISION)


def _to_table(state: BuyInState, command) -> _t.CommandBook:
    return deferred_command(TABLE, state.table_root, command, DECISION)


class BuyInProcessManager:
    """Implements ``BuyInProcessManagerHandler``."""

    # region pm_handler
    def seat_held(
        self,
        event: _table.SeatHeld,
        state: BuyInState,
        dests: _az.Destinations,
        trigger_cover: _t.Cover | None,
    ) -> _pm.ProcessManagerHandleResponse:
        """A held seat starts a buy-in and asks the wallet to hold the money."""
        if state.phase != Phase.PHASE_UNSPECIFIED:
            return _respond()
        started = _b.BuyInStarted(
            buy_in_id=event.buy_in_id,
            player_root=event.player_root,
            table_root=trigger_cover.root.value,
            seat=event.seat,
            amount=event.amount,
        )
        hold = _p.HoldFunds(
            hold_id=event.buy_in_id, table_root=started.table_root, amount=event.amount
        )
        return _respond(
            started, deferred_command(PLAYER, event.player_root, hold, DECISION)
        )

    def funds_held(
        self,
        event: _p.FundsHeld,
        state: BuyInState,
        dests: _az.Destinations,
        trigger_cover: _t.Cover | None,
    ) -> _pm.ProcessManagerHandleResponse:
        """Held money leads to confirming the seat."""
        if not _belongs(state, event.hold_id, Phase.PHASE_AWAITING_HOLD):
            return _respond()
        return _respond(
            _b.BuyInFundsHeld(buy_in_id=state.buy_in_id),
            _to_table(state, _table.ConfirmSeat(buy_in_id=state.buy_in_id)),
        )

    def player_seated(
        self,
        event: _table.PlayerSeated,
        state: BuyInState,
        dests: _az.Destinations,
        trigger_cover: _t.Cover | None,
    ) -> _pm.ProcessManagerHandleResponse:
        """A confirmed seat leads to spending the money."""
        if not _belongs(state, event.buy_in_id, Phase.PHASE_AWAITING_SEAT):
            return _respond()
        return _respond(
            _b.BuyInSeated(buy_in_id=state.buy_in_id, stack=event.stack),
            _to_player(state, _p.CaptureFunds(hold_id=state.buy_in_id)),
        )

    def funds_captured(
        self,
        event: _p.FundsCaptured,
        state: BuyInState,
        dests: _az.Destinations,
        trigger_cover: _t.Cover | None,
    ) -> _pm.ProcessManagerHandleResponse:
        """Spent money completes the buy-in."""
        if not _belongs(state, event.hold_id, Phase.PHASE_AWAITING_CAPTURE):
            return _respond()
        return _respond(_b.BuyInCompleted(buy_in_id=state.buy_in_id))

    def on_hold_funds_rejected(
        self, n: _t.Notification, rejection: _t.RejectionNotification, state: BuyInState
    ) -> _pm.ProcessManagerHandleResponse:
        """The wallet refused to hold the money: release the seat."""
        hold = unpack(rejection.rejected_command.pages[0].command, _p.HoldFunds)
        if not _belongs(state, hold.hold_id, Phase.PHASE_AWAITING_HOLD):
            return _respond()
        reason = rejection_code(rejection.rejection_reason)
        return _respond(
            _b.BuyInFailed(
                buy_in_id=state.buy_in_id,
                failed_in=Phase.PHASE_AWAITING_HOLD,
                reason=reason,
            ),
            _to_table(
                state, _table.ReleaseSeat(buy_in_id=state.buy_in_id, reason=reason)
            ),
        )

    def on_confirm_seat_rejected(
        self, n: _t.Notification, rejection: _t.RejectionNotification, state: BuyInState
    ) -> _pm.ProcessManagerHandleResponse:
        """The table refused the seat: release the money and the seat."""
        confirm = unpack(
            rejection.rejected_command.pages[0].command, _table.ConfirmSeat
        )
        if not _belongs(state, confirm.buy_in_id, Phase.PHASE_AWAITING_SEAT):
            return _respond()
        reason = rejection_code(rejection.rejection_reason)
        return _respond(
            _b.BuyInFailed(
                buy_in_id=state.buy_in_id,
                failed_in=Phase.PHASE_AWAITING_SEAT,
                reason=reason,
            ),
            _to_player(state, _p.ReleaseHold(hold_id=state.buy_in_id, reason=reason)),
            _to_table(
                state, _table.ReleaseSeat(buy_in_id=state.buy_in_id, reason=reason)
            ),
        )

    # endregion pm_handler

    # region pm_state
    def apply_buy_in_started(
        self, state: BuyInState, event: _b.BuyInStarted, ctx: _az.PageContext
    ) -> None:
        state.buy_in_id = event.buy_in_id
        state.player_root = event.player_root
        state.table_root = event.table_root
        state.seat = event.seat
        state.amount = event.amount
        state.phase = Phase.PHASE_AWAITING_HOLD

    def apply_buy_in_funds_held(
        self, state: BuyInState, event: _b.BuyInFundsHeld, ctx: _az.PageContext
    ) -> None:
        state.phase = Phase.PHASE_AWAITING_SEAT

    def apply_buy_in_seated(
        self, state: BuyInState, event: _b.BuyInSeated, ctx: _az.PageContext
    ) -> None:
        state.phase = Phase.PHASE_AWAITING_CAPTURE

    def apply_buy_in_completed(
        self, state: BuyInState, event: _b.BuyInCompleted, ctx: _az.PageContext
    ) -> None:
        state.phase = Phase.PHASE_COMPLETED

    def apply_buy_in_failed(
        self, state: BuyInState, event: _b.BuyInFailed, ctx: _az.PageContext
    ) -> None:
        state.phase = Phase.PHASE_FAILED
        state.failure_reason = event.reason

    # endregion pm_state
