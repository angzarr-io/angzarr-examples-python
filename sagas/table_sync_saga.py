"""Table Sync Saga - bridges Table and Hand domains.

Handles:
- HandStarted (from table) → DealCards (to hand)
- HandComplete (from hand) → EndHand (to table)
"""

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table

from .base import Saga, SagaContext


def _pack_command(cmd: Message, type_prefix: str = "examples") -> AnyProto:
    """Pack a command message into Any."""
    type_name = type(cmd).DESCRIPTOR.full_name
    return AnyProto(
        type_url=f"type.googleapis.com/{type_name}",
        value=cmd.SerializeToString(),
    )


def _make_command_book(domain: str, root: bytes, command: Message) -> types.CommandBook:
    """Create a CommandBook with a single command."""
    return types.CommandBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.CommandPage(
                command=_pack_command(command),
            )
        ],
    )


class TableSyncSaga(Saga):
    """Saga that synchronizes Table and Hand domains.

    Handles bidirectional communication:
    - Table → Hand: When a table starts a hand, emit DealCards
    - Hand → Table: When a hand completes, emit EndHand
    """

    @property
    def name(self) -> str:
        return "TableSyncSaga"

    @property
    def subscribed_events(self) -> list[str]:
        return ["HandStarted", "HandComplete"]

    def handle(self, context: SagaContext) -> list[types.CommandBook]:
        """Handle events and emit commands."""
        if context.event_type == "HandStarted":
            return self._handle_hand_started(context)
        elif context.event_type == "HandComplete":
            return self._handle_hand_complete(context)
        return []

    def _handle_hand_started(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate HandStarted → DealCards.

        When a table starts a new hand, we need to tell the Hand aggregate
        to deal cards to the participating players.
        """
        # Extract the event from the event book
        event = table.HandStarted()
        for page in context.event_book.pages:
            if page.HasField("event") and page.event.type_url.endswith("HandStarted"):
                page.event.Unpack(event)
                break

        # Build player list for the hand
        players = []
        for seat in event.active_players:
            players.append(
                hand.PlayerInHand(
                    player_root=seat.player_root,
                    position=seat.position,
                    stack=seat.stack,
                )
            )

        # Create DealCards command
        deal_cards = hand.DealCards(
            table_root=context.aggregate_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            players=players,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
            deck_seed=b"",  # Let aggregate generate random seed
        )

        return [_make_command_book("hand", event.hand_root, deal_cards)]

    def _handle_hand_complete(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate HandComplete → EndHand.

        When a hand completes, we need to tell the Table aggregate
        to update its state with the results.
        """
        # Extract the event from the event book
        event = hand.HandComplete()
        for page in context.event_book.pages:
            if page.HasField("event") and page.event.type_url.endswith("HandComplete"):
                page.event.Unpack(event)
                break

        # Build results for the table
        results = []
        for winner in event.winners:
            results.append(
                table.PotResult(
                    winner_root=winner.player_root,
                    amount=winner.amount,
                )
            )

        # Create EndHand command
        end_hand = table.EndHand(
            hand_root=context.aggregate_root,
            results=results,
        )

        return [_make_command_book("table", event.table_root, end_hand)]
