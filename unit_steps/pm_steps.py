"""Steps for features/example/blackjack-framework/process_manager.feature.

The buy-in process runs on its own: it receives the table's and the wallet's
news as trigger events in the conversation the buy-in belongs to, and what it
asks of the table and the wallet is recorded, not delivered.
"""

from __future__ import annotations

import re

import angzarr_router_ffi as _az
from behave import given, then, when

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import unpack
from unit_steps._harness import (
    PLAYER,
    TABLE,
    cover,
    player_root,
    request_id,
    table_root,
)
from unit_steps._refusals import reason_code

Phase = _b.BuyInState.Phase
DECISION = _t.SyncMode.SYNC_MODE_DECISION
_PHASES = {
    "waiting for funds": Phase.PHASE_AWAITING_HOLD,
    "waiting for the seat": Phase.PHASE_AWAITING_SEAT,
    "waiting for the money to be spent": Phase.PHASE_AWAITING_CAPTURE,
    "completed": Phase.PHASE_COMPLETED,
}
_CONVERSATIONS = {"one conversation": "one", "another conversation": "another"}


def conversation(w, label: str) -> str:
    return w.labels.get(f"conversation:{label}", w.correlation)


def trigger(w, label: str, domain: str, root: bytes, event) -> None:
    """Deliver ``event`` from ``(domain, root)`` to the buy-in process in the
    conversation of buy-in ``label``."""
    sequence = w.labels.setdefault(("sequence", domain, root), 0)
    w.labels[("sequence", domain, root)] = sequence + 1
    book = _t.EventBook(cover=cover(domain, root, conversation(w, label)))
    page = book.pages.add()
    page.header.sequence = sequence
    page.event.CopyFrom(_az.pack(event))
    w.run_process_manager(book, route=False)


def seat_held(w, label, name, seat, table, amount):
    event = _table.SeatHeld(
        buy_in_id=request_id(label),
        player_root=player_root(name),
        seat=seat,
        amount=amount,
    )
    trigger(w, label, TABLE, table_root(table), event)


def funds_held(w, label, name, amount, table="Main"):
    event = _p.FundsHeld(
        hold_id=request_id(label), table_root=table_root(table), amount=amount
    )
    trigger(w, label, PLAYER, player_root(name), event)


def player_seated(w, label, name, seat, table, stack):
    event = _table.PlayerSeated(
        buy_in_id=request_id(label),
        player_root=player_root(name),
        seat=seat,
        stack=stack,
    )
    trigger(w, label, TABLE, table_root(table), event)


def funds_captured(w, label, name, amount, table="Main"):
    event = _p.FundsCaptured(
        hold_id=request_id(label), table_root=table_root(table), amount=amount
    )
    trigger(w, label, PLAYER, player_root(name), event)


def buy_in_state(w, label: str) -> _b.BuyInState:
    return w.buy_in.rebuild(w.process_state(conversation(w, label)))


def asked(context, message_class, domain: str | None = None) -> list:
    """What the process asked for since the scenario's setup."""
    return [
        s
        for s in context.world.sent[context.sent_mark :]
        if s.is_a(message_class) and (domain is None or s.domain == domain)
    ]


def refusal(w, label, domain, root, command, code) -> None:
    """The refusal of a command the process sent, delivered back to it."""
    rejected = _t.CommandBook(cover=cover(domain, root, conversation(w, label)))
    page = rejected.pages.add()
    page.header.angzarr_deferred.source.CopyFrom(cover(TABLE, table_root("Main")))
    page.command.CopyFrom(_az.pack(command))
    w.refuse(rejected, _az.CodedError(code=code, message="refused"), "pm", route=False)


# --- getting a buy-in to a phase -------------------------------------------------------


@given("no buy-in has started in this conversation")
def step_no_buy_in(context):
    w = context.world
    assert not w.process_streams.get(w.correlation)
    context.sent_mark = 0


