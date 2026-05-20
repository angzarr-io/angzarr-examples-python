"""Saga: Tournament -> Table (rebalancing fan-out).

Listens for tournament events that imply per-table reseat operations
and translates them into the matching table-domain commands. Today
that means:

  PlayerMovedBetweenTables  →  LeaveTable on source_table_root
                            →  SeatPlayer on destination_table_root
                               (preserving the moved player's stack)

Drives the EA-0012 cluster acceptance scenario: the operator sends
``RebalanceTables`` to the tournament with the explicit move on the
command (source/destination/player/seat/stack). The aggregate echoes
those onto ``PlayerMovedBetweenTables``. This saga consumes that event
and fans out the per-table moves so the destination table grows by
one and the source shrinks by one with the player's stack intact.
"""

import sys
import uuid
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
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
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


@saga(name="saga-tournament-table", source="tournament", target="table")
class TournamentTableSaga:
    """Translate tournament-level reseat events into per-table commands."""

    @handles(tournament.PlayerMovedBetweenTables)
    def handle_player_moved(
        self,
        event: tournament.PlayerMovedBetweenTables,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        """Emit ``LeaveTable(source)`` + ``SeatPlayer(destination)``.

        Skipped silently when the move payload is empty (the legacy
        empty-rooted form emitted by pre-batch-16 unit tests). The
        saga only acts when both table roots and a non-empty player
        root are present.
        """
        if (
            not event.player_root
            or not event.source_table_root
            or not event.destination_table_root
        ):
            logger.info(
                "player_moved_skipped_no_payload",
                player_root_hex=event.player_root.hex(),
                source_hex=event.source_table_root.hex(),
                dest_hex=event.destination_table_root.hex(),
            )
            return []

        leave_cmd = table.LeaveTable(player_root=event.player_root)
        seat_cmd = buy_in.SeatPlayer(
            player_root=event.player_root,
            # Synthetic reservation_id for the saga-driven move — the
            # original buy-in reservation is at the source table; the
            # destination is bookkeeping internal to the tournament so
            # we mint a fresh id for the SeatPlayer.
            reservation_id=uuid.uuid4().bytes,
            seat=event.destination_seat,
            amount=event.stack,
            tournament_mode=True,
        )

        leave_book = types.CommandBook(
            cover=types.Cover(
                domain="table",
                root=types.UUID(value=event.source_table_root),
            ),
            pages=[
                types.CommandPage(
                    header=Destinations.deferred_header(source_cover, source_seq),
                    command=_pack(leave_cmd),
                )
            ],
        )
        seat_book = types.CommandBook(
            cover=types.Cover(
                domain="table",
                root=types.UUID(value=event.destination_table_root),
            ),
            pages=[
                types.CommandPage(
                    header=Destinations.deferred_header(source_cover, source_seq),
                    command=_pack(seat_cmd),
                )
            ],
        )
        return [leave_book, seat_book]


if __name__ == "__main__":
    router = (
        Router("saga-tournament-table")
        .with_handler(TournamentTableSaga, lambda: TournamentTableSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-tournament-table",
        domain="tournament",
        default_port="50415",
        logger=logger,
    )
