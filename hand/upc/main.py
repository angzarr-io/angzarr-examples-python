"""Hand domain upcaster gRPC server.

Uses class-based pattern with @upcaster decorator.
Passthrough upcaster - no transformations yet.
Add @upcasts decorated methods when schema evolution is needed.

Example transformation (when needed):
    @upcasts(CardsDealtV1, CardsDealt)
    def upcast_cards_dealt(self, old: CardsDealtV1) -> CardsDealt:
        return CardsDealt(
            table_root=old.table_root,
            hand_number=old.hand_number,
            game_variant=GameVariant.TEXAS_HOLDEM,  # New field with default
            ...
        )
"""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "angzarr"))

from angzarr_client import Router, UpcasterGrpc, run_server, upcaster
from angzarr_client.proto.angzarr.v1 import upcaster_pb2_grpc

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


@upcaster(name="upcaster-hand", domain="hand")
class HandUpcaster:
    """Hand domain upcaster.

    Add @upcasts decorated methods here when schema evolution is needed.
    Events without matching handlers pass through unchanged.
    """

    # Example (uncomment when needed):
    # @upcasts(CardsDealtV1, CardsDealt)
    # def upcast_cards_dealt(self, old: CardsDealtV1) -> CardsDealt:
    #     return CardsDealt(...)
    pass


router = (
    Router("upcaster-hand").with_handler(HandUpcaster, lambda: HandUpcaster()).build()
)
servicer = UpcasterGrpc(router)


if __name__ == "__main__":
    run_server(
        upcaster_pb2_grpc.add_UpcasterServiceServicer_to_server,
        servicer,
        service_name="upcaster-hand",
        domain="hand",
        default_port="50421",
        logger=logger,
    )
