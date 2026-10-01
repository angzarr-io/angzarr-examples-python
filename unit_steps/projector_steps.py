"""Steps for features/example/blackjack-framework/projector.feature (the ledger).

The ledger is fed the events of each side as its coordinator would deliver
them: recorded in the wallet's or the table's stream (so they carry their
sequence) and projected as a book.
"""

from __future__ import annotations

import angzarr_client.router as _az
from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack.prj_ledger import main as ledger_main
from unit_steps._harness import (
    PLAYER,
    TABLE,
    cover,
    player_root,
    request_id,
    table_root,
)

LOSE = _table.SeatOutcome.Outcome.OUTCOME_LOSE
WIN = _table.SeatOutcome.Outcome.OUTCOME_WIN


def feed(w, domain: str, root: bytes, *events) -> list:
    """Record ``events`` on ``(domain, root)`` and deliver them to the ledger."""
    pages = w.seed(domain, root, *events)
    book = _t.EventBook(cover=cover(domain, root, w.correlation))
    book.pages.extend(pages)
    w.project(book)
    return pages


def feed_player(w, name: str, *events):
    return feed(w, PLAYER, player_root(name), *events)


def feed_table(w, table: str, *events):
    return feed(w, TABLE, table_root(table), *events)


def view(w, name: str) -> _l.PlayerBalanceView:
    return w.ledger.player_view(player_root(name))


def totals(w) -> _l.LedgerTotals:
    w.ledger.refresh_totals()
    return w.ledger.projection.totals


def table_row(w, table: str) -> _l.TableLedgerRow:
    return w.ledger.projection.tables[table_root(table).hex()]


def seats(w, table: str) -> dict[str, int]:
    return w.labels.setdefault(("seats", table), {})


def buy_in(w, name: str, table: str, amount: int, label: str | None = None) -> None:
    """Both sides of a buy-in: hold, seat, spend."""
    label = label or f"buy-in:{name}:{table}"
    seat = seats(w, table).setdefault(name, len(seats(w, table)))
    feed_player(
        w,
        name,
        _p.FundsHeld(
            hold_id=request_id(label), table_root=table_root(table), amount=amount
        ),
    )
    feed_table(
        w,
        table,
        _table.PlayerSeated(
            buy_in_id=request_id(label),
            player_root=player_root(name),
            seat=seat,
            stack=amount,
        ),
    )
    feed_player(
        w,
        name,
        _p.FundsCaptured(
            hold_id=request_id(label), table_root=table_root(table), amount=amount
        ),
    )


def register_and_deposit(w, name: str, amount: int = 0) -> None:
    feed_player(
        w,
        name,
        _p.PlayerRegistered(display_name=name, email=f"{name.lower()}@example.com"),
    )
    if amount:
        feed_player(w, name, _p.FundsDeposited(amount=amount))


# --- wallets ------------------------------------------------------------------------------


@when('the ledger applies "{name}" registering as "{display}"')
def step_applies_registering(context, name, display):
    feed_player(
        context.world,
        name,
        _p.PlayerRegistered(display_name=display, email="x@example.com"),
    )


@given('the ledger has applied "{name}" registering')
def step_has_applied_registering(context, name):
    register_and_deposit(context.world, name)


@given('the ledger has applied "{name}" registering and depositing {amount:d}')
def step_has_applied_deposit(context, name, amount):
    register_and_deposit(context.world, name, amount)


@given(
    'the ledger has applied "{name}" registering and enrolling in the loyalty programme'
)
def step_has_applied_enrolling(context, name):
    register_and_deposit(context.world, name)
    feed_player(context.world, name, _p.LoyaltyEnrolled())


@when('the ledger is asked for "{name}"')
def step_asked_for(context, name):
    context.view = view(context.world, name)


@then('the ledger reports that it has not seen "{name}"')
def step_not_seen(context, name):
    assert not context.view.found


@then(
    'the ledger shows "{name}" as "{display}" with a bankroll of {bankroll:d} and nothing held'
)
def step_shows_as(context, name, display, bankroll):
    v = view(context.world, name)
    assert v.found and v.player.display_name == display
    assert (v.player.bankroll, v.player.held) == (bankroll, 0)


@then('the ledger shows "{name}" with a bankroll of {bankroll:d} and nothing held')
def step_shows_bankroll(context, name, bankroll):
    v = view(context.world, name)
    assert (v.player.bankroll, v.player.held) == (bankroll, 0), v


