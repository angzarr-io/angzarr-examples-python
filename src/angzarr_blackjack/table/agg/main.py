"""agg-table: the TableAggregate, with a pass-through UpcasterService (the
table has no legacy event shapes) for coordinators that upcast on load."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1.table_aggregate_angzarr import (
    new_table_aggregate_dispatch,
)
from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
from angzarr_blackjack._gen.io.angzarr.v1 import upcaster_pb2_grpc as _up_grpc
from angzarr_blackjack._runtime.hosts import AggregateHost
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import (
    CommandHandlerServicer,
    PassThroughUpcaster,
    UpcasterServicer,
)
from angzarr_blackjack.table.agg.handler import TableAggregate

DOMAIN = "table"
DEFAULT_PORT = "50402"


def build_host(router: _az.Router) -> AggregateHost:
    """The TableAggregate registered on ``router``."""
    return AggregateHost(router, new_table_aggregate_dispatch(TableAggregate()))


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        run_server(
            _ch_grpc.add_CommandHandlerServiceServicer_to_server,
            CommandHandlerServicer(build_host(router)),
            service_name="agg-table",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
            extra_servicers=[
                (
                    _up_grpc.add_UpcasterServiceServicer_to_server,
                    UpcasterServicer(PassThroughUpcaster()),
                )
            ],
        )


if __name__ == "__main__":
    main()
