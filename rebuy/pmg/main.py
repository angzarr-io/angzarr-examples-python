"""Rebuy process manager gRPC server.

This module runs the rebuy PM that coordinates Player <-> Tournament <-> Table rebuys.
"""

import structlog

from angzarr_client import ProcessManagerGrpc, Router, run_server
from angzarr_client.proto.angzarr import process_manager_pb2_grpc
from handlers import RebuyPM

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


if __name__ == "__main__":
    router = Router("pmg-rebuy").with_handler(RebuyPM()).build()
    servicer = ProcessManagerGrpc(router)
    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="pmg-rebuy",
        domain="rebuy",
        default_port="50393",
        logger=logger,
    )
