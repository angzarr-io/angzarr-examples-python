"""TournamentTableSaga — fans the tournament's order-of-record events out to the
per-table commands that execute them.

Stateless translator (tournament domain → table domain). Each order names its
target table by root in the event body, so routing needs no source cover:
- ``TableHaltOrdered``   → ``HaltForBalancing`` on ``target_table_root``
- ``TableResumeOrdered`` → ``ResumePlayAtTable`` on ``target_table_root``
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _trn
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.tournament_table_saga_angzarr import (
    TournamentTableSagaHandler,
)

_TABLE = "table"


def _to_table(target_table_root: bytes, cmd) -> list:
    book = _t.CommandBook()
    book.cover.domain = _TABLE
    book.cover.root.value = target_table_root
    book.pages.add().command.CopyFrom(_az.pack(cmd))
    return [book]


class TournamentTableSaga:
    """Implements ``TournamentTableSagaHandler``."""

    def table_halt_ordered(
        self, event: _trn.TableHaltOrdered, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        cmd = _table.HaltForBalancing(deficit=event.deficit)
        return (_to_table(event.target_table_root, cmd), [])

    def table_resume_ordered(
        self, event: _trn.TableResumeOrdered, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        return (_to_table(event.target_table_root, _table.ResumePlayAtTable()), [])

    def player_moved_between_tables(
        self, event: _trn.PlayerMovedBetweenTables, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        # Option A balancing chain (dest SeatPlayer) — ported with B3.
        return ([], [])


_: TournamentTableSagaHandler = TournamentTableSaga()
