"""Every blackjack component on one router, driven in process.

Registers each deployable's components exactly as its ``main`` does (each
``main.register``) on one ComponentHost that is never started, and exposes
the router's dispatch entry points by component kind. The in-process test
tier and the acceptance tier's state reader use it; nothing here decides a
business outcome.
"""

from __future__ import annotations

import angzarr_client.router as _az
from angzarr_client import ComponentHost
from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_client.proto.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

from angzarr_blackjack._gen.io.angzarr.examples.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack._runtime.books import unpack
from angzarr_blackjack.player.agg import main as player_main
from angzarr_blackjack.player.saga_table import main as player_table_main
from angzarr_blackjack.pmg_buy_in import main as buy_in_main
from angzarr_blackjack.prj_ledger import main as ledger_main
from angzarr_blackjack.prj_ledger.handler import Ledger
from angzarr_blackjack.table.agg import main as table_main
from angzarr_blackjack.table.saga_player import main as table_player_main

STATES = {
    player_main.DOMAIN: _p.PlayerState,
    table_main.DOMAIN: _table.TableState,
    buy_in_main.DOMAIN: _b.BuyInState,
}


class InProcess:
    """The components of all six deployables on one router."""

    def __init__(self) -> None:
        self.router = _az.Router()
        self.ledger = Ledger()
        host = ComponentHost(self.router)
        player_main.register(host)
        table_main.register(host)
        buy_in_main.register(host)
        player_table_main.register(host)
        table_player_main.register(host)
        ledger_main.register(host, self.ledger)

    def close(self) -> None:
        self.router.close()

    def handle(self, command: _t.ContextualCommand) -> _ch.BusinessResponse:
        """A command or notification envelope for an aggregate."""
        return self.router.dispatch(command)

    def handle_fact(self, request: _ch.FactRequest) -> _t.EventBook:
        return self.router.dispatch_fact(request)

    def handle_saga(self, request: _saga.SagaHandleRequest) -> _saga.SagaResponse:
        return self.router.dispatch_saga(request)

    def handle_process(
        self, request: _pm.ProcessManagerHandleRequest
    ) -> _pm.ProcessManagerHandleResponse:
        return self.router.dispatch_process_manager(request)

    def project(self, book: _t.EventBook) -> _t.Projection:
        return self.router.dispatch_projector(book)

    def rebuild(self, domain: str, book: _t.EventBook | None):
        """The state of ``domain``'s aggregate or process manager after
        ``book`` (its snapshot, then its pages), rebuilt by Replay."""
        request = _ch.ReplayRequest()
        if book is not None:
            if book.HasField("snapshot"):
                request.base_snapshot.CopyFrom(book.snapshot)
            request.events.extend(book.pages)
        state = self.router.dispatch_replay(domain, request).state
        return unpack(state, STATES[domain])
