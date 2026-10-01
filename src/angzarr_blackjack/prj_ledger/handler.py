"""projector-player-table-ledger: the money read model over both domains.

The ledger shows each wallet, each table's chips and the house result, and
whether all the money in the system adds up. Transfers between a wallet and a
table are seen twice, once per side, in either order; a transfer is in flight
until both sides are seen:

* buy-in:   PlayerSeated(buy_in_id)     <-> FundsCaptured(hold_id = buy_in_id)
* top-up:   ChipsAdded(hold_id)         <-> TopUpSettled(hold_id)
* cash-out: PlayerCashedOut(cashout_id) <-> CashOutCredited(cashout_id)

Invariant L4, checked only when nothing is in flight:
``sum(bankroll) + sum(stacks + wagers) + sum(house_result) = deposits - withdrawals``.

Every applied event is remembered by (domain, root, sequence), so replaying or
redelivering an event leaves the read model unchanged. The projection handed
to each fold is the ledger's own ``LedgerProjection``; each fold reads its
book's root from its page context.
"""

from __future__ import annotations

import copy
import threading

import angzarr_client.router as _az

from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

PROJECTOR = "LedgerProjector"
RECENT_RESULTS = 10
BUY_IN, TOP_UP, CASH_OUT = "buy-in", "top-up", "cash-out"
TABLE_SIDE, WALLET_SIDE = "table", "wallet"


class Ledger:
    """The read model: rows, open holds, transfer sides and applied events."""

    def __init__(self) -> None:
        self.projection = _l.LedgerProjection()
        self.open_holds: dict[str, dict[str, int]] = {}
        self.transfers: dict[tuple[str, str], dict[str, int]] = {}
        self.applied: set[tuple[str, str, int]] = set()

    # --- rows ---

    def player(self, root: bytes) -> _l.PlayerLedgerRow:
        row = self.projection.players[root.hex()]
        row.player_root = root
        return row

    def table(self, root: bytes) -> _l.TableLedgerRow:
        row = self.projection.tables[root.hex()]
        row.table_root = root
        return row

    # --- holds and transfers ---

    def open_hold(self, player_root: bytes, hold_id: bytes, amount: int) -> None:
        self.open_holds.setdefault(player_root.hex(), {})[hold_id.hex()] = amount
        self._refresh_held(player_root)

    def close_hold(self, player_root: bytes, hold_id: bytes) -> bool:
        """Close an open hold; False when it was not open."""
        closed = (
            self.open_holds.get(player_root.hex(), {}).pop(hold_id.hex(), None)
            is not None
        )
        self._refresh_held(player_root)
        return closed

    def _refresh_held(self, player_root: bytes) -> None:
        self.player(player_root).held = sum(
            self.open_holds.get(player_root.hex(), {}).values()
        )

    def transfer_side(
        self, kind: str, transfer_id: bytes, side: str, amount: int
    ) -> None:
        self.transfers.setdefault((kind, transfer_id.hex()), {})[side] = amount

    def in_flight(self) -> tuple[int, int]:
        """(amount, count) of transfers seen on one side only."""
        pending = [sides for sides in self.transfers.values() if len(sides) == 1]
        return sum(next(iter(s.values())) for s in pending), len(pending)

    # --- applied events ---

    def unapplied(self, book: _t.EventBook) -> _t.EventBook:
        """``book`` without the pages this ledger has already applied."""
        out = _t.EventBook()
        out.cover.CopyFrom(book.cover)
        key = (book.cover.domain, book.cover.root.value.hex())
        out.pages.extend(
            p for p in book.pages if (*key, p.header.sequence) not in self.applied
        )
        return out

    def mark_applied(self, book: _t.EventBook) -> None:
        key = (book.cover.domain, book.cover.root.value.hex())
        self.applied.update((*key, p.header.sequence) for p in book.pages)

    # --- totals and views ---

    def refresh_totals(self) -> None:
        totals = self.projection.totals
        totals.bankrolls = sum(r.bankroll for r in self.projection.players.values())
        totals.stacks = sum(r.stacks for r in self.projection.tables.values())
        totals.wagers = sum(r.wagers for r in self.projection.tables.values())
        totals.house_result = sum(
            r.house_result for r in self.projection.tables.values()
        )
        totals.in_flight, totals.in_flight_transfers = self.in_flight()

    def balanced(self) -> bool:
        totals = self.projection.totals
        held_everywhere = (
            totals.bankrolls + totals.stacks + totals.wagers + totals.house_result
        )
        return (
            totals.in_flight_transfers == 0
            and held_everywhere == totals.deposits - totals.withdrawals
        )

    def player_view(self, root: bytes) -> _l.PlayerBalanceView:
        row = self.projection.players.get(root.hex())
        if row is None:
            return _l.PlayerBalanceView(found=False)
        return _l.PlayerBalanceView(
            player=row, available=row.bankroll - row.held, found=True
        )

    def ledger_view(self) -> _l.LedgerView:
        return _l.LedgerView(
            totals=self.projection.totals,
            tables=sorted(self.projection.tables.values(), key=lambda r: r.table_root),
            balanced=self.balanced(),
        )

    def copy(self) -> Ledger:
        twin = Ledger()
        twin.projection.CopyFrom(self.projection)
        twin.open_holds = copy.deepcopy(self.open_holds)
        twin.transfers = copy.deepcopy(self.transfers)
        twin.applied = set(self.applied)
        return twin


