"""TableTournamentSaga — forwards per-table facts up to the owning tournament.

Stateless translator (table domain → tournament domain). It reads the routing
keys it needs:
- ``PlayerJoined``/``PlayerLeft`` carry no table_root (the table is the source
  aggregate), so the table id comes from ``source_cover.root`` — the trigger's
  identity, passed through the FFI.
- ``TableBBOnEmptyPredicted``/``Resolved`` carry their own ``table_root`` field.

The owning tournament is identified in production by ``TableExt.tournament_cover``
packed in ``source_cover.ext``; the in-process unit harness has a single
tournament and routes the emitted command to it, so the destination root is left
for the harness to resolve.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _trn
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.table_tournament_saga_angzarr import (
    TableTournamentSagaHandler,
)

_TOURNAMENT = "tournament"


def _to_tournament(cmd) -> list:
    book = _t.CommandBook()
    book.cover.domain = _TOURNAMENT
    book.pages.add().command.CopyFrom(_az.pack(cmd))
    return [book]


class TableTournamentSaga:
    """Implements ``TableTournamentSagaHandler``."""

    def player_joined(
        self, event: _table.PlayerJoined, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        cmd = _trn.RecordTablePlayerJoined(
            table_root=source_cover.root.value, player_root=event.player_root
        )
        return (_to_tournament(cmd), [])

    def player_left(
        self, event: _table.PlayerLeft, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        cmd = _trn.RecordTablePlayerLeft(
            table_root=source_cover.root.value, player_root=event.player_root
        )
        return (_to_tournament(cmd), [])

    def table_bb_on_empty_predicted(
        self, event: _table.TableBBOnEmptyPredicted, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        return (_to_tournament(_trn.RecordTableBBOnEmpty(table_root=event.table_root)), [])

    def table_bb_on_empty_resolved(
        self, event: _table.TableBBOnEmptyResolved, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        return (_to_tournament(_trn.RecordTableBBOnEmptyCleared(table_root=event.table_root)), [])

    def balancing_move_decided(
        self, event: _table.BalancingMoveDecided, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        # Option A balancing chain — ported with B3.
        return ([], [])


_: TableTournamentSagaHandler = TableTournamentSaga()
