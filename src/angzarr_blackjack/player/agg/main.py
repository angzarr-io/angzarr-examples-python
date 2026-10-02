"""agg-player: the PlayerAggregate and the PlayerUpcaster on one host."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1.player_aggregate_angzarr import (
    new_player_aggregate_dispatch,
)
from angzarr_blackjack.player.agg.handler import PlayerAggregate
from angzarr_blackjack.player.agg.upcaster import PlayerUpcaster
from angzarr_client import ComponentHost, configure_logging

DOMAIN = "player"
DEFAULT_PORT = "50401"


def register(host: ComponentHost) -> ComponentHost:
    """The PlayerAggregate and its upcaster on ``host``."""
    return host.add_aggregate(
        new_player_aggregate_dispatch(PlayerAggregate())
    ).add_upcaster(PlayerUpcaster())


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    register(ComponentHost()).run()


if __name__ == "__main__":
    main()
