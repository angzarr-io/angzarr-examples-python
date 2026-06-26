"""TournamentTableSaga — fans the tournament's order-of-record events out to the
per-table commands that execute them.

Stateless translator (tournament domain → table domain). Each order names its
target table by root in the event body, so routing needs no source cover:
- ``TableHaltOrdered``   → ``HaltForBalancing`` on ``target_table_root``
- ``TableResumeOrdered`` → ``ResumePlayAtTable`` on ``target_table_root``
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as _buy_in
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
    page = book.pages.add()
    page.command.CopyFrom(_az.pack(cmd))
    # The page carries NO sequence (the saga coordinator marks it
    # ``angzarr_deferred`` so the destination stamps the real per-root sequence),
    # and declares MERGE_AGGREGATE_HANDLES: the destination table is the authority
    # for its own concurrency (seat validation etc.), so the framework must NOT run
    # the optimistic sequence/commutative gate. Without this the default
    # COMMUTATIVE gate calls the aggregate's (unimplemented) ``replay`` and degrades
    # to STRICT, rejecting the deferred command against a non-fresh table.
    page.merge_strategy = _t.MERGE_AGGREGATE_HANDLES
    return [book]


class TournamentTableSaga:
    """Implements ``TournamentTableSagaHandler``."""

    def table_halt_ordered(
        self,
        event: _trn.TableHaltOrdered,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        cmd = _table.HaltForBalancing(deficit=event.deficit)
        return (_to_table(event.target_table_root, cmd), [])

    def table_resume_ordered(
        self,
        event: _trn.TableResumeOrdered,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        return (_to_table(event.target_table_root, _table.ResumePlayAtTable()), [])

    def player_moved_between_tables(
        self,
        event: _trn.PlayerMovedBetweenTables,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        """TDA Rule 14 fan-out: the tournament's recorded move must release the
        player at the source table (``LeaveTable``) and seat them at the
        destination with their travelling stack (``SeatPlayer``). Both targets are
        EXISTING (non-fresh) aggregates a saga can't know the sequence of, so this
        needs saga-deferred sequencing (the destination stamps the real sequence on
        delivery).

        That does NOT work end-to-end in this deployed cluster — and crucially NOT
        because the binaries are stale. Verified empirically: emitting the fan-out
        UNSTAMPED (which should become ``angzarr_deferred``), with BOTH the
        ``angzarr-saga`` and ``angzarr-aggregate`` coordinators rebuilt from core
        HEAD, the command still reaches the table aggregate as ``expects 0`` (i.e.
        is_deferred=false), conflicts on the non-fresh table, retries to exhaustion,
        and the seat never lands. The ``CommandBus`` delivers to the aggregate over
        gRPC ``HandleCommand``, and that pipeline path does not honor deferred — a
        genuine framework gap at HEAD, not a deploy artifact. (A direct deferred
        ``HandleCommand`` to a non-fresh aggregate is rejected the same way.)

        So the saga is a no-op; the cluster-acceptance harness performs the source
        ``LeaveTable`` + destination ``SeatPlayer`` directly (it tracks each table's
        sequence). The authoritative record of the move is the tournament's
        ``PlayerMovedBetweenTables`` (``rebalance_tables``). Restore this fan-out
        ROOT CAUSE + PROVEN FIX (session manly-dark-cover): the fan-out failed NOT
        because the binaries are stale (verified identical on core HEAD) but because
        the commands defaulted to MERGE_COMMUTATIVE. A deferred command on a
        non-fresh aggregate makes the COMMUTATIVE gate call the aggregate's
        ``replay`` RPC to diff field overlap; the FFI example aggregates don't
        implement ``replay`` (returns Unimplemented), so the gate degrades to STRICT
        and rejects with "Sequence mismatch: command expects 0". Declaring
        MERGE_AGGREGATE_HANDLES on the page (``_to_table`` now does) skips that gate
        — the destination table is the authority for its own seats — and the
        command, being unstamped, is stamped ``angzarr_deferred`` so the table
        assigns the real sequence on delivery. Verified end-to-end: the deferred
        SeatPlayer then lands on a non-fresh table (PlayerSeated for the moved
        player at the requested seat).

        The authoritative record stays the tournament's ``PlayerMovedBetweenTables``
        (``rebalance_tables``); this saga only executes it on the two tables."""
        seat = _buy_in.SeatPlayer(
            player_root=event.player_root,
            seat=event.destination_seat,
            amount=event.stack,
            moved_player=True,
        )
        leave = _table.LeaveTable(player_root=event.player_root)
        return (
            _to_table(event.destination_table_root, seat)
            + _to_table(event.source_table_root, leave),
            [],
        )

    def hand_for_hand_started(
        self,
        event: _trn.HandForHandStarted,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> tuple[list, list]:
        """TDA Rule 12 bubble fan-out: the tournament entered hand-for-hand play
        over ``active_table_roots`` — park each of those (non-fresh) tables for the
        synchronised hand via ``EnterTableHandForHand``. The tournament root (the
        H4H owner the tables report back to) is the event's source cover root. Each
        command is deferred + MERGE_AGGREGATE_HANDLES (see ``_to_table``)."""
        books: list = []
        for table_root in event.active_table_roots:
            books += _to_table(
                table_root,
                _table.EnterTableHandForHand(tournament_root=source_cover.root.value),
            )
        return (books, [])


_: TournamentTableSagaHandler = TournamentTableSaga()
