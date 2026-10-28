"""Steps for features/example/blackjack/shoe.feature (golden shoe vectors).

A shoe is made the way a table makes one: CreateTable with the seed and deck
count, read back from the ShoeShuffled event the table records. The random
source and the bounded draw are checked directly against ``cards``.
"""

from __future__ import annotations

from collections import Counter

from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack.cards import (
    SplitMix64,
    card_index,
    format_card,
    format_cards,
    next_seed,
)
from unit_steps._helpers import create_table, ok


@when("a shoe of {decks:d} {unit} shuffled with seed {seed:d}")
def step_shuffle(context, decks, unit, seed):
    outcome = ok(create_table(context.world, "Shoe", seed=seed, decks=decks))
    context.shoe = list(outcome.decoded(_table.ShoeShuffled)[0].cards)


@then('the first {count:d} cards dealt are "{cards}"')
def step_first_cards(context, count, cards):
    assert format_cards(context.shoe[:count]) == cards, format_cards(
        context.shoe[:count]
    )


@then('the last card dealt is "{card}"')
def step_last_card(context, card):
    assert format_card(context.shoe[-1]) == card


@then("the shoe deals in this order:")
def step_full_order(context):
    expected = " ".join(row["in order"] for row in context.table)
    assert format_cards(context.shoe) == expected, format_cards(context.shoe)


@then("the shoe holds {count:d} cards")
def step_shoe_size(context, count):
    assert len(context.shoe) == count


@then("every one of the 52 cards appears exactly {times:d} times")
def step_every_card(context, times):
    counts = Counter(card_index(card) for card in context.shoe)
    assert sorted(counts) == list(range(52)) and set(counts.values()) == {times}


@given("a shoe was shuffled with seed {seed:d}")
def step_shoe_seed(context, seed):
    context.seed = seed


@when("the next shoe is needed")
def step_next_shoe(context):
    context.next_seed = next_seed(context.seed)


@then("the next shoe is shuffled with seed {seed:d}")
def step_next_seed(context, seed):
    assert context.next_seed == seed


@given("the random source starts from seed {seed:d}")
@when("the random source starts from seed {seed:d}")
def step_random_source(context, seed):
    context.rng = SplitMix64(seed)


@then("its first three values are {first:d} {second:d} {third:d}")
def step_first_three(context, first, second, third):
    assert [context.rng.next() for _ in range(3)] == [first, second, third]


@when("five values below {bound:d} are drawn")
def step_draw_five(context, bound):
    context.draws = [context.rng.below(bound) for _ in range(5)]


@then("the draws are:")
def step_draws(context):
    assert context.draws == [int(row["value"]) for row in context.table]
