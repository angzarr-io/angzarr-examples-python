"""Saga: table → tournament H4H per-table-completion routing (TDA Rule 12).

When a table emits ``TableHandForHandRoundComplete`` carrying the
originating tournament_root (set by the apply for the prior
``TableHandForHandWaiting`` event whose tournament_root came from
the matching ``EnterTableHandForHand`` from saga-h4h-fanout), this
saga emits ``RecordTableHandComplete(table_root)`` on that
tournament. The tournament aggregate decrements its pending_tables
set and emits ``HandForHandRoundComplete`` once every table has
reported in.

Companion to saga-h4h-fanout (separate deployment, source=tournament).
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


@saga(name="saga-tournament-h4h", source="table", target="tournament")
class TableTournamentH4HSaga:
    """Route per-table H4H completion events back to the tournament."""

    @handles(table.TableHandForHandRoundComplete)
    def handle_table_round_complete(
        self,
        event: table.TableHandForHandRoundComplete,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        """Notify the tournament that this table just finished its
        synchronised H4H hand.

        Skipped when the event lacks a tournament_root (cash-game
        table or pre-batch-16 H4H state without saga routing).
        """
        if not event.tournament_root or source_cover is None:
            logger.info(
                "table_round_complete_skipped",
                has_cover=source_cover is not None,
                has_tournament_root=bool(event.tournament_root),
            )
            return []
        table_root = source_cover.proto().root.value
        cmd = tournament.RecordTableHandComplete(table_root=table_root)
        logger.info(
            "record_table_hand_complete",
            tournament_root_hex=event.tournament_root.hex(),
            table_root_hex=table_root.hex(),
        )
        return [
            types.CommandBook(
                cover=types.Cover(
                    domain="tournament",
                    root=types.UUID(value=event.tournament_root),
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
        ]


if __name__ == "__main__":
    router = (
        Router("saga-tournament-h4h")
        .with_handler(TableTournamentH4HSaga, lambda: TableTournamentH4HSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-tournament-h4h",
        domain="table",
        default_port="50417",
        logger=logger,
    )
