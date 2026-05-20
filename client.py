"""Gateway client for poker game integration.

This module provides a simple client that routes commands to the appropriate
domain aggregate through the angzarr gateway or directly to domain services.
"""

from __future__ import annotations

import hashlib

import grpc
from google.protobuf import any_pb2
from google.protobuf.message import Message

from angzarr_client import CommandResponse, DomainClient
from angzarr_client.proto.angzarr.types_pb2 import (
    CommandBook,
    CommandPage,
    Cover,
    Edition,
    PageHeader,
    UUID,
    SYNC_MODE_ASYNC,
)


def derive_root(domain: str, identifier: str) -> bytes:
    """Derive a deterministic root ID from domain and identifier.

    Args:
        domain: Domain name (e.g., "player", "table", "hand").
        identifier: Unique identifier within the domain.

    Returns:
        16-byte UUID derived via SHA-256 (truncated).
    """
    data = f"{domain}:{identifier}".encode()
    # Use first 16 bytes of SHA-256 to create a valid UUID
    full_hash = hashlib.sha256(data).digest()
    return full_hash[:16]


class GatewayClient:
    """Client for executing commands against poker aggregates.

    This client routes commands to the appropriate domain service.
    In distributed mode, it connects to each aggregate's command handler.
    """

    def __init__(self, gateway_address: str) -> None:
        """Initialize the gateway client.

        Args:
            gateway_address: Address of the gateway (e.g., "localhost:9084").
                            In this implementation, we connect directly to aggregates.
        """
        self._gateway_address = gateway_address
        self._domain_clients: dict[str, DomainClient] = {}

    def __enter__(self) -> GatewayClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close all connections."""
        self.close()

    def close(self) -> None:
        """Close all domain client connections."""
        for client in self._domain_clients.values():
            client.close()
        self._domain_clients.clear()

    def _get_domain_client(self, domain: str) -> DomainClient:
        """Get or create a domain client for the specified domain.

        Args:
            domain: Domain name (e.g., "player", "table", "hand").

        Returns:
            DomainClient connected to the domain's command handler.
        """
        if domain not in self._domain_clients:
            import os

            # Local port forward mapping for development
            local_ports = {
                "player": 1320,
                "table": 1321,
                "hand": 1322,
            }

            mode = os.environ.get("ANGZARR_MODE", "")
            if mode == "standalone":
                # Use Unix domain sockets for standalone mode
                self._domain_clients[domain] = DomainClient.for_domain(domain)
            elif mode == "distributed":
                # Use K8s DNS with actual service names: {domain}-aggregate
                namespace = os.environ.get("ANGZARR_NAMESPACE", "angzarr")
                port = int(os.environ.get("ANGZARR_CH_PORT", "1310"))
                endpoint = f"{domain}-aggregate.{namespace}.svc:{port}"
                channel = grpc.insecure_channel(endpoint)
                self._domain_clients[domain] = DomainClient(channel)
            elif domain in local_ports:
                # Use local port forwards for development
                endpoint = f"localhost:{local_ports[domain]}"
                channel = grpc.insecure_channel(endpoint)
                self._domain_clients[domain] = DomainClient(channel)
            else:
                # Try K8s DNS with actual service names
                namespace = os.environ.get("ANGZARR_NAMESPACE", "angzarr")
                port = int(os.environ.get("ANGZARR_CH_PORT", "1310"))
                endpoint = f"{domain}-aggregate.{namespace}.svc:{port}"
                channel = grpc.insecure_channel(endpoint)
                self._domain_clients[domain] = DomainClient(channel)

        return self._domain_clients[domain]

    def execute(
        self,
        domain: str,
        root: bytes,
        command: Message,
        sequence: int = 0,
        sync_mode: int | None = None,
        edition: Edition | None = None,
    ) -> CommandResponse:
        """Execute a command against a domain aggregate.

        Args:
            domain: Target domain (e.g., "player", "table", "hand").
            root: Root ID for the aggregate.
            command: Protobuf command message.
            sequence: Expected sequence number (for optimistic concurrency).
            sync_mode: Sync mode (SYNC_MODE_SIMPLE or SYNC_MODE_CASCADE).
                      Defaults to SIMPLE for single-aggregate commands.
            edition: Optional edition for what-if scenario branching.

        Returns:
            CommandResponse with execution result and events.
        """
        client = self._get_domain_client(domain)

        # Pack command into Any
        command_any = any_pb2.Any()
        command_any.Pack(command)

        # Build UUID from root bytes
        root_uuid = UUID(value=root)

        # Build Cover with optional edition
        cover = Cover(domain=domain, root=root_uuid)
        if edition is not None:
            cover.edition.CopyFrom(edition)

        # Build CommandBook
        cmd_book = CommandBook(
            cover=cover,
            pages=[
                CommandPage(
                    header=PageHeader(sequence=sequence),
                    command=command_any,
                )
            ],
        )

        # Default to ASYNC mode (standard for most operations)
        # Use SIMPLE for read-after-write, CASCADE for financial atomicity
        if sync_mode is None:
            sync_mode = SYNC_MODE_ASYNC

        response = client.execute_with_mode(cmd_book, sync_mode)
        return CommandResponse(response)
