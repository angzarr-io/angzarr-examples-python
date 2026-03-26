"""Saga: Hand -> Player

Reacts to PotAwarded events from Hand domain.
Sends DepositFunds commands to Player domain.

Uses the custom saga infrastructure from sagas/base.py.
Note: This duplicates functionality in sagas/hand_results_saga.py -
consider consolidating.
"""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from angzarr_client.destinations import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
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


class HandPlayerSaga(Saga):
    """Saga that translates PotAwarded events to DepositFunds commands.

    Design Philosophy:
        This saga produces multiple commands (one per winner).
        The Player aggregate validates deposit operations.
    """

    @property
    def name(self) -> str:
        return "saga-hand-player"

    @property
    def subscribed_events(self) -> list[str]:
        return ["PotAwarded"]

    def handle(self, context: SagaContext) -> list[types.CommandBook]:
        """Handle PotAwarded and emit DepositFunds."""
        if context.event_type == "PotAwarded":
            return self._handle_pot_awarded(context)
        return []

    def _handle_pot_awarded(self, context: SagaContext) -> list[types.CommandBook]:
        """Translate PotAwarded -> DepositFunds for each winner."""
        # Extract the event from the event book
        event = hand.PotAwarded()
        for page in context.event_book.pages:
            if page.HasField("event") and page.event.type_url.endswith("PotAwarded"):
                page.event.Unpack(event)
                break

        commands = []

        # Create DepositFunds commands for each winner
        for winner in event.winners:
            deposit_funds = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount,
                    currency_code="CHIPS",
                ),
            )

            commands.append(
                _make_command_book("player", winner.player_root, deposit_funds, context.destinations)
            )

        return commands


if __name__ == "__main__":
    from sagas.base import SagaRouter

    router = SagaRouter()
    router.register(HandPlayerSaga())

    def handle_events(source: types.EventBook, destination_sequences: dict[str, int]):
        from angzarr_client.proto.angzarr import saga_pb2

        commands = router.route(source, "hand", destination_sequences)
        return saga_pb2.SagaResponse(commands=commands)

    handler = SagaHandler(None).with_handle(handle_events)
    run_saga_server("saga-hand-player", "50414", handler, logger=logger)
