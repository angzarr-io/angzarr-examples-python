"""Steps for features/example/blackjack-framework/session.feature: every
component wired in one process, driven by client commands only.

Each client request that starts a cross-domain conversation (a buy-in or a
top-up) is sent in a conversation of its own, as a client would.
"""

from __future__ import annotations

import re
from collections import Counter

from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.player.agg import logic
from unit_steps._harness import PLAYER, TABLE, player_root, request_id, table_root
from unit_steps._helpers import (
    create_table,
    ok,
    place_bet,
    play_standing,
    register,
    seat_number_of,
    table_state,
    wallet,
)
from unit_steps._refusals import reason_code


@given("all example components are running in one process")
def step_wired(context):
    context.world.wired = True


@given(
    'table "{table}" with {seats:d} seats, {decks:d} deck, bets from {min_bet:d} to {max_bet:d} '
    "and buy-ins from {min_buy_in:d} to {max_buy_in:d} was created with shoe seed {seed:d}"
)
def step_session_table(
    context, table, seats, decks, min_bet, max_bet, min_buy_in, max_buy_in, seed
):
    ok(
        create_table(
            context.world,
            table,
            seed=seed,
            seats=seats,
            decks=decks,
            min_bet=min_bet,
            max_bet=max_bet,
            min_buy_in=min_buy_in,
            max_buy_in=max_buy_in,
        )
    )


@given('"{first}" and "{second}" are registered and have each deposited {amount:d}')
def step_two_registered(context, first, second, amount):
    register(context.world, first, amount)
    register(context.world, second, amount)


@given('"{name}" is registered and has deposited {amount:d}')
def step_one_registered(context, name, amount):
    register(context.world, name, amount)


@given("every message between components is delivered twice")
def step_twice(context):
    context.world.deliveries = 2


# --- the client's requests ------------------------------------------------------------


def buy_in(w, name: str, seat: int, table: str, amount: int):
    label = f"buy-in:{name}:{seat}"
    w.labels["last buy-in conversation"] = label
    return w.command(
        TABLE,
        table_root(table),
        _table.RequestSeat(
            player_root=player_root(name),
            seat=seat,
            amount=amount,
            request_id=request_id(label),
        ),
        correlation=label,
    )


def top_up(w, name: str, table: str, amount: int):
    count = w.labels.setdefault(f"top-ups:{name}", 0) + 1
    w.labels[f"top-ups:{name}"] = count
    label = f"top-up:{name}:{count}"
    return w.command(
        PLAYER,
        player_root(name),
        _p.RequestTopUp(
            table_root=table_root(table), amount=amount, request_id=request_id(label)
        ),
        correlation=label,
    )


def leave(w, name: str, table: str):
    seat = seat_number_of(table_state(w, table), name)
    return w.command(TABLE, table_root(table), _table.LeaveTable(seat=seat))


_STEPS = [
    (
        r'^"(?P<name>[^"]+)" buys in at seat (?P<seat>\d+) of "(?P<table>[^"]+)" for (?P<amount>\d+)$',
        lambda w, m: buy_in(w, m["name"], int(m["seat"]), m["table"], int(m["amount"])),
    ),
    (
        r'^"(?P<name>[^"]+)" tops up (?P<amount>\d+) at "(?P<table>[^"]+)"$',
        lambda w, m: top_up(w, m["name"], m["table"], int(m["amount"])),
    ),
    (
        r'^"(?P<a>[^"]+)" bets (?P<x>\d+) and "(?P<b>[^"]+)" bets (?P<y>\d+)$',
        lambda w, m: [
            ok(place_bet(w, seat_number_of(table_state(w), m["a"]), int(m["x"]))),
            ok(place_bet(w, seat_number_of(table_state(w), m["b"]), int(m["y"]))),
        ],
    ),
    (
        r"^the round is dealt and every player stands on their turn$",
        lambda w, m: play_standing(w),
    ),
    (
        r'^"(?P<a>[^"]+)" and "(?P<b>[^"]+)" leave "(?P<table>[^"]+)"$',
        lambda w, m: [
            ok(leave(w, m["a"], m["table"])),
            ok(leave(w, m["b"], m["table"])),
        ],
    ),
    (
        r'^"(?P<name>[^"]+)" leaves "(?P<table>[^"]+)"$',
        lambda w, m: ok(leave(w, m["name"], m["table"])),
    ),
    (
        r'^"(?P<name>[^"]+)" withdraws (?P<amount>\d+)$',
        lambda w, m: ok(
            w.command(
                PLAYER,
                player_root(m["name"]),
                _p.WithdrawFunds(amount=int(m["amount"])),
            )
        ),
    ),
]


def play(w, text: str):
    for pattern, run in _STEPS:
        match = re.match(pattern, text)
        if match:
            return run(w, match)
    raise AssertionError(f"unknown session step {text!r}")


@when("the session is played:")
def step_session(context):
    for row in context.table:
        result = play(context.world, row["step"])
        if hasattr(result, "error"):
            ok(result)


@when('"{name}" buys in at seat {seat:d} of "{table}" for {amount:d}')
def step_buys_in(context, name, seat, table, amount):
    buy_in(context.world, name, seat, table, amount)


@given('"{name}" has bought in at seat {seat:d} of "{table}" for {amount:d}')
def step_bought_in(context, name, seat, table, amount):
    ok(buy_in(context.world, name, seat, table, amount))
    assert seat_number_of(table_state(context.world, table), name) == seat


