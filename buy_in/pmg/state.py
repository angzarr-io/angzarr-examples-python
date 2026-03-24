"""Buy-in PM state management.

This file defines the buy-in PM state and event appliers as pure functions.
"""

from dataclasses import dataclass

from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch


@dataclass
class BuyInState:
    """Buy-in process manager state."""

    reservation_id: bytes = b""
    player_root: bytes = b""
    table_root: bytes = b""
    seat: int = -1
    amount: int = 0
    phase: int = orch.BuyInPhase.BUY_IN_PHASE_UNSPECIFIED

    @property
    def is_initialized(self) -> bool:
        """Check if this PM instance has been initialized."""
        return bool(self.reservation_id)


# --- Event appliers ---


def apply_buy_in_initiated(state: BuyInState, event: buy_in.BuyInInitiated) -> None:
    """Apply BuyInInitiated event to state."""
    state.phase = event.phase
    state.amount = event.amount.amount if event.HasField("amount") else 0
    state.reservation_id = event.reservation_id
    state.player_root = event.player_root
    state.table_root = event.table_root
    state.seat = event.seat


def apply_buy_in_phase_changed(
    state: BuyInState, event: buy_in.BuyInPhaseChanged
) -> None:
    """Apply BuyInPhaseChanged event to state."""
    state.phase = event.to_phase


def apply_buy_in_completed(state: BuyInState, _event: buy_in.BuyInCompleted) -> None:
    """Apply BuyInCompleted event to state."""
    state.phase = orch.BuyInPhase.BUY_IN_COMPLETED


def apply_buy_in_failed(state: BuyInState, _event: buy_in.BuyInFailed) -> None:
    """Apply BuyInFailed event to state."""
    state.phase = orch.BuyInPhase.BUY_IN_FAILED


def build_state(pages: list) -> BuyInState:
    """Build state from a list of event pages.

    Args:
        pages: List of EventPage objects.

    Returns:
        The built state.
    """
    state = BuyInState()

    _appliers = {
        "examples.BuyInInitiated": (buy_in.BuyInInitiated, apply_buy_in_initiated),
        "examples.BuyInPhaseChanged": (
            buy_in.BuyInPhaseChanged,
            apply_buy_in_phase_changed,
        ),
        "examples.BuyInCompleted": (buy_in.BuyInCompleted, apply_buy_in_completed),
        "examples.BuyInFailed": (buy_in.BuyInFailed, apply_buy_in_failed),
    }

    for page in pages:
        if not page.HasField("event"):
            continue
        event_any = page.event
        type_name = event_any.type_url.split("/")[-1]
        if type_name in _appliers:
            proto_cls, applier = _appliers[type_name]
            event = proto_cls()
            event_any.Unpack(event)
            applier(state, event)

    return state