@then(
    'the ledger shows "{name}" with a bankroll of {bankroll:d}, {held:d} held and {available:d} available'
)
def step_shows_held(context, name, bankroll, held, available):
    v = view(context.world, name)
    assert (v.player.bankroll, v.player.held, v.available) == (
        bankroll,
        held,
        available,
    ), v


_PLAYER_EVENTS = {
    "deposit": lambda r: _p.FundsDeposited(amount=int(r["amount"])),
    "withdrawal": lambda r: _p.FundsWithdrawn(amount=int(r["amount"])),
    "round result recorded": lambda r: _p.RoundResultRecorded(
        table_root=table_root("Main"),
        round=int(r["round"]),
        wager=abs(int(r["amount"])),
        net=int(r["amount"]),
    ),
    "round result retracted": lambda r: _p.RoundResultRetracted(
        table_root=table_root("Main"), round=int(r["round"]), net=int(r["amount"])
    ),
    "loyalty points awarded": lambda r: _p.LoyaltyPointsAwarded(
        table_root=table_root("Main"), round=int(r["round"]), points=int(r["amount"])
    ),
}


@when('the ledger applies, for "{name}":')
def step_applies_for(context, name):
    for row in context.table:
        feed_player(context.world, name, _PLAYER_EVENTS[row["event"]](row))


@when(
    'the ledger applies a deposit of {amount:d} for "{name}" stored in the previous shape'
)
def step_applies_legacy(context, amount, name):
    w = context.world
    root = player_root(name)
    w.seed_page(PLAYER, root, _az.pack(_p.FundsDepositedV1(amount_chips=amount)))
    book = _t.EventBook(cover=cover(PLAYER, root, w.correlation))
    book.pages.append(w.stream(PLAYER, root)[-1])
    w.project(book)


@when('the ledger applies the same deposit of {amount:d} for "{name}" again')
def step_applies_same(context, amount, name):
    w = context.world
    root = player_root(name)
    page = [
        p for p in w.stream(PLAYER, root) if p.event.type_url.endswith("FundsDeposited")
    ][-1]
    book = _t.EventBook(cover=cover(PLAYER, root, w.correlation))
    book.pages.append(page)
    w.project(book)


@given('the ledger has applied a hold of {amount:d} for buy-in "{label}" for "{name}"')
def step_has_applied_hold(context, amount, label, name):
    feed_player(
        context.world,
        name,
        _p.FundsHeld(
            hold_id=request_id(label), table_root=table_root("Main"), amount=amount
        ),
    )


@when('the ledger applies a hold of {amount:d} for buy-in "{label}" for "{name}"')
def step_applies_hold(context, amount, label, name):
    step_has_applied_hold(context, amount, label, name)


@then('the ledger shows "{name}" with {points:d} loyalty points')
def step_shows_points(context, name, points):
    assert view(context.world, name).player.loyalty_points == points


@then(
    'the ledger shows "{name}"\'s recent results as round {r1:d} net {n1:d} and round {r2:d} net {n2:d} retracted'
)
def step_shows_results(context, name, r1, n1, r2, n2):
    results = [
        (r.round, r.net, r.retracted)
        for r in view(context.world, name).player.recent_results
    ]
    assert results == [(r1, n1, False), (r2, n2, True)], results


# --- tables and transfers ---------------------------------------------------------------------


@when(
    'the ledger applies both sides of buy-in "{label}": "{name}" seated at table "{table}" with a stack of {stack:d}, and the hold spent'
)
def step_both_sides(context, label, name, table, stack):
    w = context.world
    feed_table(
        w,
        table,
        _table.PlayerSeated(
            buy_in_id=request_id(label), player_root=player_root(name), stack=stack
        ),
    )
    feed_player(
        w,
        name,
        _p.FundsCaptured(
            hold_id=request_id(label), table_root=table_root(table), amount=stack
        ),
    )


@when(
    'the ledger applies "{name}" being seated at table "{table}" through buy-in "{label}" with a stack of {stack:d}'
)
def step_one_side(context, name, table, label, stack):
    feed_table(
        context.world,
        table,
        _table.PlayerSeated(
            buy_in_id=request_id(label), player_root=player_root(name), stack=stack
        ),
    )


@then('the ledger shows table "{table}" with stacks of {stacks:d}')
def step_table_stacks(context, table, stacks):
    assert table_row(context.world, table).stacks == stacks


@then("the ledger reports nothing in flight")
def step_nothing_in_flight(context):
    t = totals(context.world)
    assert (t.in_flight, t.in_flight_transfers) == (0, 0), t


