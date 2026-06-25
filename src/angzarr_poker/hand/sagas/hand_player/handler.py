"""HandPlayerSaga — translates a hand-domain PotAwarded into player commands.

When a pot is awarded, each winner's bankroll is credited with their share (one
DepositFunds per winner, dispatched to that winner's player aggregate).
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as _player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.hand_player_saga_angzarr import (
    HandPlayerSagaHandler,
)


class HandPlayerSaga:
    """Implements ``HandPlayerSagaHandler``."""

    def pot_awarded(
        self, event, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        books = []
        for winner in event.winners:
            book = _t.CommandBook()
            book.cover.domain = "player"
            book.cover.root.value = winner.player_root
            deposit = _player.DepositFunds(amount=_pt.Currency(amount=winner.amount))
            book.pages.add().command.CopyFrom(_az.pack(deposit))
            books.append(book)
        return (books, [])


_: HandPlayerSagaHandler = HandPlayerSaga()
