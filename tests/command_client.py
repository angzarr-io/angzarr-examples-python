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
    """Sends commands to running angzarr coordinators via gRPC.

    Routes by domain: PLAYER_URL, TABLE_URL, HAND_URL.
    """

    def __init__(self, player_url: str):
        table_url = os.environ.get("TABLE_URL", player_url)
        hand_url = os.environ.get("HAND_URL", player_url)
        tournament_url = os.environ.get("TOURNAMENT_URL", player_url)
        reservation_url = os.environ.get("RESERVATION_URL", player_url)
        self._channels = {
            "player": grpc.insecure_channel(player_url),
            "table": grpc.insecure_channel(table_url),
            "hand": grpc.insecure_channel(hand_url),
            "tournament": grpc.insecure_channel(tournament_url),
            "reservation": grpc.insecure_channel(reservation_url),
        }
        self._stubs = {
            domain: CommandHandlerCoordinatorServiceStub(ch)
            for domain, ch in self._channels.items()
        }

    def send_command(
        self,
        domain: str,
        root: bytes,
        command: ProtoAny,
        sequence: int = 0,
        sync_mode: int | None = None,
        cascade_error_mode: int | None = None,
        correlation_id: str | None = None,
    ) -> CommandResponse:
        root_proto = _ensure_proto_uuid(root)

        cover = Cover(
            domain=domain,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )
        cover.root.CopyFrom(root_proto)

        header = PageHeader(sequence=sequence)
        page = CommandPage(header=header)
        page.command.CopyFrom(command)

        book = CommandBook()
        book.cover.CopyFrom(cover)
        book.pages.append(page)

        kwargs = {
            "command": book,
            "sync_mode": (
                sync_mode if sync_mode is not None else SyncMode.SYNC_MODE_SIMPLE
            ),
        }
        if cascade_error_mode is not None:
            kwargs["cascade_error_mode"] = cascade_error_mode

        request = CommandRequest(**kwargs)
        stub = self._stubs.get(domain, self._stubs["player"])
        return stub.HandleCommand(request, timeout=30)

    def close(self) -> None:
        for ch in self._channels.values():
            ch.close()


def create_client() -> CommandClient:
    """Factory: create GrpcClient from PLAYER_URL (default localhost:1310)."""
    player_url = os.environ.get("PLAYER_URL", "localhost:1310")
    return GrpcClient(player_url)
