"""HandFlowProcessManager service entrypoint.

Per-component process-manager service: the angzarr PM coordinator (bound
SubscriberAll) calls ProcessManagerService.Handle; the servicer routes through
Router.dispatch_process_manager to the one registered PM and ACK-skips triggers
it does not consume.
"""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server
from angzarr_poker._runtime.servicers import ProcessManagerServicer

from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.hand_flow_process_manager_angzarr import (
    register_hand_flow_process_manager,
)
from angzarr_poker.hand.process_managers.hand_flow.handler import HandFlowProcessManager

DOMAIN = "hand"
DEFAULT_PORT = "50395"


def build_router() -> _az.Router:
    """An FFI router with the HandFlowProcessManager registered. Caller owns close()."""
    router = _az.Router()
    register_hand_flow_process_manager(router, HandFlowProcessManager())
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
