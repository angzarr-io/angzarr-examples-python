"""Steps for features/example/blackjack-acceptance/cluster.feature.

Assertions read the cluster: stored history (EventQuery), the ledger
(LedgerQueryService) or the event bus. Waits are bounded by the scenario's
"within N seconds".
"""

from __future__ import annotations

import re
import time

import grpc
from behave import given, then, when
from google.protobuf.timestamp_pb2 import Timestamp

from acceptance_steps._client import PLAYER, SYNC, TABLE
from acceptance_steps._play import (
    ask_for_seat,
    bet,
    buy_in,
    cascade,
    deal,
    leave,
    merge,
    must,
    open_table,
    play_round,
    refused_with,
    register,
    seat_of,
    seated_player,
    send,
    stand_all,
    stored,
    table_state,
    top_up,
    wallet,
)
from acceptance_steps._world import eventually
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.cards import format_card, parse_card
from angzarr_blackjack.player.agg import logic

Phase = _table.TableState.Phase
Outcome = _table.SeatOutcome.Outcome
PERSIST = _t.SnapshotRetention.RETENTION_PERSIST
SNAPSHOT_EVERY = 20

_STEP_REASONS = {
    "a wager is in play": "WAGER_IN_PLAY",
    "the funds are not available": "INSUFFICIENT_AVAILABLE_FUNDS",
}


@given("the blackjack cluster is reachable")
def step_reachable(context):
    assert context.client.reachable(
        timeout=10.0
    ), "the blackjack cluster is not reachable on PLAYER_URL / TABLE_URL / LEDGER_URL"


# --- wallets ------------------------------------------------------------------------


@given('players "{a}" and "{b}" are registered and have each deposited {amount:d}')
def step_players_registered(context, a, b, amount):
    register(context.world, a, amount)
    register(context.world, b, amount)


@given('player "{name}" is registered and has deposited {amount:d}')
def step_player_deposited(context, name, amount):
    register(context.world, name, amount)


@given('player "{name}" is registered')
def step_player_registered(context, name):
    register(context.world, name)


@given('player "{name}" has not registered')
def step_not_registered(context, name):
    assert not wallet(context.world, name).registered


@then('"{name}" has a bankroll of {bankroll:d} with {available:d} available')
def step_bankroll_available(context, name, bankroll, available):
    state = wallet(context.world, name)
    assert (state.bankroll, logic.available(state)) == (bankroll, available), state


@then('"{name}" has a bankroll of {bankroll:d} and is registered as "{display}"')
def step_bankroll_and_name(context, name, bankroll, display):
    state = wallet(context.world, name)
    assert (state.bankroll, state.display_name) == (bankroll, display)


@then('"{name}" still has a bankroll of {bankroll:d}')
@then('"{name}" has a bankroll of {bankroll:d}')
def step_bankroll(context, name, bankroll):
    assert wallet(context.world, name).bankroll == bankroll


# --- tables and seats ------------------------------------------------------------------


@given(
    'table "{table}" is open with {seats:d} seats, {decks:d} deck, bets from {min_bet:d} to {max_bet:d}, buy-ins from {min_buy_in:d} to {max_buy_in:d} and shoe seed {seed:d}'
)
def step_table_full(
    context, table, seats, decks, min_bet, max_bet, min_buy_in, max_buy_in, seed
):
    open_table(
        context.world,
        table,
        seed,
        seats=seats,
        decks=decks,
        min_bet=min_bet,
        max_bet=max_bet,
        min_buy_in=min_buy_in,
        max_buy_in=max_buy_in,
    )


@given('table "{table}" is open with shoe seed {seed:d}')
def step_table_seed(context, table, seed):
    open_table(context.world, table, seed)


@given('table "{table}" is open')
def step_table_open(context, table):
    open_table(context.world, table)


@given(
    'player "{name}" is seated at table "{table}" with a stack of {stack:d} and {left:d} left in her wallet'
)
@given(
    '"{name}" is seated at seat 0 of table "{table}" with a stack of {stack:d} and {left:d} left in her wallet'
)
def step_seated_with_wallet(context, name, table, stack, left):
    seated_player(context.world, name, 0, stack, left, table)


@given(
    '"{name}" is seated at seat 0 of table "{table}" opened with shoe seed {seed:d}, with a stack of {stack:d} and {left:d} left in her wallet'
)
def step_seated_seed(context, name, table, seed, stack, left):
    seated_player(context.world, name, 0, stack, left, table, seed)


@given('"{name}" sits at seat {seat:d} of table "{table}" with a stack of {stack:d}')
def step_sits(context, name, seat, table, stack):
    seated_player(context.world, name, seat, stack, 0, table)


@given(
    '"{a}" sits at seat {seat_a:d} and "{b}" at seat {seat_b:d} of table "{table}", each with a stack of {stack:d}'
)
def step_two_sit(context, a, seat_a, b, seat_b, table, stack):
    seated_player(context.world, a, seat_a, stack, 0, table)
    seated_player(context.world, b, seat_b, stack, 0, table)


@given(
    '"{name}" sits at seat {seat:d} of table "{table}" opened with shoe seed {seed:d}'
)
def step_sits_seed(context, name, seat, table, seed):
    seated_player(context.world, name, seat, 500, 0, table, seed)


@given('"{name}" has bought in at table "{table}" for {amount:d}')
def step_bought_in(context, name, table, amount):
    open_table(context.world, table)
    buy_in(context.world, name, 0, amount, table)


@then('"{name}" has a stack of {stack:d} at table "{table}"')
def step_stack(context, name, stack, table):
    state = table_state(context.world, table)
    seat = seat_of(state, context.world.player(name))
    assert seat is not None and state.seated[seat].stack == stack, state.seated


@given('"{name}" has bet {amount:d} and the round has been dealt')
def step_bet_dealt(context, name, amount):
    w = context.world
    assert bet(w, name, amount) is not None, w.error
    deal(w)
    assert table_state(w).phase == Phase.PHASE_PLAYER_TURNS


