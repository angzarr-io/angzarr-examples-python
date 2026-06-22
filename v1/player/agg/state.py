"""Player state dataclass and pure-function event appliers.

The live aggregate wiring (``@command_handler`` class + ``@handles`` /
``@applies`` / ``@rejected`` methods) lives in ``player/agg/main.py``.
This module keeps the state + appliers in pure-function form so they can
be reused from tests, projections, or docs snippets without going through
the router.

Lifecycle (buy-in / rebuy / registration) state moved to
``reservation/agg/state.py`` after the reservation refactor. Player now
owns only bankroll + per-key (table_root or tournament_root) reservations.
"""

from dataclasses import dataclass, field

from angzarr_client.proto.examples import player_pb2 as player


@dataclass
class PlayerState:
    """Player aggregate state."""

    player_id: str = ""
    display_name: str = ""
    email: str = ""
    player_type: int = 0
    ai_model_id: str = ""
    bankroll: int = 0
    reserved_funds: int = 0
    # Per-key (table_root or tournament_root) reservation amounts. Keys are
    # bytes-as-hex; values are the reserved amount.
    table_reservations: dict = field(default_factory=dict)
    status: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.player_id)

    @property
    def available_balance(self) -> int:
        return self.bankroll - self.reserved_funds


# --- Event appliers (pure functions) ---


def apply_registered(state: PlayerState, event: player.PlayerRegistered) -> None:
    """Initialize player state from registration event."""
    state.player_id = f"player_{event.email}"
    state.display_name = event.display_name
    state.email = event.email
    state.player_type = event.player_type
    state.ai_model_id = event.ai_model_id
    state.status = "active"


def apply_deposited(state: PlayerState, event: player.FundsDeposited) -> None:
    """Apply deposit to bankroll."""
    state.bankroll += event.amount.amount if event.HasField("amount") else 0


def apply_withdrawn(state: PlayerState, event: player.FundsWithdrawn) -> None:
    """Apply withdrawal from bankroll."""
    state.bankroll -= event.amount.amount if event.HasField("amount") else 0


def apply_reserved(state: PlayerState, event: player.FundsReserved) -> None:
    """Lock funds for a reservation key (table_root or tournament_root)."""
    amount = event.amount.amount if event.HasField("amount") else 0
    state.reserved_funds += amount
    bucket = event.key.hex()
    state.table_reservations[bucket] = state.table_reservations.get(bucket, 0) + amount


def apply_released(state: PlayerState, event: player.FundsReleased) -> None:
    """Release reserved funds back to bankroll."""
    amount = event.amount.amount if event.HasField("amount") else 0
    state.reserved_funds -= amount
    bucket = event.key.hex()
    state.table_reservations.pop(bucket, None)


def apply_transferred(state: PlayerState, event: player.FundsTransferred) -> None:
    """Apply transferred funds to recipient bankroll."""
    state.bankroll += event.amount.amount if event.HasField("amount") else 0


def apply_funds_deducted(state: PlayerState, event: player.FundsDeducted) -> None:
    """Settle a previously-reserved amount: bankroll AND reserved_funds drop.

    Called when the reservation PM issues DeductReservedFunds after a
    confirmed buy-in / rebuy / registration. Mirrors the old
    ``apply_buy_in_confirmed`` / ``apply_registration_confirmed`` /
    ``apply_rebuy_confirmed`` semantics, generalized to any reserved key.
    """
    amount = event.amount.amount if event.HasField("amount") else 0
    state.reserved_funds -= amount
    state.bankroll -= amount
    state.table_reservations.pop(event.key.hex(), None)


def build_state(state: PlayerState, events: list) -> PlayerState:
    """Build state from a list of Any-wrapped events.

    Args:
        state: Initial state to mutate.
        events: List of Any-wrapped protobuf events.

    Returns:
        The mutated state.
    """
    from google.protobuf.any_pb2 import Any as AnyProto

    _appliers = {
        "angzarr_client.proto.examples.PlayerRegistered": (
            player.PlayerRegistered,
            apply_registered,
        ),
        "angzarr_client.proto.examples.FundsDeposited": (
            player.FundsDeposited,
            apply_deposited,
        ),
        "angzarr_client.proto.examples.FundsWithdrawn": (
            player.FundsWithdrawn,
            apply_withdrawn,
        ),
        "angzarr_client.proto.examples.FundsReserved": (
            player.FundsReserved,
            apply_reserved,
        ),
        "angzarr_client.proto.examples.FundsReleased": (
            player.FundsReleased,
            apply_released,
        ),
        "angzarr_client.proto.examples.FundsTransferred": (
            player.FundsTransferred,
            apply_transferred,
        ),
        "angzarr_client.proto.examples.FundsDeducted": (
            player.FundsDeducted,
            apply_funds_deducted,
        ),
    }

    for event_any in events:
        if not isinstance(event_any, AnyProto):
            continue
        type_name = event_any.type_url.split("/")[-1]
        if type_name in _appliers:
            proto_cls, applier = _appliers[type_name]
            event = proto_cls()
            event_any.Unpack(event)
            applier(state, event)

    return state
