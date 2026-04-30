"""Saga: Hand -> Table (unified Router API).

Reacts to HandComplete events from Hand domain and emits an EndHand command
to the Table domain.
"""

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Cover, Destinations, Router, SagaGrpc, handles, run_server, saga
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
        self,
        event: hand.HandComplete,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
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

        hand_root = (
            source_cover.proto().root.value if source_cover is not None else b""
        )
        end_hand = table.EndHand(hand_root=hand_root)
        end_hand.results.extend(results)

        return types.CommandBook(
            cover=types.Cover(
                domain="table",
                root=types.UUID(value=event.table_root),
            ),
            pages=[
                types.CommandPage(
                    header=Destinations.deferred_header(source_cover, source_seq),
                    command=_pack(end_hand),
                )
            ],
        )


if __name__ == "__main__":
    router = (
        Router("saga-hand-table")
        .with_handler(HandTableSaga, lambda: HandTableSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-hand-table",
        domain="hand",
        default_port="50412",
        logger=logger,
    )
