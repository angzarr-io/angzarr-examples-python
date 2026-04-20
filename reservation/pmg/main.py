"""Reservation PM gRPC server.

Runs the consolidated reservation process manager. Subscribes to events
from reservation/table/tournament topics and fans out commands to
player/reservation/table/tournament targets.

``QUERY_ENDPOINT`` points at the coordinator's sync-query port. It's used
to fetch tournament state (for entry fee / rebuy cost lookup) and table
state (for seat / capacity validation) synchronously before issuing
downstream commands.
"""

import os

import structlog

from angzarr_client import ProcessManagerGrpc, QueryClient, Router, run_server
from angzarr_client.proto.angzarr import process_manager_pb2_grpc
from handlers import ReservationPM

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


def _build_query_client() -> QueryClient | None:
    endpoint = os.environ.get("QUERY_ENDPOINT")
    if not endpoint:
        return None
    return QueryClient.connect(endpoint)


if __name__ == "__main__":
    query_client = _build_query_client()
    router = (
        Router("pmg-reservation")
        .with_handler(ReservationPM, lambda: ReservationPM(query_client=query_client))
        .build()
    )
    servicer = ProcessManagerGrpc(router)
    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="pmg-reservation",
        domain="pmg-reservation",
        default_port="50395",
        logger=logger,
    )
