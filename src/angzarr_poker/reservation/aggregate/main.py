"""Reservation aggregate service entrypoint."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server
from angzarr_poker._runtime.servicers import CommandHandlerServicer

from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.reservation_aggregate_angzarr import (
    register_reservation_aggregate,
)
from angzarr_poker.reservation.aggregate.handler import ReservationAggregate

DOMAIN = "reservation"
DEFAULT_PORT = "50405"


def build_router() -> _az.Router:
    """An FFI router with the ReservationAggregate registered. Caller owns close()."""
    router = _az.Router()
    register_reservation_aggregate(router, ReservationAggregate())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
            CommandHandlerServicer(router),
            service_name="reservation-agg",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
