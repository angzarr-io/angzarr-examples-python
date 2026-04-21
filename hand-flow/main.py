"""Hand flow process manager gRPC service.

Orchestrates the flow of poker hands by wrapping the procedural
``HandProcessManager`` from ``hand_process.py`` behind a decorator-style
process-manager class compatible with the unified Router API.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hand_process import HandProcessManager

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
from angzarr_client.proto.angzarr import types_pb2 as types
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
class HandFlowState:
    """Minimal PM state placeholder — the hand flow retains its internal
    state in the module-level ``HandProcessManager`` instance."""


def _single_command_response(
    cmd: Optional[types.CommandBook],
) -> ProcessManagerResponse:
    if cmd is None:
        return ProcessManagerResponse()
    return ProcessManagerResponse(commands=[cmd])


@process_manager(
    name="hand-flow",
    pm_domain="hand-flow",
    sources=["table", "hand"],
    targets=["hand", "table"],
    state=HandFlowState,
)
class HandFlowPM:
    """Hand-flow process manager delegating to :class:`HandProcessManager`."""

    def __init__(self) -> None:
        self._manager = HandProcessManager(
            command_sender=self._log_command,
            timeout_handler=self._handle_timeout,
        )

    def _log_command(self, cmd_book: types.CommandBook) -> None:
        logger.info(
            "command_would_send",
            domain=cmd_book.cover.domain,
        )

    def _handle_timeout(self, hand_id: bytes, player_position: int) -> None:
        logger.info("action_timeout", position=player_position)

    def _correlation_key(self, event_any_unused: object) -> str:
        # The unified Router API does not surface the source cover / correlation
        # ID to handlers. We fall back to using hand_root + hand_number as key
        # (matches ``HandProcessManager.start_hand`` default).
        return ""

    @handles(table.HandStarted)
    def on_hand_started(
        self,
        event: table.HandStarted,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        self._manager.start_hand(event, event.hand_root, correlation_id="")
        return ProcessManagerResponse()

    @handles(hand.CardsDealt)
    def on_cards_dealt(
        self,
        event: hand.CardsDealt,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        key = (
            f"{event.hand_root.hex()}_{event.hand_number}"
            if hasattr(event, "hand_root")
            else ""
        )
        cmd = self._manager.handle_cards_dealt(key, event)
        return _single_command_response(cmd)

    @handles(hand.BlindPosted)
    def on_blind_posted(
        self,
        event: hand.BlindPosted,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        cmd = self._manager.handle_blind_posted("", event)
        return _single_command_response(cmd)

    @handles(hand.ActionTaken)
    def on_action_taken(
        self,
        event: hand.ActionTaken,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        cmd = self._manager.handle_action_taken("", event)
        return _single_command_response(cmd)

    @handles(hand.BettingRoundComplete)
    def on_betting_round_complete(
        self,
        event: hand.BettingRoundComplete,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        cmd = self._manager.handle_betting_round_complete("", event)
        return _single_command_response(cmd)

    @handles(hand.CommunityCardsDealt)
    def on_community_cards_dealt(
        self,
        event: hand.CommunityCardsDealt,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        cmd = self._manager.handle_community_cards_dealt("", event)
        return _single_command_response(cmd)

    @handles(hand.ShowdownStarted)
    def on_showdown_started(
        self,
        event: hand.ShowdownStarted,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        cmd = self._manager.handle_showdown_started("", event)
        return _single_command_response(cmd)

    @handles(hand.PotAwarded)
    def on_pot_awarded(
        self,
        event: hand.PotAwarded,
        state: HandFlowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        self._manager.handle_pot_awarded("", event)
        return ProcessManagerResponse()


def main():
    """Run the hand flow process manager gRPC service."""
    router = Router("hand-flow").with_handler(HandFlowPM, lambda: HandFlowPM()).build()
    servicer = ProcessManagerGrpc(router)

    logger.info(
        "hand_flow_pm_starting",
        subscriptions=["table", "hand"],
    )

    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="hand-flow",
        domain="hand-flow",
        default_port="50391",
        logger=logger,
    )


if __name__ == "__main__":
    main()
