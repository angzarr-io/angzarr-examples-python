"""The hosts and servicers: what they add over the router binding (facts,
Replay, undo, PM compensation, the handled cover) and how a rejection is
reported over gRPC."""

import angzarr_client.router as _az
import grpc
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_client.proto.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime import servicers
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.player.agg import main as player_main
from angzarr_blackjack.player.agg.logic import NO_MATCHING_HOLD
from angzarr_blackjack.pmg_buy_in import main as buy_in_main

ALICE, TABLE, H1 = b"\x0a" * 16, b"\x01" * 16, b"\x11" * 16


@pytest.fixture
def router():
    with _az.Router() as r:
        yield r


def history(*events) -> _t.EventBook:
    book = _t.EventBook(cover=_t.Cover(domain="player", root=_t.UUID(value=ALICE)))
    for sequence, event in enumerate(events):
        book.pages.add(event=_az.pack(event)).header.sequence = sequence
    return book


def registered(*more):
    return history(
        _p.PlayerRegistered(display_name="A", email="a@x"),
        _p.FundsDeposited(amount=1000),
        *more,
    )


def test_commands_go_through_the_router(router):
    host = player_main.build_host(router)
    command = _t.ContextualCommand(events=registered())
    command.command.cover.CopyFrom(_t.Cover(domain="player", root=_t.UUID(value=ALICE)))
    command.command.pages.add(command=_az.pack(_p.WithdrawFunds(amount=300)))
    response = host.handle(command)
    assert unpack(response.events.pages[0].event, _p.FundsWithdrawn).amount == 300
    command.command.pages[0].command.CopyFrom(_az.pack(_p.WithdrawFunds(amount=5000)))
    with pytest.raises(_az.CodedError) as info:
        host.handle(command)
    assert info.value.code == "INSUFFICIENT_AVAILABLE_FUNDS"


def compensation_envelope(
    command_type: str, prior: _t.EventBook, sequences=(2,)
) -> _t.ContextualCommand:
    notification = _t.Notification(cover=prior.cover)
    notification.payload.CopyFrom(
        _az.pack(_t.Compensate(sequences=list(sequences), command_type=command_type))
    )
    envelope = _t.ContextualCommand(events=prior)
    envelope.command.cover.CopyFrom(prior.cover)
    envelope.command.pages.add(command=_az.pack(notification))
    return envelope


def test_compensate_is_routed_to_the_undo_handler(router):
    host = player_main.build_host(router)
    prior = registered(
        _p.RoundResultRecorded(table_root=TABLE, round=1, wager=20, net=20)
    )
    response = host.handle(
        compensation_envelope("io.angzarr.examples.v1.RecordRoundResult", prior)
    )
    (page,) = response.events.pages
    assert unpack(page.event, _p.RoundResultRetracted) == _p.RoundResultRetracted(
        table_root=TABLE, round=1, net=20
    )


def test_compensate_with_nothing_to_undo_answers_empty(router):
    host = player_main.build_host(router)
    response = host.handle(
        compensation_envelope("io.angzarr.examples.v1.RecordRoundResult", registered())
    )
    assert response == _ch.BusinessResponse()


def test_compensate_without_an_undo_handler_is_unimplemented(router):
    host = player_main.build_host(router)
    with pytest.raises(_az.CodedError) as info:
        host.handle(
            compensation_envelope("io.angzarr.examples.v1.DepositFunds", registered())
        )
    assert (info.value.code, info.value.grpc) == (
        "NO_UNDO_HANDLER",
        _az.GrpcCode.UNIMPLEMENTED,
    )


def test_facts_are_checked_against_the_rebuilt_wallet(router):
    host = player_main.build_host(router)
    prior = registered(_p.TopUpRequested(hold_id=H1, table_root=TABLE, amount=200))
    facts = _t.EventBook(cover=prior.cover)
    page = facts.pages.add(event=_az.pack(_p.TopUpSettled(hold_id=H1, amount=200)))
    page.header.external_deferred.external_id = H1.hex()
    facts.pages.add(event=_az.pack(_p.TopUpSettled(hold_id=H1, amount=200)))
    facts.pages.add(event=_az.pack(_p.CashOutCredited(amount=5)))
    recorded = host.handle_fact(_ch.FactRequest(facts=facts, prior_events=prior))
    first, second, third = (
        unpack(p.event, cls)
        for p, cls in zip(
            recorded.pages, (_p.TopUpSettled, _p.TopUpSettled, _p.CashOutCredited)
        )
    )
    assert first.anomaly == ""
    assert second.anomaly == NO_MATCHING_HOLD
    assert third.amount == 5
    assert recorded.pages[0].header.external_deferred.external_id == H1.hex()
    assert recorded.cover == prior.cover


