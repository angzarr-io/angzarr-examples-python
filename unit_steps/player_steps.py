"""Steps for features/example/blackjack/player.feature (the wallet)."""

from __future__ import annotations

import re

import angzarr_router_ffi as _az
from behave import given, step, then, when

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.player.agg import logic
from unit_steps._harness import PLAYER, cover, player_root, request_id, table_root
from unit_steps._helpers import (
    cashed_out_at_table,
    chips_added_at_table,
    hold_funds,
    ok,
    open_hold,
    refuse_top_up,
    register,
    request_top_up,
    wallet,
)

# --- identity ------------------------------------------------------------------


@given('player "{name}" has not registered')
def step_not_registered(context, name):
    assert not wallet(context.world, name).registered


@given('player "{name}" is registered')
def step_registered(context, name):
    register(context.world, name)


@given('player "{name}" is registered with {amount:d} deposited')
def step_registered_with(context, name, amount):
    register(context.world, name, amount)


@given('player "{name}" is registered and enrolled in the loyalty programme')
def step_registered_enrolled(context, name):
    register(context.world, name)
    ok(context.world.command(PLAYER, player_root(name), _p.EnrollLoyalty()))


@when('"{name}" registers with display name "{display:Text}" and email "{email:Text}"')
def step_register(context, name, display, email):
    context.world.command(
        PLAYER, player_root(name), _p.RegisterPlayer(display_name=display, email=email)
    )


@when(
    '"{name}" is imported from the old system as "{display}" with email "{email}" and legacy id "{legacy}"'
)
def step_import(context, name, display, email, legacy):
    context.world.command(
        PLAYER,
        player_root(name),
        _p.ImportPlayer(display_name=display, email=email, legacy_id=legacy),
    )


@when('"{name}" changes her display name to "{display}"')
def step_rename(context, name, display):
    context.world.command(
        PLAYER, player_root(name), _p.UpdateProfile(display_name=display)
    )


@then('"{name}" is registered as "{display}"')
def step_is_registered_as(context, name, display):
    state = wallet(context.world, name)
    assert state.registered, f"{name} is not registered"
    assert state.display_name == display, f"display name is {state.display_name!r}"


# --- money ---------------------------------------------------------------------


@when('"{name}" deposits {amount:d}')
def step_deposit(context, name, amount):
    context.world.command(PLAYER, player_root(name), _p.DepositFunds(amount=amount))


@when('"{name}" withdraws {amount:d}')
def step_withdraw(context, name, amount):
    context.world.command(PLAYER, player_root(name), _p.WithdrawFunds(amount=amount))


@then('"{name}" has a bankroll of {bankroll:d} with {available:d} available')
def step_bankroll(context, name, bankroll, available):
    state = wallet(context.world, name)
    assert state.bankroll == bankroll, f"bankroll is {state.bankroll}"
    assert logic.available(state) == available, f"available is {logic.available(state)}"


@then('the wallet of "{name}" balances')
def step_wallet_balances(context, name):
    state = wallet(context.world, name)
    assert logic.ledger_balances(state), f"L1 broken: {state}"


@then('"{name}" has sent {amount:d} to tables in total')
def step_sent(context, name, amount):
    assert wallet(context.world, name).total_to_tables == amount


@then('"{name}" has received {amount:d} from tables in total')
def step_received(context, name, amount):
    assert wallet(context.world, name).total_from_tables == amount


@then(
    '"{name}" has deposited {deposited:d}, withdrawn {withdrawn:d}, sent {sent:d} to tables and received {received:d} from tables'
)
def step_totals(context, name, deposited, withdrawn, sent, received):
    state = wallet(context.world, name)
    actual = (
        state.total_deposited,
        state.total_withdrawn,
        state.total_to_tables,
        state.total_from_tables,
    )
    assert actual == (deposited, withdrawn, sent, received), f"totals are {actual}"


# --- holds ---------------------------------------------------------------------


@step(
    '{amount:d} of "{name}"\'s funds are held for buy-in "{label}" at table "{table}"'
)
def step_hold(context, amount, name, label, table):
    outcome = hold_funds(context.world, name, label, table, amount)
    if context.step_type == "given":
        ok(outcome)


@given('{amount:d} of "{name}"\'s funds are held for a buy-in at table "{table}"')
def step_hold_unnamed(context, amount, name, table):
    ok(hold_funds(context.world, name, "a buy-in", table, amount))


@given(
    '{amount:d} of "{name}"\'s funds were held for buy-in "{label}" at table "{table}" and {closed}'
)
def step_hold_closed(context, amount, name, label, table, closed):
    w = context.world
    ok(hold_funds(w, name, label, table, amount))
    if closed == "captured":
        ok(
            w.command(
                PLAYER, player_root(name), _p.CaptureFunds(hold_id=request_id(label))
            )
        )
    else:
        ok(
            w.command(
                PLAYER,
                player_root(name),
                _p.ReleaseHold(hold_id=request_id(label), reason=closed),
            )
        )


@when('the hold "{label}" of "{name}" is captured')
def step_capture(context, label, name):
    context.world.command(
        PLAYER, player_root(name), _p.CaptureFunds(hold_id=request_id(label))
    )


