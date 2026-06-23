"""HandFlowProcessManager — tracks a hand's lifecycle phase (event-sourced).

A process manager is stateful and event-sourced: it folds its OWN prior events
into ``HandFlowState`` (via appliers) and reacts to triggers from the table/hand
domains. On a HandStarted trigger it emits ``HandFlowStarted`` — its own event —
which the applier folds into the DEALING phase (capturing the player count and
dealer). The emission also carries a state snapshot to augment rebuild. So the
PM receives events, emits events, and augments with snapshots — it does not
carry state out-of-band.

Implements the generated ``HandFlowProcessManagerHandler`` seam. Only the
hand-started transition is ported in this slice; cards_dealt / hand_complete
raise NotImplementedError until their phases are ported.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as _hand
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_poker._gen.io.angzarr.examples.v1.hand_flow_process_manager_angzarr import (
    HandFlowProcessManagerHandler,
)

# HandFlowState.phase values (mirrors the proto comment).
_AWAITING_DEAL, _DEALING, _BLINDS, _BETTING, _COMPLETE = range(5)


class HandFlowProcessManager:
    """Implements ``HandFlowProcessManagerHandler`` (hand-started slice)."""

    # --- triggers (react to other domains, emit own events) ---

    def hand_started(
        self,
        event: _table.HandStarted,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        flow_event = _hand.HandFlowStarted(
            hand_root=event.hand_root,
            player_count=len(event.active_players),
            dealer_position=event.dealer_position,
        )
        # The state after folding the event — emitted alongside as a snapshot
        # so rebuild can fast-path without replaying. (Same applier the core
        # uses on rebuild.)
        folded = _hand.HandFlowState()
        self.apply_hand_flow_started(folded, flow_event)

        resp = _pm.ProcessManagerHandleResponse()
        book = resp.process_events.add()
        book.cover.domain = "hand"
        book.pages.add().event.CopyFrom(_az.pack(flow_event))
        book.snapshot.state.CopyFrom(_az.pack(folded))
        return resp

    # --- appliers (fold own events into state; used on rebuild) ---

    def apply_hand_flow_started(
        self, state: _hand.HandFlowState, event: _hand.HandFlowStarted
    ) -> None:
        state.hand_root = event.hand_root
        state.phase = _DEALING
        state.player_count = event.player_count
        state.dealer_position = event.dealer_position

    # --- not-yet-ported phases ---

    def cards_dealt(self, event, state, dests):
        raise NotImplementedError("cards_dealt phase not ported")

    def hand_complete(self, event, state, dests):
        raise NotImplementedError("hand_complete phase not ported")


_: HandFlowProcessManagerHandler = HandFlowProcessManager()