@given('buy-in "{label}" for "{name}" at seat {seat:d} of table "{table}" is {phase}')
def step_buy_in_at_phase(context, label, name, seat, table, phase):
    w = context.world
    phase, _, where = phase.partition(" in ")
    if where:
        named = re.fullmatch(r'conversation "([^"]+)"', where)
        w.labels[f"conversation:{label}"] = named[1] if named else _CONVERSATIONS[where]
    target = _PHASES[phase]
    seat_held(w, label, name, seat, table, 500)
    if target >= Phase.PHASE_AWAITING_SEAT:
        funds_held(w, label, name, 500, table)
    if target >= Phase.PHASE_AWAITING_CAPTURE:
        player_seated(w, label, name, seat, table, 500)
    if target >= Phase.PHASE_COMPLETED:
        funds_captured(w, label, name, 500, table)
    assert buy_in_state(w, label).phase == target
    context.sent_mark = len(w.sent)


@given('table "{table}" was asked to confirm buy-in "{label}"')
def step_was_asked_to_confirm(context, table, label):
    earlier = [
        s for s in context.world.sent[: context.sent_mark] if s.is_a(_table.ConfirmSeat)
    ]
    assert [unpack(s.command, _table.ConfirmSeat).buy_in_id for s in earlier] == [
        request_id(label)
    ]


@given("the buy-in history for this conversation is:")
def step_history(context):
    w = context.world
    events = []
    for row in context.table:
        text = row["step"]
        label = text.split('"')[1]
        if text.startswith("buy-in"):
            parts = text.split('"')
            seat = int(text.split("seat ")[1].split()[0])
            amount = int(text.rsplit("for ", 1)[1])
            events.append(
                _b.BuyInStarted(
                    buy_in_id=request_id(label),
                    player_root=player_root(parts[3]),
                    table_root=table_root(parts[5]),
                    seat=seat,
                    amount=amount,
                )
            )
        elif text.startswith("funds held"):
            events.append(_b.BuyInFundsHeld(buy_in_id=request_id(label)))
        elif text.startswith("seat confirmed"):
            stack = int(text.rsplit(" ", 1)[1])
            events.append(_b.BuyInSeated(buy_in_id=request_id(label), stack=stack))
        else:
            raise AssertionError(f"unknown buy-in history step {text!r}")
    stream = w.process_streams.setdefault(w.correlation, [])
    for event in events:
        page = _t.EventPage()
        page.header.sequence = len(stream)
        page.event.CopyFrom(_az.pack(event))
        stream.append(page)


# --- news arriving -----------------------------------------------------------------------


@when(
    'seat {seat:d} at table "{table}" is held for "{name}" by buy-in "{label}" of {amount:d}'
)
def step_seat_held_news(context, seat, table, name, label, amount):
    seat_held(context.world, label, name, seat, table, amount)


@when('the wallet of "{name}" holds {amount:d} for buy-in "{label}"')
def step_funds_held_news(context, name, amount, label):
    funds_held(context.world, label, name, amount)


@when(
    '"{name}" is seated at seat {seat:d} of table "{table}" through buy-in "{label}" with a stack of {stack:d}'
)
def step_seated_news(context, name, seat, table, label, stack):
    player_seated(context.world, label, name, seat, table, stack)


@when('the wallet of "{name}" spends {amount:d} for buy-in "{label}"')
def step_captured_news(context, name, amount, label):
    funds_captured(context.world, label, name, amount)


@when(
    'the wallet of "{name}" refuses to hold {amount:d} for buy-in "{label}" because {reason}'
)
def step_hold_refused(context, name, amount, label, reason):
    hold = _p.HoldFunds(
        hold_id=request_id(label), table_root=table_root("Main"), amount=amount
    )
    refusal(context.world, label, PLAYER, player_root(name), hold, reason_code(reason))


@when('table "{table}" refuses to confirm buy-in "{label}" because {reason}')
def step_confirm_refused(context, table, label, reason):
    confirm = _table.ConfirmSeat(buy_in_id=request_id(label))
    refusal(
        context.world, label, TABLE, table_root(table), confirm, reason_code(reason)
    )


