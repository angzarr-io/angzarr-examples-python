"""Saga: Hand -> Table

Reacts to HandComplete events from Hand domain.
Sends EndHand commands to Table domain.

Uses the custom saga infrastructure from sagas/base.py which provides
context.aggregate_root (source aggregate root from EventBook cover).
"""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from angzarr_client.destinations import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table
from angzarr_client.saga_handler import SagaHandler, run_saga_server

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from sagas.base import Saga, SagaContext

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


def _pack_command(cmd: Message) -> AnyProto:
    """Pack a command message into Any."""
    type_name = type(cmd).DESCRIPTOR.full_name
    return AnyProto(
        type_url=f"type.googleapis.com/{type_name}",
        value=cmd.SerializeToString(),
    )


def _make_command_book(
    domain: str,
    root: bytes,
    command: Message,
    destinations: Destinations | None = None,
) -> types.CommandBook:
    """Create a CommandBook with a single command."""
    book = types.CommandBook(
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

    if destinations is not None:
        destinations.stamp_command(book, domain)

    return book


class HandTableSaga(Saga):
    """Saga that translates HandComplete events to EndHand commands.

    Design Philosophy:
        This saga just translates events to commands. The Table aggregate
        validates and decides whether to accept the EndHand command.
    """

    @property
    def name(self) -> str:
        return "saga-hand-table"

    @property
    def subscribed_events(self) -> list[str]:
        return ["HandComplete"]

    def handle(self, context: SagaContext) -> list[types.CommandBook]:
        """Handle HandComplete and emit EndHand."""
        if context.event_type == "HandComplete":
            return self._handle_hand_complete(context)
        return []

    def _handle_hand_complete(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate HandComplete -> EndHand.

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
        results = [
            table.PotResult(
                winner_root=winner.player_root,
                amount=winner.amount,
                pot_type=winner.pot_type,
                winning_hand=winner.winning_hand,
            )
            for winner in event.winners
        ]

        # Create EndHand command - Table aggregate validates results
        # hand_root comes from context.aggregate_root (source aggregate root)
        end_hand = table.EndHand(
            hand_root=context.aggregate_root,
        )
        end_hand.results.extend(results)

        return [_make_command_book("table", event.table_root, end_hand, context.destinations)]


if __name__ == "__main__":
    # For standalone execution, we need to integrate with the SagaRouter
    # The SagaHandler expects a different interface, so we create an adapter
    from sagas.base import SagaRouter

    router = SagaRouter()
    router.register(HandTableSaga())

    # Custom handle function that bridges to the SagaRouter
    def handle_events(source: types.EventBook, destination_sequences: dict[str, int]):
        from angzarr_client.proto.angzarr import saga_pb2

        commands = router.route(source, "hand", destination_sequences)
        return saga_pb2.SagaResponse(commands=commands)

    handler = SagaHandler(None).with_handle(handle_events)
    run_saga_server("saga-hand-table", "50412", handler, logger=logger)
