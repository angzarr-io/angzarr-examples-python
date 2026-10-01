"""The table → player translators: settlement facts, round history and
loyalty. Stateless; target players come from the event, never a lookup.

* saga-table-player-settlement turns money the table already moved into
  FACTS for the wallet, which records them exactly once per external id.
* saga-table-player-history and saga-table-player-loyalty each react to the
  same RoundSettled with one command per settled seat, in seat order.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import deferred_command, fact

PLAYER = "player"

Reaction = tuple[list[_t.CommandBook], list[_t.EventBook]]


# region saga_facts
class TablePlayerSettlementSaga:
    """Implements ``TablePlayerSettlementSagaHandler``: chips added and
    cash-outs become facts the wallet cannot refuse."""

    def chips_added(
        self, event: _table.ChipsAdded, dests: _az.Destinations, source_cover: _t.Cover
    ) -> Reaction:
        settled = _p.TopUpSettled(
            hold_id=event.hold_id,
            table_root=source_cover.root.value,
            amount=event.amount,
        )
        return [], [
            fact(
                PLAYER,
                event.player_root,
                settled,
                event.hold_id.hex(),
                "top-up settled at table",
            )
        ]

    def player_cashed_out(
        self,
        event: _table.PlayerCashedOut,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> Reaction:
        credited = _p.CashOutCredited(
            cashout_id=event.cashout_id,
            table_root=source_cover.root.value,
            amount=event.amount,
        )
        return [], [
            fact(
                PLAYER,
                event.player_root,
                credited,
                event.cashout_id.hex(),
                "cash-out at table",
            )
        ]


# endregion saga_facts


class TablePlayerHistorySaga:
    """Implements ``TablePlayerHistorySagaHandler``: one RecordRoundResult per
    settled seat."""

    def round_settled(
        self,
        event: _table.RoundSettled,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> Reaction:
        commands = [
            deferred_command(
                PLAYER,
                outcome.player_root,
                _p.RecordRoundResult(
                    table_root=source_cover.root.value,
                    round=event.round,
                    wager=outcome.wager,
                    net=outcome.net,
                ),
            )
            for outcome in sorted(event.outcomes, key=lambda o: o.seat)
        ]
        return commands, []


class TablePlayerLoyaltySaga:
    """Implements ``TablePlayerLoyaltySagaHandler``: one point per chip
    wagered, per settled seat."""

    def round_settled(
        self,
        event: _table.RoundSettled,
        dests: _az.Destinations,
        source_cover: _t.Cover,
    ) -> Reaction:
        commands = [
            deferred_command(
                PLAYER,
                outcome.player_root,
                _p.AwardLoyaltyPoints(
                    table_root=source_cover.root.value,
                    round=event.round,
                    points=outcome.wager,
                ),
            )
            for outcome in sorted(event.outcomes, key=lambda o: o.seat)
        ]
        return commands, []
