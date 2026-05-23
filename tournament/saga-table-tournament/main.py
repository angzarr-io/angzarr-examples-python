"""Saga: table → tournament cross-table state forwarder.

Translates table-domain events into the tournament's per-table state
updates and BB-on-empty flag signals so the tournament aggregate can
evaluate TDA Rule 11D's cross-table deficit rule against its own
event-sourced state.

The routing key (which tournament owns the source table) arrives in
``source_cover.ext`` as a packed ``TableExt`` whose ``tournament_cover``
field carries the tournament's root. Tables without a tournament
parent (standalone unit tests, non-tournament play) leave ``ext``
unset; the saga returns an empty command list for them — strictly
opt-in routing, no fan-out for orphan tables.

The downstream tournament emits ``TableHaltOrdered`` /
``TableResumeOrdered`` when the cross-table rule fires;
``saga-tournament-halt-fanout`` translates those back into table-
domain ``HaltForBalancing`` / ``ResumePlayAtTable`` commands.
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
from angzarr_client.helpers import unpack_ext_as
from angzarr_client.proto.angzarr.v1 import saga_pb2_grpc
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in
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


def _tournament_root_from_source_cover(source_cover) -> bytes | None:
    """Extract the parent tournament root from the table event's
    Cover.ext slot. Returns None when the table isn't tournament-owned
    (standalone unit test / non-tournament play) — sagas treat this as
    a no-op, not an error."""
    if source_cover is None:
        return None
    table_ext = unpack_ext_as(source_cover.proto(), table.TableExt)
    if table_ext is None:
        return None
    if not table_ext.HasField("tournament_cover"):
        return None
    return table_ext.tournament_cover.root.value


def _book_to_tournament(
    tournament_root: bytes,
    cmd,
    source_cover,
    source_seq: int,
) -> types.CommandBook:
    """Build a CommandBook keyed to the tournament aggregate's root,
    carrying ``cmd`` as its single page. Preserves the source cover's
    correlation_id so the cross-domain trace stays intact."""
    return types.CommandBook(
        cover=types.Cover(
            domain="tournament",
            root=types.UUID(value=tournament_root),
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


@saga(name="saga-table-tournament", source="table", target="tournament")
class TableTournamentSaga:
    """Forward table-domain state changes into the owning tournament's
    cross-table ledger. Stateless — the routing key arrives in-band via
    ``source_cover.ext``."""

    @handles(table.PlayerJoined)
    def handle_player_joined(
        self,
        event: table.PlayerJoined,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        tournament_root = _tournament_root_from_source_cover(source_cover)
        if tournament_root is None:
            return []
        cmd = tournament.RecordTablePlayerJoined(
            table_root=source_cover.proto().root.value,
            player_root=event.player_root,
        )
        return [_book_to_tournament(tournament_root, cmd, source_cover, source_seq)]

    @handles(buy_in.PlayerSeated)
    def handle_player_seated(
        self,
        event: buy_in.PlayerSeated,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        """SeatPlayer / buy-in is the rebalance refill path — same
        RecordTablePlayerJoined effect on tournament-side counts."""
        tournament_root = _tournament_root_from_source_cover(source_cover)
        if tournament_root is None:
            return []
        cmd = tournament.RecordTablePlayerJoined(
            table_root=source_cover.proto().root.value,
            player_root=event.player_root,
        )
        return [_book_to_tournament(tournament_root, cmd, source_cover, source_seq)]

    @handles(table.PlayerLeft)
    def handle_player_left(
        self,
        event: table.PlayerLeft,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        tournament_root = _tournament_root_from_source_cover(source_cover)
        if tournament_root is None:
            return []
        cmd = tournament.RecordTablePlayerLeft(
            table_root=source_cover.proto().root.value,
            player_root=event.player_root,
        )
        return [_book_to_tournament(tournament_root, cmd, source_cover, source_seq)]

    @handles(table.TableBBOnEmptyPredicted)
    def handle_bb_on_empty_predicted(
        self,
        event: table.TableBBOnEmptyPredicted,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        tournament_root = _tournament_root_from_source_cover(source_cover)
        if tournament_root is None:
            return []
        cmd = tournament.RecordTableBBOnEmpty(
            table_root=source_cover.proto().root.value,
        )
        return [_book_to_tournament(tournament_root, cmd, source_cover, source_seq)]

    @handles(table.TableBBOnEmptyResolved)
    def handle_bb_on_empty_resolved(
        self,
        event: table.TableBBOnEmptyResolved,
        destinations: Destinations,
        source_cover: Cover | None = None,
        source_seq: int = 0,
    ) -> list:
        tournament_root = _tournament_root_from_source_cover(source_cover)
        if tournament_root is None:
            return []
        cmd = tournament.RecordTableBBOnEmptyCleared(
            table_root=source_cover.proto().root.value,
        )
        return [_book_to_tournament(tournament_root, cmd, source_cover, source_seq)]


if __name__ == "__main__":
    router = (
        Router("saga-table-tournament")
        .with_handler(TableTournamentSaga, lambda: TableTournamentSaga())
        .build()
    )
    servicer = SagaGrpc(router)
    run_server(
        saga_pb2_grpc.add_SagaServiceServicer_to_server,
        servicer,
        service_name="saga-table-tournament",
        domain="table",
        default_port="50420",
        logger=logger,
    )
