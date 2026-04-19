"""Hand Flow Process Manager - OO Pattern (unified Router).

This PM coordinates the workflow between table and hand domains using
the decorator-based Router pattern.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from google.protobuf.any_pb2 import Any as ProtoAny

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


# region pm_state_oo
class HandPhase(Enum):
    AWAITING_DEAL = "awaiting_deal"
    DEALING = "dealing"
    BLINDS = "blinds"
    BETTING = "betting"
    COMPLETE = "complete"


@dataclass
class HandFlowState:
    """PM state - tracks workflow progress."""

    hand_id: str = ""
    phase: HandPhase = HandPhase.AWAITING_DEAL
    player_count: int = 0


# endregion


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(domain: str, cmd, sequence: int = 0) -> types.CommandBook:
    return types.CommandBook(
        cover=types.Cover(domain=domain),
        pages=[
            types.CommandPage(
                header=types.PageHeader(sequence=sequence),
                command=_pack(cmd),
            )
        ],
    )


# region pm_handler_oo
@process_manager(
    name="pmg-hand-flow",
    pm_domain="hand-flow",
    sources=["table", "hand"],
    targets=["hand", "table"],
    state=HandFlowState,
)
class HandFlowPM:
    """OO-style process manager using unified Router decorators."""

    @handles(table.HandStarted)
    def on_hand_started(
        self,
        event: table.HandStarted,
        state: HandFlowState,
        destinations: Destinations,
    ) -> Optional[ProcessManagerResponse]:
        """Table started a hand -> send DealCards to hand domain."""
        state.hand_id = event.hand_id
        state.phase = HandPhase.DEALING
        state.player_count = event.player_count

        deal_cards = hand.DealCards(
            hand_id=event.hand_id,
            player_count=event.player_count,
        )
        seq = destinations.sequence_for("hand") if destinations else 0
        return ProcessManagerResponse(
            commands=[_command_book("hand", deal_cards, seq or 0)]
        )

    @handles(hand.CardsDealt)
    def handle_cards_dealt(
        self,
        event: hand.CardsDealt,
        state: HandFlowState,
        destinations: Destinations,
    ) -> Optional[ProcessManagerResponse]:
        """Cards dealt -> post blinds."""
        state.phase = HandPhase.BLINDS
        post_blinds = hand.PostBlinds(hand_id=state.hand_id)
        seq = destinations.sequence_for("hand") if destinations else 0
        return ProcessManagerResponse(
            commands=[_command_book("hand", post_blinds, seq or 0)]
        )

    @handles(hand.HandComplete)
    def handle_hand_complete(
        self,
        event: hand.HandComplete,
        state: HandFlowState,
        destinations: Destinations,
    ) -> Optional[ProcessManagerResponse]:
        """Hand complete -> end hand on table."""
        state.phase = HandPhase.COMPLETE
        end_hand = table.EndHand(
            hand_id=state.hand_id,
            winner_id=event.winner_id,
        )
        seq = destinations.sequence_for("table") if destinations else 0
        return ProcessManagerResponse(
            commands=[_command_book("table", end_hand, seq or 0)]
        )


# endregion


if __name__ == "__main__":
    router = Router("pmg-hand-flow").with_handler(HandFlowPM()).build()
    servicer = ProcessManagerGrpc(router)
    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="pmg-hand-flow",
        domain="hand-flow",
        default_port="50396",
    )
