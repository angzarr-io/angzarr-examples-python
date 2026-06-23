"""Player bounded context: the Player aggregate ported onto the angzarr-cli
generated harness seam.

``handler`` carries the bankroll business rules (the ``PlayerAggregateHandler``
Protocol implementation): registration plus the deposit / withdraw / reserve /
release / transfer / deduct primitives. The buy-in, rebuy, and tournament
registration lifecycles do NOT live here — after the reservation refactor they
moved to the reservation aggregate; ``player.feature`` drives those through it.
"""

from .handler import PlayerAggregate

__all__ = ["PlayerAggregate"]
