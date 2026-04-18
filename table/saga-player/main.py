"""Saga: Table -> Player (unified Router API).

Reacts to HandEnded events from Table domain and emits ReleaseFunds commands
to the Player domain (one command per player in ``stack_changes``).
"""

import sys
from pathlib import Path

import structlog
from google.protobuf.any_pb2 import Any as ProtoAny

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from angzarr_client import Destinations, Router, SagaGrpc, handles, run_server, saga
from angzarr_client.proto.angzarr import saga_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
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


@saga(name="saga-table-player", source="table", target="player")
class TablePlayerSaga:
    """Saga that translates HandEnded events to ReleaseFunds commands."""

    @handles(table.HandEnded)
    def handle_hand_ended(
        self,
        event: table.HandEnded,
        destinations: Destinations,
    ) -> list[types.CommandBook]:
        dest_seq = destinations.sequence_for("player") if destinations else 0
        dest_seq = dest_seq if dest_seq is not None else 0
        commands: list[types.CommandBook] = []

        for player_hex in event.stack_changes:
            player_root = bytes.fromhex(player_hex)
            release = player.ReleaseFunds(
                table_root=event.hand_root,
            )
            commands.append(
                types.CommandBook(
                    cover=types.Cover(
                        domain="player",
                        root=types.UUID(value=player_root),
                    ),
                    pages=[
                        types.CommandPage(
                            header=types.PageHeader(sequence=dest_seq),
                            command=_pack(release),
                        )
                    ],
                )
            )

        return commands


if __name__ == "__main__":
    router = Router("saga-table-player").with_handler(TablePlayerSaga()).build()
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-table-player",
        domain="table",
        default_port="50413",
        logger=logger,
    )
