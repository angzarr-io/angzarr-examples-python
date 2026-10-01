"""saga-table-player: the three table → player sagas (settlement facts,
round history, loyalty), each registered on one router that routes every
table event to the sagas declaring it."""

from __future__ import annotations

import structlog

import angzarr_client.router as _az
from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_history_saga_angzarr import (
    register_table_player_history_saga,
)
from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_loyalty_saga_angzarr import (
    register_table_player_loyalty_saga,
)
from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_settlement_saga_angzarr import (
    register_table_player_settlement_saga,
)
from angzarr_client.proto.io.angzarr.v1 import saga_pb2_grpc as _saga_grpc
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import SagaServicer
from angzarr_blackjack.table.saga_player.handler import (
    TablePlayerHistorySaga,
    TablePlayerLoyaltySaga,
    TablePlayerSettlementSaga,
)

DEFAULT_PORT = "50412"


def register(router: _az.Router) -> None:
    register_table_player_settlement_saga(router, TablePlayerSettlementSaga())
    register_table_player_history_saga(router, TablePlayerHistorySaga())
    register_table_player_loyalty_saga(router, TablePlayerLoyaltySaga())


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        register(router)
        run_server(
            _saga_grpc.add_SagaServiceServicer_to_server,
            SagaServicer(router),
            service_name="saga-table-player",
            domain="table",
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
        )


if __name__ == "__main__":
    main()