# --- buy-ins -----------------------------------------------------------------------------


@when(
    '"{name}" asks for seat {seat:d} of "{table}" for {amount:d} and waits for every follow-up to finish'
)
def step_seat_cascade(context, name, seat, table, amount):
    ask_for_seat(context.world, name, seat, amount, table, sync=SYNC.SYNC_MODE_CASCADE)


@when(
    '"{name}" asks for seat {seat:d} of "{table}" for {amount:d} while the buy-in process restarts mid-flow'
)
def step_seat_restart(context, name, seat, table, amount):
    ask_for_seat(context.world, name, seat, amount, table)
    context.client.restart("pmg-buy-in")


@when('"{name}" asks for seat {seat:d} of "{table}" for {amount:d}')
def step_ask_seat(context, name, seat, table, amount):
    ask_for_seat(context.world, name, seat, amount, table)


@when(
    '"{name}" asks for seat {first:d} and seat {second:d} of "{table}" for {amount:d} each, without waiting for either'
)
def step_two_seats(context, name, first, second, table, amount):
    ask_for_seat(context.world, name, first, amount, table)
    ask_for_seat(context.world, name, second, amount, table)


@then(
    'the answer reports "{name}" seated at seat {seat:d} of "{table}" with a stack of {stack:d}'
)
def step_answer_seated(context, name, seat, table, stack):
    w = context.world
    assert w.error is None, w.error
    held = [
        unpack(p.event, _table.SeatHeld)
        for p in w.response.events.pages
        if type_name(p.event.type_url).endswith("SeatHeld")
    ]
    assert held and held[0].seat == seat
    state = table_state(w, table)
    assert (
        state.seated[seat].player_root == w.player(name)
        and state.seated[seat].stack == stack
    )


@then(
    'at that moment the wallet of "{name}" has already spent {amount:d} on the buy-in'
)
def step_already_spent(context, name, amount):
    w = context.world
    hold = wallet(w, name).holds[w.request(w.notes["last buy-in"]).hex()]
    assert hold.status == _p.Hold.Status.STATUS_CAPTURED and hold.amount == amount


@then("within {n:d} seconds the buy-in's history across both services reads, in order:")
def step_buy_in_history(context, n):
    w = context.world
    corr = w.conversation(w.notes["last buy-in"])
    describe = {
        "SeatHeld": lambda e: ("table", f"seat {e.seat} held"),
        "FundsHeld": lambda e: ("player", f"{e.amount} held for the buy-in"),
        "PlayerSeated": lambda e: (
            "table",
            f'"{_name_of(w, e.player_root)}" seated with {e.stack}',
        ),
        "FundsCaptured": lambda e: ("player", f"{e.amount} spent on the buy-in"),
    }
    expected = [(row["service"], row["what happened"]) for row in context.table]

    def history_reads():
        pages = []
        for domain in (TABLE, PLAYER):
            for page in w.client.conversation(domain, corr).pages:
                name = type_name(page.event.type_url).rsplit(".", 1)[-1]
                if name in describe:
                    event = unpack(
                        page.event, getattr(_table if domain == TABLE else _p, name)
                    )
                    pages.append(
                        (page.created_at.ToNanoseconds(), describe[name](event))
                    )
        actual = [d for _, d in sorted(pages, key=lambda item: item[0])]
        assert actual == expected, actual

    eventually(history_reads, n)


def _name_of(w, player_root: bytes) -> str:
    for name in ("Alice", "Bob", "Carol"):
        if w.player(name) == player_root:
            return name
    return player_root.hex()


@then('within {n:d} seconds seat {seat:d} at table "{table}" is free again')
def step_seat_free_again(context, n, seat, table):
    def free():
        state = table_state(context.world, table)
        assert seat not in state.seated and seat not in {
            h.seat for h in state.seat_holds.values()
        }
        assert stored(
            context.world, TABLE, context.world.table(table), _table.SeatReleased
        )

    eventually(free, n)


def _released_reasons(w, table="Main") -> list[str]:
    return [e.reason for e in stored(w, TABLE, w.table(table), _table.SeatReleased)]


@then("the buy-in is reported failed because {reason}")
def step_buy_in_failed(context, reason):
    assert _released_reasons(context.world) == [_STEP_REASONS[reason]]


@then('one buy-in is reported failed because "{name}" is already seated')
def step_one_failed(context, name):
    assert _released_reasons(context.world) == ["PLAYER_ALREADY_SEATED"]


@then(
    'within {n:d} seconds "{name}" is seated in exactly one of seats {a:d} and {b:d} with a stack of {stack:d}'
)
def step_seated_once(context, n, name, a, b, stack):
    w = context.world

    def once():
        state = table_state(w)
        mine = [
            s
            for s in (a, b)
            if s in state.seated and state.seated[s].player_root == w.player(name)
        ]
        assert len(mine) == 1 and state.seated[mine[0]].stack == stack, state.seated
        w.notes["other seat"] = b if mine[0] == a else a
        assert not state.seat_holds, state.seat_holds

    eventually(once, n)


@then("the other seat is free")
def step_other_free(context):
    state = table_state(context.world)
    assert context.world.notes["other seat"] not in state.seated


@then(
    'within {n:d} seconds "{name}" is seated at seat {seat:d} of "{table}" with a stack of {stack:d}'
)
def step_seated_within(context, n, name, seat, table, stack):
    def seated():
        state = table_state(context.world, table)
        assert state.seated[seat].player_root == context.world.player(name)
        assert state.seated[seat].stack == stack

    eventually(seated, n)


