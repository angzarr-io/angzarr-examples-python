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


# region rejected_handler
def handle_table_join_rejected(
    notification: types.Notification,
    state: PlayerState,
) -> player.FundsReleased:
    """Handle JoinTable rejection by releasing reserved funds.

    Always returns a FundsReleased event — ``amount`` is zero when no
    reservation exists for the rejected table, so downstream read-models
    still see a correlated compensation record.
    """
    rejection = types.RejectionNotification()
    if notification.HasField("payload"):
        notification.payload.Unpack(rejection)

    key = b""
    if rejection.HasField("rejected_command"):
        rc = rejection.rejected_command
        if rc.HasField("cover") and rc.cover.HasField("root"):
            key = rc.cover.root.value

    bucket = key.hex()
    reserved_amount = state.table_reservations.get(bucket, 0)
    new_reserved = state.reserved_funds - reserved_amount
    new_available = state.bankroll - new_reserved

    return player.FundsReleased(
        amount=poker_types.Currency(amount=reserved_amount, currency_code="CHIPS"),
        key=key,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        released_at=now(),
    )


# endregion
