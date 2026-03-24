"""Hand Results Saga - bridges Hand/Table and Player domains.

Handles:
- HandEnded (from table) → ReleaseFunds (to player)
- PotAwarded (from hand) → DepositFunds (to player)
"""

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

# Note: poker_types is used for DepositFunds Currency

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


class HandResultsSaga(Saga):
    """Saga that handles hand results and updates player balances.

    Handles:
    - HandEnded: Release reserved funds back to players
    - PotAwarded: Deposit winnings to players
    """

    @property
    def name(self) -> str:
        return "HandResultsSaga"

    @property
    def subscribed_events(self) -> list[str]:
        return ["HandEnded", "PotAwarded"]

    def handle(self, context: SagaContext) -> list[types.CommandBook]:
        """Handle events and emit commands."""
        if context.event_type == "HandEnded":
            return self._handle_hand_ended(context)
        elif context.event_type == "PotAwarded":
            return self._handle_pot_awarded(context)
        return []

    def _handle_hand_ended(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate HandEnded → ReleaseFunds commands.

        When a hand ends at the table, we need to release the reserved funds
        for each player that participated.
        """
        # Extract the event from the event book
        event = table.HandEnded()
        for page in context.event_book.pages:
            if page.HasField("event") and page.event.type_url.endswith("HandEnded"):
                page.event.Unpack(event)
                break

        commands = []

        # Emit ReleaseFunds for each player in stack_changes
        for player_root_hex, change in event.stack_changes.items():
            # Convert hex string back to bytes
            player_root = bytes.fromhex(player_root_hex)

            # Create ReleaseFunds command
            # ReleaseFunds only needs the table_root - the aggregate knows the reserved amount
            release_funds = player.ReleaseFunds(
                table_root=context.aggregate_root,
            )

            commands.append(_make_command_book("player", player_root, release_funds))

        return commands

    def _handle_pot_awarded(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate PotAwarded → DepositFunds commands.

        When a pot is awarded, we need to deposit the winnings to each
        winning player's bankroll.
        """
        # Extract the event from the event book
        event = hand.PotAwarded()
        for page in context.event_book.pages:
            if page.HasField("event") and page.event.type_url.endswith("PotAwarded"):
                page.event.Unpack(event)
                break

        commands = []

        # Emit DepositFunds for each winner
        for winner in event.winners:
            # Create DepositFunds command
            deposit_funds = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount,
                    currency_code="CHIPS",
                ),
            )

            commands.append(
                _make_command_book("player", winner.player_root, deposit_funds)
            )

        return commands
