"""Player state dataclass and pure-function event appliers.

The live aggregate wiring (``@command_handler`` class + ``@handles`` /
``@applies`` / ``@rejected`` methods) lives in ``player/agg/main.py``.
This module keeps the state + appliers in pure-function form so they can
be reused from tests, projections, or docs snippets without going through
the router.
"""

from dataclasses import dataclass, field

from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration


@dataclass
class PendingBuyIn:
    """In-flight buy-in request awaiting Table acceptance."""

    table_root: bytes = b""
    seat: int = 0
    amount: int = 0


@dataclass
class PendingRegistration:
    """In-flight tournament-registration request awaiting Tournament enrollment."""

    tournament_root: bytes = b""
    fee: int = 0


@dataclass
class PendingRebuy:
    """In-flight rebuy request awaiting Tournament approval + Table chip add."""

    tournament_root: bytes = b""
    table_root: bytes = b""
    seat: int = 0
    fee: int = 0
    chips_to_add: int = 0


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
    table_reservations: dict = field(default_factory=dict)
    status: str = ""
    # Pending cross-aggregate orchestrations, keyed by reservation_id hex.
    pending_buy_ins: dict[str, PendingBuyIn] = field(default_factory=dict)
    pending_registrations: dict[str, PendingRegistration] = field(default_factory=dict)
    pending_rebuys: dict[str, PendingRebuy] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return bool(self.player_id)

    @property
    def available_balance(self) -> int:
        return self.bankroll - self.reserved_funds


# --- Event appliers (pure functions) ---


# docs:start:state_router
def apply_registered(state: PlayerState, event: player.PlayerRegistered) -> None:
    """Apply PlayerRegistered event to state."""
    state.player_id = f"player_{event.email}"
    state.display_name = event.display_name
    state.email = event.email
    state.player_type = event.player_type
    state.ai_model_id = event.ai_model_id
    state.status = "active"
    state.bankroll = 0
    state.reserved_funds = 0


def apply_deposited(state: PlayerState, event: player.FundsDeposited) -> None:
    """Apply FundsDeposited event to state."""
    if event.new_balance:
        state.bankroll = event.new_balance.amount


def apply_withdrawn(state: PlayerState, event: player.FundsWithdrawn) -> None:
    """Apply FundsWithdrawn event to state."""
    if event.new_balance:
        state.bankroll = event.new_balance.amount


def apply_reserved(state: PlayerState, event: player.FundsReserved) -> None:
    """Apply FundsReserved event to state."""
    if event.new_reserved_balance:
        state.reserved_funds = event.new_reserved_balance.amount
    if event.table_root and event.amount:
        table_key = event.table_root.hex()
        state.table_reservations[table_key] = event.amount.amount


def apply_released(state: PlayerState, event: player.FundsReleased) -> None:
    """Apply FundsReleased event to state."""
    if event.new_reserved_balance:
        state.reserved_funds = event.new_reserved_balance.amount
    if event.table_root:
        table_key = event.table_root.hex()
        state.table_reservations.pop(table_key, None)


def apply_transferred(state: PlayerState, event: player.FundsTransferred) -> None:
    """Apply FundsTransferred event to state."""
    if event.new_balance:
        state.bankroll = event.new_balance.amount


# --- Buy-in orchestration appliers ---


def apply_buy_in_requested(state: PlayerState, event: buy_in.BuyInRequested) -> None:
    """Reserve funds for a pending buy-in."""
    reservation_hex = event.reservation_id.hex()
    amount = event.amount.amount if event.HasField("amount") else 0
    state.reserved_funds += amount
    state.pending_buy_ins[reservation_hex] = PendingBuyIn(
        table_root=event.table_root,
        seat=event.seat,
        amount=amount,
    )


def apply_buy_in_confirmed(state: PlayerState, event: buy_in.BuyInConfirmed) -> None:
    """Move reserved funds out of the bankroll into the table."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_buy_ins.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.amount
    table_key = pending.table_root.hex()
    state.table_reservations[table_key] = pending.amount
    state.bankroll -= pending.amount


def apply_buy_in_released(
    state: PlayerState, event: buy_in.BuyInReservationReleased
) -> None:
    """Return reserved funds on a released buy-in."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_buy_ins.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.amount


