"""The TableAggregate on the generated ``TableAggregateHandler`` seam.

This is the stage-1 slice of the table: ``CreateTable`` records
``TableCreated`` and the first ``ShoeShuffled``, and the two appliers fold
them into ``TableState``. A command runs ``_guard_*`` → ``_validate_*`` → ``_compute_*``; the computation is pure and folds the events it emits into a
working copy of the state, so a later event in the same book sees an earlier
one. House rules are in :mod:`.rules`.

The rest of the seam (seats, bets, rounds, settlement) is not implemented on
this branch: it waits on the blackjack rulings R1-R4 (see the README). A
command outside the slice reaches no method here and the router reports it as
a failure; nothing pretends to handle it.
"""

from __future__ import annotations

import angzarr_client.router as _az

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import event_book
from angzarr_blackjack.cards import shuffle
from angzarr_blackjack.errors import invalid, precondition
from angzarr_blackjack.table.agg import rules

TableState = _table.TableState
# The page context of an event folded before it is stored.
_UNSTORED = _az.PageContext()
Phase = TableState.Phase


class _Book:
    """Events emitted by one command, folded as they are emitted into a copy
    of the state."""

    def __init__(self, aggregate: TableAggregate, state: TableState) -> None:
        self._aggregate = aggregate
        self.state = TableState()
        self.state.CopyFrom(state)
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)
        self._aggregate.apply(self.state, event)

    def to_event_book(self) -> _t.EventBook | None:
        if not self.events:
            return None
        return event_book(*self.events)


class TableAggregate:
    """Implements the stage-1 part of ``TableAggregateHandler``: creating the
    table and shuffling its first shoe."""

    def __init__(self) -> None:
        self._appliers = {
            _table.TableCreated: self.apply_table_created,
            _table.ShoeShuffled: self.apply_shoe_shuffled,
        }

    def apply(self, state: TableState, event) -> None:
        """Fold an event this command has just computed (no stored page yet)."""
        self._appliers[type(event)](state, event, _UNSTORED)

    def _run(self, guard, validate, compute, cmd, state) -> _t.EventBook | None:
        guard(state)
        validate(cmd)
        book = _Book(self, state)
        compute(cmd, book)
        return book.to_event_book()

    # --- creating the table ---

    def create_table(
        self, cmd: _table.CreateTable, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_new, self._validate_config, self._compute_create, cmd, state
        )

    @staticmethod
    def _guard_new(state: TableState) -> None:
        if state.phase != Phase.PHASE_UNSPECIFIED:
            raise precondition("TABLE_ALREADY_EXISTS", "the table already exists")

    @staticmethod
    def _validate_config(cmd: _table.CreateTable) -> None:
        if not rules.config_is_valid(
            cmd.seats,
            cmd.decks,
            cmd.min_bet,
            cmd.max_bet,
            cmd.min_buy_in,
            cmd.max_buy_in,
        ):
            raise invalid(
                "INVALID_TABLE_CONFIG", "the table configuration breaks the house rules"
            )

    @staticmethod
    def _compute_create(cmd: _table.CreateTable, book: _Book) -> None:
        book.emit(
            _table.TableCreated(
                name=cmd.name,
                min_bet=cmd.min_bet,
                max_bet=cmd.max_bet,
                min_buy_in=cmd.min_buy_in,
                max_buy_in=cmd.max_buy_in,
                seats=cmd.seats,
                decks=cmd.decks,
            )
        )
        book.emit(
            _table.ShoeShuffled(
                shoe_number=1,
                seed=cmd.shoe_seed,
                decks=cmd.decks,
                cards=shuffle(cmd.shoe_seed, cmd.decks),
            )
        )

    # --- appliers ---

    def apply_table_created(
        self, state: TableState, event: _table.TableCreated, ctx: _az.PageContext
    ) -> None:
        state.name = event.name
        state.min_bet = event.min_bet
        state.max_bet = event.max_bet
        state.min_buy_in = event.min_buy_in
        state.max_buy_in = event.max_buy_in
        state.seats = event.seats
        state.decks = event.decks
        state.phase = Phase.PHASE_IDLE

    def apply_shoe_shuffled(
        self, state: TableState, event: _table.ShoeShuffled, ctx: _az.PageContext
    ) -> None:
        state.shoe_number = event.shoe_number
        state.shoe_seed = event.seed
        state.decks = event.decks
        del state.shoe[:]
        state.shoe.extend(event.cards)
