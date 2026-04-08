"""Acceptance tests for poker example applications.

These tests run against a deployed Kubernetes cluster with the poker apps.
Commands are sent directly to aggregate coordinator sidecars via gRPC.
Events are persisted to PostgreSQL and published to RabbitMQ.

Environment variables:
- PLAYER_URL: Player aggregate coordinator (default: localhost:1310)
"""

import os
import time
import uuid

import grpc
import pytest
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.helpers import uuid_to_proto
from angzarr_client.proto.angzarr import (
    CommandBook,
    CommandPage,
    CommandRequest,
    CommandResponse,
    Cover,
    PageHeader,
    SyncMode,
)
from angzarr_client.proto.examples import player_pb2, poker_types_pb2


def player_url() -> str:
    """Get player aggregate coordinator URL from environment or use default."""
    return os.environ.get("PLAYER_URL", "localhost:1310")


def new_uuid():
    """Generate a new UUID and return its proto representation."""
    return uuid_to_proto(uuid.uuid4())


def pack_command(msg, type_name: str) -> ProtoAny:
    """Pack a protobuf message into an Any with the given type name."""
    return ProtoAny(
        type_url=f"type.googleapis.com/{type_name}",
        value=msg.SerializeToString(),
    )


def make_command_request(
    domain: str,
    root,
    command: ProtoAny,
    sequence: int = 0,
) -> CommandRequest:
    """Build a CommandRequest for the given domain, root, and command."""
    cover = Cover(
        domain=domain,
        correlation_id=str(uuid.uuid4()),
    )
    cover.root.CopyFrom(root)

    header = PageHeader(sequence=sequence)
    page = CommandPage(header=header)
    page.command.CopyFrom(command)

    book = CommandBook()
    book.cover.CopyFrom(cover)
    book.pages.append(page)

    return CommandRequest(
        command=book,
        sync_mode=SyncMode.SYNC_MODE_SIMPLE,
    )


def send_player_command(request: CommandRequest) -> CommandResponse:
    """Send a command to the player aggregate coordinator."""
    url = player_url()
    channel = grpc.insecure_channel(url)
    try:
        from angzarr_client.proto.angzarr import (
            CommandHandlerCoordinatorServiceStub,
        )

        stub = CommandHandlerCoordinatorServiceStub(channel)
        return stub.HandleCommand(request, timeout=30)
    finally:
        channel.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlayerAggregate:
    """Acceptance tests for the player aggregate."""

    def test_connectivity(self):
        """Verify player aggregate is reachable via gRPC."""
        url = player_url()
        print(f"Connecting to player aggregate at {url}")
        channel = grpc.insecure_channel(url)
        try:
            # Use channel_ready_future to check connectivity
            grpc.channel_ready_future(channel).result(timeout=10)
            print("Player aggregate is reachable")
        except grpc.FutureTimeoutError:
            pytest.fail(f"Failed to connect to player aggregate at {url}")
        finally:
            channel.close()

    def test_register_player(self):
        """RegisterPlayer returns a PlayerRegistered event."""
        player_id = new_uuid()
        player_id_hex = player_id.value.hex()
        print(f"Registering player with ID: {player_id_hex}")

        cmd = player_pb2.RegisterPlayer(
            display_name="AcceptanceTestPlayer",
            email=f"test-{player_id_hex[:8]}@example.com",
            player_type=poker_types_pb2.HUMAN,
        )

        request = make_command_request(
            "player",
            player_id,
            pack_command(cmd, "examples.RegisterPlayer"),
        )

        response = send_player_command(request)
        print(f"RegisterPlayer response: {response}")

        assert response.HasField("events"), "Response should contain events"
        events = response.events
        assert events.HasField("cover"), "Event book should have a cover"
        assert len(events.pages) > 0, "Should have at least one event"
        print(f"Successfully registered player, got {len(events.pages)} event(s)")

    def test_register_and_deposit(self):
        """Register a player then deposit funds at sequence 1 (with retries)."""
        player_id = new_uuid()
        player_id_hex = player_id.value.hex()
        print(f"Test: Register and deposit for player {player_id_hex}")

        # Step 1: Register
        register_cmd = player_pb2.RegisterPlayer(
            display_name="DepositTestPlayer",
            email=f"deposit-{player_id_hex[:8]}@example.com",
            player_type=poker_types_pb2.HUMAN,
        )

        register_request = make_command_request(
            "player",
            player_id,
            pack_command(register_cmd, "examples.RegisterPlayer"),
        )

        register_response = send_player_command(register_request)
        assert register_response.HasField("events"), "Registration should succeed"
        print("Player registered successfully")

        # Step 2: Deposit funds at sequence 1, with retry/backoff
        deposit_cmd = player_pb2.DepositFunds(
            amount=poker_types_pb2.Currency(amount=1000, currency_code="USD"),
        )

        max_attempts = 30
        last_err = None
        for attempt in range(1, max_attempts + 1):
            deposit_request = make_command_request(
                "player",
                player_id,
                pack_command(deposit_cmd, "examples.DepositFunds"),
                sequence=1,
            )
            try:
                resp = send_player_command(deposit_request)
                assert resp.HasField("events"), "Response should contain events"
                events = resp.events
                assert len(events.pages) > 0, "Should have deposited event"
                print(
                    f"Successfully deposited funds, got {len(events.pages)} event(s)"
                )
                last_err = None
                break
            except grpc.RpcError as e:
                print(f"DepositFunds attempt {attempt}/{max_attempts} failed: {e}")
                last_err = e
                time.sleep(0.5 * attempt)

        if last_err is not None:
            pytest.fail(
                f"DepositFunds failed after {max_attempts} attempts: {last_err}"
            )

    def test_duplicate_registration_fails(self):
        """Second registration with same player ID is rejected."""
        player_id = new_uuid()
        player_id_hex = player_id.value.hex()
        print(f"Test: Duplicate registration for player {player_id_hex}")

        cmd = player_pb2.RegisterPlayer(
            display_name="DuplicateTestPlayer",
            email=f"dup-{player_id_hex[:8]}@example.com",
            player_type=poker_types_pb2.HUMAN,
        )

        # First registration should succeed
        request1 = make_command_request(
            "player",
            player_id,
            pack_command(cmd, "examples.RegisterPlayer"),
        )
        response1 = send_player_command(request1)
        assert response1.HasField("events"), "First registration should succeed"
        print("First registration succeeded")

        # Second registration with same ID should fail
        request2 = make_command_request(
            "player",
            player_id,
            pack_command(cmd, "examples.RegisterPlayer"),
        )

        with pytest.raises(grpc.RpcError) as exc_info:
            send_player_command(request2)

        status = exc_info.value
        code = status.code()
        print(f"Duplicate registration correctly rejected: {code}")
        assert code in (
            grpc.StatusCode.ALREADY_EXISTS,
            grpc.StatusCode.FAILED_PRECONDITION,
        ), f"Expected ALREADY_EXISTS or FAILED_PRECONDITION, got {code}"
