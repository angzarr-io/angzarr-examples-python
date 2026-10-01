"""Steps for features/example/blackjack/round.feature (playing a round)."""

from __future__ import annotations

import parse
from behave import given, register_type, step, then, when

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack.cards import (
    format_card,
    format_cards,
    hand_value,
    is_blackjack,
    next_seed,
    parse_cards,
    shuffle,
)
from angzarr_blackjack.table.agg import rules
from unit_steps._harness import TABLE, player_root, table_root
from unit_steps._helpers import (
    act,
    create_table,
    deal,
    play_standing,
    ok,
    place_bet,
    seat_player,
    set_shoe,
    table_state,
)

Phase = _table.TableState.Phase
Outcome = _table.SeatOutcome.Outcome
_OUTCOMES = {
    "lose": Outcome.OUTCOME_LOSE,
    "push": Outcome.OUTCOME_PUSH,
    "win": Outcome.OUTCOME_WIN,
    "blackjack": Outcome.OUTCOME_BLACKJACK,
}
_SEATS = {"Alice": 0, "Bob": 1}


def table_events(w, message_class, table: str = "Main") -> list:
    return w.events(TABLE, table_root(table), message_class)


def last_event(w, message_class, table: str = "Main"):
    events = table_events(w, message_class, table)
    assert events, f"no {message_class.DESCRIPTOR.name} at table {table}"
    return events[-1]


# --- the table for a round ----------------------------------------------------------


@given(
    'table "{table}" with bets from {min_bet:d} to {max_bet:d} where "{first}" sits at seat {seat_1:d} '
    'and "{second}" at seat {seat_2:d}, each with a stack of {stack:d}'
)
def step_round_table(
    context, table, min_bet, max_bet, first, seat_1, second, seat_2, stack
):
    w = context.world
    ok(create_table(w, table, min_bet=min_bet, max_bet=max_bet))
    seat_player(w, first, seat_1, stack, table)
    seat_player(w, second, seat_2, stack, table)


@given('"{name}" has {stack:d} chips left')
def step_chips_left(context, name, stack):
    """History in which the player's stack came down to ``stack``: they left
    and were seated again with it."""
    w = context.world
    seat = _SEATS[name]
    current = table_state(w).seated[seat]
    w.seed(
        TABLE,
        table_root("Main"),
        _table.PlayerCashedOut(
            player_root=player_root(name), seat=seat, amount=current.stack
        ),
        _table.PlayerSeated(player_root=player_root(name), seat=seat, stack=stack),
    )


@given('the shoe begins "{cards}"')
def step_shoe_begins(context, cards):
    set_shoe(context.world, cards)


@given('table "{table}"\'s first shoe was shuffled from seed {seed:d}')
def step_first_shoe(context, table, seed):
    context.world.seed(
        TABLE,
        table_root(table),
        _table.ShoeShuffled(shoe_number=1, seed=seed, decks=1, cards=shuffle(seed, 1)),
    )


@given(
    'table "{table}"\'s first shoe was shuffled from seed {seed:d} and has {left:d} cards left'
)
def step_first_shoe_left(context, table, seed, left):
    """Shoe 1 from ``seed`` with only its last ``left`` cards still undealt."""
    if table_state(context.world, table).phase == Phase.PHASE_UNSPECIFIED:
        ok(create_table(context.world, table, seed=seed))
    context.world.seed(
        TABLE,
        table_root(table),
        _table.ShoeShuffled(
            shoe_number=1, seed=seed, decks=1, cards=shuffle(seed, 1)[-left:]
        ),
    )


@given("{count:d} players have bet {amount:d}")
def step_players_bet(context, count, amount):
    for seat in range(count):
        ok(place_bet(context.world, seat, amount))


@given('round {round:d} has been played and settled at table "{table}"')
def step_round_played(context, round, table):
    ok(place_bet(context.world, 0, 20, table))
    play_standing(context.world, table)
    assert table_state(context.world, table).round == round


# --- betting -------------------------------------------------------------------------


@step('"{name}" {verb} bet {amount:d} at seat {seat:d}')
def step_bet(context, name, verb, amount, seat):
    outcome = place_bet(context.world, seat, amount)
    if verb == "has":
        ok(outcome)


@when('"{name}" bets {amount:d} at seat {seat:d}')
def step_bets(context, name, amount, seat):
    place_bet(context.world, seat, amount)


@when("someone bets {amount:d} at seat {seat:d}")
def step_someone_bets(context, amount, seat):
    place_bet(context.world, seat, amount)


@then("seat {seat:d} has a wager of {wager:d} and a stack of {stack:d}")
def step_wager_and_stack(context, seat, wager, stack):
    s = table_state(context.world).seated[seat]
    assert (s.wager, s.stack) == (wager, stack), f"wager {s.wager}, stack {s.stack}"


