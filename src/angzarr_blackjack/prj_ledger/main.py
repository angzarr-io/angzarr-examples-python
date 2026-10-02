"""projector-player-table-ledger: the LedgerProjector and LedgerQueryService."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2_grpc as _l_grpc
from angzarr_blackjack._gen.io.angzarr.examples.v1.ledger_projector_angzarr import (
    new_ledger_projector_dispatch,
)
from angzarr_blackjack.prj_ledger.handler import Ledger, LedgerProjector
from angzarr_blackjack.prj_ledger.query import LedgerQueryServicer
from angzarr_client import ComponentHost, configure_logging

DEFAULT_PORT = "50431"
QUERY_SERVICE = _l.DESCRIPTOR.services_by_name["LedgerQueryService"].full_name


def register(host: ComponentHost, ledger: Ledger) -> ComponentHost:
    """The LedgerProjector over ``ledger`` and the LedgerQueryService on
    ``host``. Every delivery folds into the one ledger."""
    dispatch = new_ledger_projector_dispatch(LedgerProjector(ledger))
    dispatch.factory = lambda: ledger.projection
    return host.add_projector(dispatch).add_service(
        _l_grpc.add_LedgerQueryServiceServicer_to_server,
        LedgerQueryServicer(ledger),
        QUERY_SERVICE,
    )


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    # One worker: every delivery folds into the shared ledger in turn.
    register(ComponentHost(max_workers=1), Ledger()).run()


if __name__ == "__main__":
    main()
