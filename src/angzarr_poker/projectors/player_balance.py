"""PlayerProjector — materializes a per-player bankroll read model.

Folds player-domain funds events into one row per player (player_root ->
{display_name, balance}), the "player display" of available chips. The read
model is a CQRS view SEPARATE from the player aggregate, so it can lag the write
side; it is kept in-process and served over PlayerProjectionQueryService
(player_main.py) so a client can observe read-model eventual consistency from
outside the write side (cluster scenario EA-0004).

Per-domain projector: bound to the player topic only. Distinct from the
cross-domain OutputProjector narrator (an auxiliary rendered view).

Implements the generated ``PlayerProjectorHandler`` seam. The framework hands
each delivery a fresh ``PlayerBalanceProjection`` (the per-delivery fold target)
plus the typed events; ``finish`` receives the EventBook, whose ``cover.root``
identifies the player the events belong to (the event payloads do not carry it).
A funds event's ``new_balance`` is the ABSOLUTE balance, so the latest one folded
in a delivery is the player's current bankroll — no running total needed.
"""

from __future__ import annotations

import threading

from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1 import projection_pb2 as _proj
from angzarr_poker._gen.io.angzarr.examples.v1.player_projector_angzarr import (
    PlayerProjectorHandler,
)


class PlayerProjector:
    """Implements ``PlayerProjectorHandler``; holds the bankroll read model.

    ``_rows`` maps player_root (bytes) -> PlayerBalanceProjection. A lock guards
    it because the projector service folds deliveries on a gRPC thread pool while
    the query service reads on another thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[bytes, _proj.PlayerBalanceProjection] = {}

    # --- per-delivery folds (accumulate into the fresh projection) ---------

    def player_registered(self, projection, event) -> None:
        # Registration establishes identity; bankroll stays at its zero default
        # until a funds event lands. Only the name is known here.
        projection.display_name = event.display_name

    def funds_deposited(self, projection, event) -> None:
        projection.balance.CopyFrom(event.new_balance)

    def funds_withdrawn(self, projection, event) -> None:
        projection.balance.CopyFrom(event.new_balance)

    # --- finish: upsert the per-delivery fold into the keyed read model ----

    def finish(self, projection, events: _t.EventBook) -> _t.Projection:
        root = events.cover.root.value
        with self._lock:
            row = self._rows.get(root)
            if row is None:
                row = _proj.PlayerBalanceProjection(player_root=root)
                self._rows[root] = row
            # Merge: keep prior fields a delivery without that event didn't set.
            if projection.display_name:
                row.display_name = projection.display_name
            if projection.HasField("balance"):
                row.balance.CopyFrom(projection.balance)
        return _t.Projection(projector="PlayerProjector")

    # --- read surface (consumed by the query servicer) ---------------------

    def balance_for(self, player_root: bytes) -> _proj.PlayerBalanceProjection | None:
        """A copy of the player's read-model row, or None if not yet observed."""
        with self._lock:
            row = self._rows.get(player_root)
            if row is None:
                return None
            out = _proj.PlayerBalanceProjection()
            out.CopyFrom(row)
            return out


_: PlayerProjectorHandler = PlayerProjector()