@when("the buy-in is rebuilt from its history")
def step_rebuild(context):
    context.rebuilt = buy_in_state(context.world, "")


# --- where the buy-in is -----------------------------------------------------------------


@then('buy-in "{label}" {verb} {phase}')
def step_buy_in_phase(context, label, verb, phase):
    phase = phase.removeprefix("still ")
    if phase.startswith("failed because"):
        return _assert_failed(context, label, phase.removeprefix("failed because "))
    state = buy_in_state(context.world, label)
    assert state.buy_in_id == request_id(label), "the buy-in is not this one"
    assert state.phase == _PHASES[phase], f"phase is {Phase.Name(state.phase)}"


def _assert_failed(context, label, reason) -> None:
    state = buy_in_state(context.world, label)
    assert state.phase == Phase.PHASE_FAILED, Phase.Name(state.phase)
    assert state.failure_reason == reason_code(reason), state.failure_reason


@then('it belongs to "{name}", seat {seat:d} of table "{table}", for {amount:d}')
def step_belongs(context, name, seat, table, amount):
    s = context.rebuilt
    assert (s.player_root, s.seat, s.table_root, s.amount) == (
        player_root(name),
        seat,
        table_root(table),
        amount,
    )


# --- what the buy-in asks for --------------------------------------------------------------


@then(
    'the wallet of "{name}" is asked to hold {amount:d} for buy-in "{label}" at table "{table}"'
)
def step_asked_hold(context, name, amount, label, table):
    (sent,) = asked(context, _p.HoldFunds)
    hold = unpack(sent.command, _p.HoldFunds)
    assert sent.root == player_root(name)
    assert (hold.hold_id, hold.amount, hold.table_root) == (
        request_id(label),
        amount,
        table_root(table),
    )
    context.request = sent


@then("the request is decided before the buy-in moves on")
def step_decided(context):
    header = context.request.emitted.pages[0].header
    assert header.sync_mode == DECISION
    assert header.WhichOneof("sequence_type") == "angzarr_deferred"


@then('table "{table}" is asked to confirm buy-in "{label}"')
def step_asked_confirm(context, table, label):
    (sent,) = asked(context, _table.ConfirmSeat)
    assert sent.root == table_root(table)
    assert unpack(sent.command, _table.ConfirmSeat).buy_in_id == request_id(label)


@then('table "{table}" is not asked to confirm buy-in "{label}" again')
def step_not_asked_confirm(context, table, label):
    assert not asked(context, _table.ConfirmSeat)


@then('the wallet of "{name}" is asked to spend the hold for buy-in "{label}"')
def step_asked_capture(context, name, label):
    (sent,) = asked(context, _p.CaptureFunds)
    assert sent.root == player_root(name)
    assert unpack(sent.command, _p.CaptureFunds).hold_id == request_id(label)


@then('table "{table}" is asked to release the seat held by buy-in "{label}"')
def step_asked_release_seat(context, table, label):
    (sent,) = asked(context, _table.ReleaseSeat)
    assert sent.root == table_root(table)
    assert unpack(sent.command, _table.ReleaseSeat).buy_in_id == request_id(label)


@then('the wallet of "{name}" is asked to release the hold for buy-in "{label}"')
def step_asked_release_hold(context, name, label):
    (sent,) = asked(context, _p.ReleaseHold)
    assert sent.root == player_root(name)
    assert unpack(sent.command, _p.ReleaseHold).hold_id == request_id(label)


@then("nothing is asked of the wallet")
def step_nothing_of_wallet(context):
    assert not [
        s for s in context.world.sent[context.sent_mark :] if s.domain == PLAYER
    ]


@then("{nothing} asked of the table or the wallet")
def step_nothing_asked(context, nothing):
    assert nothing in ("nothing is", "nothing more is")
    assert not context.world.sent[context.sent_mark :], "the buy-in asked for something"


@then('the request to confirm buy-in "{label}" belongs to conversation "{corr}"')
def step_request_conversation(context, label, corr):
    (sent,) = asked(context, _table.ConfirmSeat)
    assert sent.delivered.cover.correlation_id == corr