@then("the bet is for round {round:d}")
def step_bet_round(context, round):
    assert context.world.last.decoded(_table.BetPlaced)[0].round == round


# --- dealing and acting ----------------------------------------------------------------


@given("the round has been dealt")
def step_dealt(context):
    ok(deal(context.world))


@when("the round is dealt")
def step_deal(context):
    deal(context.world)


_ACTIONS = {
    "hits": _table.Hit,
    "stands": _table.Stand,
    "doubles down": _table.DoubleDown,
    "has hit": _table.Hit,
    "has doubled down": _table.DoubleDown,
}


@parse.with_pattern("|".join(sorted(_ACTIONS, key=len, reverse=True)))
def _action(text: str) -> str:
    return text


register_type(Action=_action)


@step('"{name}" {action:Action} at seat {seat:d}')
def step_act(context, name, action, seat):
    outcome = act(context.world, _ACTIONS[action], seat)
    if action.startswith("has "):
        ok(outcome)


@when("the round is played with every player standing as soon as it is their turn")
def step_play_standing(context):
    play_standing(context.world)


@then("round {round:d} is dealt with:")
def step_dealt_with(context, round):
    dealt = context.world.last.decoded(_table.RoundDealt)
    assert len(dealt) == 1, context.world.last.types()
    hands = {h.seat: h for h in dealt[0].hands}
    assert dealt[0].round == round
    assert len(hands) == len(context.table.rows)
    for row in context.table:
        hand = hands[int(row["seat"])]
        assert format_cards(hand.cards) == row["cards"], format_cards(hand.cards)
        assert hand.total == int(row["total"])


@then("seat {seat:d} is dealt no cards")
def step_no_cards(context, seat):
    dealt = context.world.last.decoded(_table.RoundDealt)[0]
    assert seat not in {h.seat for h in dealt.hands}


@then("the dealer shows {up} with the hole card {hole} face down")
def step_dealer_shows(context, up, hole):
    dealt = context.world.last.decoded(_table.RoundDealt)[0]
    assert (format_card(dealt.dealer_up), format_card(dealt.dealer_hole)) == (up, hole)


@then("it is seat {seat:d}'s turn")
def step_turn(context, seat):
    state = table_state(context.world)
    assert (
        state.phase == Phase.PHASE_PLAYER_TURNS and state.turn == seat
    ), f"turn is {state.turn}"


@then("seat {seat:d} holds a blackjack")
def step_holds_blackjack(context, seat):
    assert table_state(context.world).seated[seat].hand.blackjack


@then("seat {seat:d} is dealt {card} for a {kind} {total:d}")
def step_dealt_card(context, seat, card, kind, total):
    dealt = context.world.last.decoded(_table.CardDealt)[0]
    assert (dealt.seat, format_card(dealt.card), dealt.total) == (seat, card, total)
    assert dealt.soft == (kind == "soft") and not dealt.busted


@then("seat {seat:d} is dealt {card} and busts with {total:d}")
def step_busts(context, seat, card, total):
    dealt = context.world.last.decoded(_table.CardDealt)[0]
    assert (dealt.seat, format_card(dealt.card), dealt.total, dealt.busted) == (
        seat,
        card,
        total,
        True,
    )


@then("seat {seat:d} is dealt {card} for {total:d} on a wager of {wager:d}")
def step_doubled(context, seat, card, total, wager):
    doubled = context.world.last.decoded(_table.HandDoubled)[0]
    assert (doubled.seat, format_card(doubled.card), doubled.total) == (
        seat,
        card,
        total,
    )
    assert table_state(context.world).seated[seat].wager == wager


@then("seat {seat:d} stands on {total:d}")
def step_stands_on(context, seat, total):
    stood = context.world.last.decoded(_table.HandStood)[0]
    assert (stood.seat, stood.total) == (seat, total)


@then("seat {seat:d} is dealt the first and third cards of that shoe")
def step_first_and_third(context, seat):
    shoe = last_event(context.world, _table.ShoeShuffled)
    dealt = context.world.last.decoded(_table.RoundDealt)[0]
    hand = {h.seat: h for h in dealt.hands}[seat]
    assert list(hand.cards) == [shoe.cards[0], shoe.cards[2]]


# --- the dealer ------------------------------------------------------------------------


def _dealer(context) -> _table.DealerPlayed:
    played = context.world.last.decoded(_table.DealerPlayed)
    assert len(played) == 1, f"the dealer did not play: {context.world.last.types()}"
    return played[0]


@then("the dealer reveals {hole} and stands on a soft {total:d} without drawing")
def step_dealer_soft(context, hole, total):
    d = _dealer(context)
    assert (format_card(d.hole), list(d.drawn), d.total, d.soft) == (
        hole,
        [],
        total,
        True,
    )


