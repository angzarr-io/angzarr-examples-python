"""TableHandSaga — translates table-domain HandStarted into hand-domain commands.

A saga is stateless: it reacts to a source event and emits commands to other
aggregates. When a table starts a hand, this saga issues a Shuffle (hand_root as
the replay-deterministic deck seed) followed by DealCards to the hand domain, so
the hand aggregate deals the same players the table seated.

Implements the generated ``TableHandSagaHandler`` seam: ``hand_started`` returns
``(command_books, event_books)``; the command stamping/sequencing is left to the
coordinator (the test asserts the emitted commands, not their sequences).
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as _hand
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.table_hand_saga_angzarr import (
    TableHandSagaHandler,
)


class TableHandSaga:
    """Implements ``TableHandSagaHandler``."""

    def hand_started(
        self, event: _hand.HandStarted, dests: _az.Destinations
    ) -> tuple[list, list]:
        book = _t.CommandBook()
        book.cover.domain = "hand"
        book.cover.root.value = event.hand_root

        shuffle = _hand.Shuffle(seed=event.hand_root, game_variant=event.game_variant)
        book.pages.add().command.CopyFrom(_az.pack(shuffle))

        players = [
            _hand.PlayerInHand(player_root=s.player_root, position=s.position, stack=s.stack)
            for s in event.active_players
        ]
        deal = _hand.DealCards(
            table_root=event.hand_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            players=players,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
        )
        book.pages.add().command.CopyFrom(_az.pack(deal))
        return ([book], [])

    def on_deal_cards_rejected(
        self, n: _t.Notification, rejection: _t.RejectionNotification
    ) -> list:
        # No compensation in this slice — a rejected deal is acknowledged.
        return []


_: TableHandSagaHandler = TableHandSaga()
