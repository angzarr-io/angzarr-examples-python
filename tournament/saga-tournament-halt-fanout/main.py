"""Saga: tournament → table halt/resume fan-out (TDA Rule 11D).

Consumes ``TableHaltOrdered`` / ``TableResumeOrdered`` events from the
tournament aggregate and translates them into the per-table
``HaltForBalancing`` / ``ResumePlayAtTable`` commands that flip the
target table's ``halted_for_balancing`` flag and gate ``StartHand``.

The order events carry ``target_table_root`` explicitly so this saga
is pure stateless translation. The deficit on ``HaltForBalancing`` is
echoed from the tournament's emitted event — the deficit decision
(operator-supplied or auto-detected) was already made at the
tournament level.
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
from angzarr_client.proto.angzarr.v1 import saga_pb2_grpc
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import table_pb2 as table
from angzarr_client.proto.examples.v1 import tournament_pb2 as tournament

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


def _book_to_table(
    target_table_root: bytes,
    cmd,
    source_cover,
    source_seq: int,
) -> types.CommandBook:
    return types.CommandBook(
        cover=types.Cover(
            domain="table",
            root=types.UUID(value=target_table_root),
            correlation_id=source_cover.proto().correlation_id
            if source_cover is not None
            else "",
        ),
        pages=[
            types.CommandPage(
                header=Destinations.deferred_header(source_cover, source_seq),
                command=_pack(cmd),
            )
        ],
    )


@saga(name="saga-tournament-halt-fanout", source="tournament", target="table")
class TournamentHaltFanoutSaga:
    """Fan tournament halt/resume orders out to per-table commands."""

    @handles(tournament.TableHaltOrdered)
    def handle_halt_ordered(
        self,
        event: tournament.TableHaltOrdered,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        if not event.target_table_root:
            logger.warning(
                "halt_ordered_missing_target",
                source_seq=source_seq,
            )
            return []
        cmd = table.HaltForBalancing(deficit=event.deficit)
        return [_book_to_table(event.target_table_root, cmd, source_cover, source_seq)]

    @handles(tournament.TableResumeOrdered)
    def handle_resume_ordered(
        self,
        event: tournament.TableResumeOrdered,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        if not event.target_table_root:
            logger.warning(
                "resume_ordered_missing_target",
                source_seq=source_seq,
            )
            return []
        cmd = table.ResumePlayAtTable()
        return [_book_to_table(event.target_table_root, cmd, source_cover, source_seq)]


if __name__ == "__main__":
    router = (
        Router("saga-tournament-halt-fanout")
        .with_handler(TournamentHaltFanoutSaga, lambda: TournamentHaltFanoutSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-tournament-halt-fanout",
        domain="tournament",
        default_port="50421",
        logger=logger,
    )
