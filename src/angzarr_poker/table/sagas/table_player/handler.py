"""TablePlayerSaga — translates a table-domain HandEnded into player commands.

When a hand ends, each participant's reserved chips are released back to their
bankroll (one ReleaseFunds per participant — including zero-net-change players,
so their reservation is cleared).
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as _player
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.table_player_saga_angzarr import (
    TablePlayerSagaHandler,
)


class TablePlayerSaga:
    """Implements ``TablePlayerSagaHandler``."""

    def hand_ended(
        self, event, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        books = []
        for player_hex in event.stack_changes:
            player_root = bytes.fromhex(player_hex)
            book = _t.CommandBook()
            book.cover.domain = "player"
            book.cover.root.value = player_root
            book.pages.add().command.CopyFrom(
                _az.pack(_player.ReleaseFunds(key=player_root))
            )
            books.append(book)
        return (books, [])


_: TablePlayerSagaHandler = TablePlayerSaga()
