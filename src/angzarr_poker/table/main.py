"""Table bounded context service entrypoint.

The baseline (``table/agg/main.py``) wired the Table aggregate into a gRPC
``CommandHandlerService`` via the hand-written ``Router``/``CommandHandlerGrpc``
helpers and ``run_server``. The new harness uses the angzarr-cli generated seam
over the shared ``angzarr_router_ffi`` core: a process builds an in-process
:class:`angzarr_router_ffi.Router`, registers the aggregate dispatch generated
from ``table.proto`` (``register_table_aggregate``), and drives it via
``router.dispatch(contextual_command)``. The core owns folding, sequence
stamping, and the coded-error round trip.

``build_router`` is the reusable bootstrap (also handy for tests); ``main`` is
the process entrypoint.
"""

from __future__ import annotations

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
    register_table_aggregate,
)
from angzarr_poker.table.handler import TableAggregate

# Domain this aggregate owns (matches the generated AggregateDispatch domain).
DOMAIN = "table"


def build_router() -> _az.Router:
    """Construct a router with the Table aggregate registered.

    The caller owns the returned router and is responsible for ``close()``
    (or use it as a context manager)."""
    router = _az.Router()
    register_table_aggregate(router, TableAggregate())
    return router


def main() -> None:
    """Process entrypoint: build the router and hold it open to serve
    dispatches. The generated seam is registered against the shared router-ffi
    core; commands arrive as ``ContextualCommand`` and are run via
    ``router.dispatch(...)``."""
    with build_router() as router:  # noqa: F841 — held open for the service lifetime
        # The FFI router is driven in-process via ``router.dispatch(...)``; the
        # surrounding service shell (transport, lifecycle) lives outside this
        # generated-seam port. Keep the registered router alive for as long as
        # the service should accept commands.
        _serve_forever(router)


def _serve_forever(router: _az.Router) -> None:
    """Block, keeping the registered router alive. Replace with the deployment's
    transport loop (the FFI core exposes synchronous ``dispatch``; it carries no
    server of its own)."""
    import threading

    threading.Event().wait()


if __name__ == "__main__":
    main()
