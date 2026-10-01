"""LedgerQueryService: the read API over the ledger, served next to the
framework ProjectorService by the projector process."""

from __future__ import annotations

from angzarr_blackjack._gen.io.angzarr.examples.v1 import (
    ledger_pb2_grpc as _l_grpc,
)
from angzarr_blackjack.prj_ledger.handler import Ledger


class LedgerQueryServicer(_l_grpc.LedgerQueryServiceServicer):
    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def GetPlayerBalance(self, request, context):  # noqa: N802 — gRPC method name
        return self._ledger.player_view(request.player_root)

    def GetLedger(self, request, context):  # noqa: N802
        self._ledger.refresh_totals()
        return self._ledger.ledger_view()