# --- Registration orchestration appliers ---


def apply_registration_requested(
    state: PlayerState, event: registration.RegistrationRequested
) -> None:
    """Reserve the registration fee."""
    reservation_hex = event.reservation_id.hex()
    fee = event.fee.amount if event.HasField("fee") else 0
    state.reserved_funds += fee
    state.pending_registrations[reservation_hex] = PendingRegistration(
        tournament_root=event.tournament_root,
        fee=fee,
    )


def apply_registration_confirmed(
    state: PlayerState, event: registration.RegistrationFeeConfirmed
) -> None:
    """Deduct the registration fee from bankroll + reserved."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_registrations.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.fee
    state.bankroll -= pending.fee


def apply_registration_released(
    state: PlayerState, event: registration.RegistrationFeeReleased
) -> None:
    """Return the reserved registration fee."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_registrations.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.fee


# --- Rebuy orchestration appliers ---


def apply_rebuy_requested(state: PlayerState, event: rebuy.RebuyRequested) -> None:
    """Reserve the rebuy fee."""
    reservation_hex = event.reservation_id.hex()
    fee = event.fee.amount if event.HasField("fee") else 0
    state.reserved_funds += fee
    state.pending_rebuys[reservation_hex] = PendingRebuy(
        tournament_root=event.tournament_root,
        table_root=event.table_root,
        seat=event.seat,
        fee=fee,
        chips_to_add=0,
    )


def apply_rebuy_confirmed(state: PlayerState, event: rebuy.RebuyFeeConfirmed) -> None:
    """Deduct the rebuy fee from bankroll + reserved."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_rebuys.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.fee
    state.bankroll -= pending.fee


def apply_rebuy_released(state: PlayerState, event: rebuy.RebuyFeeReleased) -> None:
    """Return the reserved rebuy fee."""
    reservation_hex = event.reservation_id.hex()
    pending = state.pending_rebuys.pop(reservation_hex, None)
    if pending is None:
        return
    state.reserved_funds -= pending.fee


# docs:end:state_router


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
        "examples.PlayerRegistered": (player.PlayerRegistered, apply_registered),
        "examples.FundsDeposited": (player.FundsDeposited, apply_deposited),
        "examples.FundsWithdrawn": (player.FundsWithdrawn, apply_withdrawn),
        "examples.FundsReserved": (player.FundsReserved, apply_reserved),
        "examples.FundsReleased": (player.FundsReleased, apply_released),
        "examples.FundsTransferred": (player.FundsTransferred, apply_transferred),
        # Buy-in orchestration
        "examples.BuyInRequested": (buy_in.BuyInRequested, apply_buy_in_requested),
        "examples.BuyInConfirmed": (buy_in.BuyInConfirmed, apply_buy_in_confirmed),
        "examples.BuyInReservationReleased": (
            buy_in.BuyInReservationReleased,
            apply_buy_in_released,
        ),
        # Registration orchestration
        "examples.RegistrationRequested": (
            registration.RegistrationRequested,
            apply_registration_requested,
        ),
        "examples.RegistrationFeeConfirmed": (
            registration.RegistrationFeeConfirmed,
            apply_registration_confirmed,
        ),
        "examples.RegistrationFeeReleased": (
            registration.RegistrationFeeReleased,
            apply_registration_released,
        ),
        # Rebuy orchestration
        "examples.RebuyRequested": (rebuy.RebuyRequested, apply_rebuy_requested),
        "examples.RebuyFeeConfirmed": (
            rebuy.RebuyFeeConfirmed,
            apply_rebuy_confirmed,
        ),
        "examples.RebuyFeeReleased": (rebuy.RebuyFeeReleased, apply_rebuy_released),
    }

    for event_any in events:
        if not isinstance(event_any, AnyProto):
            continue
        # Extract type name from type_url (e.g., "type.googleapis.com/examples.PlayerRegistered")
        type_name = event_any.type_url.split("/")[-1]
        if type_name in _appliers:
            proto_cls, applier = _appliers[type_name]
            event = proto_cls()
            event_any.Unpack(event)
            applier(state, event)

    return state
