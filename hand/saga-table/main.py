"""Saga: Hand -> Table (unified Router API).

Reacts to HandComplete events from Hand domain and emits an EndHand command
to the Table domain.
"""

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Destinations, Router, SagaGrpc, handles, run_server, saga
from angzarr_client.proto.angzarr import saga_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table

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


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


@saga(name="saga-hand-table", source="hand", target="table")
class HandTableSaga:
    """Saga that translates HandComplete events to EndHand commands."""

    @handles(hand.HandComplete)
    def handle_hand_complete(
        self, event: hand.HandComplete, destinations: Destinations
    ) -> types.CommandBook:
        results = [
            table.PotResult(
                winner_root=winner.player_root,
                amount=winner.amount,
                pot_type=winner.pot_type,
                winning_hand=winner.winning_hand,
            )
            for winner in event.winners
        ]

        # TODO(saga-source-context): the unified saga dispatch does not expose
        # the source event book's cover root. ``event.table_root`` is present
        # on HandComplete, so we use it here as the target root; previously
        # this saga stamped ``self._current_root`` (the source root), which
        # equalled the hand aggregate root. EndHand.hand_root below preserves
        # the hand_root via the event itself — EndHand expects it as the
        # source hand identifier.
        end_hand = table.EndHand()
        end_hand.results.extend(results)

        seq = destinations.sequence_for("table") if destinations else 0
        seq = seq if seq is not None else 0

        return types.CommandBook(
            cover=types.Cover(
                domain="table",
                root=types.UUID(value=event.table_root),
            ),
            pages=[
                types.CommandPage(
                    header=types.PageHeader(sequence=seq),
                    command=_pack(end_hand),
                )
            ],
        )


if __name__ == "__main__":
    router = Router("saga-hand-table").with_handler(HandTableSaga()).build()
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-hand-table",
        domain="hand",
        default_port="50412",
        logger=logger,
    )
