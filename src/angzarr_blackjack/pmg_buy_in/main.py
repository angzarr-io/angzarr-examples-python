"""pmg-buy-in: the BuyInProcessManager."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1.buy_in_process_manager_angzarr import (
    new_buy_in_process_manager_dispatch,
)
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2_grpc as _pm_grpc
from angzarr_blackjack._runtime.hosts import ProcessManagerHost
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import ProcessManagerServicer
from angzarr_blackjack.pmg_buy_in.handler import BuyInProcessManager

DOMAIN = "buy-in"
DEFAULT_PORT = "50421"


def build_host(router: _az.Router) -> ProcessManagerHost:
    """The BuyInProcessManager registered on ``router``."""
    return ProcessManagerHost(
        router, new_buy_in_process_manager_dispatch(BuyInProcessManager())
    )


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        run_server(
            _pm_grpc.add_ProcessManagerServiceServicer_to_server,
            ProcessManagerServicer(build_host(router)),
            service_name="pmg-buy-in",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
        )


if __name__ == "__main__":
    main()
