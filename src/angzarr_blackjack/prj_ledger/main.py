"""projector-player-table-ledger: the LedgerProjector and LedgerQueryService."""

from __future__ import annotations

import structlog

import angzarr_client.router as _az
from angzarr_blackjack._gen.io.angzarr.examples.v1 import (
    ledger_pb2_grpc as _l_grpc,
)
from angzarr_blackjack._gen.io.angzarr.examples.v1.ledger_projector_angzarr import (
    new_ledger_projector_dispatch,
)
from angzarr_client.proto.io.angzarr.v1 import projector_pb2_grpc as _prj_grpc
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import ProjectorServicer
from angzarr_blackjack.prj_ledger.handler import LedgerProjectorHost
from angzarr_blackjack.prj_ledger.query import LedgerQueryServicer

DEFAULT_PORT = "50431"


def build_host(router: _az.Router) -> LedgerProjectorHost:
    return LedgerProjectorHost(router, new_ledger_projector_dispatch)


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        host = build_host(router)
        run_server(
            _prj_grpc.add_ProjectorServiceServicer_to_server,
            ProjectorServicer(host),
            service_name="projector-player-table-ledger",
            domain="ledger",
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
            extra_servicers=[
                (
                    _l_grpc.add_LedgerQueryServiceServicer_to_server,
                    LedgerQueryServicer(host.ledger),
                )
            ],
        )


if __name__ == "__main__":
    main()
