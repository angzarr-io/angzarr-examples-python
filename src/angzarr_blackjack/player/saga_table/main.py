"""saga-player-table: the PlayerTableSaga."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1.player_table_saga_angzarr import (
    new_player_table_saga_dispatch,
)
from angzarr_blackjack.player.saga_table.handler import PlayerTableSaga
from angzarr_client import ComponentHost, configure_logging

DEFAULT_PORT = "50411"


def register(host: ComponentHost) -> ComponentHost:
    """The PlayerTableSaga on ``host``."""
    return host.add_saga(new_player_table_saga_dispatch(PlayerTableSaga()))


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    register(ComponentHost()).run()


if __name__ == "__main__":
    main()
