"""Reservation bounded context gRPC server.

The reservation aggregate owns lifecycle records for buy-in / rebuy /
tournament-registration flows. ``Initiate*`` handlers do sync DECISION
queries against the player aggregate via ``QueryClient``; the address
comes from ``QUERY_ENDPOINT`` (typically the local angzarr sidecar's
event-query port).
"""

import os

import structlog

from angzarr_client import (
    CommandHandlerGrpc,
    QueryClient,
    Router,
    configure_logging,
    run_server,
)
from angzarr_client.proto.angzarr.v1 import command_handler_pb2_grpc

from .handlers import Reservation


def _build_query_client() -> QueryClient | None:
    """Connect to the coordinator for sync DECISION reads."""
    endpoint = os.environ.get("QUERY_ENDPOINT")
    if not endpoint:
        return None
    return QueryClient.connect(endpoint)


if __name__ == "__main__":
    configure_logging()
    logger = structlog.get_logger()
    query_client = _build_query_client()
    router = (
        Router("reservation")
        .with_handler(Reservation, lambda: Reservation(query_client=query_client))
        .build()
    )
    servicer = CommandHandlerGrpc(router)
    run_server(
        command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
        servicer,
        service_name="reservation-agg",
        domain="reservation",
        default_port="50305",
        logger=logger,
    )