@when('"{name}" tops up {amount:d} at "{table}"')
def step_tops_up(context, name, amount, table):
    top_up(context.world, name, table, amount)


@given('"{name}" has bet {amount:d} and the round has been dealt')
def step_bet_and_dealt(context, name, amount):
    w = context.world
    ok(place_bet(w, seat_number_of(table_state(w), name), amount))
    ok(w.command(TABLE, table_root("Main"), _table.DealRound()))
    assert table_state(w).phase == _table.TableState.Phase.PHASE_PLAYER_TURNS


@given(
    '"{name}" has asked for seat {first:d} of "{table}" for {a:d} and seat {second:d} of "{table2}" for {b:d}, '
    "and both seats and both holds are in place"
)
def step_two_buy_ins_pending(context, name, first, table, a, second, table2, b):
    w = context.world
    w.paused.add(_table.ConfirmSeat.DESCRIPTOR.full_name)
    ok(buy_in(w, name, first, table, a))
    ok(buy_in(w, name, second, table2, b))
    held = {h.seat for h in table_state(w, table).seat_holds.values()}
    assert held == {first, second}, held
    assert logic.held(wallet(w, name)) == a + b
    assert len(w.in_flight) == 2


@when("both buy-ins carry on, seat {seat:d}'s first")
def step_carry_on(context, seat):
    w = context.world
    holds = table_state(w).seat_holds

    def order(sent):
        buy_in_id = unpack(sent.command, _table.ConfirmSeat).buy_in_id.hex()
        return 0 if holds[buy_in_id].seat == seat else 1

    w.release(order)


# --- outcomes -------------------------------------------------------------------------


@then('round {round:d} was settled with "{a}" winning {x:d} and "{b}" winning {y:d}')
def step_round_nets(context, round, a, x, b, y):
    (settled,) = context.world.events(TABLE, table_root("Main"), _table.RoundSettled)
    nets = {o.player_root: o.net for o in settled.outcomes}
    assert settled.round == round
    assert nets == {player_root(a): x, player_root(b): y}, nets


@then('"{a}" has a bankroll of {x:d} and "{b}" has a bankroll of {y:d}')
def step_two_bankrolls(context, a, x, b, y):
    actual = (wallet(context.world, a).bankroll, wallet(context.world, b).bankroll)
    assert actual == (x, y), actual


@then('"{name}" has a bankroll of {amount:d}')
def step_one_bankroll(context, name, amount):
    assert wallet(context.world, name).bankroll == amount


@then('table "{table}" has a house result of {house:d} and no one seated')
def step_house_and_empty(context, table, house):
    state = table_state(context.world, table)
    assert state.house_result == house and not state.seated, state


@then('no chips were added at table "{table}"')
def step_no_chips(context, table):
    assert not context.world.events(TABLE, table_root(table), _table.ChipsAdded)


@then("the buy-in fails because {reason}")
def step_buy_in_fails(context, reason):
    w = context.world
    state = w.buy_in.rebuild(w.process_state(w.labels["last buy-in conversation"]))
    assert state.phase == _b.BuyInState.Phase.PHASE_FAILED, state
    assert state.failure_reason == reason_code(reason)


def _player_events(w, message_class) -> list:
    out = []
    for domain, root in list(w.streams):
        if domain == PLAYER:
            out.extend(w.events(PLAYER, root, message_class))
    return out


@then(
    'every transfer between a wallet and table "{table}" was recorded once on each side'
)
def step_paired(context, table):
    """Invariant L3."""
    w = context.world
    root = table_root(table)
    pairs = [
        (
            [
                (e.buy_in_id, e.stack)
                for e in w.events(TABLE, root, _table.PlayerSeated)
            ],
            [
                (e.hold_id, e.amount)
                for e in _player_events(w, _p.FundsCaptured)
                if e.table_root == root
            ],
        ),
        (
            [(e.hold_id, e.amount) for e in w.events(TABLE, root, _table.ChipsAdded)],
            [
                (e.hold_id, e.amount)
                for e in _player_events(w, _p.TopUpSettled)
                if e.table_root == root
            ],
        ),
        (
            [
                (e.cashout_id, e.amount)
                for e in w.events(TABLE, root, _table.PlayerCashedOut)
            ],
            [
                (e.cashout_id, e.amount)
                for e in _player_events(w, _p.CashOutCredited)
                if e.table_root == root
            ],
        ),
    ]
    for table_side, wallet_side in pairs:
        assert Counter(table_side) == Counter(wallet_side), (table_side, wallet_side)
        assert all(n == 1 for n in Counter(table_side).values()), table_side


@then("the ledger's totals match a recount of every wallet and table")
def step_recount(context):
    w = context.world
    wallets = [w.state(d, r) for (d, r) in list(w.streams) if d == PLAYER]
    tables = [w.state(d, r) for (d, r) in list(w.streams) if d == TABLE]
    recount = {
        "deposits": sum(s.total_deposited for s in wallets),
        "withdrawals": sum(s.total_withdrawn for s in wallets),
        "bankrolls": sum(s.bankroll for s in wallets),
        "stacks": sum(seat.stack for s in tables for seat in s.seated.values()),
        "wagers": sum(seat.wager for s in tables for seat in s.seated.values()),
        "house_result": sum(s.house_result for s in tables),
    }
    w.ledger.refresh_totals()
    totals = w.ledger.projection.totals
    ledger = {key: getattr(totals, key) for key in recount}
    assert ledger == recount, (ledger, recount)
