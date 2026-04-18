"""Rejection handler helpers (legacy standalone entry point).

The live rejection handler is now a ``@rejected`` method on
``PlayerAggregate`` in ``player/agg/main.py``. This module retains the
pure-function form for reuse in documentation examples and any non-router
code paths that construct a FundsReleased event from a rejected JoinTable.
"""

from .state import PlayerState

from angzarr_client import now
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types


# docs:start:rejected_handler
def handle_table_join_rejected(
    notification: types.Notification,
    state: PlayerState,
) -> player.FundsReleased | None:
    """Handle JoinTable rejection by releasing reserved funds.

    Returns the FundsReleased event directly (packed into an EventBook by the
    router) or ``None`` if no reservation exists for the rejected table.
    """
    rejection = types.RejectionNotification()
    if notification.HasField("payload"):
        notification.payload.Unpack(rejection)

    table_root = b""
    if rejection.HasField("rejected_command"):
        rc = rejection.rejected_command
        if rc.HasField("cover") and rc.cover.HasField("root"):
            table_root = rc.cover.root.value

    table_key = table_root.hex()
    reserved_amount = state.table_reservations.get(table_key, 0)
    if reserved_amount == 0:
        return None
    new_reserved = state.reserved_funds - reserved_amount
    new_available = state.bankroll - new_reserved

    return player.FundsReleased(
        amount=poker_types.Currency(amount=reserved_amount, currency_code="CHIPS"),
        table_root=table_root,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        released_at=now(),
    )


# docs:end:rejected_handler
