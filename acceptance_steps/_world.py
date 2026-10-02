"""Per-scenario context for the cluster tier.

The cluster keeps state across scenarios, so every entity a scenario names
gets a root unique to the scenario: ``uuid5(NAMESPACE_OID,
"<nonce>:<kind>:<label>")``. Every request is sent in a conversation whose
correlation id starts with the nonce — the scenario's own default
conversation, or one per buy-in / top-up — so the event stream keeps exactly
this scenario's books.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from acceptance_steps._client import ClusterClient
from acceptance_steps._stream import EventStreamSubscriber


class World:
    def __init__(
        self, client: ClusterClient, stream: EventStreamSubscriber | None
    ) -> None:
        self.client = client
        self.stream = stream
        self.nonce = uuid.uuid4().hex[:16]
        self.correlation = self.nonce
        self.notes: dict = {}
        self.response = None  # the last CommandResponse
        self.error = None  # the last grpc.RpcError
        if stream is not None:
            stream.scope(self.nonce)

    def root(self, kind: str, label: str) -> bytes:
        return uuid.uuid5(uuid.NAMESPACE_OID, f"{self.nonce}:{kind}:{label}").bytes

    def player(self, name: str) -> bytes:
        return self.root("player", name)

    def table(self, name: str) -> bytes:
        return self.root("table", name)

    def request(self, label: str) -> bytes:
        return self.root("request", label)

    def conversation(self, label: str) -> str:
        return f"{self.nonce}/{label}"

    def events(self) -> EventStreamSubscriber:
        assert self.stream is not None, "the event stream is not connected"
        return self.stream


def eventually(check: Callable[[], object], within: float, every: float = 0.2):
    """Retry ``check`` until it returns without raising (and truthy) or
    ``within`` seconds pass; then re-raise its last failure."""
    deadline = time.monotonic() + within
    while True:
        try:
            result = check()
            if result is not False:
                return result
            failure = AssertionError("condition not met")
        except AssertionError as exc:
            failure = exc
        except Exception as exc:  # noqa: BLE001 — a service still restarting
            failure = AssertionError(str(exc))
        if time.monotonic() >= deadline:
            raise failure
        time.sleep(every)
