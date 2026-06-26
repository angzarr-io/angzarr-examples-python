"""Player aggregate service entrypoint."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server
from angzarr_poker._runtime.servicers import CommandHandlerServicer

from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.player_aggregate_angzarr import (
    register_player_aggregate,
)
from angzarr_poker.player.aggregate.handler import PlayerAggregate

DOMAIN = "player"
DEFAULT_PORT = "50401"


def build_router() -> _az.Router:
    """An FFI router with the PlayerAggregate registered. Caller owns close()."""
    router = _az.Router()
    register_player_aggregate(router, PlayerAggregate())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
            CommandHandlerServicer(router),
            service_name="player-agg",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
