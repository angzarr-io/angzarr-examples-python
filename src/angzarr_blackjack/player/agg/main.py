"""agg-player: the PlayerAggregate and the PlayerUpcaster on one server."""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1.player_aggregate_angzarr import (
    new_player_aggregate_dispatch,
)
from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
from angzarr_blackjack._gen.io.angzarr.v1 import upcaster_pb2_grpc as _up_grpc
from angzarr_blackjack._runtime.hosts import AggregateHost, typed_fact
from angzarr_blackjack._runtime.server import configure_logging, run_server
from angzarr_blackjack._runtime.servicers import (
    CommandHandlerServicer,
    UpcasterServicer,
)
from angzarr_blackjack.player.agg.handler import PlayerAggregate
from angzarr_blackjack.player.agg.upcaster import PlayerUpcaster

DOMAIN = "player"
DEFAULT_PORT = "50401"


def build_host(router: _az.Router) -> AggregateHost:
    """The PlayerAggregate registered on ``router``, with its facts and undo."""
    handler = PlayerAggregate()
    return AggregateHost(
        router,
        new_player_aggregate_dispatch(handler),
        facts={
            _p.TopUpSettled.DESCRIPTOR.full_name: typed_fact(
                _p.TopUpSettled, handler.handle_top_up_settled
            ),
            _p.CashOutCredited.DESCRIPTOR.full_name: typed_fact(
                _p.CashOutCredited, handler.handle_cash_out_credited
            ),
        },
        undo={
            _p.RecordRoundResult.DESCRIPTOR.full_name: handler.on_record_round_result_undo
        },
    )


def main() -> None:
    configure_logging()
    with _az.Router() as router:
        host = build_host(router)
        run_server(
            _ch_grpc.add_CommandHandlerServiceServicer_to_server,
            CommandHandlerServicer(host),
            service_name="agg-player",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=structlog.get_logger(),
            extra_servicers=[
                (
                    _up_grpc.add_UpcasterServiceServicer_to_server,
                    UpcasterServicer(PlayerUpcaster()),
                )
            ],
        )


if __name__ == "__main__":
    main()