@then("the dealer reveals {hole} and stands on {total:d} without drawing")
def step_dealer_stands(context, hole, total):
    d = _dealer(context)
    assert (format_card(d.hole), list(d.drawn), d.total, d.busted) == (
        hole,
        [],
        total,
        False,
    )


@then("the dealer reveals {hole}, draws {drawn} and stands on {total:d}")
def step_dealer_draws(context, hole, drawn, total):
    d = _dealer(context)
    assert (format_card(d.hole), format_cards(d.drawn), d.total, d.busted) == (
        hole,
        drawn,
        total,
        False,
    )


@then("the dealer reveals {hole}, draws {drawn} and busts with {total:d}")
def step_dealer_busts(context, hole, drawn, total):
    d = _dealer(context)
    assert (format_card(d.hole), format_cards(d.drawn), d.total, d.busted) == (
        hole,
        drawn,
        total,
        True,
    )


@then("the dealer reveals {hole} for a blackjack")
def step_dealer_blackjack(context, hole):
    d = _dealer(context)
    assert format_card(d.hole) == hole and d.blackjack and not d.drawn


# --- settlement --------------------------------------------------------------------------


def _settled(context) -> _table.RoundSettled:
    settled = context.world.last.decoded(_table.RoundSettled)
    assert len(settled) == 1, f"the round was not settled: {context.world.last.types()}"
    return settled[0]


@then("round {round:d} is settled with:")
def step_settled_with(context, round):
    settled = _settled(context)
    assert settled.round == round
    actual = [
        (o.seat, o.wager, o.outcome, o.returned, o.stack_after)
        for o in settled.outcomes
    ]
    expected = [
        (
            int(r["seat"]),
            int(r["wager"]),
            _OUTCOMES[r["outcome"]],
            int(r["returned"]),
            int(r["stack after"]),
        )
        for r in context.table
    ]
    assert actual == expected, f"{actual} != {expected}"


@then("round {round:d} is settled")
def step_round_settled(context, round):
    assert [s.round for s in table_events(context.world, _table.RoundSettled)] == [
        round
    ]


@then("the house {verb} {amount:d}")
def step_house(context, verb, amount):
    delta = _settled(context).house_delta
    assert delta == (amount if verb == "wins" else -amount), f"house delta {delta}"


@then("the house breaks even")
def step_house_even(context):
    assert _settled(context).house_delta == 0


@then(
    "the table records, as one step, that seat {seat:d} stood, the dealer played and round {round:d} was settled"
)
def step_one_step(context, seat, round):
    last = context.world.last
    assert last.types() == ["HandStood", "DealerPlayed", "RoundSettled"], last.types()
    assert last.decoded(_table.HandStood)[0].seat == seat
    assert last.decoded(_table.RoundSettled)[0].round == round


@then("the table is ready for the next round's bets")
def step_ready(context):
    state = table_state(context.world)
    assert state.phase == Phase.PHASE_IDLE and not any(
        s.wager for s in state.seated.values()
    )


@then('the table "{table}" ledger balanced after every step')
def step_balanced_every_step(context, table):
    w = context.world
    host = w.hosts[TABLE]
    pages = w.stream(TABLE, table_root(table))
    full = w.book(TABLE, table_root(table), from_snapshot=False)
    for count in range(1, len(pages) + 1):
        prefix = type(full)()
        prefix.pages.extend(full.pages[:count])
        assert rules.ledger_balances(
            host.rebuild(prefix)
        ), f"L2 broken after event {count}"


# --- card values --------------------------------------------------------------------------


@when("a hand holds {cards}")
def step_hand_holds(context, cards):
    context.hand = parse_cards(cards)


@then("the hand is worth {total:d}, {kind}")
def step_hand_worth(context, total, kind):
    value, soft = hand_value(context.hand)
    assert value == total, value
    if kind == "blackjack":
        assert is_blackjack(context.hand)
    else:
        assert soft == (kind == "soft") and not is_blackjack(context.hand)


# --- reshuffling --------------------------------------------------------------------------


@then("shoe {number:d} is shuffled from seed {seed:d} before the cards are dealt")
def step_reshuffled(context, number, seed):
    last = context.world.last
    assert last.types()[:2] == ["ShoeShuffled", "RoundDealt"], last.types()
    shoe = last.decoded(_table.ShoeShuffled)[0]
    assert (shoe.shoe_number, shoe.seed) == (number, seed)
    assert list(shoe.cards) == shuffle(seed, 1)
    first_seed = table_events(context.world, _table.ShoeShuffled)[-2].seed
    assert next_seed(first_seed) == seed


@then("the round is dealt from shoe {number:d}")
def step_dealt_from(context, number):
    last = context.world.last
    assert (
        "ShoeShuffled" not in last.types() and "RoundDealt" in last.types()
    ), last.types()
    assert table_state(context.world).shoe_number == number
