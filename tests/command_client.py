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


def _ensure_proto_uuid(root):
    """Convert root to proto UUID if needed."""
    from angzarr_client.proto.angzarr import UUID

    if isinstance(root, bytes):
        return UUID(value=root)
    return root


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


def create_client() -> CommandClient:
    """Factory: create GrpcClient from PLAYER_URL (default localhost:1310)."""
    player_url = os.environ.get("PLAYER_URL", "localhost:1310")
    return GrpcClient(player_url)
