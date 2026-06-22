"""Table bounded-context service entrypoint.

Transport model: **Python owns the executable and the gRPC server; the
angzarr_router_ffi core does the dispatch.** A command arrives over gRPC as a
``ContextualCommand``; the servicer hands it to the in-process FFI
``Router.dispatch`` (a C-ABI cdylib), which rebuilds state (snapshot or replay),
stamps sequences, and **calls back into the Python business logic**
(``TableAggregate``) before returning a ``BusinessResponse``. There is one GIL,
re-acquired for the callback — not an additional one.

We reuse angzarr-client's ``run_server`` bootstrap (health, reflection, port).
The servicer below mirrors ``angzarr_client.router.server.CommandHandlerGrpc``
but maps the FFI's ``CodedError`` onto the proper gRPC status (the stock adapter
predates the FFI core and would collapse rejections to INTERNAL).
"""

from __future__ import annotations

import grpc
import structlog

import angzarr_router_ffi as _az
from angzarr_client import configure_logging
from angzarr_client.server import run_server

from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
    register_table_aggregate,
)
from angzarr_poker.table.handler import TableAggregate

DOMAIN = "table"
DEFAULT_PORT = "50402"

# GrpcCode integers (3=INVALID_ARGUMENT, 5=NOT_FOUND, 9=FAILED_PRECONDITION,
# 13=INTERNAL, ...) are the canonical gRPC status numbers; map by value.
_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}


def _grpc_status(code: int) -> grpc.StatusCode:
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


class CommandHandlerServicer(command_handler_pb2_grpc.CommandHandlerServiceServicer):
    """gRPC adapter over the FFI router. ``Handle``/``HandleSync`` both run one
    ``ContextualCommand`` through ``Router.dispatch`` and translate a business
    ``CodedError`` into its carried gRPC status."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def HandleSync(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def _dispatch(self, request, context):
        try:
            return self._router.dispatch(request)
        except _az.CodedError as exc:
            context.abort(_grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


def build_router() -> _az.Router:
    """An FFI router with the Table aggregate registered. Caller owns close()."""
    router = _az.Router()
    register_table_aggregate(router, TableAggregate())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            command_handler_pb2_grpc.add_CommandHandlerServiceServicer_to_server,
            CommandHandlerServicer(router),
            service_name="table-agg",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