def test_replay_returns_the_state_after_the_events(router):
    host = player_main.build_host(router)
    book = registered(_p.FundsWithdrawn(amount=100))
    snapshot = _t.Snapshot(
        sequence=0,
        state=_az.pack(
            _p.PlayerState(registered=True, bankroll=50, total_deposited=50)
        ),
    )
    response = host.replay(
        _ch.ReplayRequest(base_snapshot=snapshot, events=list(book.pages)[1:])
    )
    state = unpack(response.state, _p.PlayerState)
    assert (state.bankroll, state.total_deposited, state.total_withdrawn) == (
        950,
        1050,
        100,
    )
    assert (
        unpack(host.replay(_ch.ReplayRequest()).state, _p.PlayerState)
        == _p.PlayerState()
    )


def test_pm_compensation_keeps_its_commands(router):
    host = buy_in_main.build_host(router)
    state = _t.EventBook(cover=_t.Cover(domain="buy-in", correlation_id="C"))
    state.pages.add(
        event=_az.pack(
            _b.BuyInStarted(
                buy_in_id=H1, player_root=ALICE, table_root=TABLE, amount=500
            )
        )
    )
    rejected = _t.CommandBook(
        cover=_t.Cover(domain="player", root=_t.UUID(value=ALICE))
    )
    rejected.pages.add(command=_az.pack(_p.HoldFunds(hold_id=H1, amount=500)))
    notification = _t.Notification()
    notification.payload.CopyFrom(
        _az.pack(
            _t.RejectionNotification(
                rejected_command=rejected,
                rejection_reason="INSUFFICIENT_AVAILABLE_FUNDS: no",
            )
        )
    )
    trigger = _t.EventBook(cover=_t.Cover(domain="player", correlation_id="C"))
    trigger.pages.add(event=_az.pack(notification))
    response = host.handle(
        _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=state)
    )
    (command,) = response.commands
    assert unpack(command.pages[0].command, _table.ReleaseSeat).buy_in_id == H1
    assert (
        unpack(response.process_events[0].pages[0].event, _b.BuyInFailed).reason
        == "INSUFFICIENT_AVAILABLE_FUNDS"
    )
    rejected.pages[0].command.CopyFrom(_az.pack(_p.DepositFunds(amount=1)))
    notification.payload.CopyFrom(
        _az.pack(_t.RejectionNotification(rejected_command=rejected))
    )
    trigger.pages[0].event.CopyFrom(_az.pack(notification))
    assert (
        host.handle(
            _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=state)
        )
        == _pm.ProcessManagerHandleResponse()
    )


def test_pm_triggers_go_through_the_router(router):
    host = buy_in_main.build_host(router)
    trigger = _t.EventBook(
        cover=_t.Cover(domain="table", root=_t.UUID(value=TABLE), correlation_id="C")
    )
    trigger.pages.add(
        event=_az.pack(
            _table.SeatHeld(buy_in_id=H1, player_root=ALICE, seat=0, amount=500)
        )
    )
    response = host.handle(
        _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=_t.EventBook())
    )
    started = unpack(response.process_events[0].pages[0].event, _b.BuyInStarted)
    assert started.table_root == TABLE


# --- servicers ---------------------------------------------------------------------------


class _Aborted(Exception):
    pass


class FakeContext:
    def abort(self, code, message):
        self.code, self.message = code, message
        raise _Aborted


def test_grpc_status_mapping():
    assert servicers.grpc_status(9) == grpc.StatusCode.FAILED_PRECONDITION
    assert servicers.grpc_status(3) == grpc.StatusCode.INVALID_ARGUMENT
    assert servicers.grpc_status(999) == grpc.StatusCode.INTERNAL


