"""saga-player-table: a wallet top-up request becomes AddChips at the table.

A stateless translator. The target table comes from the event
(``TopUpRequested.table_root``) and the player from the source cover; nothing
is looked up. AddChips is a command because the table may refuse it
(WAGER_IN_PLAY, NOT_SEATED, TOP_UP_EXCEEDS_MAX); the refusal is delivered to
the player, which compensates (``PlayerAggregate.on_add_chips_rejected``).
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import deferred_command

TABLE = "table"


# region saga
class PlayerTableSaga:
    """Implements ``PlayerTableSagaHandler``."""

    def top_up_requested(
        self, event: _p.TopUpRequested, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list[_t.CommandBook], list[_t.EventBook]]:
        add_chips = _table.AddChips(
            player_root=source_cover.root.value,
            hold_id=event.hold_id,
            amount=event.amount,
        )
        return [deferred_command(TABLE, event.table_root, add_chips)], []


# endregion saga