@then("the wallet holds and spends the money for that buy-in exactly once")
def step_held_spent_once(context):
    w = context.world
    hold_id = w.request(w.notes["last buy-in"])
    held = [
        e
        for e in stored(w, PLAYER, w.player("Alice"), _p.FundsHeld)
        if e.hold_id == hold_id
    ]
    spent = [
        e
        for e in stored(w, PLAYER, w.player("Alice"), _p.FundsCaptured)
        if e.hold_id == hold_id
    ]
    assert (len(held), len(spent)) == (1, 1)


@then(
    "within {n:d} seconds the stored history of that conversation holds exactly one seat confirmation and one spent hold for {amount:d} under the same buy-in"
)
def step_paired(context, n, amount):
    w = context.world
    corr = w.conversation(w.notes["last buy-in"])

    def paired():
        seated = [
            unpack(p.event, _table.PlayerSeated)
            for p in w.client.conversation(TABLE, corr).pages
            if type_name(p.event.type_url).endswith("PlayerSeated")
        ]
        spent = [
            unpack(p.event, _p.FundsCaptured)
            for p in w.client.conversation(PLAYER, corr).pages
            if type_name(p.event.type_url).endswith("FundsCaptured")
        ]
        assert len(seated) == len(spent) == 1, (seated, spent)
        assert seated[0].buy_in_id == spent[0].hold_id
        assert seated[0].stack == spent[0].amount == amount

    eventually(paired, n)


# --- leaving, top-ups ---------------------------------------------------------------------


@when('"{name}" leaves "{table}" and waits for every follow-up to finish')
def step_leave_cascade(context, name, table):
    leave(context.world, name, table, sync=SYNC.SYNC_MODE_CASCADE)
    assert context.world.error is None, context.world.error


@when('"{name}" leaves "{table}" while the settlement translator restarts mid-delivery')
def step_leave_restart(context, name, table):
    leave(context.world, name, table)
    context.client.restart("saga-table-player")


@then('at the moment the answer arrives "{name}" has a bankroll of {bankroll:d}')
def step_answer_bankroll(context, name, bankroll):
    assert wallet(context.world, name).bankroll == bankroll


@when('"{name}" asks to top up {amount:d} at "{table}"')
def step_top_up(context, name, amount, table):
    top_up(context.world, name, amount, table)
    assert context.world.error is None, context.world.error


@then("within {n:d} seconds the top-up is reported refused because {reason}")
def step_top_up_refused(context, n, reason):
    w = context.world
    hold_id = w.request(w.notes["last top-up"])

    def refused():
        refusals = [
            e
            for e in stored(w, PLAYER, w.player("Alice"), _p.TopUpRefused)
            if e.hold_id == hold_id
        ]
        assert [e.reason for e in refusals] == [_STEP_REASONS[reason]]

    eventually(refused, n)


@then('within {n:d} seconds "{name}" has a stack of {stack:d} at table "{table}"')
def step_stack_within(context, n, name, stack, table):
    eventually(lambda: step_stack(context, name, stack, table), n)


@then("the top-up was settled in the wallet exactly once")
def step_settled_once(context):
    w = context.world
    hold_id = w.request(w.notes["last top-up"])
    assert (
        len(
            [
                e
                for e in stored(w, PLAYER, w.player("Alice"), _p.TopUpSettled)
                if e.hold_id == hold_id
            ]
        )
        == 1
    )


@then(
    'within {n:d} seconds "{a}" has a bankroll of {x:d} and "{b}" has a bankroll of {y:d}'
)
def step_two_bankrolls(context, n, a, x, b, y):
    eventually(
        lambda: (wallet(context.world, a).bankroll, wallet(context.world, b).bankroll)
        == (x, y),
        n,
    )


@then('within {n:d} seconds "{name}" has a bankroll of {bankroll:d}')
def step_bankroll_within(context, n, name, bankroll):
    eventually(lambda: step_bankroll(context, name, bankroll), n)


@then("the cash-out was credited to the wallet exactly once")
def step_credited_once(context):
    w = context.world
    credits = stored(w, PLAYER, w.player("Alice"), _p.CashOutCredited)
    cashed = stored(w, TABLE, w.table("Main"), _table.PlayerCashedOut)
    assert (
        len(credits) == len(cashed) == 1
        and credits[0].cashout_id == cashed[0].cashout_id
    )


# --- deposits and the ledger ---------------------------------------------------------------


@when('"{name}" deposits {amount:d} and waits for the read models to catch up')
def step_deposit_simple(context, name, amount):
    must(
        context.world,
        PLAYER,
        context.world.player(name),
        _p.DepositFunds(amount=amount),
        sync_mode=SYNC.SYNC_MODE_SIMPLE,
    )


@when('"{name}" deposits {amount:d} without waiting for anything downstream')
def step_deposit_async(context, name, amount):
    must(
        context.world,
        PLAYER,
        context.world.player(name),
        _p.DepositFunds(amount=amount),
        sync_mode=SYNC.SYNC_MODE_ASYNC,
    )


@when('"{name}" deposits {amount:d}')
def step_deposit(context, name, amount):
    must(
        context.world,
        PLAYER,
        context.world.player(name),
        _p.DepositFunds(amount=amount),
    )


@then(
    'at the moment the answer arrives the ledger shows "{name}" with a bankroll of {bankroll:d}'
)
def step_ledger_now(context, name, bankroll):
    view = context.client.balance(context.world.player(name))
    assert view.found and view.player.bankroll == bankroll, view


@then('within {n:d} seconds the ledger shows "{name}" with a bankroll of {bankroll:d}')
def step_ledger_within(context, n, name, bankroll):
    eventually(lambda: step_ledger_now(context, name, bankroll), n)


@then('the ledger still shows "{name}" with a bankroll of {bankroll:d}')
def step_ledger_still(context, name, bankroll):
    step_ledger_now(context, name, bankroll)


@then('after {n:d} seconds the ledger still reports that it has not seen "{name}"')
def step_ledger_unseen(context, n, name):
    time.sleep(n)
    assert not context.client.balance(context.world.player(name)).found


