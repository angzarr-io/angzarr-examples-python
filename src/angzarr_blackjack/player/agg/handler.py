"""The PlayerAggregate on the generated ``PlayerAggregateHandler`` seam.

The wallet's rules live in :mod:`.logic` as pure functions; this class wires
each command to its guard/validate/compute triple, each event to its applier,
and implements the compensation, undo and fact handlers.
"""

from __future__ import annotations

from collections.abc import Callable

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import event_book, unpack
from angzarr_blackjack.errors import rejection_code
from angzarr_blackjack.player.agg import logic as L


def _run(
    guard: Callable,
    validate: Callable,
    compute: Callable,
    cmd,
    state: _p.PlayerState,
) -> _t.EventBook | None:
    guard(state)
    effect = validate(cmd, state)
    events = compute(cmd, state, effect)
    return event_book(*events) if events else None


def _response(events: list) -> _ch.BusinessResponse | None:
    return _ch.BusinessResponse(events=event_book(*events)) if events else None


class PlayerAggregate:
    """Implements ``PlayerAggregateHandler``: the wallet."""

    # --- commands ---

    def register_player(self, cmd: _p.RegisterPlayer, state, cctx: _az.CommandContext):
        return _run(
            L.guard_not_registered, L.validate_register, L.compute_register, cmd, state
        )

    def import_player(self, cmd: _p.ImportPlayer, state, cctx: _az.CommandContext):
        return _run(
            L.guard_not_registered, L.validate_import, L.compute_import, cmd, state
        )

    def update_profile(self, cmd: _p.UpdateProfile, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered,
            L.validate_update_profile,
            L.compute_update_profile,
            cmd,
            state,
        )

    def deposit_funds(self, cmd: _p.DepositFunds, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered, L.validate_deposit, L.compute_deposit, cmd, state
        )

    def withdraw_funds(self, cmd: _p.WithdrawFunds, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered, L.validate_withdraw, L.compute_withdraw, cmd, state
        )

    def request_top_up(self, cmd: _p.RequestTopUp, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered,
            L.validate_request_top_up,
            L.compute_request_top_up,
            cmd,
            state,
        )

    def enroll_loyalty(self, cmd: _p.EnrollLoyalty, state, cctx: _az.CommandContext):
        return _run(L.guard_registered, L.validate_enroll, L.compute_enroll, cmd, state)

    def hold_funds(self, cmd: _p.HoldFunds, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered, L.validate_hold_funds, L.compute_hold_funds, cmd, state
        )

    def capture_funds(self, cmd: _p.CaptureFunds, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered, L.validate_capture, L.compute_capture, cmd, state
        )

    def release_hold(self, cmd: _p.ReleaseHold, state, cctx: _az.CommandContext):
        return _run(
            L.guard_registered, L.validate_release, L.compute_release, cmd, state
        )

    def record_round_result(
        self, cmd: _p.RecordRoundResult, state, cctx: _az.CommandContext
    ):
        return _run(
            L.guard_registered,
            L.validate_record_result,
            L.compute_record_result,
            cmd,
            state,
        )

    def award_loyalty_points(
        self, cmd: _p.AwardLoyaltyPoints, state, cctx: _az.CommandContext
    ):
        return _run(L.guard_registered, L.validate_award, L.compute_award, cmd, state)

    # --- compensation: the table refused a top-up ---

    # region rejected_handler
    def on_add_chips_rejected(
        self,
        n: _t.Notification,
        rejection: _t.RejectionNotification,
        state: _p.PlayerState,
        cctx: _az.CommandContext,
    ) -> _ch.BusinessResponse | None:
        """Release the top-up's hold. The refusal is matched by hold id against
        the wallet as it is now; a hold already settled or refused is left alone."""
        add_chips = unpack(rejection.rejected_command.pages[0].command, _table.AddChips)
        reason = rejection_code(rejection.rejection_reason)
        return _response(L.compute_top_up_refused(add_chips.hold_id, reason, state))

    # endregion rejected_handler

    # --- undo: a CASCADE_ERROR_COMPENSATE request undid a recorded round result ---

    def on_record_round_result_undo(
        self,
        n: _t.Notification,
        compensate: _t.Compensate,
        state: _p.PlayerState,
        cctx: _az.CommandContext,
    ) -> _ch.BusinessResponse | None:
        """Retract the round results recorded by the events at the sequences
        the Compensate names."""
        return _response(L.compute_retract_results(compensate.sequences, state))

    # --- facts from the table (handle_fact: annotate, never refuse) ---

    def handle_top_up_settled(self, fact: _p.TopUpSettled, state: _p.PlayerState):
        return L.check_top_up_settled(fact, state)

    def handle_cash_out_credited(self, fact: _p.CashOutCredited, state: _p.PlayerState):
        return fact

    # --- appliers ---

    def apply_player_registered(self, state, event):
        L.apply_registered(state, event)

    def apply_player_imported(self, state, event):
        L.apply_imported(state, event)

    def apply_profile_updated(self, state, event):
        L.apply_profile_updated(state, event)

    def apply_funds_deposited(self, state, event):
        L.apply_deposited(state, event)

    def apply_funds_withdrawn(self, state, event):
        L.apply_withdrawn(state, event)

    def apply_funds_held(self, state, event):
        L.apply_funds_held(state, event)

    def apply_funds_captured(self, state, event):
        L.apply_funds_captured(state, event)

    def apply_hold_released(self, state, event):
        L.apply_hold_released(state, event)

    def apply_top_up_requested(self, state, event):
        L.apply_top_up_requested(state, event)

    def apply_top_up_refused(self, state, event):
        L.apply_top_up_refused(state, event)

    def apply_top_up_settled(self, state, event):
        L.apply_top_up_settled(state, event)

    def apply_cash_out_credited(self, state, event):
        L.apply_cash_out_credited(state, event)

    def apply_loyalty_enrolled(self, state, event):
        L.apply_loyalty_enrolled(state, event)

    def apply_round_result_recorded(self, state, event):
        L.apply_round_result_recorded(state, event, _az.current_page().sequence)

    def apply_round_result_retracted(self, state, event):
        L.apply_round_result_retracted(state, event)

    def apply_loyalty_points_awarded(self, state, event):
        L.apply_loyalty_points_awarded(state, event)
