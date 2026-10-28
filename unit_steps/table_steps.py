"""Steps for features/example/blackjack/table.feature: creating a table (the
stage-1 slice; the seat and chip scenarios wait on the blackjack rulings)."""

from __future__ import annotations

from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack.cards import format_cards
from unit_steps._helpers import create_table, ok, table_state

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