@when('the hold "{label}" of "{name}" is released because "{reason}"')
def step_release(context, label, name, reason):
    context.world.command(
        PLAYER,
        player_root(name),
        _p.ReleaseHold(hold_id=request_id(label), reason=reason),
    )


@then('"{name}" has an open hold "{label}" of {amount:d} for table "{table}"')
def step_open_hold(context, name, label, amount, table):
    hold = open_hold(wallet(context.world, name), label)
    assert hold is not None, f"no open hold {label}"
    assert hold.amount == amount and hold.table_root == table_root(
        table
    ), f"hold is {hold}"


@then('"{name}" has no open hold "{label}"')
def step_no_open_hold(context, name, label):
    state = wallet(context.world, name)
    assert request_id(label).hex() in state.holds, f"hold {label} was never placed"
    assert open_hold(state, label) is None, f"hold {label} is still open"


@then('"{name}" has no hold "{label}"')
def step_no_hold(context, name, label):
    assert request_id(label).hex() not in wallet(context.world, name).holds


# --- top-ups -------------------------------------------------------------------


@step('"{name}" asks to top up {amount:d} at table "{table}" with request "{label}"')
def step_ask_top_up(context, name, amount, table, label):
    request_top_up(context.world, name, label, table, amount)


@given('"{name}" asked to top up {amount:d} at table "{table}" with request "{label}"')
def step_asked_top_up(context, name, amount, table, label):
    if not wallet(context.world, name).registered:
        register(context.world, name, amount)
    ok(request_top_up(context.world, name, label, table, amount))


@then('a top-up of {amount:d} for table "{table}" is requested')
def step_top_up_requested(context, amount, table):
    requested = context.world.last.decoded(_p.TopUpRequested)
    assert (
        len(requested) == 1
    ), f"expected one TopUpRequested, got {context.world.last.types()}"
    assert requested[0].amount == amount and requested[0].table_root == table_root(
        table
    )


def _holder(w, label: str) -> str:
    """The registered player whose wallet holds ``label``, else the only one."""
    players = w.labels.setdefault("players", [])
    for name in players:
        if request_id(label).hex() in wallet(w, name).holds:
            return name
    assert len(players) == 1, f"cannot tell whose request {label} is among {players}"
    return players[0]


@when('table "{table}" refuses top-up "{label}" because a wager is in play')
def step_table_refuses(context, table, label):
    w = context.world
    name = _holder(w, label)
    hold = wallet(w, name).holds.get(request_id(label).hex())
    amount = hold.amount if hold is not None else 0
    w.last = refuse_top_up(w, name, label, table, amount, "WAGER_IN_PLAY")


@then('the top-up "{label}" is refused with reason "{reason}"')
def step_top_up_refused(context, label, reason):
    w = context.world
    refused = [
        e
        for e in w.events(PLAYER, player_root(_holder(w, label)), _p.TopUpRefused)
        if e.hold_id == request_id(label)
    ]
    assert len(refused) == 1, f"expected one refusal of {label}, got {len(refused)}"
    assert refused[0].reason == reason, f"reason is {refused[0].reason!r}"


@then("the refusal changes nothing in the wallet")
def step_refusal_no_change(context):
    last = context.world.last
    assert (
        last.error is None and not last.events
    ), f"the refusal changed the wallet: {last.types()}"


@step('table "{table}" settled top-up "{label}" of {amount:d}')
def step_settled(context, table, label, amount):
    chips_added_at_table(
        context.world, _holder(context.world, label), label, table, amount
    )


@when('table "{table}" reports top-up "{label}" of {amount:d} settled')
def step_reports_settled(context, table, label, amount):
    chips_added_at_table(
        context.world, _holder(context.world, label), label, table, amount
    )


@then("the settlement is recorded and flagged because it matches no open hold")
def step_settlement_flagged(context):
    settled = context.world.last.decoded(_p.TopUpSettled)
    assert (
        len(settled) == 1
    ), f"expected the settlement recorded, got {context.world.last.types()}"
    assert settled[0].anomaly == logic.NO_MATCHING_HOLD


@when('table "{table}" reports that "{name}" cashed out {amount:d}')
def step_reports_cash_out(context, table, name, amount):
    cashed_out_at_table(context.world, name, table, amount)


# --- loyalty and round history ---------------------------------------------------


@when('"{name}" enrolls in the loyalty programme')
def step_enroll(context, name):
    context.world.command(PLAYER, player_root(name), _p.EnrollLoyalty())


@step(
    '"{name}" {tense} awarded {points:d} loyalty points for round {round:d} at table "{table}"'
)
def step_award(context, name, tense, points, round, table):
    outcome = context.world.command(
        PLAYER,
        player_root(name),
        _p.AwardLoyaltyPoints(table_root=table_root(table), round=round, points=points),
    )
    if tense == "was":
        ok(outcome)


@then('"{name}" is a loyalty member with {points:d} points')
def step_loyalty_member(context, name, points):
    state = wallet(context.world, name)
    assert state.loyalty_enrolled, f"{name} is not enrolled"
    assert state.loyalty_points == points, f"points are {state.loyalty_points}"


