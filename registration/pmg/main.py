"""Registration process manager gRPC server.

This module runs the registration PM that coordinates Player <-> Tournament registrations.
"""

import structlog

from angzarr_client import ProcessManagerGrpc, Router, run_server
from angzarr_client.proto.angzarr import process_manager_pb2_grpc
from handlers import RegistrationPM

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
    router = Router("pmg-registration").with_handler(RegistrationPM()).build()
    servicer = ProcessManagerGrpc(router)
    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="pmg-registration",
        domain="registration",
        default_port="50394",
        logger=logger,
    )
