"""Shared building blocks for the in-process step definitions.

Givens run the real commands through the components wherever a command can
produce the history (registering, depositing, seating, betting); the only
history seeded directly is what no command can produce on demand: a shoe in a
given order, a legacy-shaped event, or a single side of a transfer.
"""

from __future__ import annotations

import angzarr_client.router as _az

from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack.cards import card_from_index, parse_cards
from unit_steps._harness import (
    PLAYER,
    TABLE,
    World,
    cover,
    player_root,
    request_id,
    table_root,
)

TABLE_DEFAULTS = dict(
    min_bet=10, max_bet=100, min_buy_in=100, max_buy_in=1000, seats=3, decks=1
)


def ok(outcome):
    assert outcome.error is None, f"setup step was refused: {outcome.error}"
    return outcome


# --- the wallet ----------------------------------------------------------------


def register(w: World, name: str, deposit: int = 0) -> None:
    w.labels.setdefault("players", []).append(name)
    ok(
        w.command(
            PLAYER,
            player_root(name),
            _p.RegisterPlayer(display_name=name, email=f"{name.lower()}@example.com"),
        )
    )
    if deposit:
        ok(w.command(PLAYER, player_root(name), _p.DepositFunds(amount=deposit)))


def wallet(w: World, name: str) -> _p.PlayerState:
    return w.state(PLAYER, player_root(name))


def hold_funds(w: World, name: str, label: str, table: str, amount: int):
    return w.command(
        PLAYER,
        player_root(name),
        _p.HoldFunds(
            hold_id=request_id(label), table_root=table_root(table), amount=amount
        ),
    )


def request_top_up(w: World, name: str, label: str, table: str, amount: int):
    return w.command(
        PLAYER,
        player_root(name),
        _p.RequestTopUp(
            table_root=table_root(table), amount=amount, request_id=request_id(label)
        ),
    )


def add_chips_command(name: str, label: str, table: str, amount: int) -> _t.CommandBook:
    """The AddChips the top-up translator sends for a top-up, as delivered:
    deferred, its source the wallet whose request triggered it."""
    book = _t.CommandBook(cover=cover(TABLE, table_root(table)))
    page = book.pages.add()
    page.header.angzarr_deferred.source.CopyFrom(cover(PLAYER, player_root(name)))
    page.header.angzarr_deferred.source_component = "sagas"
    page.command.CopyFrom(
        _az.pack(
            _table.AddChips(
                player_root=player_root(name), hold_id=request_id(label), amount=amount
            )
        )
    )
    return book


def chips_added_at_table(
    w: World, name: str, label: str, table: str, amount: int, stack_after: int = 0
):
    """The table's ChipsAdded for a top-up, through the settlement translator."""
    event = _table.ChipsAdded(
        hold_id=request_id(label),
        player_root=player_root(name),
        amount=amount,
        stack_after=stack_after,
    )
    return w.run_sagas(table_event_book(w, table, event))


def cashed_out_at_table(
    w: World, name: str, table: str, amount: int, label: str = "cash-out"
):
    event = _table.PlayerCashedOut(
        cashout_id=request_id(label), player_root=player_root(name), amount=amount
    )
    return w.run_sagas(table_event_book(w, table, event))


def table_event_book(w: World, table: str, event, sequence: int = 0) -> _t.EventBook:
    book = _t.EventBook(cover=cover(TABLE, table_root(table), w.correlation))
    page = book.pages.add()
    page.header.sequence = sequence
    page.event.CopyFrom(_az.pack(event))
    return book


def refuse_top_up(w: World, name: str, label: str, table: str, amount: int, code: str):
    """The table's refusal of a top-up's AddChips, delivered to the wallet."""
    rejected = add_chips_command(name, label, table, amount)
    notification = w.rejection(rejected, f"{code}: the table refused the chips")
    return w.notify(
        notification, rejected.pages[0].header.angzarr_deferred, w.correlation
    )


def open_hold(state: _p.PlayerState, label: str):
    hold = state.holds.get(request_id(label).hex())
    if hold is not None and hold.status == _p.Hold.Status.STATUS_OPEN:
        return hold
    return None


# --- the table -----------------------------------------------------------------


def create_table(w: World, name: str = "Main", seed: int = 42, **config):
    settings = {**TABLE_DEFAULTS, **config}
    return w.command(
        TABLE,
        table_root(name),
        _table.CreateTable(name=name, shoe_seed=seed, **settings),
    )


def table_state(w: World, name: str = "Main") -> _table.TableState:
    return w.state(TABLE, table_root(name))


def request_seat(
    w: World, player: str, seat: int, amount: int, label: str, table: str = "Main"
):
    return w.command(
        TABLE,
        table_root(table),
        _table.RequestSeat(
            player_root=player_root(player),
            seat=seat,
            amount=amount,
            request_id=request_id(label),
        ),
    )


def confirm_seat(w: World, label: str, table: str = "Main"):
    return w.command(
        TABLE, table_root(table), _table.ConfirmSeat(buy_in_id=request_id(label))
    )


def seat_player(
    w: World,
    player: str,
    seat: int,
    stack: int,
    table: str = "Main",
    label: str | None = None,
) -> None:
    """Hold a seat for a buy-in and confirm it (the table's half of a buy-in)."""
    label = label or f"buy-in:{player}:{seat}"
    ok(request_seat(w, player, seat, stack, label, table))
    ok(confirm_seat(w, label, table))


def place_bet(w: World, seat: int, amount: int, table: str = "Main"):
    return w.command(
        TABLE, table_root(table), _table.PlaceBet(seat=seat, amount=amount)
    )


def set_shoe(w: World, cards_text: str, table: str = "Main") -> None:
    """The next cards dealt are ``cards_text``; the rest of the shoe follows
    in fresh-deck order with those cards taken out."""
    state = table_state(w, table)
    top = parse_cards(cards_text)
    taken = [(c.rank, c.suit) for c in top]
    rest = []
    for card in fresh_deck():
        key = (card.rank, card.suit)
        if key in taken:
            taken.remove(key)
        else:
            rest.append(card)
    w.seed(
        TABLE,
        table_root(table),
        _table.ShoeShuffled(
            shoe_number=state.shoe_number,
            seed=state.shoe_seed,
            decks=1,
            cards=[*top, *rest],
        ),
    )


def fresh_deck():
    return [card_from_index(i) for i in range(52)]


def seat_number_of(state, name: str) -> int | None:
    for number, seat in state.seated.items():
        if seat.player_root == player_root(name):
            return number
    return None


def act(w: World, action, seat: int, table: str = "Main"):
    return w.command(TABLE, table_root(table), action(seat=seat))


def deal(w: World, table: str = "Main"):
    return w.command(TABLE, table_root(table), _table.DealRound())


def play_standing(w: World, table: str = "Main") -> None:
    """Deal, then stand every seat as soon as it is on turn."""
    ok(deal(w, table))
    while table_state(w, table).phase == _table.TableState.Phase.PHASE_PLAYER_TURNS:
        ok(act(w, _table.Stand, table_state(w, table).turn, table))
