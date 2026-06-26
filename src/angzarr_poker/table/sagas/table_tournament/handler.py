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

from typing import Optional

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _trn
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.table_tournament_saga_angzarr import (
    TableTournamentSagaHandler,
)

_TOURNAMENT = "tournament"


def _owning_tournament(source_cover: _t.Cover) -> Optional[_t.Cover]:
    """The cover of the tournament that owns the source table, carried in the
    table's ``TableExt`` (``source_cover.ext``). ``None`` when the table is
    free-standing — a table not enrolled in a tournament has nothing to forward,
    and emitting a rootless tournament command would be rejected ("Cover must
    have a root UUID")."""
    if not source_cover.ext.value:
        return None
    ext = _table.TableExt()
    if not source_cover.ext.Unpack(ext):
        return None
    if not ext.HasField("tournament_cover") or not ext.tournament_cover.root.value:
        return None
    return ext.tournament_cover


def _to_tournament(cmd, owner: Optional[_t.Cover]) -> list:
    """A command book addressed to the owning tournament, or nothing when the
    table is not part of one."""
    if owner is None:
        return []
    book = _t.CommandBook()
    book.cover.domain = _TOURNAMENT
    book.cover.root.CopyFrom(owner.root)
    page = book.pages.add()
    page.command.CopyFrom(_az.pack(cmd))
    # Deferred (unstamped) + MERGE_AGGREGATE_HANDLES: the owning tournament is
    # non-fresh and the saga can't know its sequence, so the tournament stamps the
    # real sequence on delivery and owns its own concurrency (the default
    # COMMUTATIVE gate would call the tournament's unimplemented ``replay`` and
    # degrade to STRICT, rejecting the command). See tournament_table._to_table.
    page.merge_strategy = _t.MERGE_AGGREGATE_HANDLES
    return [book]


class TableTournamentSaga:
    """Implements ``TableTournamentSagaHandler``."""

    def player_joined(
        self,
        event: _table.PlayerJoined,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        owner = _owning_tournament(source_cover)
        cmd = _trn.RecordTablePlayerJoined(
            table_root=source_cover.root.value, player_root=event.player_root
        )
        return (_to_tournament(cmd, owner), [])

    def player_left(
        self, event: _table.PlayerLeft, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        owner = _owning_tournament(source_cover)
        cmd = _trn.RecordTablePlayerLeft(
            table_root=source_cover.root.value, player_root=event.player_root
        )
        return (_to_tournament(cmd, owner), [])

    def table_bb_on_empty_predicted(
        self,
        event: _table.TableBBOnEmptyPredicted,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        owner = _owning_tournament(source_cover)
        return (
            _to_tournament(
                _trn.RecordTableBBOnEmpty(table_root=event.table_root), owner
            ),
            [],
        )

    def table_bb_on_empty_resolved(
        self,
        event: _table.TableBBOnEmptyResolved,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        owner = _owning_tournament(source_cover)
        return (
            _to_tournament(
                _trn.RecordTableBBOnEmptyCleared(table_root=event.table_root), owner
            ),
            [],
        )

    def balancing_move_decided(
        self,
        event: _table.BalancingMoveDecided,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        """Forward the source table's BB-next decision up to the owning
        tournament as ``RebalanceTables`` (the tournament records the move and
        orders the destination seating). Only fires when the table is enrolled
        in a tournament (``source_cover.ext`` carries the tournament cover);
        a free-standing table has nothing to forward.

        ``BalancingMoveDecided`` carries no stack, so ``RebalanceTables.stack``
        is left zero here — the tournament is the chip authority and supplies
        the moved player's stack when it records the move."""
        owner = _owning_tournament(source_cover)
        cmd = _trn.RebalanceTables(
            source_table_root=event.source_table_root,
            destination_table_root=event.destination_table_root,
            player_root=event.player_root,
            destination_seat=event.destination_seat,
        )
        return (_to_tournament(cmd, owner), [])


_: TableTournamentSagaHandler = TableTournamentSaga()
