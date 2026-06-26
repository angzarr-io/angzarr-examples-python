"""TablePlayerSaga service entrypoint.

Per-component saga service: the angzarr saga coordinator (bound SubscriberAll)
calls SagaService.Handle; the servicer routes through Router.dispatch_saga to the
one registered saga and ACK-skips events it does not consume.
"""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server
from angzarr_poker._runtime.servicers import SagaServicer

from angzarr_poker._gen.io.angzarr.v1 import saga_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.table_player_saga_angzarr import (
    register_table_player_saga,
)
from angzarr_poker.table.sagas.table_player.handler import TablePlayerSaga

DOMAIN = "table"
DEFAULT_PORT = "50412"


def build_router() -> _az.Router:
    """An FFI router with the TablePlayerSaga registered. Caller owns close()."""
    router = _az.Router()
    register_table_player_saga(router, TablePlayerSaga())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            saga_pb2_grpc.add_SagaServiceServicer_to_server,
            SagaServicer(router),
            service_name="saga-table-player",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
