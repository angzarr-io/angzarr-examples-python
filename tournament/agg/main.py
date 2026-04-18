"""Tournament bounded context gRPC server.

Uses the unified Router API with the @command_handler class decorator.
"""

import structlog

from angzarr_client import (
    CommandHandlerGrpc,
    Router,
    configure_logging,
    run_server,
)
from angzarr_client.proto.angzarr import command_handler_pb2_grpc

from .handlers import Tournament


router = Router("tournament").with_handler(Tournament()).build()


if __name__ == "__main__":
    configure_logging()
    logger = structlog.get_logger()
    servicer = CommandHandlerGrpc(router)
    run_server(
        command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
        servicer,
        service_name="tournament-agg",
        domain="tournament",
        default_port="50304",
        logger=logger,
    )
