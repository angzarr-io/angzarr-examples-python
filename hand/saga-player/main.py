"""Saga: Hand -> Player

Reacts to PotAwarded events from Hand domain.
Sends DepositFunds commands to Player domain.

Uses the OO-style Saga pattern with @handles decorators.
"""

import structlog

from angzarr_client import Destinations, now
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.saga import Saga, domain, handles, output_domain, run_saga_server

from google.protobuf.any_pb2 import Any as ProtoAny

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@domain("hand")
@output_domain("player")
class HandPlayerSaga(Saga):
    """Saga that translates PotAwarded events to DepositFunds commands.

    Produces multiple commands (one per winner). The Player aggregate
    validates deposit operations.
    """

    name = "saga-hand-player"

    @handles(hand.PotAwarded)
    def handle_pot_awarded(
        self,
        event: hand.PotAwarded,
        destinations: Destinations = None,
    ) -> None:
        """Translate PotAwarded -> DepositFunds for each winner."""
        for winner in event.winners:
            deposit_funds = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount,
                    currency_code="CHIPS",
                ),
            )
            self.emit_command("player", winner.player_root, deposit_funds)


if __name__ == "__main__":
    run_saga_server(HandPlayerSaga, "50414", logger=logger)
