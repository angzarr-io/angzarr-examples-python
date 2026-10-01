"""Steps for features/example/blackjack-framework/saga.feature (translators)."""

from __future__ import annotations

import angzarr_router_ffi as _az
from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.player.agg import logic
from angzarr_blackjack.table.agg.handler import cashout_id
from unit_steps._harness import (
    PLAYER,
    SAGAS,
    TABLE,
    cover,
    player_root,
    request_id,
    table_root,
)
from unit_steps._helpers import (
    create_table,
    ok,
    place_bet,
    play_standing,
    refuse_top_up,
    register,
    seat_number_of,
    seat_player,
    table_state,
    wallet,
)

Outcome = _table.SeatOutcome.Outcome
_OUTCOMES = {
    "lose": Outcome.OUTCOME_LOSE,
    "push": Outcome.OUTCOME_PUSH,
    "win": Outcome.OUTCOME_WIN,
    "blackjack": Outcome.OUTCOME_BLACKJACK,
}


def single_page_book(domain: str, root: bytes, page, corr: str) -> _t.EventBook:
    book = _t.EventBook(cover=cover(domain, root, corr))
    book.pages.append(page)
    return book


def last_page(w, domain: str, root: bytes, message_class):
    name = message_class.DESCRIPTOR.full_name
    pages = [p for p in w.stream(domain, root) if type_name(p.event.type_url) == name]
    assert pages, f"no {message_class.DESCRIPTOR.name} in {domain}"
    return pages[-1]


def ensure_table(w, table: str) -> None:
    if table_state(w, table).phase == _table.TableState.Phase.PHASE_UNSPECIFIED:
        ok(create_table(w, table))


# --- wallets and seats ---------------------------------------------------------------


@given('"{name}" is registered with {amount:d} deposited')
def step_registered_with(context, name, amount):
    register(context.world, name, amount)


@given('"{name}" deposited {amount:d}')
def step_deposited(context, name, amount):
    if not wallet(context.world, name).registered:
        register(context.world, name)
    ok(context.world.command(PLAYER, player_root(name), _p.DepositFunds(amount=amount)))


@given('"{name}" deposited {amount:d} afterwards')
def step_deposited_afterwards(context, name, amount):
    ok(context.world.command(PLAYER, player_root(name), _p.DepositFunds(amount=amount)))


@given('"{name}" is registered and not a loyalty member')
def step_not_member(context, name):
    register(context.world, name)
    assert not wallet(context.world, name).loyalty_enrolled


@given('"{name}" is seated at table "{table}" with a stack of {stack:d}')
def step_seated_at(context, name, table, stack):
    ensure_table(context.world, table)
    seat_player(context.world, name, 0, stack, table)


@given('"{name}" has a bet in play at table "{table}"')
def step_bet_in_play(context, name, table):
    w = context.world
    ensure_table(w, table)
    if seat_number_of(table_state(w, table), name) is None:
        seat_player(w, name, 0, 500, table)
    ok(place_bet(w, seat_number_of(table_state(w, table), name), 20, table))


@then('"{name}" has a stack of {stack:d} at table "{table}"')
def step_stack_at(context, name, stack, table):
    state = table_state(context.world, table)
    seat = seat_number_of(state, name)
    assert seat is not None, f"{name} is not seated"
    assert state.seated[seat].stack == stack, f"stack is {state.seated[seat].stack}"


# --- the top-up translator -----------------------------------------------------------


def run_top_up_translator(w, event_class, name: str = "Alice"):
    page = last_page(w, PLAYER, player_root(name), event_class)
    w.sent_mark = len(w.sent)
    w.saga_response = w.run_sagas(
        single_page_book(PLAYER, player_root(name), page, w.correlation)
    )


@when("the top-up translator handles the {what}")
def step_top_up_translator(context, what):
    event = {
        "request": _p.TopUpRequested,
        "same request again": _p.TopUpRequested,
        "deposit": _p.FundsDeposited,
    }[what]
    run_top_up_translator(context.world, event)


@given("the top-up translator has handled the request")
def step_top_up_translator_handled(context):
    run_top_up_translator(context.world, _p.TopUpRequested)