@then("within {n:d} seconds the ledger reports nothing in flight")
def step_nothing_in_flight(context, n):
    def settled():
        totals = context.client.ledger().totals
        assert (totals.in_flight, totals.in_flight_transfers) == (0, 0), totals

    eventually(settled, n)


@then("the ledger reports the money as balanced")
def step_ledger_balanced(context):
    assert context.client.ledger().balanced


@then(
    "a recount from the stored histories of every wallet and table gives the same totals as the ledger"
)
def step_recount(context):
    """L4 recomputed from EventQuery, independently of the projection."""
    client = context.client
    wallets = [client.state(PLAYER, root) for root in client.roots(PLAYER)]
    tables = [client.state(TABLE, root) for root in client.roots(TABLE)]
    recount = {
        "deposits": sum(s.total_deposited for s in wallets),
        "withdrawals": sum(s.total_withdrawn for s in wallets),
        "bankrolls": sum(s.bankroll for s in wallets),
        "stacks": sum(seat.stack for s in tables for seat in s.seated.values()),
        "wagers": sum(seat.wager for s in tables for seat in s.seated.values()),
        "house_result": sum(s.house_result for s in tables),
    }
    totals = client.ledger().totals
    assert {k: getattr(totals, k) for k in recount} == recount, (totals, recount)
    assert (
        recount["bankrolls"]
        + recount["stacks"]
        + recount["wagers"]
        + recount["house_result"]
        == recount["deposits"] - recount["withdrawals"]
    )


# --- a scripted session ---------------------------------------------------------------------

_SESSION = [
    (
        r'^"(?P<n>[^"]+)" buys in at seat (?P<s>\d+) of "(?P<t>[^"]+)" for (?P<a>\d+)$',
        lambda w, m: buy_in(w, m["n"], int(m["s"]), int(m["a"]), m["t"]),
    ),
    (
        r'^"(?P<n>[^"]+)" tops up (?P<a>\d+) at "(?P<t>[^"]+)"$',
        lambda w, m: _top_up_and_wait(w, m["n"], int(m["a"]), m["t"]),
    ),
    (
        r'^"(?P<a>[^"]+)" bets (?P<x>\d+) and "(?P<b>[^"]+)" bets (?P<y>\d+)$',
        lambda w, m: [bet(w, m["a"], int(m["x"])), bet(w, m["b"], int(m["y"]))],
    ),
    (
        r"^the round is dealt and every player stands on their turn$",
        lambda w, m: [deal(w), stand_all(w)],
    ),
    (
        r'^"(?P<a>[^"]+)" and "(?P<b>[^"]+)" leave "(?P<t>[^"]+)"$',
        lambda w, m: [leave(w, m["a"], m["t"]), leave(w, m["b"], m["t"])],
    ),
    (r'^"(?P<n>[^"]+)" leaves "(?P<t>[^"]+)"$', lambda w, m: leave(w, m["n"], m["t"])),
    (
        r'^"(?P<n>[^"]+)" withdraws (?P<a>\d+)$',
        lambda w, m: must(
            w, PLAYER, w.player(m["n"]), _p.WithdrawFunds(amount=int(m["a"]))
        ),
    ),
]


def _top_up_and_wait(w, name, amount, table):
    stack = (
        table_state(w, table)
        .seated[seat_of(table_state(w, table), w.player(name))]
        .stack
    )
    top_up(w, name, amount, table)
    eventually(
        lambda: table_state(w, table)
        .seated[seat_of(table_state(w, table), w.player(name))]
        .stack
        == stack + amount,
        15,
    )


@when("the session is played:")
def step_session(context):
    w = context.world
    for row in context.table:
        for pattern, run in _SESSION:
            match = re.match(pattern, row["step"])
            if match:
                run(w, match)
                assert w.error is None, f"{row['step']}: {w.error.details()}"
                break
        else:
            raise AssertionError(f"unknown session step {row['step']!r}")


@then(
    'within {n:d} seconds round {round:d} at "{table}" is reported settled with "{a}" winning {x:d} and "{b}" winning {y:d}'
)
def step_round_reported(context, n, round, table, a, x, b, y):
    w = context.world

    def settled():
        (event,) = [
            e
            for e in stored(w, TABLE, w.table(table), _table.RoundSettled)
            if e.round == round
        ]
        nets = {o.player_root: o.net for o in event.outcomes}
        assert nets == {w.player(a): x, w.player(b): y}, nets

    eventually(settled, n)


@then(
    'within {n:d} seconds "{name}" has a bankroll of {bankroll:d} and a stack of {stack:d} at table "{table}"'
)
def step_bankroll_and_stack(context, n, name, bankroll, stack, table):
    def both():
        step_bankroll(context, name, bankroll)
        step_stack(context, name, stack, table)

    eventually(both, n)


# --- two callers at once ------------------------------------------------------------------


@given('a deposit of {amount:d} for "{name}" was prepared from her wallet as it is now')
def step_prepare_deposit(context, amount, name):
    w = context.world
    w.notes["prepared"] = (
        _p.DepositFunds(amount=amount),
        w.client.book(PLAYER, w.player(name)).next_sequence,
        name,
    )


@given(
    'a withdrawal of {amount:d} for "{name}" was prepared from her wallet as it is now'
)
def step_prepare_withdrawal(context, amount, name):
    w = context.world
    w.notes["prepared"] = (
        _p.WithdrawFunds(amount=amount),
        w.client.book(PLAYER, w.player(name)).next_sequence,
        name,
    )


@given('"{name}" has since changed her display name to "{display}"')
def step_renamed(context, name, display):
    must(
        context.world,
        PLAYER,
        context.world.player(name),
        _p.UpdateProfile(display_name=display),
    )