def test_rejections_are_reported_with_their_code():
    def refuse(_):
        raise _az.CodedError(
            code="WAGER_IN_PLAY",
            message="in play",
            grpc=_az.GrpcCode.FAILED_PRECONDITION,
        )

    context = FakeContext()
    with pytest.raises(_Aborted):
        servicers._call(context, refuse, None)
    assert (context.code, context.message) == (
        grpc.StatusCode.FAILED_PRECONDITION,
        "WAGER_IN_PLAY: in play",
    )


def test_unexpected_failures_are_internal():
    def crash(_):
        raise ValueError("boom")

    context = FakeContext()
    with pytest.raises(_Aborted):
        servicers._call(context, crash, None)
    assert (context.code, context.message) == (grpc.StatusCode.INTERNAL, "boom")


def test_unconsumed_events_are_acknowledged(router):
    """A saga service receives every event of its source domains; an event no
    saga consumes is acknowledged, a malformed request is refused."""
    saga = servicers.SagaServicer(router)
    source = _t.EventBook(cover=_t.Cover(domain="nowhere"))
    source.pages.add(event=_az.pack(_p.FundsDeposited(amount=1)))
    assert (
        saga.Handle(_saga.SagaHandleRequest(source=source), FakeContext())
        == _saga.SagaResponse()
    )
    context = FakeContext()
    with pytest.raises(_Aborted):
        saga.Handle(
            _saga.SagaHandleRequest(source=_t.EventBook(cover=source.cover)), context
        )
    assert context.code == grpc.StatusCode.INVALID_ARGUMENT


def test_pass_through_upcaster_returns_events_unchanged():
    from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2 as _up

    page = _t.EventPage(event=_az.pack(_table.TableCreated(name="Main")))
    request = _up.UpcastRequest(domain="table", events=[page])
    assert list(servicers.PassThroughUpcaster().upcast(request).events) == [page]


def test_ledger_query_service_reads_the_ledger(router):
    from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
    from angzarr_blackjack.prj_ledger import main as ledger_main
    from angzarr_blackjack.prj_ledger.query import LedgerQueryServicer

    host = ledger_main.build_host(router)
    book = _t.EventBook(cover=_t.Cover(domain="player", root=_t.UUID(value=ALICE)))
    book.pages.add(event=_az.pack(_p.FundsDeposited(amount=40)))
    host.project(book)
    query = LedgerQueryServicer(host.ledger)
    view = query.GetPlayerBalance(_l.GetPlayerBalanceRequest(player_root=ALICE), None)
    assert (view.found, view.player.bankroll, view.available) == (True, 40, 40)
    ledger = query.GetLedger(_l.GetLedgerRequest(), None)
    assert (ledger.totals.deposits, ledger.totals.bankrolls, ledger.balanced) == (
        40,
        40,
        True,
    )


def test_undo_retracts_only_the_named_recording(router):
    host = player_main.build_host(router)
    prior = registered(
        _p.RoundResultRecorded(table_root=TABLE, round=1, wager=20, net=20),
        _p.RoundResultRecorded(table_root=TABLE, round=2, wager=20, net=-20),
    )
    command_type = "io.angzarr.examples.v1.RecordRoundResult"
    response = host.handle(compensation_envelope(command_type, prior, (2,)))
    (page,) = response.events.pages
    assert unpack(page.event, _p.RoundResultRetracted).round == 1
    response = host.handle(compensation_envelope(command_type, prior, (1,)))
    assert response == _ch.BusinessResponse()


def test_process_state_replays_from_its_snapshot(router):
    host = buy_in_main.build_host(router)
    snapshot_state = _b.BuyInState(buy_in_id=H1, amount=500)
    book = _t.EventBook(
        snapshot=_t.Snapshot(sequence=0, state=_az.pack(snapshot_state))
    )
    book.pages.add(event=_az.pack(_b.BuyInFundsHeld(buy_in_id=H1))).header.sequence = 1
    state = host.rebuild(book)
    assert (state.buy_in_id, state.amount) == (H1, 500)
    assert state.phase == _b.BuyInState.Phase.PHASE_AWAITING_SEAT
    assert host.rebuild(None) == _b.BuyInState()


def test_recorded_results_keep_their_page_sequence(router):
    host = player_main.build_host(router)
    state = host.rebuild(
        registered(_p.RoundResultRecorded(table_root=TABLE, round=1, wager=20, net=20))
    )
    (result,) = state.round_results.values()
    assert result.sequence == 2
