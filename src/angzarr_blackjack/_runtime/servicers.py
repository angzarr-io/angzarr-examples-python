"""gRPC adapters from the framework services onto the component hosts.

Each angzarr coordinator calls its framework service on the component process;
these translate the call into the host (and through it the router) and report
a coded rejection as its gRPC status, message ``"CODE: message"``.

Saga and process-manager coordinators deliver every event of their source
domains, so a component routinely receives events it does not consume. That is
not a failure: the servicer acknowledges them with an empty response
(UNIMPLEMENTED would be retried forever and starve the events it does handle).
"""

from __future__ import annotations

from collections.abc import Callable

import grpc

import angzarr_client.router as _az
from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2_grpc as _pm_grpc
from angzarr_client.proto.io.angzarr.v1 import projector_pb2_grpc as _prj_grpc
from angzarr_client.proto.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_client.proto.io.angzarr.v1 import saga_pb2_grpc as _saga_grpc
from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2 as _up
from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2_grpc as _up_grpc
from angzarr_blackjack._runtime.hosts import AggregateHost, ProcessManagerHost
from angzarr_blackjack.errors import status_message

_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}
_UNIMPLEMENTED = grpc.StatusCode.UNIMPLEMENTED.value[0]


def grpc_status(code: int) -> grpc.StatusCode:
    """Map a framework GrpcCode integer to a grpc.StatusCode (INTERNAL default)."""
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


def _call(context, fn: Callable, request, *, ack_unconsumed=None):
    try:
        return fn(request)
    except _az.CodedError as exc:
        if ack_unconsumed is not None and exc.grpc == _UNIMPLEMENTED:
            return ack_unconsumed()
        context.abort(grpc_status(exc.grpc), status_message(exc))
    except Exception as exc:  # noqa: BLE001 — last-resort guard at the transport edge
        context.abort(grpc.StatusCode.INTERNAL, str(exc))


class CommandHandlerServicer(_ch_grpc.CommandHandlerServiceServicer):
    """``CommandHandlerService`` for one aggregate."""

    def __init__(self, host: AggregateHost) -> None:
        self._host = host

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        return _call(context, self._host.handle, request)

    def HandleFact(self, request, context):  # noqa: N802
        return _call(context, self._host.handle_fact, request)

    def Replay(self, request, context):  # noqa: N802
        return _call(context, self._host.replay, request)


class PassThroughUpcaster:
    """The upcaster of a domain with no legacy event shapes: events come back
    unchanged."""

    def upcast(self, request: _up.UpcastRequest) -> _up.UpcastResponse:
        return _up.UpcastResponse(events=request.events)


class UpcasterServicer(_up_grpc.UpcasterServiceServicer):
    """``UpcasterService`` over an upcaster with an ``upcast(request)`` method."""

    def __init__(self, upcaster) -> None:
        self._upcaster = upcaster

    def Upcast(self, request, context):  # noqa: N802
        return _call(context, self._upcaster.upcast, request)


class SagaServicer(_saga_grpc.SagaServiceServicer):
    """``SagaService`` over every saga registered on the router."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802
        return _call(
            context,
            self._router.dispatch_saga,
            request,
            ack_unconsumed=_saga.SagaResponse,
        )


class ProcessManagerServicer(_pm_grpc.ProcessManagerServiceServicer):
    """``ProcessManagerService`` for one process manager."""

    def __init__(self, host: ProcessManagerHost) -> None:
        self._host = host

    def Handle(self, request, context):  # noqa: N802
        return _call(
            context,
            self._host.handle,
            request,
            ack_unconsumed=_pm.ProcessManagerHandleResponse,
        )


class ProjectorServicer(_prj_grpc.ProjectorServiceServicer):
    """``ProjectorService`` over a projector host with a ``project(book)`` method."""

    def __init__(self, host) -> None:
        self._host = host

    def Handle(self, request, context):  # noqa: N802
        return _call(context, self._host.project, request)

    def HandleSpeculative(self, request, context):  # noqa: N802
        return _call(context, self._host.speculate, request)
