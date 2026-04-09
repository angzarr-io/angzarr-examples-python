"""CommandClient abstraction for acceptance tests.

Provides two implementations:
- InProcessClient: wraps handler functions directly (no gRPC, for unit/local tests)
- GrpcClient: connects to a running coordinator via gRPC (for acceptance tests)

The factory function `create_client()` checks the PLAYER_URL env var:
- If set: returns a GrpcClient connected to that endpoint
- If not set: returns an InProcessClient
"""

import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import grpc
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr import (
    CommandBook,
    CommandHandlerCoordinatorServiceStub,
    CommandPage,
    CommandRequest,
    CommandResponse,
    Cover,
    PageHeader,
    SyncMode,
)


class CommandClient(ABC):
    """Abstract base class for sending commands to aggregates."""

    @abstractmethod
    def send_command(
        self,
        domain: str,
        root: bytes,
        command: ProtoAny,
        sequence: int = 0,
    ) -> CommandResponse:
        """Send a command to the given domain/root.

        Args:
            domain: Aggregate domain (e.g. "player", "table").
            root: Proto UUID for the aggregate root.
            command: Packed protobuf command as Any.
            sequence: Expected sequence number for optimistic concurrency.

        Returns:
            CommandResponse from the coordinator.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any resources (channels, connections)."""
        ...


class GrpcClient(CommandClient):
    """Sends commands to a running angzarr coordinator via gRPC."""

    def __init__(self, endpoint: str):
        self._endpoint = endpoint
        self._channel = grpc.insecure_channel(endpoint)
        self._stub = CommandHandlerCoordinatorServiceStub(self._channel)

    def send_command(
        self,
        domain: str,
        root: bytes,
        command: ProtoAny,
        sequence: int = 0,
    ) -> CommandResponse:
        root_proto = _ensure_proto_uuid(root)

        cover = Cover(
            domain=domain,
            correlation_id=str(uuid.uuid4()),
        )
        cover.root.CopyFrom(root_proto)

        header = PageHeader(sequence=sequence)
        page = CommandPage(header=header)
        page.command.CopyFrom(command)

        book = CommandBook()
        book.cover.CopyFrom(cover)
        book.pages.append(page)

        request = CommandRequest(
            command=book,
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        return self._stub.HandleCommand(request, timeout=30)

    def close(self) -> None:
        self._channel.close()


@dataclass
class _AggregateState:
    """Tracks in-process aggregate state across commands."""

    events: list = field(default_factory=list)
    sequence: int = 0


class InProcessClient(CommandClient):
    """Executes commands directly against handler functions (no gRPC).

    Maintains per-root state so that sequential commands against the same
    aggregate root see the effects of prior commands.
    """

    def __init__(self):
        # (domain, root_hex) -> _AggregateState
        self._states: dict[tuple[str, str], _AggregateState] = {}
        self._handlers: dict[str, dict[str, object]] = {}
        self._state_builders: dict[str, object] = {}
        self._state_factories: dict[str, object] = {}

        self._register_player_handlers()

    def _register_player_handlers(self):
        """Register player domain handlers."""
        from player.agg.handlers import (
            handle_deposit,
            handle_register,
            handle_release,
            handle_reserve,
            handle_withdraw,
        )
        from player.agg.state import PlayerState, build_state

        self._handlers["player"] = {
            "examples.RegisterPlayer": handle_register,
            "examples.DepositFunds": handle_deposit,
            "examples.WithdrawFunds": handle_withdraw,
            "examples.ReserveFunds": handle_reserve,
            "examples.ReleaseFunds": handle_release,
        }
        self._state_builders["player"] = build_state
        self._state_factories["player"] = PlayerState

    def send_command(
        self,
        domain: str,
        root: bytes,
        command: ProtoAny,
        sequence: int = 0,
    ) -> CommandResponse:
        from angzarr_client.proto.angzarr import types_pb2 as types

        root_hex = root.hex() if isinstance(root, bytes) else root.value.hex()

        # Get or create aggregate state
        key = (domain, root_hex)
        agg_state = self._states.setdefault(key, _AggregateState())

        # Rebuild domain state from stored events
        state_factory = self._state_factories.get(domain)
        state_builder = self._state_builders.get(domain)
        if state_factory is None or state_builder is None:
            raise ValueError(f"No handlers registered for domain: {domain}")

        state = state_factory()
        event_anys = [page.event for page in agg_state.events if page.HasField("event")]
        state = state_builder(state, event_anys)

        # Look up handler
        type_name = command.type_url.split("/")[-1]
        handlers = self._handlers.get(domain, {})
        handler = handlers.get(type_name)
        if handler is None:
            raise ValueError(f"No handler for {type_name} in domain {domain}")

        # Unpack command from Any into concrete proto type
        cmd_type = handler._command_type
        cmd = cmd_type()
        command.Unpack(cmd)

        # Execute handler with concrete command
        result_event = handler(cmd, state, agg_state.sequence)

        # Pack result into event page
        event_any = ProtoAny()
        event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")

        event_page = types.EventPage(
            header=types.PageHeader(sequence=agg_state.sequence),
            event=event_any,
        )

        # Update stored state
        agg_state.events.append(event_page)
        agg_state.sequence += 1

        # Build response
        root_proto = _ensure_proto_uuid(root)
        event_book = types.EventBook(
            cover=types.Cover(domain=domain),
            pages=[event_page],
        )
        event_book.cover.root.CopyFrom(root_proto)

        response = CommandResponse()
        response.events.CopyFrom(event_book)
        return response

    def close(self) -> None:
        self._states.clear()


def _ensure_proto_uuid(root):
    """Convert root to proto UUID if needed."""
    from angzarr_client.proto.angzarr import UUID

    if isinstance(root, bytes):
        return UUID(value=root)
    # Already a proto UUID
    return root


def create_client() -> CommandClient:
    """Factory: create the appropriate CommandClient based on environment.

    If PLAYER_URL is set, returns a GrpcClient; otherwise InProcessClient.
    """
    player_url = os.environ.get("PLAYER_URL")
    if player_url:
        return GrpcClient(player_url)
    return InProcessClient()
