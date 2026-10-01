"""The components through the router binding (commands, undo, facts,
Replay, process-manager compensation) and served by angzarr-client's
ComponentHost over gRPC."""

import angzarr_client.router as _az
import grpc
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.inprocess import InProcess
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.player.agg import main as player_main
from angzarr_blackjack.player.agg.logic import NO_MATCHING_HOLD
from angzarr_blackjack.pmg_buy_in import main as buy_in_main

ALICE, TABLE, H1 = b"\x0a" * 16, b"\x01" * 16, b"\x11" * 16


@pytest.fixture
def components():
    c = InProcess()
    yield c
    c.close()


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


def test_commands_go_through_the_router(components):
    host = components
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


def test_compensate_is_routed_to_the_undo_handler(components):
    host = components
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


def test_compensate_with_nothing_to_undo_answers_empty(components):
    host = components
    response = host.handle(
        compensation_envelope("io.angzarr.examples.v1.RecordRoundResult", registered())
    )
    assert response == _ch.BusinessResponse()


def test_compensate_without_an_undo_handler_is_unimplemented(components):
    host = components
    with pytest.raises(_az.CodedError) as info:
        host.handle(
            compensation_envelope("io.angzarr.examples.v1.DepositFunds", registered())
        )
    assert (info.value.code, info.value.grpc) == (
        "NO_UNDO_HANDLER",
        _az.GrpcCode.UNIMPLEMENTED,
    )


def test_facts_are_checked_against_the_rebuilt_wallet(components):
    host = components
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


def test_replay_returns_the_state_after_the_events(components):
    host = components
    book = registered(_p.FundsWithdrawn(amount=100))
    snapshot = _t.Snapshot(
        sequence=0,
        state=_az.pack(
            _p.PlayerState(registered=True, bankroll=50, total_deposited=50)
        ),
    )
    response = host.router.dispatch_replay(
        "player", _ch.ReplayRequest(base_snapshot=snapshot, events=list(book.pages)[1:])
    )
    state = unpack(response.state, _p.PlayerState)
    assert (state.bankroll, state.total_deposited, state.total_withdrawn) == (
        950,
        1050,
        100,
    )
    assert (
        unpack(
            host.router.dispatch_replay("player", _ch.ReplayRequest()).state,
            _p.PlayerState,
        )
        == _p.PlayerState()
    )


def test_pm_compensation_keeps_its_commands(components):
    host = components
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
    response = host.handle_process(
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
        host.handle_process(
            _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=state)
        )
        == _pm.ProcessManagerHandleResponse()
    )


def test_pm_triggers_go_through_the_router(components):
    host = components
    trigger = _t.EventBook(
        cover=_t.Cover(domain="table", root=_t.UUID(value=TABLE), correlation_id="C")
    )
    trigger.pages.add(
        event=_az.pack(
            _table.SeatHeld(buy_in_id=H1, player_root=ALICE, seat=0, amount=500)
        )
    )
    response = host.handle_process(
        _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=_t.EventBook())
    )
    started = unpack(response.process_events[0].pages[0].event, _b.BuyInStarted)
    assert started.table_root == TABLE


def test_ledger_query_service_reads_the_ledger(components):
    from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
    from angzarr_blackjack.prj_ledger.query import LedgerQueryServicer

    host = components
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


def test_undo_retracts_only_the_named_recording(components):
    host = components
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


def test_process_state_replays_from_its_snapshot(components):
    host = components
    snapshot_state = _b.BuyInState(buy_in_id=H1, amount=500)
    book = _t.EventBook(
        snapshot=_t.Snapshot(sequence=0, state=_az.pack(snapshot_state))
    )
    book.pages.add(event=_az.pack(_b.BuyInFundsHeld(buy_in_id=H1))).header.sequence = 1
    state = host.rebuild("buy-in", book)
    assert (state.buy_in_id, state.amount) == (H1, 500)
    assert state.phase == _b.BuyInState.Phase.PHASE_AWAITING_SEAT
    assert host.rebuild("buy-in", None) == _b.BuyInState()


def test_recorded_results_keep_their_page_sequence(components):
    host = components
    state = host.rebuild(
        "player",
        registered(_p.RoundResultRecorded(table_root=TABLE, round=1, wager=20, net=20)),
    )
    (result,) = state.round_results.values()
    assert result.sequence == 2


# --- the components served over gRPC -----------------------------------------------------


def _error_code(error: grpc.RpcError) -> str:
    """The angzarr error code a failed call carries in its status details."""
    from google.rpc import error_details_pb2, status_pb2

    for key, value in error.trailing_metadata() or ():
        if key == "grpc-status-details-bin":
            status = status_pb2.Status.FromString(value)
            for detail in status.details:
                info = error_details_pb2.ErrorInfo()
                if detail.Unpack(info):
                    return info.reason
    return ""


def test_the_player_host_serves_commands_and_reports_coded_refusals():
    from angzarr_client import ComponentHost
    from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
    from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2 as _up
    from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2_grpc as _up_grpc

    host = player_main.register(ComponentHost())
    address = host.start("127.0.0.1:0")
    try:
        with grpc.insecure_channel(address) as channel:
            stub = _ch_grpc.CommandHandlerServiceStub(channel)
            command = _t.ContextualCommand(events=registered())
            command.command.cover.CopyFrom(
                _t.Cover(domain="player", root=_t.UUID(value=ALICE))
            )
            command.command.pages.add(command=_az.pack(_p.WithdrawFunds(amount=300)))
            response = stub.Handle(command, timeout=10)
            assert (
                unpack(response.events.pages[0].event, _p.FundsWithdrawn).amount == 300
            )
            command.command.pages[0].command.CopyFrom(
                _az.pack(_p.WithdrawFunds(amount=5000))
            )
            with pytest.raises(grpc.RpcError) as info:
                stub.Handle(command, timeout=10)
            assert info.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            assert info.value.details() == "requested 5000 but only 1000 is available"
            assert _error_code(info.value) == "INSUFFICIENT_AVAILABLE_FUNDS"
            legacy = _t.EventPage(event=_az.pack(_p.FundsDepositedV1(amount_chips=3)))
            upcast = _up_grpc.UpcasterServiceStub(channel).Upcast(
                _up.UpcastRequest(domain="player", events=[legacy]), timeout=10
            )
            assert upcast.events[0].event.type_url.endswith(".FundsDeposited")
    finally:
        host.stop()


def test_every_deployable_registers_its_services():
    from angzarr_client import ComponentHost

    from angzarr_blackjack.player.saga_table import main as player_table_main
    from angzarr_blackjack.prj_ledger import main as ledger_main
    from angzarr_blackjack.prj_ledger.handler import Ledger
    from angzarr_blackjack.table.agg import main as table_main
    from angzarr_blackjack.table.saga_player import main as table_player_main

    v1 = "io.angzarr.v1."
    expected = {
        player_main: [v1 + "CommandHandlerService", v1 + "UpcasterService"],
        table_main: [v1 + "CommandHandlerService", v1 + "UpcasterService"],
        buy_in_main: [v1 + "ProcessManagerService"],
        player_table_main: [v1 + "SagaService"],
        table_player_main: [v1 + "SagaService"],
    }
    for main, services in expected.items():
        host = main.register(ComponentHost())
        try:
            assert host.services == services, main.__name__
        finally:
            host.stop()
    host = ledger_main.register(ComponentHost(), Ledger())
    try:
        assert host.services == [
            v1 + "ProjectorService",
            "io.angzarr.examples.v1.LedgerQueryService",
        ]
    finally:
        host.stop()
