"""TableHandSaga — translates table-domain HandStarted into hand-domain commands.

A saga is stateless: it reacts to a source event and emits commands to other
aggregates. When a table starts a hand, this saga issues a Shuffle (seed =
hand_root, for a deterministic per-hand deck) followed by DealCards to the hand
domain, so the hand aggregate deals the same players the table seated from the
shuffled deck.

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
        self, event: _hand.HandStarted, dests: _az.Destinations, source_cover: _t.Cover
    ) -> tuple[list, list]:
        # Shuffle and DealCards are SEPARATE aggregate transactions in order:
        # Shuffle (→ DeckShuffled) advances the hand by one sequence and
        # establishes the deck on state; DealCards then rebuilds over it and
        # draws from state.remaining_deck. Each command carries its own expected
        # sequence — Shuffle at the hand's current next-sequence, DealCards at
        # the next one (Shuffle emits exactly one event). Sharing a sequence (or
        # one multi-page book) makes DealCards conflict once Shuffle commits.
        base = dests.sequence_for("hand") or 0

        shuffle_book = _t.CommandBook()
        shuffle_book.cover.domain = "hand"
        shuffle_book.cover.root.value = event.hand_root
        shuffle = _hand.Shuffle(seed=event.hand_root, game_variant=event.game_variant)
        page = shuffle_book.pages.add()
        page.header.sequence = base
        page.command.CopyFrom(_az.pack(shuffle))

        players = [
            _hand.PlayerInHand(
                player_root=s.player_root, position=s.position, stack=s.stack
            )
            for s in event.active_players
        ]
        deal_book = _t.CommandBook()
        deal_book.cover.domain = "hand"
        deal_book.cover.root.value = event.hand_root
        deal = _hand.DealCards(
            table_root=event.hand_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            players=players,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
        )
        page = deal_book.pages.add()
        page.header.sequence = base + 1
        page.command.CopyFrom(_az.pack(deal))

        return ([shuffle_book, deal_book], [])

    def on_deal_cards_rejected(
        self, n: _t.Notification, rejection: _t.RejectionNotification
    ) -> list:
        # No compensation in this slice — a rejected deal is acknowledged.
        return []


_: TableHandSagaHandler = TableHandSaga()