@then(
    'table "{table}" is asked to add {amount:d} chips for "{name}" from top-up "{label}"'
)
def step_asked_to_add_chips(context, table, amount, name, label):
    sent = context.world.sent_of(_table.AddChips)
    assert len(sent) == 1, f"{len(sent)} AddChips sent"
    assert (sent[0].domain, sent[0].root) == (TABLE, table_root(table))
    add = unpack(sent[0].command, _table.AddChips)
    assert (add.player_root, add.hold_id, add.amount) == (
        player_root(name),
        request_id(label),
        amount,
    )


@then("the request is applied to whatever the table looks like when it arrives")
def step_deferred(context):
    emitted = context.world.sent_of(_table.AddChips)[0].emitted
    header = emitted.pages[0].header
    assert header.WhichOneof("sequence_type") == "angzarr_deferred"


@then("no request is sent to any table")
def step_nothing_sent(context):
    assert not context.world.saga_response.commands
    assert not context.world.sent


@then('table "{table}" recorded chips from top-up "{label}" once')
def step_chips_once(context, table, label):
    added = [
        e
        for e in context.world.events(TABLE, table_root(table), _table.ChipsAdded)
        if e.hold_id == request_id(label)
    ]
    assert len(added) == 1, f"{len(added)} ChipsAdded"


@when('table "{table}" handles the request to add chips from top-up "{label}"')
def step_table_handles_add_chips(context, table, label):
    run_top_up_translator(context.world, _p.TopUpRequested)


@then('the wallet of "{name}" is told the request was refused')
def step_wallet_told(context, name):
    sent = context.world.sent_of(_table.AddChips)[-1]
    assert sent.outcome.error is not None and sent.outcome.notified
    assert context.world.events(PLAYER, player_root(name), _p.TopUpRefused)


@when(
    'the wallet of "{name}" is told table "{table}" refused the request to add chips from top-up "{label}"'
)
def step_told_add_chips_refused(context, name, table, label):
    w = context.world
    hold = wallet(w, name).holds[request_id(label).hex()]
    w.last = refuse_top_up(w, name, label, table, hold.amount, "WAGER_IN_PLAY")


@when('the wallet of "{name}" is told table "{table}" refused a seat confirmation')
def step_told_confirm_refused(context, name, table):
    w = context.world
    rejected = _t.CommandBook(cover=cover(TABLE, table_root(table), w.correlation))
    page = rejected.pages.add()
    page.header.angzarr_deferred.source.CopyFrom(cover(PLAYER, player_root(name)))
    page.command.CopyFrom(_az.pack(_table.ConfirmSeat(buy_in_id=request_id("B1"))))
    notification = w.rejection(rejected, "PLAYER_ALREADY_SEATED: the player is seated")
    w.last = w.notify(notification, page.header.angzarr_deferred, w.correlation)


@then('nothing is undone in the wallet of "{name}"')
def step_nothing_undone_wallet(context, name):
    last = context.world.last
    assert last.error is None and not last.events, last.types()
    assert not context.world.events(PLAYER, player_root(name), _p.TopUpRefused)


# --- the settlement translator: facts ------------------------------------------------


@given('table "{table}" added {amount:d} chips for "{name}" from top-up "{label}"')
def step_table_added(context, table, amount, name, label):
    _seed_chips_added(context, table, amount, name, label)


@given(
    'table "{table}" added {amount:d} chips for "{name}" from top-up "{label}" that the wallet never requested'
)
def step_table_added_unrequested(context, table, amount, name, label):
    _seed_chips_added(context, table, amount, name, label)


def _seed_chips_added(context, table, amount, name, label):
    w = context.world
    (page,) = w.seed(
        TABLE,
        table_root(table),
        _table.ChipsAdded(
            hold_id=request_id(label),
            player_root=player_root(name),
            amount=amount,
            stack_after=amount,
        ),
    )
    context.table_page = page