@then("the ledger reports {amount:d} in flight in {count:d} transfer")
def step_in_flight(context, amount, count):
    t = totals(context.world)
    assert (t.in_flight, t.in_flight_transfers) == (amount, count), t


@then("the ledger does not report the money as balanced")
def step_not_balanced(context):
    totals(context.world)
    assert not context.world.ledger.ledger_view().balanced


@then("the ledger reports the money as balanced")
def step_balanced(context):
    totals(context.world)
    assert (
        context.world.ledger.ledger_view().balanced
    ), context.world.ledger.ledger_view()


def _transfer_sides(w, transfer: str, name: str, table: str, amount: int):
    """The (table side, wallet side) events of a transfer of ``amount``."""
    label = f"{transfer}:{name}"
    if transfer == "buy-in":
        return (
            _table.PlayerSeated(
                buy_in_id=request_id(label), player_root=player_root(name), stack=amount
            ),
            _p.FundsCaptured(
                hold_id=request_id(label), table_root=table_root(table), amount=amount
            ),
        )
    if transfer == "top-up":
        return (
            _table.ChipsAdded(
                hold_id=request_id(label), player_root=player_root(name), amount=amount
            ),
            _p.TopUpSettled(
                hold_id=request_id(label), table_root=table_root(table), amount=amount
            ),
        )
    return (
        _table.PlayerCashedOut(
            cashout_id=request_id(label), player_root=player_root(name), amount=amount
        ),
        _p.CashOutCredited(
            cashout_id=request_id(label), table_root=table_root(table), amount=amount
        ),
    )


@given(
    'the ledger has applied the deposits and holds behind a {transfer} of {amount:d} between "{name}" and table "{table}"'
)
def step_behind_transfer(context, transfer, amount, name, table):
    w = context.world
    register_and_deposit(w, name, 1000)
    feed_table(w, table, _table.TableCreated(name=table))
    label = f"{transfer}:{name}"
    if transfer == "buy-in":
        feed_player(
            w,
            name,
            _p.FundsHeld(
                hold_id=request_id(label), table_root=table_root(table), amount=amount
            ),
        )
    elif transfer == "top-up":
        buy_in(w, name, table, 500)
        feed_player(
            w,
            name,
            _p.TopUpRequested(
                hold_id=request_id(label), table_root=table_root(table), amount=amount
            ),
        )
    else:
        buy_in(w, name, table, amount)
    context.transfer = (transfer, amount, name, table)


@when(
    "the ledger applies the table side and the wallet side of the {transfer} in {order} order"
)
def step_both_sides_in_order(context, transfer, order):
    w = context.world
    _, amount, name, table = context.transfer
    table_side, wallet_side = _transfer_sides(w, transfer, name, table, amount)
    if order == "table-first":
        feed_table(w, table, table_side)
        feed_player(w, name, wallet_side)
    else:
        feed_player(w, name, wallet_side)
        feed_table(w, table, table_side)