@given('"{name}" has since {verb} {amount:d}')
def step_since(context, name, verb, amount):
    message = (
        _p.DepositFunds(amount=amount)
        if verb == "deposited"
        else _p.WithdrawFunds(amount=amount)
    )
    must(context.world, PLAYER, context.world.player(name), message)


@when("the prepared deposit is sent, allowing it to merge with unrelated changes")
def step_send_commutative(context):
    message, expected, name = context.world.notes["prepared"]
    send(
        context.world,
        PLAYER,
        context.world.player(name),
        message,
        expected=expected,
        merge=merge("MERGE_COMMUTATIVE"),
    )


@when("the prepared withdrawal is sent for manual review on conflict")
def step_send_manual(context):
    message, expected, name = context.world.notes["prepared"]
    send(
        context.world,
        PLAYER,
        context.world.player(name),
        message,
        expected=expected,
        merge=merge("MERGE_MANUAL"),
    )


@then("the deposit is accepted")
def step_accepted(context):
    assert context.world.error is None, context.world.error


@then("the {what} is refused as out of date, and may be retried")
def step_refused_retryable(context, what):
    """A stale request refused as retryable; "the other" is the one of two
    prepared requests that did not land."""
    w = context.world
    if what == "other":
        (error,) = [e for e in w.notes["answers"] if e is not None]
    else:
        error = w.error
    assert (
        error is not None and error.code() == grpc.StatusCode.FAILED_PRECONDITION
    ), error


@then(
    "the withdrawal is refused as needing review, and must not be retried automatically"
)
def step_refused_manual(context):
    error = context.world.error
    assert error is not None and error.code() == grpc.StatusCode.ABORTED, error


def _dead_letter(context, message_class, within: float = 10.0):
    stream = context.world.events()

    def found(_events):
        for letter in stream.dead_letters:
            command = letter.rejected_command
            if (
                command.pages
                and type_name(command.pages[0].command.type_url)
                == message_class.DESCRIPTOR.full_name
            ):
                return letter
        return None

    return stream.wait(found, within)


@then("the withdrawal is waiting in the dead-letter queue for review")
def step_withdrawal_dlq(context):
    letter = _dead_letter(context, _p.WithdrawFunds)
    assert letter.WhichOneof("rejection_details") == "sequence_mismatch"


@given(
    "two bets of {amount:d} at seat {seat:d} were prepared from the table as it is now"
)
def step_prepare_two_bets(context, amount, seat):
    w = context.world
    expected = w.client.book(TABLE, w.table("Main")).next_sequence
    w.notes["prepared"] = [(_table.PlaceBet(seat=seat, amount=amount), expected)] * 2


@given(
    "a bet of {x:d} at seat {s1:d} and a bet of {y:d} at seat {s2:d} were prepared from the table as it is now"
)
def step_prepare_bets(context, x, s1, y, s2):
    w = context.world
    expected = w.client.book(TABLE, w.table("Main")).next_sequence
    w.notes["prepared"] = [
        (_table.PlaceBet(seat=s1, amount=x), expected),
        (_table.PlaceBet(seat=s2, amount=y), expected),
    ]


@given("two hits for seat {seat:d} were prepared from the table as it is now")
def step_prepare_hits(context, seat):
    w = context.world
    expected = w.client.book(TABLE, w.table("Main")).next_sequence
    w.notes["prepared"] = [(_table.Hit(seat=seat), expected)] * 2


def _send_prepared(context, strategy: str) -> None:
    w = context.world
    w.notes["answers"] = []
    for message, expected in w.notes["prepared"]:
        send(
            w, TABLE, w.table("Main"), message, expected=expected, merge=merge(strategy)
        )
        w.notes["answers"].append(w.error)


@when("both bets are sent, letting the table judge them against its full history")
def step_send_bets(context):
    _send_prepared(context, "MERGE_AGGREGATE_HANDLES")


@when("both hits are sent, refusing either if the table has changed")
def step_send_hits(context):
    _send_prepared(context, "MERGE_STRICT")


@then("exactly one bet of {amount:d} is placed at seat {seat:d}")
def step_one_bet(context, amount, seat):
    w = context.world
    bets = [
        e for e in stored(w, TABLE, w.table("Main"), _table.BetPlaced) if e.seat == seat
    ]
    assert [b.amount for b in bets] == [amount]
    assert sum(error is None for error in w.notes["answers"]) == 1


@then("the other is refused because seat {seat:d} has already bet this round")
def step_other_already_bet(context, seat):
    (error,) = [e for e in context.world.notes["answers"] if e is not None]
    assert refused_with(error, "ALREADY_BET"), error.details()


@then("seat {s1:d} has a wager of {x:d} and seat {s2:d} has a wager of {y:d}")
def step_two_wagers(context, s1, x, s2, y):
    state = table_state(context.world)
    assert (state.seated[s1].wager, state.seated[s2].wager) == (x, y)
    assert all(error is None for error in context.world.notes["answers"])


@then("exactly one of the hits deals a card to seat {seat:d}, the {card}")
def step_one_hit(context, seat, card):
    w = context.world
    dealt = [
        e for e in stored(w, TABLE, w.table("Main"), _table.CardDealt) if e.seat == seat
    ]
    assert [format_card(e.card) for e in dealt] == [format_card(parse_card(card))]
    assert sum(error is None for error in w.notes["answers"]) == 1


# --- migration ---------------------------------------------------------------------------


@when('"{name}" is imported from the old system without triggering any follow-up')
def step_import(context, name):
    must(
        context.world,
        PLAYER,
        context.world.player(name),
        _p.ImportPlayer(
            display_name=name, email=f"{name.lower()}@example.com", legacy_id="L-1"
        ),
        sync_mode=SYNC.SYNC_MODE_ISOLATED,
    )


@then('"{name}" is registered as "{display}" with a bankroll of {bankroll:d}')
def step_registered_as(context, name, display, bankroll):
    state = wallet(context.world, name)
    assert (state.registered, state.display_name, state.bankroll) == (
        True,
        display,
        bankroll,
    )