@step(
    'the result of round {round:d} at table "{table}" {tense} recorded for "{name}" as a net {net:d} on a wager of {wager:d}'
)
def step_record_result(context, round, table, tense, name, net, wager):
    outcome = context.world.command(
        PLAYER,
        player_root(name),
        _p.RecordRoundResult(
            table_root=table_root(table), round=round, wager=wager, net=net
        ),
    )
    if tense == "was":
        ok(outcome)


@then('"{name}" has {count:d} recorded round result')
def step_recorded_results(context, name, count):
    assert len(wallet(context.world, name).round_results) == count


@then('the result of round {round:d} at table "{table}" still stands for "{name}"')
def step_still_stands(context, round, table, name):
    result = wallet(context.world, name).round_results[
        logic.result_key(table_root(table), round)
    ]
    assert not result.retracted


@then('"{name}" has {count:d} standing round result')
@then('"{name}" has {count:d} standing round results')
def step_standing_results(context, name, count):
    standing = [
        r for r in wallet(context.world, name).round_results.values() if not r.retracted
    ]
    assert len(standing) == count, f"{len(standing)} standing results"


@when(
    'the recording of round {round:d} at table "{table}" for "{name}" is undone, '
    "identified by the events that recorded it"
)
def step_undo_record(context, round, table, name):
    w = context.world
    root = player_root(name)
    recorded = [
        p.header.sequence
        for p in w.stream(PLAYER, root)
        if p.event.type_url.endswith(_p.RoundResultRecorded.DESCRIPTOR.full_name)
        and unpack(p.event, _p.RoundResultRecorded).round == round
        and unpack(p.event, _p.RoundResultRecorded).table_root == table_root(table)
    ]
    assert recorded, f"round {round} was never recorded"
    compensate = _t.Compensate(
        sequences=recorded,
        reason="a follow-up of the round failed",
        command_type=_p.RecordRoundResult.DESCRIPTOR.full_name,
    )
    notification = _t.Notification(cover=cover(PLAYER, root))
    notification.payload.CopyFrom(_az.pack(compensate))
    deferred = _t.AngzarrDeferredSequence(
        source=cover("table", table_root(table)), source_component="sagas"
    )
    w.last = w.notify(
        notification, deferred, w.correlation, kind="compensate-notification"
    )


@then('the result of round {round:d} at table "{table}" is retracted for "{name}"')
def step_retracted(context, round, table, name):
    retracted = context.world.events(PLAYER, player_root(name), _p.RoundResultRetracted)
    assert [(r.table_root, r.round) for r in retracted] == [
        (table_root(table), round)
    ], retracted
    result = wallet(context.world, name).round_results[
        logic.result_key(table_root(table), round)
    ]
    assert result.retracted


# --- history written by older versions -----------------------------------------


@given('"{name}"\'s history holds a deposit of {amount:d} in the previous shape')
def step_legacy_deposit(context, name, amount):
    context.world.seed_page(
        PLAYER, player_root(name), _az.pack(_p.FundsDepositedV1(amount_chips=amount))
    )


# --- a sequence of money movements (L1) ------------------------------------------

_ROWS = [
    (
        r"^deposit$",
        lambda w, n, a, m: w.command(PLAYER, player_root(n), _p.DepositFunds(amount=a)),
    ),
    (
        r"^withdraw$",
        lambda w, n, a, m: w.command(
            PLAYER, player_root(n), _p.WithdrawFunds(amount=a)
        ),
    ),
    (
        r'^hold for buy-in "(?P<label>[^"]+)" at table "(?P<table>[^"]+)"$',
        lambda w, n, a, m: hold_funds(w, n, m["label"], m["table"], a),
    ),
    (
        r'^capture hold "(?P<label>[^"]+)"$',
        lambda w, n, a, m: w.command(
            PLAYER, player_root(n), _p.CaptureFunds(hold_id=request_id(m["label"]))
        ),
    ),
    (
        r'^request top-up "(?P<label>[^"]+)" at table "(?P<table>[^"]+)"$',
        lambda w, n, a, m: request_top_up(w, n, m["label"], m["table"], a),
    ),
    (
        r'^top-up "(?P<label>[^"]+)" refused by the table$',
        lambda w, n, a, m: refuse_top_up(w, n, m["label"], "Main", a, "WAGER_IN_PLAY"),
    ),
    (
        r'^top-up "(?P<label>[^"]+)" settled by the table$',
        lambda w, n, a, m: chips_added_at_table(w, n, m["label"], "Main", a),
    ),
    (
        r'^cash-out from table "(?P<table>[^"]+)"$',
        lambda w, n, a, m: cashed_out_at_table(w, n, m["table"], a),
    ),
]


@when('the following happen to "{name}" in order:')
def step_sequence(context, name):
    w = context.world
    for row in context.table:
        for pattern, run in _ROWS:
            match = re.match(pattern, row["step"])
            if match:
                result = run(w, name, int(row["amount"]), match.groupdict())
                if hasattr(result, "error"):
                    ok(result)
                break
        else:
            raise AssertionError(f"unknown money movement {row['step']!r}")