@given('"{name}" cashed out {amount:d} from table "{table}"')
def step_cashed_out(context, name, amount, table):
    w = context.world
    sequence = len(w.stream(TABLE, table_root(table)))
    (page,) = w.seed(
        TABLE,
        table_root(table),
        _table.PlayerCashedOut(
            cashout_id=cashout_id(table_root(table), sequence),
            player_root=player_root(name),
            amount=amount,
        ),
    )
    context.table_page = page


def run_settlement_translator(context, table: str = "Main") -> None:
    w = context.world
    w.saga_response = w.run_sagas(
        single_page_book(TABLE, table_root(table), context.table_page, w.correlation)
    )


def _fact_external_id(context) -> str:
    """The idempotency key the translator put on the fact it emitted."""
    (fact_book,) = context.world.saga_response.events
    return fact_book.pages[0].header.external_deferred.external_id


@when("the settlement translator handles the {what}")
def step_settlement_handles(context, what):
    run_settlement_translator(context)


@given("the settlement translator has handled the {what}")
def step_settlement_handled(context, what):
    run_settlement_translator(context)


@then(
    'the wallet of "{name}" records, as a fact it cannot refuse, that top-up "{label}" of {amount:d} settled'
)
def step_fact_settled(context, name, label, amount):
    last = context.world.last
    settled = last.decoded(_p.TopUpSettled)
    assert len(settled) == 1, last.types()
    assert (settled[0].hold_id, settled[0].amount, settled[0].anomaly) == (
        request_id(label),
        amount,
        "",
    )
    assert _fact_external_id(context) == request_id(label).hex()


@then(
    'the wallet of "{name}" records, as a fact it cannot refuse, a credit of {amount:d} from table "{table}"'
)
def step_fact_credit(context, name, amount, table):
    last = context.world.last
    credited = last.decoded(_p.CashOutCredited)
    assert len(credited) == 1, last.types()
    assert (credited[0].table_root, credited[0].amount) == (table_root(table), amount)
    assert _fact_external_id(context) == credited[0].cashout_id.hex()


@then("the second delivery is recognised as already recorded")
def step_already_recorded(context):
    assert context.world.last.already_processed


@then(
    'the wallet of "{name}" records the settlement and flags it because it matches no open hold'
)
def step_fact_flagged(context, name):
    settled = context.world.last.decoded(_p.TopUpSettled)
    assert len(settled) == 1 and settled[0].anomaly == logic.NO_MATCHING_HOLD
    assert wallet(context.world, name).anomalies == 1


# --- one settled round, several follow-ups -------------------------------------------


@given('round {round:d} at table "{table}" settled with:')
def step_round_settled_with(context, round, table):
    outcomes = [
        _table.SeatOutcome(
            seat=int(r["seat"]),
            player_root=player_root(r["player"]),
            wager=int(r["wager"]),
            outcome=_OUTCOMES[r["outcome"]],
            returned=int(r["returned"]),
            net=int(r["returned"]) - int(r["wager"]),
        )
        for r in context.table
    ]
    delta = sum(o.wager for o in outcomes) - sum(o.returned for o in outcomes)
    (page,) = context.world.seed(
        TABLE,
        table_root(table),
        _table.RoundSettled(
            round=round, outcomes=outcomes, house_delta=delta, house_result_after=delta
        ),
    )
    context.table_page = page


@when("the {translator} translator handles the settlement")
def step_round_translator(context, translator):
    w = context.world
    w.saga_response = w.run_sagas(
        single_page_book(TABLE, table_root("Main"), context.table_page, w.correlation),
        route=False,
    )


def _commands(context, message_class) -> list[tuple[bytes, object]]:
    return [
        (book.cover.root.value, unpack(book.pages[0].command, message_class))
        for book in context.world.saga_response.commands
        if type_name(book.pages[0].command.type_url)
        == message_class.DESCRIPTOR.full_name
    ]


@then('the wallets are asked to record round {round:d} at table "{table}" as:')
def step_asked_record(context, round, table):
    actual = [
        (root, c.table_root, c.round, c.wager, c.net)
        for root, c in _commands(context, _p.RecordRoundResult)
    ]
    expected = [
        (
            player_root(r["player"]),
            table_root(table),
            round,
            int(r["wager"]),
            int(r["net"]),
        )
        for r in context.table
    ]
    assert actual == expected, actual