@given('the ledger shows table "{table}" with stacks of {stacks:d} after buy-ins')
def step_stacks_after_buy_ins(context, table, stacks):
    w = context.world
    feed_table(w, table, _table.TableCreated(name=table))
    for name in ("Alice", "Bob"):
        register_and_deposit(w, name, stacks)
        buy_in(w, name, table, stacks // 2)
    assert table_row(w, table).stacks == stacks


@given('the ledger has applied bets of {first:d} and {second:d} at table "{table}"')
def step_bets(context, first, second, table):
    feed_table(
        context.world,
        table,
        _table.BetPlaced(
            round=1, seat=0, player_root=player_root("Alice"), amount=first
        ),
        _table.BetPlaced(
            round=1, seat=1, player_root=player_root("Bob"), amount=second
        ),
    )
    context.wagers = [first, second]


@when(
    'the ledger applies round {round:d} at table "{table}" settling with {returned:d} returned and the house winning {house:d}'
)
def step_round(context, round, table, returned, house):
    first, second = context.wagers
    assert first + second - returned == house
    outcomes = [
        _table.SeatOutcome(
            seat=0,
            player_root=player_root("Alice"),
            wager=first,
            outcome=WIN,
            returned=returned,
        ),
        _table.SeatOutcome(
            seat=1,
            player_root=player_root("Bob"),
            wager=second,
            outcome=LOSE,
            returned=0,
        ),
    ]
    feed_table(
        context.world,
        table,
        _table.RoundSettled(round=round, outcomes=outcomes, house_delta=house),
    )


@then(
    'the ledger shows table "{table}" with stacks of {stacks:d}, no wagers and a house result of {house:d}'
)
def step_table_row(context, table, stacks, house):
    row = table_row(context.world, table)
    assert (row.stacks, row.wagers, row.house_result) == (stacks, 0, house), row


# --- whole-system balance and replay ----------------------------------------------------------


def house_wins(w, table: str, amount: int) -> None:
    """A round in which every seated player loses; seat 0 bets 20 and the
    next seat the rest of ``amount``."""
    players = sorted(seats(w, table), key=lambda n: seats(w, table)[n])
    wagers = [20, amount - 20] if len(players) > 1 else [amount]
    bets = [
        _table.BetPlaced(
            round=1, seat=seats(w, table)[n], player_root=player_root(n), amount=a
        )
        for n, a in zip(players, wagers)
    ]
    outcomes = [
        _table.SeatOutcome(
            seat=b.seat, player_root=b.player_root, wager=b.amount, outcome=LOSE
        )
        for b in bets
    ]
    feed_table(
        w,
        table,
        *bets,
        _table.RoundSettled(round=1, outcomes=outcomes, house_delta=amount),
    )


def cash_out(w, name: str, table: str, amount: int) -> None:
    label = f"cash-out:{name}"
    feed_table(
        w,
        table,
        _table.PlayerCashedOut(
            cashout_id=request_id(label), player_root=player_root(name), amount=amount
        ),
    )
    feed_player(
        w,
        name,
        _p.CashOutCredited(
            cashout_id=request_id(label), table_root=table_root(table), amount=amount
        ),
    )


def apply_session_row(w, what: str, amount: int) -> None:
    if what == "the house wins a round":
        return house_wins(w, "Main", amount)
    name = what.split('"')[1]
    table = what.split('"')[3] if what.count('"') >= 4 else "Main"
    if what.endswith("deposits"):
        register_and_deposit(w, name, amount)
    elif "buys in" in what:
        if table_root(table).hex() not in w.ledger.projection.tables:
            feed_table(w, table, _table.TableCreated(name=table))
        buy_in(w, name, table, amount)
    elif what.endswith("cashes out"):
        cash_out(w, name, "Main", amount)
    elif what.endswith("withdraws"):
        feed_player(w, name, _p.FundsWithdrawn(amount=amount))
    else:
        raise AssertionError(f"unknown session step {what!r}")


@given("the ledger has applied a complete session in which:")
def step_complete_session(context):
    for row in context.table:
        apply_session_row(context.world, row["what"], int(row["amount"]))


@given("the ledger has applied a complete two-player session")
def step_two_player_session(context):
    w = context.world
    for what, amount in [
        ('"Alice" deposits', 1000),
        ('"Bob" deposits', 1000),
        ('"Alice" buys in at "Main"', 500),
        ('"Bob" buys in at "Main"', 500),
        ("the house wins a round", 50),
        ('"Alice" cashes out', 480),
        ('"Bob" withdraws', 200),
    ]:
        apply_session_row(w, what, amount)


@when("the ledger is asked for the totals")
def step_asked_totals(context):
    context.totals = totals(context.world)


_TOTALS = {
    "deposits": "deposits",
    "withdrawals": "withdrawals",
    "bankrolls": "bankrolls",
    "stacks": "stacks",
    "wagers": "wagers",
    "house result": "house_result",
}


@then("the ledger totals are:")
def step_totals_are(context):
    actual = {
        row["total"]: getattr(context.totals, _TOTALS[row["total"]])
        for row in context.table
    }
    expected = {row["total"]: int(row["amount"]) for row in context.table}
    assert actual == expected, actual


@when("the ledger is rebuilt from the same history")
def step_rebuild_ledger(context):
    w = context.world
    router = _az.Router()
    context.rebuilt_router = router
    host = ledger_main.build_host(router)
    for domain, root, page in w.log:
        book = _t.EventBook(cover=cover(domain, root, w.correlation))
        book.pages.append(page)
        host.project(book)
    host.ledger.refresh_totals()
    context.rebuilt = host.ledger


@then("the rebuilt ledger equals the original ledger")
def step_rebuilt_equals(context):
    original = context.world.ledger
    original.refresh_totals()
    try:
        assert context.rebuilt.projection == original.projection
        assert context.rebuilt.balanced() == original.balanced()
    finally:
        context.rebuilt_router.close()
