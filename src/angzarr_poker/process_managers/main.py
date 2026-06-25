"""Process-manager service entrypoint (hosts every poker process manager).

Transport model: the angzarr **process-manager coordinator** subscribes to the
bus, rebuilds the PM's event-sourced state, and calls this service's
``ProcessManagerService.Handle`` with a ``ProcessManagerHandleRequest`` (the
trigger event book + prior process state + destination sequences). The servicer
hands it to the in-process FFI ``Router.dispatch_process_manager``, which folds
the prior state, runs the matching Python business logic, and returns a
``ProcessManagerHandleResponse`` (own process-events + emitted commands). The
coordinator persists the process-events and forwards the commands.

One service hosts both poker PMs — HandFlowProcessManager (hand-lifecycle) and
ReservationProcessManager (buy-in / rebuy / registration). The core routes a
trigger to every co-resident PM that consumes its domain, so a single registry
serves the hand, table, tournament, and reservation PM coordinators.
"""

from __future__ import annotations

import grpc
import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server

from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.hand_flow_process_manager_angzarr import (
    register_hand_flow_process_manager,
)
from angzarr_poker._gen.io.angzarr.examples.v1.reservation_process_manager_angzarr import (
    register_reservation_process_manager,
)
from angzarr_poker.process_managers.hand_flow import HandFlowProcessManager
from angzarr_poker.process_managers.reservation import ReservationProcessManager

DOMAIN = "hand"
DEFAULT_PORT = "50395"

_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}


def _grpc_status(code: int) -> grpc.StatusCode:
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


class ProcessManagerServicer(process_manager_pb2_grpc.ProcessManagerServiceServicer):
    """gRPC adapter over the FFI router's process-manager dispatch. ``Handle``
    runs one ``ProcessManagerHandleRequest`` through
    ``Router.dispatch_process_manager`` and translates a business ``CodedError``
    into its carried gRPC status."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        try:
            return self._router.dispatch_process_manager(request)
        except _az.CodedError as exc:
            # The PM coordinator delivers every subscribed event here; a trigger
            # whose domain no co-resident PM consumes is not a failure. ACK it
            # with an empty response rather than aborting UNIMPLEMENTED, which
            # would NACK + requeue forever and starve the triggers we handle.
            if exc.grpc == grpc.StatusCode.UNIMPLEMENTED.value[0]:
                return _pm.ProcessManagerHandleResponse()
            context.abort(_grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


def build_router() -> _az.Router:
    """An FFI router with every poker process manager registered. Caller owns close()."""
    router = _az.Router()
    register_hand_flow_process_manager(router, HandFlowProcessManager())
    register_reservation_process_manager(router, ReservationProcessManager())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
            ProcessManagerServicer(router),
            service_name="pmg-hand-flow",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
