"""saga-table-player: the three table -> player sagas (settlement facts,
round history, loyalty) on one host, whose router routes every table event
to the sagas declaring it."""

from __future__ import annotations

import os

from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_history_saga_angzarr import (
    new_table_player_history_saga_dispatch,
)
from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_loyalty_saga_angzarr import (
    new_table_player_loyalty_saga_dispatch,
)
from angzarr_blackjack._gen.io.angzarr.examples.v1.table_player_settlement_saga_angzarr import (
    new_table_player_settlement_saga_dispatch,
)
from angzarr_blackjack.table.saga_player.handler import (
    TablePlayerHistorySaga,
    TablePlayerLoyaltySaga,
    TablePlayerSettlementSaga,
)
from angzarr_client import ComponentHost, configure_logging

DEFAULT_PORT = "50412"


def register(host: ComponentHost) -> ComponentHost:
    """The settlement, history and loyalty sagas on ``host``."""
    return (
        host.add_saga(
            new_table_player_settlement_saga_dispatch(TablePlayerSettlementSaga())
        )
        .add_saga(new_table_player_history_saga_dispatch(TablePlayerHistorySaga()))
        .add_saga(new_table_player_loyalty_saga_dispatch(TablePlayerLoyaltySaga()))
    )


def main() -> None:
    configure_logging()
    os.environ.setdefault("PORT", DEFAULT_PORT)
    register(ComponentHost()).run()


if __name__ == "__main__":
    main()
