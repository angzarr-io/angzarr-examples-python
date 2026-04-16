"""Player aggregate package (functional handler pattern)."""

from .agg.handlers import (
    handle_deposit_funds,
    handle_register_player,
    handle_release_funds,
    handle_reserve_funds,
    handle_transfer_funds,
    handle_withdraw_funds,
)
from .agg.state import PlayerState, build_state

__all__ = [
    "PlayerState",
    "build_state",
    "handle_deposit_funds",
    "handle_register_player",
    "handle_release_funds",
    "handle_reserve_funds",
    "handle_transfer_funds",
    "handle_withdraw_funds",
]
