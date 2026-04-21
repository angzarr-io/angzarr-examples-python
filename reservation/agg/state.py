"""Reservation aggregate state — pending records for the three lifecycle
flavors (buy-in, rebuy, registration).

The reservation aggregate owns *only* the lifecycle records. It does not
hold bankroll. Funds live on the player aggregate; this aggregate's
``Initiate*`` handlers do a sync DECISION query against player to gate
on ``available_balance`` before emitting the request event.
"""

from dataclasses import dataclass, field


@dataclass
class PendingBuyIn:
    """In-flight buy-in awaiting Table acceptance."""

    player_root: bytes = b""
    table_root: bytes = b""
    seat: int = 0
    amount: int = 0


@dataclass
class PendingRegistration:
    """In-flight tournament-registration awaiting Tournament enrollment."""

    player_root: bytes = b""
    tournament_root: bytes = b""
    fee: int = 0


@dataclass
class PendingRebuy:
    """In-flight rebuy awaiting Tournament approval + Table chip add."""

    player_root: bytes = b""
    tournament_root: bytes = b""
    table_root: bytes = b""
    seat: int = 0
    fee: int = 0


@dataclass
class ReservationState:
    """Reservation aggregate state — three pending dicts keyed by reservation_id hex."""

    pending_buy_ins: dict[str, PendingBuyIn] = field(default_factory=dict)
    pending_registrations: dict[str, PendingRegistration] = field(default_factory=dict)
    pending_rebuys: dict[str, PendingRebuy] = field(default_factory=dict)
