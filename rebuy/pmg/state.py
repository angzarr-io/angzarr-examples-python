"""Rebuy PM state management."""

from dataclasses import dataclass

from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import rebuy_pb2 as rebuy


@dataclass
class RebuyState:
    """Rebuy process manager state."""

    reservation_id: bytes = b""
    player_root: bytes = b""
    tournament_root: bytes = b""
    table_root: bytes = b""
    seat: int = -1
    fee: int = 0
    chips_to_add: int = 0
    phase: int = orch.RebuyPhase.REBUY_PHASE_UNSPECIFIED

    @property
    def is_initialized(self) -> bool:
        """Check if this PM instance has been initialized."""
        return bool(self.reservation_id)


# --- Event appliers ---


def apply_rebuy_initiated(state: RebuyState, event: rebuy.RebuyInitiated) -> None:
    """Apply RebuyInitiated event to state."""
    state.phase = event.phase
    state.fee = event.fee.amount if event.HasField("fee") else 0
    state.chips_to_add = event.chips_to_add
    state.reservation_id = event.reservation_id
    state.player_root = event.player_root
    state.tournament_root = event.tournament_root
    state.table_root = event.table_root
    state.seat = event.seat


def apply_rebuy_phase_changed(
    state: RebuyState, event: rebuy.RebuyPhaseChanged
) -> None:
    """Apply RebuyPhaseChanged event to state."""
    state.phase = event.to_phase


def apply_rebuy_completed(state: RebuyState, _event: rebuy.RebuyCompleted) -> None:
    """Apply RebuyCompleted event to state."""
    state.phase = orch.RebuyPhase.REBUY_COMPLETED


def apply_rebuy_failed(state: RebuyState, _event: rebuy.RebuyFailed) -> None:
    """Apply RebuyFailed event to state."""
    state.phase = orch.RebuyPhase.REBUY_FAILED
