"""Base saga infrastructure.

Sagas are stateless event-to-command translators that enable loose coupling
between domains. They subscribe to events from one domain and emit commands
to another domain.

Design Philosophy:
    Sagas are translators, NOT decision makers. They should NOT rebuild
    destination state to make business decisions. The framework provides
    destination sequences for command stamping. Business logic belongs in
    aggregates.

Example: TableSyncSaga subscribes to HandStarted from table domain and
emits DealCards to hand domain.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from angzarr_client.destinations import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types

log = structlog.get_logger()


@dataclass
class SagaContext:
    """Context passed to saga handlers.

    Contains the event book, extracted event type, aggregate metadata,
    and destinations for command stamping.
    """

    event_book: types.EventBook
    event_type: str
    aggregate_type: str
    aggregate_root: bytes
    destinations: Destinations


class Saga(ABC):
    """Base class for saga handlers.

    A saga subscribes to specific event types and handles them by emitting
    commands to other domains. Sagas are stateless - they translate events
    to commands without maintaining state.

    Design Philosophy:
        Sagas are translators, NOT decision makers. Use destinations.stamp_command()
        to set sequence numbers on commands. Don't rebuild destination state.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the saga's name for logging and routing."""
        ...

    @property
    @abstractmethod
    def subscribed_events(self) -> list[str]:
        """Return list of event type names this saga handles.

        Event types are matched by suffix (e.g., "HandStarted" matches
        "type.googleapis.com/examples.HandStarted").
        """
        ...

    @abstractmethod
    def handle(self, context: SagaContext) -> list[types.CommandBook]:
        """Handle an event and return commands to dispatch.

        Args:
            context: Saga context with event book, metadata, and destinations.
                     Use context.destinations.stamp_command() for sequence stamping.

        Returns:
            List of CommandBooks to dispatch to target domains.
        """
        ...


class SagaRouter:
    """Routes events to registered saga handlers.

    The router dispatches events from an EventBook to all sagas that
    subscribe to the event type. Multiple sagas can handle the same
    event type - all will be invoked.

    Saga failures are logged but don't stop other sagas from processing.
    """

    def __init__(self):
        """Initialize an empty router."""
        self._sagas: list[Saga] = []

    def register(self, saga: Saga) -> "SagaRouter":
        """Register a saga handler.

        Args:
            saga: Saga to register.

        Returns:
            Self for chaining.
        """
        self._sagas.append(saga)
        log.info("saga_registered", saga=saga.name, events=saga.subscribed_events)
        return self

    def route(
        self,
        event_book: types.EventBook,
        aggregate_type: str,
        destination_sequences: dict[str, int] | None = None,
    ) -> list[types.CommandBook]:
        """Route events from an EventBook to matching sagas.

        Args:
            event_book: EventBook containing events to route.
            aggregate_type: Type of the source aggregate.
            destination_sequences: Map of domain to next sequence number for stamping.

        Returns:
            Combined list of CommandBooks from all matching sagas.
        """
        commands = []
        destinations = Destinations(destination_sequences or {})

        # Extract aggregate root from event book cover
        aggregate_root = b""
        if event_book.cover and event_book.cover.root:
            aggregate_root = event_book.cover.root.value

        # Process each event page
        for page in event_book.pages:
            if not page.HasField("event"):
                continue

            event_any = page.event
            event_type = self._extract_event_type(event_any.type_url)

            context = SagaContext(
                event_book=event_book,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_root=aggregate_root,
                destinations=destinations,
            )

            # Find and invoke matching sagas
            for saga in self._sagas:
                if event_type in saga.subscribed_events:
                    try:
                        saga_commands = saga.handle(context)
                        commands.extend(saga_commands)
                        log.debug(
                            "saga_handled",
                            saga=saga.name,
                            event_type=event_type,
                            commands_emitted=len(saga_commands),
                        )
                    except Exception as e:
                        log.error(
                            "saga_failed",
                            saga=saga.name,
                            event_type=event_type,
                            error=str(e),
                        )
                        # Continue processing - saga failures don't stop others

        return commands

    def _extract_event_type(self, type_url: str) -> str:
        """Extract event type name from type URL.

        Args:
            type_url: Full type URL (e.g., "type.googleapis.com/examples.HandStarted")

        Returns:
            Event type name (e.g., "HandStarted")
        """
        if "." in type_url:
            return type_url.split(".")[-1]
        return type_url
