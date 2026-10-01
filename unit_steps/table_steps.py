"""Steps for features/example/blackjack/table.feature (seats and chips)."""

from __future__ import annotations

import re
import uuid

from behave import given, step, then, when

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack.cards import format_cards
from angzarr_blackjack.table.agg import rules
from unit_steps._harness import TABLE, player_root, request_id, table_root
from unit_steps._helpers import (
    confirm_seat,
    create_table,
    ok,
    request_seat,
    seat_number_of,
    seat_player,
    table_state,
)

Phase = _table.TableState.Phase


# --- creating -------------------------------------------------------------------


@given('table "{name}" does not exist')
def step_no_table(context, name):
    assert table_state(context.world, name).phase == Phase.PHASE_UNSPECIFIED


@given('table "{name}" exists')
def step_table_exists(context, name):
    ok(create_table(context.world, name))


@when(
    'table "{name}" is created with {seats:d} seats, {decks:d} deck and shoe seed {seed:d}'
)
def step_create(context, name, seats, decks, seed):
    create_table(context.world, name, seed=seed, seats=seats, decks=decks)


@when(
    'table "{name}" is created with {seats:d} seats, {decks:d} decks, bets {min_bet:d} to {max_bet:d} '
    "and buy-ins {min_buy_in:d} to {max_buy_in:d}"
)
def step_create_config(
    context, name, seats, decks, min_bet, max_bet, min_buy_in, max_buy_in
):
    create_table(
        context.world,
        name,
        seats=seats,
        decks=decks,
        min_bet=min_bet,
        max_bet=max_bet,
        min_buy_in=min_buy_in,
        max_buy_in=max_buy_in,
    )


@then('table "{name}" is open with {seats:d} empty seats')
def step_open(context, name, seats):
    state = table_state(context.world, name)
    assert state.phase == Phase.PHASE_IDLE and state.seats == seats and not state.seated


@then('table "{name}" has shoe {number:d} shuffled from seed {seed:d}')
def step_shoe_from_seed(context, name, number, seed):
    state = table_state(context.world, name)
    assert (state.shoe_number, state.shoe_seed) == (number, seed)


@then('the first {count:d} cards of the shoe are "{cards}"')
def step_first_cards(context, count, cards):
    state = table_state(context.world, "Main")
    assert format_cards(state.shoe[:count]) == cards, format_cards(state.shoe[:count])


# --- seats ----------------------------------------------------------------------


@step(
    '"{name}" {verb} for seat {seat:d} at table "{table}" with a buy-in of {amount:d} as request "{label}"'
)
def step_ask_seat(context, name, verb, seat, table, amount, label):
    outcome = request_seat(context.world, name, seat, amount, label, table)
    if verb == "asked":
        ok(outcome)


@given(
    'seat {seat:d} at table "{table}" is held for "{name}" by buy-in "{label}" of {amount:d}'
)
def step_seat_held_given(context, seat, table, name, label, amount):
    ok(request_seat(context.world, name, seat, amount, label, table))


@then(
    'seat {seat:d} at table "{table}" is held for "{name}" by buy-in "{label}" of {amount:d}'
)
def step_seat_held(context, seat, table, name, label, amount):
    hold = table_state(context.world, table).seat_holds.get(request_id(label).hex())
    assert hold is not None, f"buy-in {label} holds no seat"
    assert (hold.seat, hold.player_root, hold.amount) == (
        seat,
        player_root(name),
        amount,
    )


@given('seat {seat:d} at table "{table}" is {occupied} by "{name}"')
def step_seat_occupied(context, seat, table, occupied, name):
    if occupied == "held":
        ok(request_seat(context.world, name, seat, 500, f"held:{name}", table))
    else:
        seat_player(context.world, name, seat, 500, table)


@then('no one is seated at table "{table}"')
def step_no_one_seated(context, table):
    assert not table_state(context.world, table).seated


@given(
    '"{name}" is seated at seat {seat:d} of table "{table}" with a stack of {stack:d}'
)
def step_seated_given(context, name, seat, table, stack):
    seat_player(context.world, name, seat, stack, table)


@then(
    '"{name}" is seated at seat {seat:d} of table "{table}" with a stack of {stack:d}'
)
def step_seated(context, name, seat, table, stack):
    state = table_state(context.world, table)
    assert seat in state.seated, f"seat {seat} is empty"
    assert state.seated[seat].player_root == player_root(name)
    assert state.seated[seat].stack == stack, f"stack is {state.seated[seat].stack}"


