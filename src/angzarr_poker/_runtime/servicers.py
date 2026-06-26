"""Shared gRPC servicer adapters over the FFI Router dispatch methods.

Each angzarr component coordinator (aggregate / saga / process-manager /
projector) calls the matching framework gRPC service on the business process;
these thin servicers translate that call into the in-process FFI
``Router.dispatch*`` and surface a business ``CodedError`` as its carried gRPC
status.

The saga and process-manager coordinators bind SubscriberAll (every event), so a
per-component service routinely receives events whose source domain no registered
component consumes. That is not a failure: the servicer ACK-skips them with an
empty response (returning UNIMPLEMENTED would NACK + requeue forever and starve
the events it does handle).
"""

from __future__ import annotations

import grpc

import angzarr_router_ffi as _az
from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2_grpc
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2_grpc
from angzarr_poker._gen.io.angzarr.v1 import projector_pb2_grpc
from angzarr_poker._gen.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_poker._gen.io.angzarr.v1 import saga_pb2_grpc

_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}
_UNIMPLEMENTED = grpc.StatusCode.UNIMPLEMENTED.value[0]


def grpc_status(code: int) -> grpc.StatusCode:
    """Map a framework GrpcCode integer to a grpc.StatusCode (INTERNAL default)."""
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


class CommandHandlerServicer(command_handler_pb2_grpc.CommandHandlerServiceServicer):
    """Aggregate command port. ``Handle``/``HandleSync`` run one
    ``ContextualCommand`` through ``Router.dispatch``."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def HandleSync(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def _dispatch(self, request, context):
        try:
            return self._router.dispatch(request)
        except _az.CodedError as exc:
            context.abort(grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


class SagaServicer(saga_pb2_grpc.SagaServiceServicer):
    """Saga port. ``Handle`` runs one ``SagaHandleRequest`` through
    ``Router.dispatch_saga``; ACK-skips events with no registered saga."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        try:
            return self._router.dispatch_saga(request)
        except _az.CodedError as exc:
            if exc.grpc == _UNIMPLEMENTED:
                return _saga.SagaResponse()
            context.abort(grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


class ProcessManagerServicer(process_manager_pb2_grpc.ProcessManagerServiceServicer):
    """Process-manager port. ``Handle`` runs one ``ProcessManagerHandleRequest``
    through ``Router.dispatch_process_manager``; ACK-skips unconsumed triggers."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        try:
            return self._router.dispatch_process_manager(request)
        except _az.CodedError as exc:
            if exc.grpc == _UNIMPLEMENTED:
                return _pm.ProcessManagerHandleResponse()
            context.abort(grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


class ProjectorServicer(projector_pb2_grpc.ProjectorServiceServicer):
    """Projector port. ``Handle``/``HandleSpeculative`` fold one ``EventBook``
    through ``Router.dispatch_projector``."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def HandleSpeculative(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def _dispatch(self, request, context):
        try:
            return self._router.dispatch_projector(request)
        except _az.CodedError as exc:
            context.abort(grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
