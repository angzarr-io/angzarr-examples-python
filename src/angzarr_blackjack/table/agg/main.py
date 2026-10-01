"""agg-table: the TableAggregate, with a pass-through upcaster (the table has
no legacy event shapes) for coordinators that upcast on load."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
    new_table_aggregate_dispatch,
)
from angzarr_blackjack.table.agg.handler import TableAggregate
from angzarr_client import ComponentHost, PassThroughUpcaster, configure_logging

DOMAIN = "table"
DEFAULT_PORT = "50402"


def register(host: ComponentHost) -> ComponentHost:
    """The TableAggregate on ``host``."""
    return host.add_aggregate(
        new_table_aggregate_dispatch(TableAggregate())
    ).add_upcaster(PassThroughUpcaster())


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    register(ComponentHost()).run()


if __name__ == "__main__":
    main()
