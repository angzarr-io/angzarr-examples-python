"""HandTableSaga — translates a hand-domain HandComplete into a table command.

When a hand completes, the table is told to end the round, carrying the pot
winners through as the round results.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.hand_table_saga_angzarr import (
    HandTableSagaHandler,
)


class HandTableSaga:
    """Implements ``HandTableSagaHandler``."""

    def hand_complete(
        self, event, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        book = _t.CommandBook()
        book.cover.domain = "table"
        book.cover.root.value = event.table_root
        results = [
            _table.PotResult(
                winner_root=w.player_root,
                amount=w.amount,
                pot_type=w.pot_type,
                winning_hand=w.winning_hand,
            )
            for w in event.winners
        ]
        end = _table.EndHand(results=results)
        book.pages.add().command.CopyFrom(_az.pack(end))
        return ([book], [])


_: HandTableSagaHandler = HandTableSaga()
