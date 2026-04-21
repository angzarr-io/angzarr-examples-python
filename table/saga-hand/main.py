"""Saga: Table -> Hand (unified Router API).

DOC: This file is referenced in docs/docs/examples/sagas.mdx
     Update documentation when making changes to saga patterns.

Reacts to HandStarted events from Table domain and emits a DealCards command
to the Hand domain.
"""

import sys
from pathlib import Path

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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


# region saga
# region saga_handler
@saga(name="saga-table-hand", source="table", target="hand")
class TableHandSaga:
    """Saga that translates HandStarted events to DealCards commands."""

    @handles(table.HandStarted)
    def handle_hand_started(
        self,
        event: table.HandStarted,
        destinations: Destinations,
        source_cover: types.Cover = None,
        source_seq: int = 0,
    ) -> types.CommandBook:
        """Translate HandStarted -> DealCards.

        Uses ``AngzarrDeferredSequence`` so AMQP redelivery of HandStarted
        is recognized as a duplicate by the framework's
        ``check_deferred_idempotency`` and short-circuits to the cached
        DealCards events without re-invoking the hand handler.
        """
        players = [
            hand.PlayerInHand(
                player_root=seat.player_root,
                position=seat.position,
                stack=seat.stack,
            )
            for seat in event.active_players
        ]

        # Use the deterministic hand_root as deck_seed so the shuffle is
        # reproducible across runs. Same hand_root (sha256(table_id, hand_n))
        # always produces the same hole + community cards — required for
        # deterministic acceptance tests.
        deal_cards = hand.DealCards(
            table_root=event.hand_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
            deck_seed=event.hand_root,
        )
        deal_cards.players.extend(players)

        return types.CommandBook(
            cover=types.Cover(
                domain="hand",
                root=types.UUID(value=event.hand_root),
            ),
            pages=[
                types.CommandPage(
                    header=Destinations.deferred_header(source_cover, source_seq),
                    command=_pack(deal_cards),
                )
            ],
        )


# endregion
# endregion


# region event_router
if __name__ == "__main__":
    router = (
        Router("saga-table-hand")
        .with_handler(TableHandSaga, lambda: TableHandSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-table-hand",
        domain="table",
        default_port="50411",
        logger=logger,
    )
# endregion