@given(
    '"{name}" is seated at seat {seat:d} of table "{table}" through buy-in "{label}" of {amount:d}'
)
def step_seated_through(context, name, seat, table, label, amount):
    seat_player(context.world, name, seat, amount, table, label)


@step('buy-in "{label}" {verb} confirmed at table "{table}"')
def step_confirm(context, label, verb, table):
    outcome = confirm_seat(context.world, label, table)
    if verb == "was":
        ok(outcome)


@when('the seat held by buy-in "{label}" is released because "{reason}"')
def step_release_seat(context, label, reason):
    context.world.command(
        TABLE,
        table_root("Main"),
        _table.ReleaseSeat(buy_in_id=request_id(label), reason=reason),
    )


@then('seat {seat:d} at table "{table}" is free')
def step_seat_free(context, seat, table):
    state = table_state(context.world, table)
    assert seat not in state.seated, f"seat {seat} is taken"
    assert seat not in {
        h.seat for h in state.seat_holds.values()
    }, f"seat {seat} is held"


# --- chips ----------------------------------------------------------------------


def add_chips(w, amount: int, label: str, name: str, table: str):
    return w.command(
        TABLE,
        table_root(table),
        _table.AddChips(
            player_root=player_root(name), hold_id=request_id(label), amount=amount
        ),
    )


@step(
    '{amount:d} chips from top-up "{label}" {verb} added for "{name}" at table "{table}"'
)
def step_add_chips(context, amount, label, verb, name, table):
    outcome = add_chips(context.world, amount, label, name, table)
    if verb == "were":
        ok(outcome)


@then('table "{table}" has taken in {amount:d} chips')
def step_taken_in(context, table, amount):
    assert table_state(context.world, table).chips_in == amount


@then('table "{table}" has paid out {amount:d} chips')
def step_paid_out(context, table, amount):
    assert table_state(context.world, table).chips_out == amount


@then('table "{table}" has taken in {taken:d} chips and paid out {paid:d}')
def step_taken_and_paid(context, table, taken, paid):
    state = table_state(context.world, table)
    assert (state.chips_in, state.chips_out) == (taken, paid)


@then('the table "{table}" ledger balances')
def step_table_balances(context, table):
    state = table_state(context.world, table)
    assert rules.ledger_balances(state), f"L2 broken: {state}"


# --- leaving --------------------------------------------------------------------


@when('the player at seat {seat:d} of table "{table}" leaves')
def step_leave(context, seat, table):
    context.world.command(TABLE, table_root(table), _table.LeaveTable(seat=seat))


@then('"{name}" cashes out {amount:d} from table "{table}"')
def step_cashes_out(context, name, amount, table):
    cashed = context.world.last.decoded(_table.PlayerCashedOut)
    assert len(cashed) == 1, context.world.last.types()
    assert (cashed[0].player_root, cashed[0].amount) == (player_root(name), amount)


@then(
    'the cash-out identity is derived from table "{table}" and the position of the cash-out in its history'
)
def step_cashout_identity(context, table):
    page = context.world.last.events[0]
    cashed = context.world.last.decoded(_table.PlayerCashedOut)[0]
    expected = uuid.uuid5(
        uuid.UUID(bytes=table_root(table)), f"cashout/{page.header.sequence}"
    )
    assert cashed.cashout_id == expected.bytes


# --- a sequence of seat and chip movements (L2) -----------------------------------

_ROWS = [
    r'^"(?P<name>[^"]+)" buys in at seat (?P<seat>\d+) through buy-in "(?P<label>[^"]+)"$',
    r'^"(?P<name>[^"]+)" adds chips from top-up "(?P<label>[^"]+)"$',
    r'^"(?P<name>[^"]+)" leaves$',
]


@when('the following happen at table "{table}" in order:')
def step_table_sequence(context, table):
    w = context.world
    for row in context.table:
        amount = int(row["amount"])
        text = row["step"]
        if m := re.match(_ROWS[0], text):
            seat_player(w, m["name"], int(m["seat"]), amount, table, m["label"])
        elif m := re.match(_ROWS[1], text):
            ok(add_chips(w, amount, m["label"], m["name"], table))
        elif m := re.match(_ROWS[2], text):
            number = seat_number_of(table_state(w, table), m["name"])
            ok(w.command(TABLE, table_root(table), _table.LeaveTable(seat=number)))
            assert w.last.decoded(_table.PlayerCashedOut)[0].amount == amount
        else:
            raise AssertionError(f"unknown table movement {text!r}")
