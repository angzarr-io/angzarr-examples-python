"""Per-scenario world for the cluster acceptance harness.

A deployed cluster keeps aggregate state in postgres across scenarios, and the
poker features reuse entity names ("Main", "Alice") between scenarios. If two
scenarios mapped "Main" to the same table root they would collide — the second
CreateTable would hit an already-created aggregate, and event assertions would
observe the prior run's history.

So each scenario gets a fresh random ``nonce``; an entity name resolves to
``sha256(nonce + name)[:16]`` — a 16-byte root unique to this scenario run.
The same name resolves to the same root within the scenario (so a later
JoinTable references the table CreateTable made), but never across scenarios or
re-runs. The nonce also serves as the correlation id stamped on every command.
"""

from __future__ import annotations

import hashlib
import uuid

from acceptance_steps._client import ClusterClient


class World:
    """One scenario's cluster context: the shared client, a per-scenario root
    namespace, and the bookkeeping a multi-step poker scenario threads
    (resolved child roots like a hand's id)."""

    def __init__(self, client: ClusterClient) -> None:
        self.client = client
        self.nonce = uuid.uuid4().hex
        self.correlation_id = self.nonce
        # Child roots discovered mid-scenario (e.g. a hand_root read off the
        # table's HandStarted), keyed by a caller-chosen label.
        self.roots: dict[str, bytes] = {}

    def root(self, name: str) -> bytes:
        """The scenario-unique 16-byte root for entity ``name``."""
        return hashlib.sha256((self.nonce + ":" + name).encode()).digest()[:16]
