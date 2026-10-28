"""The blackjack components on one router, driven in process.

Registers each deployable's components exactly as its ``main`` does (each
``main.register``) on one ComponentHost that is never started, and exposes
the router's dispatch entry points. The in-process test tier uses it; nothing
here decides a business outcome.

On this branch the only deployable is agg-table (the stage-1 slice); the
others wait on the blackjack rulings R1-R4 (see the README).
"""

from __future__ import annotations

import angzarr_client.router as _az
from angzarr_client import ComponentHost
from angzarr_client.proto.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

from angzarr_blackjack.table.agg import main as table_main


class InProcess:
    """The components of every deployable on one router."""

    def __init__(self) -> None:
        self.router = _az.Router()
        host = ComponentHost(self.router)
        table_main.register(host)

    def close(self) -> None:
        self.router.close()

    def handle(self, command: _t.ContextualCommand) -> _ch.CommandHandlerResponse:
        """A command envelope for an aggregate: its events and, always, the
        post-command state in ``events.snapshot.state``."""
        return self.router.dispatch(command)
