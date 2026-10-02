"""pmg-buy-in: the BuyInProcessManager."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1.buy_in_process_manager_angzarr import (
    new_buy_in_process_manager_dispatch,
)
from angzarr_blackjack.pmg_buy_in.handler import BuyInProcessManager
from angzarr_client import ComponentHost, configure_logging

DOMAIN = "buy-in"
DEFAULT_PORT = "50421"


def register(host: ComponentHost) -> ComponentHost:
    """The BuyInProcessManager on ``host``."""
    return host.add_process_manager(
        new_buy_in_process_manager_dispatch(BuyInProcessManager())
    )


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    register(ComponentHost()).run()


if __name__ == "__main__":
    main()