# --- one settled round, several follow-ups --------------------------------------------------


@given('the loyalty round at table "{table}" is ready for "{name}"\'s final stand')
def step_loyalty_round(context, table, name):
    w = context.world
    register(w, "Alice", 500)
    register(w, "Bob", 500, enroll=True)
    open_table(w, table, 7)
    buy_in(w, "Alice", 0, 500, table)
    buy_in(w, "Bob", 1, 500, table)
    bet(w, "Alice", 20, table)
    bet(w, "Bob", 30, table)
    deal(w, table)
    must(w, TABLE, w.table(table), _table.Stand(seat=0))
    state = table_state(w, table)
    assert (
        state.phase == Phase.PHASE_PLAYER_TURNS and state.turn == 1
    ), "Bob is not on turn"


_MODES = {
    "stopping at the first failure": "CASCADE_ERROR_FAIL_FAST",
    "carrying on past failures": "CASCADE_ERROR_CONTINUE",
    "undoing them if one fails": "CASCADE_ERROR_COMPENSATE",
    "setting failures aside for review": "CASCADE_ERROR_DEAD_LETTER",
}


@when('"{name}" stands and waits for every follow-up, {mode}')
def step_stand_cascade(context, name, mode):
    w = context.world
    send(
        w,
        TABLE,
        w.table("Main"),
        _table.Stand(seat=1),
        sync_mode=SYNC.SYNC_MODE_CASCADE,
        cascade_error_mode=cascade(_MODES[mode]),
    )


@when('"{name}" stands without waiting for anything downstream')
def step_stand_async(context, name):
    w = context.world
    send(
        w, TABLE, w.table("Main"), _table.Stand(seat=1), sync_mode=SYNC.SYNC_MODE_ASYNC
    )


@then('the answer is a failure because "{name}" is not a loyalty member')
def step_answer_failure(context, name):
    assert refused_with(
        context.world.error, "LOYALTY_NOT_ENROLLED"
    ), context.world.error


@then("the answer is a success")
def step_answer_success(context):
    assert context.world.error is None, context.world.error


@then(
    "the round's own history at table \"{table}\" is kept: the final stand, the dealer's play and the settlement of round {round:d}"
)
def step_round_kept(context, table, round):
    w = context.world
    names = [
        type_name(p.event.type_url).rsplit(".", 1)[-1]
        for p in w.client.book(TABLE, w.table(table)).pages
    ]
    assert names[-3:] == ["HandStood", "DealerPlayed", "RoundSettled"], names[-3:]
    assert stored(w, TABLE, w.table(table), _table.RoundSettled)[-1].round == round


@then(
    'the answer reports exactly one failed follow-up: the loyalty award for "{name}", refused because she is not a loyalty member'
)
def step_one_reaction_error(context, name):
    (error,) = context.world.response.reaction_errors
    assert error.command_type == _p.AwardLoyaltyPoints.DESCRIPTOR.full_name
    assert error.target.root.value == context.world.player(name)
    assert "LOYALTY_NOT_ENROLLED" in error.message


@then("the answer reports no failed follow-ups")
def step_no_reaction_errors(context):
    assert not context.world.response.reaction_errors


def _awards(w, name, round):
    return [
        e
        for e in stored(w, PLAYER, w.player(name), _p.LoyaltyPointsAwarded)
        if e.round == round
    ]


@then('"{name}" was awarded {points:d} loyalty points for round {round:d}')
def step_awarded(context, name, points, round):
    eventually(
        lambda: [a.points for a in _awards(context.world, name, round)] == [points], 10
    )


@then('"{name}" was not awarded loyalty points for round {round:d}')
def step_not_awarded(context, name, round):
    assert not _awards(context.world, name, round)


def _results(w, name, round):
    return [
        e
        for e in stored(w, PLAYER, w.player(name), _p.RoundResultRecorded)
        if e.round == round
    ]


@then('round {round:d} results are recorded for "{a}" and "{b}"')
def step_results_recorded(context, round, a, b):
    assert all(len(_results(context.world, n, round)) == 1 for n in (a, b))


@then('within {n:d} seconds round {round:d} results are recorded for "{a}" and "{b}"')
def step_results_recorded_within(context, n, round, a, b):
    eventually(lambda: step_results_recorded(context, round, a, b), n)


@then(
    'within {n:d} seconds every round {round:d} result recorded for "{a}" or "{b}" has been retracted'
)
def step_results_retracted(context, n, round, a, b):
    w = context.world

    def retracted():
        for name in (a, b):
            recorded = _results(w, name, round)
            undone = [
                e
                for e in stored(w, PLAYER, w.player(name), _p.RoundResultRetracted)
                if e.round == round
            ]
            assert len(undone) == len(recorded), (name, recorded, undone)

    eventually(retracted, n)


@then('neither "{a}" nor "{b}" has a round {round:d} result standing')
def step_none_standing(context, a, b, round):
    for name in (a, b):
        standing = [
            r
            for r in wallet(context.world, name).round_results.values()
            if r.round == round and not r.retracted
        ]
        assert not standing, (name, standing)


@then(
    'the refusal of "{name}"\'s loyalty award has been delivered back to table "{table}"'
)
def step_refusal_delivered(context, name, table):
    """The table compensates no loyalty award, so the delivered refusal adds
    nothing to its history: the round's own events stay its last."""
    w = context.world
    names = [
        type_name(p.event.type_url).rsplit(".", 1)[-1]
        for p in w.client.book(TABLE, w.table(table)).pages
    ]
    assert names[-1] == "RoundSettled", names[-3:]


@then('round {round:d} at "{table}" is still settled')
def step_still_settled(context, round, table):
    settled = stored(
        context.world, TABLE, context.world.table(table), _table.RoundSettled
    )
    assert [s.round for s in settled] == [round]
    assert table_state(context.world, table).phase == Phase.PHASE_IDLE