@then(
    'the wallets are asked to award loyalty points for round {round:d} at table "{table}" as:'
)
def step_asked_award(context, round, table):
    actual = [
        (root, c.table_root, c.round, c.points)
        for root, c in _commands(context, _p.AwardLoyaltyPoints)
    ]
    expected = [
        (player_root(r["player"]), table_root(table), round, int(r["points"]))
        for r in context.table
    ]
    assert actual == expected, actual


@given('round {round:d} at table "{table}" settled')
def step_round_settled(context, round, table):
    w = context.world
    ok(create_table(w, table, seed=2))
    seat_player(w, "Alice", 0, 500, table)
    seat_player(w, "Bob", 1, 500, table)
    ok(place_bet(w, 0, 20, table))
    ok(place_bet(w, 1, 30, table))
    play_standing(w, table)
    context.table_page = last_page_of(w, table, _table.RoundSettled)
    assert unpack(context.table_page.event, _table.RoundSettled).round == round


def last_page_of(w, table, message_class):
    return last_page(w, TABLE, table_root(table), message_class)


@when("the settlement is delivered")
def step_settlement_delivered(context):
    w = context.world
    root = table_root("Main")
    full = _t.EventBook(cover=cover(TABLE, root, w.correlation))
    full.pages.extend(w.stream(TABLE, root))
    w.project(full)
    w.saga_response = w.run_sagas(
        single_page_book(TABLE, root, context.table_page, w.correlation), route=False
    )


def _settled(context) -> _table.RoundSettled:
    return unpack(context.table_page.event, _table.RoundSettled)


@then('it is folded into table "{table}"')
def step_folded(context, table):
    state = table_state(context.world, table)
    settled = _settled(context)
    assert state.house_result == settled.house_result_after
    for outcome in settled.outcomes:
        assert state.seated[outcome.seat].stack == outcome.stack_after
        assert state.seated[outcome.seat].wager == 0


@then("it is handled by the round-history translator and the loyalty translator")
def step_both_translators(context):
    settled = _settled(context)
    players = [o.player_root for o in settled.outcomes]
    assert [root for root, _ in _commands(context, _p.RecordRoundResult)] == players
    assert [root for root, _ in _commands(context, _p.AwardLoyaltyPoints)] == players


@then("it is applied to the ledger")
def step_applied_to_ledger(context):
    row = context.world.ledger.projection.tables[table_root("Main").hex()]
    assert row.house_result == _settled(context).house_result_after
    assert row.wagers == 0


@given(
    'the loyalty translator asked to award "{name}" {points:d} points for round {round:d} at table "{table}"'
)
def step_loyalty_asked(context, name, points, round, table):
    w = context.world
    outcome = _table.SeatOutcome(
        seat=0,
        player_root=player_root(name),
        wager=points,
        outcome=Outcome.OUTCOME_LOSE,
    )
    (page,) = w.seed(
        TABLE,
        table_root(table),
        _table.RoundSettled(round=round, outcomes=[outcome], house_delta=points),
    )
    source = single_page_book(TABLE, table_root(table), page, w.correlation)
    response = w.run_sagas(source, route=False)
    awards = [
        (i, book)
        for i, book in enumerate(response.commands)
        if type_name(book.pages[0].command.type_url)
        == _p.AwardLoyaltyPoints.DESCRIPTOR.full_name
    ]
    assert len(awards) == 1
    context.pending = (awards[0][1], source, awards[0][0])
    w.sent.clear()


@when('the wallet of "{name}" handles the request')
def step_wallet_handles(context, name):
    w = context.world
    command, source, index = context.pending
    context.table_events_before = len(w.stream(TABLE, source.cover.root.value))
    w.sent_mark = len(w.sent)
    w.last = w.deliver(command, source, index, "saga", SAGAS, w.correlation).outcome


@then('nothing is undone at table "{table}"')
def step_nothing_undone_table(context, table):
    assert (
        len(context.world.stream(TABLE, table_root(table)))
        == context.table_events_before
    )
