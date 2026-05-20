"""Saga: tournament → table H4H fan-out (TDA Rule 12).

When the tournament aggregate emits ``HandForHandStarted`` carrying
the active table list, this saga fans ``EnterTableHandForHand`` out
to each table so they all enter the WAITING state in lockstep.

The companion saga ``saga-tournament-h4h`` (separate deployment,
source=table) routes per-table completion events back to the
tournament. Two sagas because each Router instance subscribes to a
single AMQP source domain.
"""

import sys
from pathlib import Path

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from angzarr_client import (
    Cover,
    Destinations,
    Router,
    SagaGrpc,
    handles,
    run_server,
    saga,
)
from angzarr_client.proto.angzarr import saga_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import table_pb2 as table
from angzarr_client.proto.examples import tournament_pb2 as tournament

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


@saga(name="saga-h4h-fanout", source="tournament", target="table")
class H4HFanoutSaga:
    """Fan tournament-side H4H events out to each active table."""

    @handles(tournament.HandForHandStarted)
    def handle_h4h_started(
        self,
        event: tournament.HandForHandStarted,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        """For each active table, emit EnterTableHandForHand carrying
        the originating tournament_root so the per-table completion
        event can be routed back via the companion saga.
        """
        if source_cover is None or not event.active_table_roots:
            logger.info(
                "h4h_started_skipped",
                has_cover=source_cover is not None,
                table_count=len(event.active_table_roots),
            )
            return []
        tournament_root = source_cover.proto().root.value
        books = []
        for table_root in event.active_table_roots:
            cmd = table.EnterTableHandForHand(tournament_root=tournament_root)
            books.append(
                types.CommandBook(
                    cover=types.Cover(
                        domain="table",
                        root=types.UUID(value=table_root),
                    ),
                    pages=[
                        types.CommandPage(
                            header=Destinations.deferred_header(
                                source_cover, source_seq
                            ),
                            command=_pack(cmd),
                        )
                    ],
                )
            )
        logger.info(
            "h4h_fanout",
            tournament_root_hex=tournament_root.hex(),
            table_count=len(books),
        )
        return books


if __name__ == "__main__":
    router = (
        Router("saga-h4h-fanout")
        .with_handler(H4HFanoutSaga, lambda: H4HFanoutSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-h4h-fanout",
        domain="tournament",
        default_port="50416",
        logger=logger,
    )