@then('the loyalty award for "{name}" is waiting in the dead-letter queue for review')
def step_award_dlq(context, name):
    letter = _dead_letter(context, _p.AwardLoyaltyPoints)
    assert letter.rejected_command.cover.root.value == context.world.player(name)


# --- snapshots ------------------------------------------------------------------------------


@given('table "{table}" saves a routine snapshot every {count:d} events')
def step_snapshot_interval(context, table, count):
    """The deployment's snapshot interval for the table (values.yaml)."""
    assert (
        count == SNAPSHOT_EVERY
    ), f"the example deploys the table with a snapshot every {SNAPSHOT_EVERY} events"
    open_table(context.world, table)


@given('"{name}" has played {rounds:d} rounds at table "{table}"')
def step_played_rounds(context, name, rounds, table):
    w = context.world
    seated_player(w, name, 0, 500, 0, table)
    for _ in range(rounds):
        play_round(w, name, 20, table)


@given('"{name}" has played at table "{table}" until the shoe has been replaced twice')
def step_played_until_reshuffles(context, name, table):
    w = context.world
    seated_player(w, name, 0, 1000, 0, table)
    for _ in range(40):
        if table_state(w, table).shoe_number >= 3:
            break
        play_round(w, name, 10, table)
    assert table_state(w, table).shoe_number == 3


@given(
    '"{name}" has played one round at table "{table}", betting {amount:d} and standing on her turn'
)
def step_played_one(context, name, table, amount):
    play_round(context.world, name, amount, table)


@when('table "{table}"\'s stored history is read')
def step_history_read(context, table):
    context.world.notes["book"] = context.client.book(TABLE, context.world.table(table))


@then("it starts from a snapshot taken after the {nth:d}th event or later")
def step_starts_from_snapshot(context, nth):
    book = context.world.notes["book"]
    assert (
        book.HasField("snapshot") and book.snapshot.sequence >= nth - 1
    ), book.snapshot


def _replayed(w, table):
    full = _t.EventBook()
    for book in w.client.books(TABLE, w.table(table)):
        full.pages.extend(book.pages)
    return w.client.fold(TABLE, full)


@then(
    'the table rebuilt from that snapshot shows the same stack for "{name}" as the table replayed from the start'
)
def step_snapshot_equals_replay(context, name):
    w = context.world
    from_snapshot = w.client.fold(TABLE, w.notes["book"])
    replayed = _replayed(w, "Main")
    seat = seat_of(replayed, w.player(name))
    assert from_snapshot.seated[seat].stack == replayed.seated[seat].stack


@when('table "{table}"\'s stored snapshots are listed')
def step_snapshots_listed(context, table):
    w = context.world
    w.notes["snapshots"] = [
        b.snapshot
        for b in w.client.books(TABLE, w.table(table))
        if b.HasField("snapshot")
    ]


@then("there is a lasting snapshot for each of shoes {a:d}, {b:d} and {c:d}")
def step_lasting_per_shoe(context, a, b, c):
    shoes = set()
    for snap in context.world.notes["snapshots"]:
        if snap.retention == PERSIST:
            state = _table.TableState()
            state.ParseFromString(snap.state.value)
            shoes.add(state.shoe_number)
    assert shoes >= {a, b, c}, shoes


@then("exactly one routine snapshot remains, the newest")
def step_one_routine(context):
    snaps = context.world.notes["snapshots"]
    routine = [s for s in snaps if s.retention != PERSIST]
    assert len(routine) == 1 and routine[0].sequence == max(s.sequence for s in snaps)


# --- what-ifs, speculation, upcasting, looking back -----------------------------------------


@given('"{name}" bet {amount:d}, the round was dealt and she stood and lost')
def step_bet_stood_lost(context, name, amount):
    w = context.world
    play_round(w, name, amount)
    (settled,) = stored(w, TABLE, w.table("Main"), _table.RoundSettled)
    assert settled.outcomes[0].outcome == Outcome.OUTCOME_LOSE
    w.notes["main pages"] = len(w.client.book(TABLE, w.table("Main")).pages)


@when(
    'a what-if of table "{table}" branches just before her stand and she hits and then stands'
)
def step_what_if(context, table):
    w = context.world
    pages = w.client.book(TABLE, w.table(table)).pages
    stand = next(
        p.header.sequence
        for p in pages
        if type_name(p.event.type_url).endswith("HandStood")
    )
    edition = _t.Edition(name=f"what-if-{w.nonce}")
    edition.divergences.add(domain=TABLE, sequence=stand)
    w.notes["edition"] = edition
    must(w, TABLE, w.table(table), _table.Hit(seat=0), edition=edition)
    must(w, TABLE, w.table(table), _table.Stand(seat=0), edition=edition)


@then('in the what-if "{name}" wins round {round:d} and has a stack of {stack:d}')
def step_what_if_wins(context, name, round, stack):
    w = context.world
    edition = w.notes["edition"]
    settled = stored(w, TABLE, w.table("Main"), _table.RoundSettled, edition=edition)
    assert [(s.round, s.outcomes[0].outcome) for s in settled][-1] == (
        round,
        Outcome.OUTCOME_WIN,
    )
    step_stack_in(w, name, stack, edition=edition)


def step_stack_in(w, name, stack, **query):
    state = table_state(w, "Main", **query)
    assert state.seated[seat_of(state, w.player(name))].stack == stack


@then(
    'at the real table "{table}" "{name}" lost round {round:d} and has a stack of {stack:d}'
)
def step_real_lost(context, table, name, round, stack):
    w = context.world
    (settled,) = stored(w, TABLE, w.table(table), _table.RoundSettled)
    assert (settled.round, settled.outcomes[0].outcome) == (round, Outcome.OUTCOME_LOSE)
    step_stack_in(w, name, stack)


