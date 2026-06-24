"""Tournament aggregate — cross-table coordination slice.

Implements the coordination commands/appliers of ``TournamentAggregateHandler``
on the angzarr-cli generated seam: the per-table active-player counts (fed by the
TableTournamentSaga forwarding PlayerJoined/PlayerLeft) and the TDA Rule 11D
short-table halt decision.

The tournament is the authority for cross-table coordination: it holds the
per-table counts in ``TournamentState.table_player_counts`` and decides when a
table is short enough to halt — deficit = (largest table's count) − (this table's
count); a deficit of 3 or more, signalled when the big blind would land on an empty
seat, emits ``TableHaltOrdered`` which the TournamentTableSaga fans out to the
table's ``HaltForBalancing``.

Only the coordination methods are ported here; the tournament's own lifecycle
(create / register / blinds / eliminations / payouts) is a separate port, so
dispatching those commands raises AttributeError (loud, not a silent no-op).
"""

from __future__ import annotations

from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _trn
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t

# Rule 11D: a table 3 or more players short of the largest table halts.
_HALT_DEFICIT_THRESHOLD = 3


def _now() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _book(*events) -> _t.EventBook:
    book = _t.EventBook()
    for ev in events:
        book.pages.add().event.CopyFrom(_az.pack(ev))
    return book


class TournamentAggregate:
    """Coordination slice of ``TournamentAggregateHandler``."""

    # --- per-table counts (forwarded by TableTournamentSaga) ---

    def record_table_player_joined(
        self, cmd: _trn.RecordTablePlayerJoined, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TournamentTablePlayerJoined(
                table_root=cmd.table_root, player_root=cmd.player_root, recorded_at=_now()
            )
        )

    def record_table_player_left(
        self, cmd: _trn.RecordTablePlayerLeft, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TournamentTablePlayerLeft(
                table_root=cmd.table_root, player_root=cmd.player_root, recorded_at=_now()
            )
        )

    def apply_tournament_table_player_joined(
        self, state: _trn.TournamentState, event: _trn.TournamentTablePlayerJoined
    ) -> None:
        state.table_player_counts[event.table_root.hex()] += 1

    def apply_tournament_table_player_left(
        self, state: _trn.TournamentState, event: _trn.TournamentTablePlayerLeft
    ) -> None:
        key = event.table_root.hex()
        if state.table_player_counts.get(key, 0) > 0:
            state.table_player_counts[key] -= 1

    # --- Rule 11D halt/resume decision ---

    def record_table_bb_on_empty(
        self, cmd: _trn.RecordTableBBOnEmpty, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        counts = state.table_player_counts
        if not counts:
            return None
        this_count = counts.get(cmd.table_root.hex(), 0)
        # Rule 11D second clause: compared to the table with the MOST players,
        # not the average across peers.
        deficit = max(counts.values()) - this_count
        if deficit >= _HALT_DEFICIT_THRESHOLD:
            return _book(
                _trn.TableHaltOrdered(
                    target_table_root=cmd.table_root, deficit=deficit, ordered_at=_now()
                )
            )
        return None

    def record_table_bb_on_empty_cleared(
        self,
        cmd: _trn.RecordTableBBOnEmptyCleared,
        state: _trn.TournamentState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TableResumeOrdered(target_table_root=cmd.table_root, ordered_at=_now())
        )

    def apply_table_halt_ordered(
        self, state: _trn.TournamentState, event: _trn.TableHaltOrdered
    ) -> None:
        # Order-of-record; no count change. (Re-arm tracking is added with EU-1184F.)
        pass

    def apply_table_resume_ordered(
        self, state: _trn.TournamentState, event: _trn.TableResumeOrdered
    ) -> None:
        pass
