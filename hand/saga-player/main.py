"""Saga: Hand -> Player (unified Router API).

Reacts to PotAwarded events from Hand domain and emits DepositFunds commands
to the Player domain (one command per winner).
"""

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Destinations, Router, SagaGrpc, handles, run_server, saga
from angzarr_client.proto.angzarr import saga_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

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


@saga(name="saga-hand-player", source="hand", target="player")
class HandPlayerSaga:
    """Saga that translates PotAwarded events to DepositFunds commands."""

    @handles(hand.PotAwarded)
    def handle_pot_awarded(
        self,
        event: hand.PotAwarded,
        destinations: Destinations,
        source_cover: types.Cover = None,
        source_seq: int = 0,
    ) -> list[types.CommandBook]:
        books: list[types.CommandBook] = []
        for winner in event.winners:
            deposit = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount,
                    currency_code="CHIPS",
                ),
            )
            books.append(
                types.CommandBook(
                    cover=types.Cover(
                        domain="player",
                        root=types.UUID(value=winner.player_root),
                    ),
                    pages=[
                        types.CommandPage(
                            header=Destinations.deferred_header(
                                source_cover, source_seq
                            ),
                            command=_pack(deposit),
                        )
                    ],
                )
            )
        return books


if __name__ == "__main__":
    router = (
        Router("saga-hand-player")
        .with_handler(HandPlayerSaga, lambda: HandPlayerSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-hand-player",
        domain="hand",
        default_port="50414",
        logger=logger,
    )
