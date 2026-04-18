"""Player bounded context gRPC server.

Uses the unified Router API with the @command_handler class decorator.
"""

import structlog

from angzarr_client import (
    CommandHandlerGrpc,
    Router,
    applies,
    command_handler,
    configure_logging,
    handles,
    rejected,
    run_server,
)
from angzarr_client.proto.angzarr import command_handler_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from angzarr_client import now

from .handlers import (
    handle_deposit_funds,
    handle_register_player,
    handle_release_funds,
    handle_reserve_funds,
    handle_transfer_funds,
    handle_withdraw_funds,
)
from .state import (
    PlayerState,
    apply_deposited,
    apply_registered,
    apply_released,
    apply_reserved,
    apply_transferred,
    apply_withdrawn,
)


# docs:start:command_router
@command_handler(domain="player", state=PlayerState)
class PlayerAggregate:
    """Player aggregate - dispatches commands and applies events."""

    # --- Command handlers ---

    @handles(player.RegisterPlayer)
    def on_register_player(
        self, cmd: player.RegisterPlayer, state: PlayerState, seq: int
    ) -> player.PlayerRegistered:
        return handle_register_player(cmd, state)

    @handles(player.DepositFunds)
    def on_deposit_funds(
        self, cmd: player.DepositFunds, state: PlayerState, seq: int
    ) -> player.FundsDeposited:
        return handle_deposit_funds(cmd, state)

    @handles(player.WithdrawFunds)
    def on_withdraw_funds(
        self, cmd: player.WithdrawFunds, state: PlayerState, seq: int
    ) -> player.FundsWithdrawn:
        return handle_withdraw_funds(cmd, state)

    @handles(player.ReserveFunds)
    def on_reserve_funds(
        self, cmd: player.ReserveFunds, state: PlayerState, seq: int
    ) -> player.FundsReserved:
        return handle_reserve_funds(cmd, state)

    @handles(player.ReleaseFunds)
    def on_release_funds(
        self, cmd: player.ReleaseFunds, state: PlayerState, seq: int
    ) -> player.FundsReleased:
        return handle_release_funds(cmd, state)

    @handles(player.TransferFunds)
    def on_transfer_funds(
        self, cmd: player.TransferFunds, state: PlayerState, seq: int
    ) -> player.FundsTransferred:
        return handle_transfer_funds(cmd, state)

    # --- Event appliers ---

    @applies(player.PlayerRegistered)
    def _apply_registered(
        self, state: PlayerState, event: player.PlayerRegistered
    ) -> None:
        apply_registered(state, event)

    @applies(player.FundsDeposited)
    def _apply_deposited(
        self, state: PlayerState, event: player.FundsDeposited
    ) -> None:
        apply_deposited(state, event)

    @applies(player.FundsWithdrawn)
    def _apply_withdrawn(
        self, state: PlayerState, event: player.FundsWithdrawn
    ) -> None:
        apply_withdrawn(state, event)

    @applies(player.FundsReserved)
    def _apply_reserved(
        self, state: PlayerState, event: player.FundsReserved
    ) -> None:
        apply_reserved(state, event)

    @applies(player.FundsReleased)
    def _apply_released(
        self, state: PlayerState, event: player.FundsReleased
    ) -> None:
        apply_released(state, event)

    @applies(player.FundsTransferred)
    def _apply_transferred(
        self, state: PlayerState, event: player.FundsTransferred
    ) -> None:
        apply_transferred(state, event)

    # --- Rejection handlers (compensation) ---

    # docs:start:rejected_handler
    @rejected("table", "JoinTable")
    def on_join_table_rejected(
        self, notification: types.Notification, state: PlayerState
    ) -> player.FundsReleased | None:
        """Handle JoinTable rejection by releasing reserved funds.

        Called when the JoinTable command (issued by saga-player-table after
        FundsReserved) is rejected by the Table aggregate.
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


# Build the router with the aggregate handler instance.
router = Router("player").with_handler(PlayerAggregate()).build()
# docs:end:command_router


if __name__ == "__main__":
    configure_logging()
    logger = structlog.get_logger()
    servicer = CommandHandlerGrpc(router)
    run_server(
        command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
        servicer,
        service_name="player-agg",
        domain="player",
        default_port="50301",
        logger=logger,
    )
