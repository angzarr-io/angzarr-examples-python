"""The table through the router binding (commands, their post-command
state) and served by
angzarr-client's ComponentHost over gRPC."""

import angzarr_client.router as _az
import grpc
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.inprocess import InProcess
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.cards import shuffle
from angzarr_blackjack.table.agg import main as table_main

TABLE = b"\x01" * 16
CONFIG = dict(
    seats=3, decks=1, min_bet=10, max_bet=100, min_buy_in=100, max_buy_in=1000
)


@pytest.fixture
def components():
    c = InProcess()
    yield c
    c.close()


def history(*events) -> _t.EventBook:
    book = _t.EventBook(cover=_t.Cover(domain="table", root=_t.UUID(value=TABLE)))
    for sequence, event in enumerate(events):
        book.pages.add(payload=_az.pack(event)).sequence = sequence
    return book


def create_command(prior: _t.EventBook) -> _t.ContextualCommand:
    command = _t.ContextualCommand(events=prior)
    command.command.cover.CopyFrom(prior.cover)
    command.command.page.command.payload.CopyFrom(
        _az.pack(_table.CreateTable(name="Main", shoe_seed=42, **CONFIG))
    )
    return command


def test_commands_go_through_the_router(components):
    response = components.handle(create_command(history()))
    created, shoe = response.events.pages
    assert unpack(created.payload, _table.TableCreated).name == "Main"
    assert list(unpack(shoe.payload, _table.ShoeShuffled).cards) == shuffle(42, 1)
    with pytest.raises(_az.CodedError) as info:
        components.handle(
            create_command(history(_table.TableCreated(name="Main", **CONFIG)))
        )
    assert info.value.code == "TABLE_ALREADY_EXISTS"


def test_every_response_carries_the_state_after_the_command(components):
    state = unpack(
        components.handle(create_command(history())).events.snapshot.state,
        _table.TableState,
    )
    assert (state.name, state.phase, state.shoe_seed, list(state.shoe)) == (
        "Main",
        _table.TableState.Phase.PHASE_IDLE,
        42,
        shuffle(42, 1),
    )


def test_a_command_outside_the_slice_fails_loudly(components):
    """Seats, bets and rounds wait on the blackjack rulings: the table has no
    handler for them, and the router reports that as an internal failure,
    never as a business answer."""
    command = create_command(history(_table.TableCreated(name="Main", **CONFIG)))
    command.command.page.command.payload.CopyFrom(
        _az.pack(_table.RequestSeat(seat=0, amount=100))
    )
    with pytest.raises(_az.CodedError) as info:
        components.handle(command)
    assert info.value.grpc == _az.GrpcCode.INTERNAL


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


def test_the_table_host_serves_commands_and_reports_coded_refusals():
    from angzarr_client import ComponentHost
    from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc

    # A version of the test's own, so this test does not depend on the
    # generated build version (the next test covers that).
    host = table_main.register(ComponentHost(rules_version="0.0.0+test"))
    address = host.start("127.0.0.1:0")
    try:
        with grpc.insecure_channel(address) as channel:
            stub = _ch_grpc.CommandHandlerServiceStub(channel)
            response = stub.Handle(create_command(history()), timeout=10)
            assert (
                unpack(response.events.pages[0].payload, _table.TableCreated).name
                == "Main"
            )
            prior = history(_table.TableCreated(name="Main", **CONFIG))
            with pytest.raises(grpc.RpcError) as info:
                stub.Handle(create_command(prior), timeout=10)
            assert info.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            assert info.value.details() == "the table already exists"
            assert _error_code(info.value) == "TABLE_ALREADY_EXISTS"
    finally:
        host.stop()


def test_the_deployable_host_reports_the_generated_build_version():
    from angzarr_client.proto.io.angzarr.v1 import component_pb2 as _component
    from angzarr_client.proto.io.angzarr.v1 import component_pb2_grpc as _c_grpc

    from angzarr_blackjack._version import __version__

    # main()'s host starts (no MISSING_RULES_VERSION) and describes its
    # component with the version versionator generated at build.
    assert __version__
    host = table_main.host()
    address = host.start("127.0.0.1:0")
    try:
        with grpc.insecure_channel(address) as channel:
            descriptor = _c_grpc.ComponentServiceStub(channel).Describe(
                _component.DescribeRequest(), timeout=10
            )
        assert descriptor.rules_version == __version__
    finally:
        host.stop()


def test_every_deployable_registers_its_services():
    from angzarr_client import ComponentHost

    v1 = "io.angzarr.v1."
    host = table_main.register(ComponentHost())
    try:
        assert host.services == [
            v1 + "ComponentService",
            v1 + "CommandHandlerService",
            v1 + "UpcasterService",
        ]
    finally:
        host.stop()