# region projector
class LedgerProjector:
    """Implements ``LedgerProjectorHandler``: folds wallet and table events
    into the :class:`Ledger`."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    # --- wallets ---

    def player_registered(
        self, projection, event: _p.PlayerRegistered, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).display_name = event.display_name

    def player_imported(
        self, projection, event: _p.PlayerImported, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).display_name = event.display_name

    def profile_updated(
        self, projection, event: _p.ProfileUpdated, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).display_name = event.display_name

    def funds_deposited(
        self, projection, event: _p.FundsDeposited, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).bankroll += event.amount
        projection.totals.deposits += event.amount

    def funds_withdrawn(
        self, projection, event: _p.FundsWithdrawn, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).bankroll -= event.amount
        projection.totals.withdrawals += event.amount

    def funds_held(self, projection, event: _p.FundsHeld, ctx: _az.PageContext) -> None:
        self.ledger.open_hold(ctx.cover.root.value, event.hold_id, event.amount)

    def funds_captured(
        self, projection, event: _p.FundsCaptured, ctx: _az.PageContext
    ) -> None:
        root = ctx.cover.root.value
        self.ledger.close_hold(root, event.hold_id)
        self.ledger.player(root).bankroll -= event.amount
        self.ledger.transfer_side(BUY_IN, event.hold_id, WALLET_SIDE, event.amount)

    def hold_released(
        self, projection, event: _p.HoldReleased, ctx: _az.PageContext
    ) -> None:
        self.ledger.close_hold(ctx.cover.root.value, event.hold_id)

    def top_up_requested(
        self, projection, event: _p.TopUpRequested, ctx: _az.PageContext
    ) -> None:
        self.ledger.open_hold(ctx.cover.root.value, event.hold_id, event.amount)

    def top_up_refused(
        self, projection, event: _p.TopUpRefused, ctx: _az.PageContext
    ) -> None:
        self.ledger.close_hold(ctx.cover.root.value, event.hold_id)

    def top_up_settled(
        self, projection, event: _p.TopUpSettled, ctx: _az.PageContext
    ) -> None:
        root = ctx.cover.root.value
        self.ledger.close_hold(root, event.hold_id)
        self.ledger.player(root).bankroll -= event.amount
        self.ledger.transfer_side(TOP_UP, event.hold_id, WALLET_SIDE, event.amount)

    def cash_out_credited(
        self, projection, event: _p.CashOutCredited, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).bankroll += event.amount
        self.ledger.transfer_side(CASH_OUT, event.cashout_id, WALLET_SIDE, event.amount)

    def loyalty_enrolled(
        self, projection, event: _p.LoyaltyEnrolled, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value)

    def loyalty_points_awarded(
        self, projection, event: _p.LoyaltyPointsAwarded, ctx: _az.PageContext
    ) -> None:
        self.ledger.player(ctx.cover.root.value).loyalty_points += event.points

    def round_result_recorded(
        self, projection, event: _p.RoundResultRecorded, ctx: _az.PageContext
    ) -> None:
        results = self.ledger.player(ctx.cover.root.value).recent_results
        results.append(
            _l.LedgerRoundResult(
                table_root=event.table_root, round=event.round, net=event.net
            )
        )
        del results[: max(0, len(results) - RECENT_RESULTS)]

    def round_result_retracted(
        self, projection, event: _p.RoundResultRetracted, ctx: _az.PageContext
    ) -> None:
        for result in self.ledger.player(ctx.cover.root.value).recent_results:
            if result.table_root == event.table_root and result.round == event.round:
                result.retracted = True

    # --- tables ---

    def table_created(
        self, projection, event: _table.TableCreated, ctx: _az.PageContext
    ) -> None:
        self.ledger.table(ctx.cover.root.value).name = event.name

    def player_seated(
        self, projection, event: _table.PlayerSeated, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.stacks += event.stack
        row.chips_in += event.stack
        self.ledger.transfer_side(BUY_IN, event.buy_in_id, TABLE_SIDE, event.stack)

    def chips_added(
        self, projection, event: _table.ChipsAdded, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.stacks += event.amount
        row.chips_in += event.amount
        self.ledger.transfer_side(TOP_UP, event.hold_id, TABLE_SIDE, event.amount)

    def player_cashed_out(
        self, projection, event: _table.PlayerCashedOut, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.stacks -= event.amount
        row.chips_out += event.amount
        self.ledger.transfer_side(CASH_OUT, event.cashout_id, TABLE_SIDE, event.amount)

    def bet_placed(
        self, projection, event: _table.BetPlaced, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.stacks -= event.amount
        row.wagers += event.amount

    def hand_doubled(
        self, projection, event: _table.HandDoubled, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.stacks -= event.added
        row.wagers += event.added

    def round_settled(
        self, projection, event: _table.RoundSettled, ctx: _az.PageContext
    ) -> None:
        row = self.ledger.table(ctx.cover.root.value)
        row.wagers -= sum(o.wager for o in event.outcomes)
        row.stacks += sum(o.returned for o in event.outcomes)
        row.house_result += event.house_delta

    # --- the delivery's result ---

    def finish(self, projection, events: _t.EventBook) -> _t.Projection:
        """Refresh the totals and report the row this book changed."""
        self.ledger.refresh_totals()
        root = events.cover.root.value
        view = (
            self.ledger.player_view(root)
            if events.cover.domain == "player"
            else self.ledger.ledger_view()
        )
        sequence = events.pages[-1].header.sequence if events.pages else 0
        return _t.Projection(
            cover=events.cover,
            projector=PROJECTOR,
            sequence=sequence,
            projection=_az.pack(view),
        )


# endregion projector


class LedgerProjectorHost:
    """The LedgerProjector registered on the router over one :class:`Ledger`.
    ``project`` applies each page of a delivered book at most once."""

    def __init__(self, router: _az.Router, dispatch_factory) -> None:
        self.ledger = Ledger()
        self.router = router
        self._lock = threading.Lock()
        dispatch = dispatch_factory(LedgerProjector(self.ledger))
        dispatch.factory = lambda: self.ledger.projection
        router.register_projector(dispatch)

    def project(self, book: _t.EventBook) -> _t.Projection:
        with self._lock:
            fresh = self.ledger.unapplied(book)
            projection = self.router.dispatch_projector(fresh)
            self.ledger.mark_applied(fresh)
            return projection

    def speculate(self, book: _t.EventBook) -> _t.Projection:
        """The projection ``book`` would produce, leaving the ledger untouched."""
        with self._lock:
            saved = self.ledger.copy()
            try:
                return self.router.dispatch_projector(self.ledger.unapplied(book))
            finally:
                self._restore(saved)

    def _restore(self, saved: Ledger) -> None:
        self.ledger.projection.CopyFrom(saved.projection)
        self.ledger.open_holds = saved.open_holds
        self.ledger.transfers = saved.transfers
        self.ledger.applied = saved.applied