@then("the real table's history is unchanged")
def step_real_unchanged(context):
    w = context.world
    assert len(w.client.book(TABLE, w.table("Main")).pages) == w.notes["main pages"]


@when('"{name}" tries a withdrawal of {amount:d} speculatively')
def step_speculative(context, name, amount):
    w = context.world
    w.notes["pages"] = len(w.client.book(PLAYER, w.player(name)).pages)
    w.response, w.error = None, None
    try:
        w.response = w.client.speculate(
            PLAYER,
            w.player(name),
            _p.WithdrawFunds(amount=amount),
            correlation=w.correlation,
        )
    except grpc.RpcError as exc:
        w.error = exc


@then(
    "the speculative answer shows a withdrawal of {amount:d} leaving a bankroll of {bankroll:d}"
)
def step_speculative_answer(context, amount, bankroll):
    w = context.world
    assert w.error is None, w.error
    (withdrawn,) = [unpack(p.event, _p.FundsWithdrawn) for p in w.response.events.pages]
    assert withdrawn.amount == amount
    book = w.client.book(PLAYER, w.player("Alice"))
    book.pages.extend(w.response.events.pages)
    assert w.client.fold(PLAYER, book).bankroll == bankroll


@then("the speculative answer is a refusal because only {available:d} is available")
def step_speculative_refusal(context, available):
    assert refused_with(
        context.world.error, "INSUFFICIENT_AVAILABLE_FUNDS"
    ), context.world.error


@then('"{name}"\'s history is unchanged')
def step_history_unchanged(context, name):
    w = context.world
    assert len(w.client.book(PLAYER, w.player(name)).pages) == w.notes["pages"]


@given('"{name}"\'s stored history holds a deposit of {amount:d} in the previous shape')
def step_legacy(context, name, amount):
    w = context.world
    w.client.store_fact(
        PLAYER,
        w.player(name),
        _p.FundsDepositedV1(amount_chips=amount),
        external_id=f"{w.nonce}-legacy",
        correlation=w.correlation,
    )


@then("reading \"{name}\"'s history shows both deposits in today's shape")
def step_both_upcast(context, name):
    w = context.world
    names = [
        type_name(p.event.type_url) for p in w.client.book(PLAYER, w.player(name)).pages
    ]
    assert names.count(_p.FundsDeposited.DESCRIPTOR.full_name) == 2, names
    assert _p.FundsDepositedV1.DESCRIPTOR.full_name not in names


@when('"{name}"\'s wallet is read as of just before the buy-in')
def step_as_of_sequence(context, name):
    w = context.world
    pages = w.client.book(PLAYER, w.player(name)).pages
    held = next(
        p.header.sequence
        for p in pages
        if type_name(p.event.type_url).endswith("FundsHeld")
    )
    w.notes["as of"] = wallet(
        w, name, temporal=_t.TemporalQuery(as_of_sequence=held - 1)
    )


@given("a moment was noted")
def step_note_moment(context):
    time.sleep(0.5)
    moment = Timestamp()
    moment.GetCurrentTime()
    context.world.notes["moment"] = moment
    time.sleep(0.5)


@when('"{name}"\'s wallet is read as of the noted moment')
def step_as_of_time(context, name):
    w = context.world
    w.notes["as of"] = wallet(
        w, name, temporal=_t.TemporalQuery(as_of_time=w.notes["moment"])
    )


@then("that wallet has a bankroll of {bankroll:d} with nothing held")
def step_as_of_nothing_held(context, bankroll):
    state = context.world.notes["as of"]
    assert (state.bankroll, logic.held(state)) == (bankroll, 0)


@then("that wallet has a bankroll of {bankroll:d}")
def step_as_of_bankroll(context, bankroll):
    assert context.world.notes["as of"].bankroll == bankroll


@given('a live view is watching the conversation of "{name}"\'s next request')
def step_live_view(context, name):
    w = context.world
    w.notes["watched"] = w.conversation(f"buy-in:{name}:0")


@then(
    "within {n:d} seconds the live view has shown the seat held, the money held, the seat confirmed and the money spent"
)
def step_live_view_shown(context, n):
    w = context.world
    watched = w.notes["watched"]
    wanted = ["SeatHeld", "FundsHeld", "PlayerSeated", "FundsCaptured"]

    def shown(events):
        names = [
            type_name(d.page.event.type_url).rsplit(".", 1)[-1]
            for d in events
            if d.correlation == watched
        ]
        return [n for n in names if n in wanted] == wanted

    w.events().wait(shown, n)


@then("the live view has shown nothing from any other conversation")
def step_live_view_isolated(context):
    w = context.world
    watched = w.notes["watched"]
    in_view = [d for d in w.events().events if d.correlation == watched]
    elsewhere = [d for d in w.events().events if d.correlation != watched]
    assert (
        in_view and elsewhere
    ), "the scenario's other conversations reached the bus too"
    assert all(d.correlation == watched for d in in_view)
    assert not any(
        type_name(d.page.event.type_url).endswith("PlayerRegistered") for d in in_view
    )


# --- restarts ---------------------------------------------------------------------------------


@when("the wallet service and the table service restart")
def step_restart_aggregates(context):
    w = context.world
    w.notes["shoe"] = list(table_state(w).shoe)
    context.client.restart("agg-player", "agg-table")


@then('the next round at table "{table}" is dealt from where the shoe left off')
def step_next_round_shoe(context, table):
    w = context.world
    shoe = w.notes["shoe"]
    bet(w, "Alice", 20, table)
    assert w.error is None, w.error
    deal(w, table)
    dealt = stored(w, TABLE, w.table(table), _table.RoundDealt)[-1]
    assert list(dealt.hands[0].cards) == [shoe[0], shoe[2]]
    assert (dealt.dealer_up, dealt.dealer_hole) == (shoe[1], shoe[3])
