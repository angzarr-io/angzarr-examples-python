"""saga-player-table: PlayerTableSaga."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1.player_table_saga_angzarr import (
    register_player_table_saga,
)
from angzarr_blackjack._gen.io.angzarr.v1 import saga_pb2_grpc as _saga_grpc
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import SagaServicer
from angzarr_blackjack.player.saga_table.handler import PlayerTableSaga

DEFAULT_PORT = "50411"


def register(router: _az.Router) -> None:
    register_player_table_saga(router, PlayerTableSaga())


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        register(router)
        run_server(
            _saga_grpc.add_SagaServiceServicer_to_server,
            SagaServicer(router),
            service_name="saga-player-table",
            domain="player",
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
        )


if __name__ == "__main__":
    main()
