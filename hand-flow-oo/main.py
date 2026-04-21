"""Hand flow process manager gRPC service (OO Pattern, unified Router).

Minimal declarative PM skeleton showing the new ``@process_manager`` /
``@handles`` / ``Router`` pattern with a placeholder state.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from angzarr_client import (
    Destinations,
    ProcessManagerGrpc,
    ProcessManagerResponse,
    Router,
    handles,
    process_manager,
    run_server,
)
from angzarr_client.proto.angzarr import process_manager_pb2_grpc
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table

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


@dataclass
class PMState:
    """PM's aggregate state (rebuilt from its own events)."""

    hand_root: Optional[bytes] = None
    hand_in_progress: bool = False


@process_manager(
    name="hand-flow",
    pm_domain="hand-flow",
    sources=["table", "hand"],
    targets=["hand", "table"],
    state=PMState,
)
class HandFlowPM:
    """Hand Flow Process Manager using unified Router decorators."""

    @handles(table.HandStarted)
    def handle_hand_started(
        self,
        event: table.HandStarted,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()

    @handles(hand.CardsDealt)
    def handle_cards_dealt(
        self,
        event: hand.CardsDealt,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()

    @handles(hand.BlindPosted)
    def handle_blind_posted(
        self,
        event: hand.BlindPosted,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()

    @handles(hand.ActionTaken)
    def handle_action_taken(
        self,
        event: hand.ActionTaken,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()

    @handles(hand.CommunityCardsDealt)
    def handle_community_dealt(
        self,
        event: hand.CommunityCardsDealt,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()

    @handles(hand.PotAwarded)
    def handle_pot_awarded(
        self,
        event: hand.PotAwarded,
        state: PMState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        return ProcessManagerResponse()


def main():
    """Run the hand flow process manager gRPC service."""
    router = Router("hand-flow").with_handler(HandFlowPM, lambda: HandFlowPM()).build()
    servicer = ProcessManagerGrpc(router)

    logger.info(
        "hand_flow_pm_starting",
        pattern="OO",
        subscriptions=["table", "hand"],
    )

    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="hand-flow",
        domain="hand-flow",
        default_port="50395",
        logger=logger,
    )


if __name__ == "__main__":
    main()
