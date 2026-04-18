"""Player domain upcaster gRPC server.

Uses class-based pattern with @upcaster decorator.
Passthrough upcaster - no transformations yet.
Add @upcasts methods when schema evolution is needed.

Example transformation (when needed):
    @upcasts(PlayerRegisteredV1, PlayerRegistered)
    def upcast_registered(self, old: PlayerRegisteredV1) -> PlayerRegistered:
        return PlayerRegistered(
            display_name=old.display_name,
            email=old.email,
            player_type=old.player_type,
            ai_model_id="",  # New field with default
            registered_at=timestamp_pb2.Timestamp(),
        )
"""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "angzarr"))

from angzarr_client import Router, UpcasterGrpc, run_server, upcaster
from angzarr_client.proto.angzarr import upcaster_pb2_grpc

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


@upcaster(name="upcaster-player", domain="player")
class PlayerUpcaster:
    """Player domain upcaster.

    Add @upcasts decorated methods here when schema evolution is needed.
    Events without matching handlers pass through unchanged.
    """

    # Example (uncomment when needed):
    # @upcasts(PlayerRegisteredV1, PlayerRegistered)
    # def upcast_registered(self, old: PlayerRegisteredV1) -> PlayerRegistered:
    #     return PlayerRegistered(...)
    pass


router = Router("upcaster-player").with_handler(PlayerUpcaster()).build()
servicer = UpcasterGrpc(router)


if __name__ == "__main__":
    run_server(
        upcaster_pb2_grpc.add_UpcasterServiceServicer_to_server,
        servicer,
        service_name="upcaster-player",
        domain="player",
        default_port="50411",
        logger=logger,
    )
