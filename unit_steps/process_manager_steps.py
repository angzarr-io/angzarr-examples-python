"""Process-manager unit steps — HandFlowProcessManager (hand-started slice).

Exercises the PROCESS MANAGER component type: a stateful handler dispatched with
a trigger event (via the FFI Router.dispatch_process_manager) that emits its new
flow state as a snapshot process-event. The Given steps build the source
HandStarted; the When dispatches it; the Then steps decode the emitted flow-state
snapshot and assert the phase, player count, and dealer.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."
_DEALING = 1


@given(
    "a hand has just started with dealer at position {dealer:d}, "
    "small blind {sb:d}, big blind {bb:d}"
)
def _given_hand_just_started(context, dealer, sb, bb):
    context.pm_event = table.HandStarted(
        hand_root=uuid_for("hand-1"),
        hand_number=1,
        dealer_position=dealer,
        small_blind=sb,
        big_blind=bb,
    )


@given("the seated players are:")
def _given_seated_players(context):
    for row in context.table:
        context.pm_event.active_players.add(
            position=int(row["position"]),
            player_root=uuid_for(row["player"]),
            stack=int(row["stack"]),
        )


@when("the hand is started")
def _when_hand_started(context):
    context.world.dispatch_process_manager("table", P + "HandStarted", context.pm_event)


def _folded_state(context):
    """Rebuild HandFlowState by folding the PM's emitted own-event through its
    applier — exercising the event-sourced path (the PM emits an event; the
    applier folds it), not just the snapshot."""
    if getattr(context, "flow_state", None) is None:
        event = context.world.process_event(P + "HandFlowStarted", hand.HandFlowStarted())
        state = hand.HandFlowState()
        context.world.hand_flow_pm.apply_hand_flow_started(state, event)
        context.flow_state = state
    return context.flow_state


@then("the hand is in the dealing phase")
def _then_dealing_phase(context):
    assert _folded_state(context).phase == _DEALING, "phase is not DEALING"


@then("the hand has {n:d} players")
def _then_player_count(context, n):
    assert _folded_state(context).player_count == n


@then("the dealer is at position {n:d}")
def _then_dealer_position(context, n):
    assert _folded_state(context).dealer_position == n
