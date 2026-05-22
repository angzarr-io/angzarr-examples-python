"""CommandClient for acceptance tests.

Sends commands to running angzarr coordinators via gRPC. Routes by domain:
PLAYER_URL, TABLE_URL, HAND_URL, TOURNAMENT_URL, RESERVATION_URL — each
falls back to PLAYER_URL if unset.

Default sync_mode is SYNC_MODE_ASYNC so cluster scenarios can observe
downstream saga/PM propagation via ``within N seconds`` rather than
blocking on each command; financial commands override per-call.

Use `create_client()` to build one; defaults to localhost:1310.
"""

import os
import uuid

import grpc
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr.v1.command_handler_pb2 import CommandResponse
from angzarr_client.proto.angzarr.v1.command_handler_pb2_grpc import (
    CommandHandlerCoordinatorServiceStub,
)
from angzarr_client.proto.angzarr.v1.types_pb2 import (
    UUID,
    CommandBook,
    CommandPage,
    CommandRequest,
    Cover,
    PageHeader,
    SyncMode,
)


def _ensure_proto_uuid(root):
    if isinstance(root, bytes):
        return UUID(value=root)
    return root


class CommandClient:
    """Sends commands to running angzarr coordinators via gRPC.

    Routes by domain: player/table/hand/tournament/reservation, each from
    its own *_URL env var (all default to ``player_url``).
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
                sync_mode if sync_mode is not None else SyncMode.SYNC_MODE_ASYNC
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
    """Factory: create CommandClient from PLAYER_URL (default localhost:1310)."""
    player_url = os.environ.get("PLAYER_URL", "localhost:1310")
    return CommandClient(player_url)
