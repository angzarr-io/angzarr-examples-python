"""Registration PM state management."""

from dataclasses import dataclass

from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import registration_pb2 as registration


@dataclass
class RegistrationState:
    """Registration process manager state."""

    reservation_id: bytes = b""
    player_root: bytes = b""
    tournament_root: bytes = b""
    fee: int = 0
    starting_stack: int = 0
    phase: int = orch.RegistrationPhase.REGISTRATION_PHASE_UNSPECIFIED

    @property
    def is_initialized(self) -> bool:
        """Check if this PM instance has been initialized."""
        return bool(self.reservation_id)


# --- Event appliers ---


def apply_registration_initiated(
    state: RegistrationState, event: registration.RegistrationInitiated
) -> None:
    """Apply RegistrationInitiated event to state."""
    state.phase = event.phase
    state.fee = event.fee.amount if event.HasField("fee") else 0
    state.reservation_id = event.reservation_id
    state.player_root = event.player_root
    state.tournament_root = event.tournament_root


def apply_registration_phase_changed(
    state: RegistrationState, event: registration.RegistrationPhaseChanged
) -> None:
    """Apply RegistrationPhaseChanged event to state."""
    state.phase = event.to_phase


def apply_registration_completed(
    state: RegistrationState, event: registration.RegistrationCompleted
) -> None:
    """Apply RegistrationCompleted event to state."""
    state.phase = orch.RegistrationPhase.REGISTRATION_COMPLETED
    state.starting_stack = event.starting_stack


def apply_registration_failed(
    state: RegistrationState, _event: registration.RegistrationFailed
) -> None:
    """Apply RegistrationFailed event to state."""
    state.phase = orch.RegistrationPhase.REGISTRATION_FAILED
