"""Hand bounded context gRPC server.

Uses the unified Router API with the @command_handler class decorator.
"""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "angzarr"))

from angzarr_client import (
    CommandHandlerGrpc,
    Router,
    configure_logging,
    run_server,
)
from angzarr_client.proto.angzarr import command_handler_pb2_grpc

from .handlers import Hand

router = Router("hand").with_handler(Hand()).build()


if __name__ == "__main__":
    configure_logging()
    logger = structlog.get_logger()
    servicer = CommandHandlerGrpc(router)
    run_server(
        command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
        servicer,
        service_name="hand-agg",
        domain="hand",
        default_port="50403",
        logger=logger,
    )
