"""Reservation PM state.

One unified state for buy-in / rebuy / registration flows. Instances are
keyed by ``reservation_id`` (the PM framework creates one per flow); the
``kind`` field discriminates the three flavors so a single PM can carry
them all without three separate state classes.
"""

from dataclasses import dataclass

from angzarr_client.proto.examples import orchestration_pb2 as orch

KIND_UNSPECIFIED = ""
KIND_BUY_IN = "buy_in"
KIND_REBUY = "rebuy"
KIND_REGISTRATION = "registration"


@dataclass
class ReservationPMState:
    """Unified PM state for the three lifecycle flows."""

    reservation_id: bytes = b""
    kind: str = KIND_UNSPECIFIED
    player_root: bytes = b""
    table_root: bytes = b""
    tournament_root: bytes = b""
    seat: int = -1
    amount: int = 0
    fee: int = 0
    # Phase is typed loosely — we stash whichever of the three enum values
    # is relevant for this flow's kind.
    phase: int = 0

    @property
    def is_initialized(self) -> bool:
        return bool(self.reservation_id)

    @property
    def reservation_key(self) -> bytes:
        """The bytes we pass in ReserveFunds.key / DeductReservedFunds.key.

        Buy-in and rebuy reserve against the ``table_root``. Registration
        reserves against the ``tournament_root`` since there's no table yet.
        """
        if self.kind == KIND_REGISTRATION:
            return self.tournament_root
        return self.table_root


__all__ = [
    "KIND_UNSPECIFIED",
    "KIND_BUY_IN",
    "KIND_REBUY",
    "KIND_REGISTRATION",
    "ReservationPMState",
    "orch",
]
