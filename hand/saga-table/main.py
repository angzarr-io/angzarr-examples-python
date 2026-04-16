"""Saga: Hand -> Table

Reacts to HandComplete events from Hand domain.
Sends EndHand commands to Table domain.

Uses the OO-style Saga pattern with @handles decorators.
"""

import structlog

from angzarr_client import Destinations, now
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table
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
@output_domain("table")
class HandTableSaga(Saga):
    """Saga that translates HandComplete events to EndHand commands.

    When a hand completes, the Table aggregate needs to update its state
    with the results.
    """

    name = "saga-hand-table"

    @handles(hand.HandComplete)
    def handle_hand_complete(
        self,
        event: hand.HandComplete,
        destinations: Destinations = None,
    ) -> None:
        """Translate HandComplete -> EndHand."""
        results = [
            table.PotResult(
                winner_root=winner.player_root,
                amount=winner.amount,
                pot_type=winner.pot_type,
                winning_hand=winner.winning_hand,
            )
            for winner in event.winners
        ]

        end_hand = table.EndHand(
            hand_root=self._current_root,
        )
        end_hand.results.extend(results)

        self.emit_command("table", event.table_root, end_hand)


if __name__ == "__main__":
    run_saga_server(HandTableSaga, "50412", logger=logger)
