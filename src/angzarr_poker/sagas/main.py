"""Saga service entrypoint (hosts every poker saga).

Transport model: the angzarr **saga coordinator** subscribes to the bus and
calls this service's ``SagaService.Handle`` with a ``SagaHandleRequest`` (the
source event book + destination sequences). The servicer hands it to the
in-process FFI ``Router.dispatch_saga``, which routes the source — by its cover
domain — to every registered saga that consumes that domain (the multi-saga
routing the core supports), and returns a ``SagaResponse`` of emitted command
books. The coordinator forwards those commands to their target aggregates.

One service hosts every poker saga: ``table``-sourced (TableHandSaga,
TablePlayerSaga, TableTournamentSaga), ``hand``-sourced (HandTableSaga,
HandPlayerSaga), and ``tournament``-sourced (TournamentTableSaga). The core
keys dispatch on the source cover domain, so a single registry serves the
table, hand, and tournament saga coordinators.
"""

from __future__ import annotations

import grpc
import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server

from angzarr_poker._gen.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_poker._gen.io.angzarr.v1 import saga_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.table_hand_saga_angzarr import (
    register_table_hand_saga,
)
from angzarr_poker._gen.io.angzarr.examples.v1.table_player_saga_angzarr import (
    register_table_player_saga,
)
from angzarr_poker._gen.io.angzarr.examples.v1.hand_table_saga_angzarr import (
    register_hand_table_saga,
)
from angzarr_poker._gen.io.angzarr.examples.v1.hand_player_saga_angzarr import (
    register_hand_player_saga,
)
from angzarr_poker._gen.io.angzarr.examples.v1.table_tournament_saga_angzarr import (
    register_table_tournament_saga,
)
from angzarr_poker._gen.io.angzarr.examples.v1.tournament_table_saga_angzarr import (
    register_tournament_table_saga,
)
from angzarr_poker.sagas.table_hand import TableHandSaga
from angzarr_poker.sagas.table_player import TablePlayerSaga
from angzarr_poker.sagas.hand_table import HandTableSaga
from angzarr_poker.sagas.hand_player import HandPlayerSaga
from angzarr_poker.sagas.table_tournament import TableTournamentSaga
from angzarr_poker.sagas.tournament_table import TournamentTableSaga

DOMAIN = "saga"
DEFAULT_PORT = "50410"

_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}


def _grpc_status(code: int) -> grpc.StatusCode:
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


class SagaServicer(saga_pb2_grpc.SagaServiceServicer):
    """gRPC adapter over the FFI router's saga dispatch. ``Handle`` runs one
    ``SagaHandleRequest`` through ``Router.dispatch_saga`` and translates a
    business ``CodedError`` into its carried gRPC status."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        try:
            return self._router.dispatch_saga(request)
        except _az.CodedError as exc:
            # The saga coordinator subscribes to ALL events (SubscriberAll) and
            # delivers them to this one queue, so we routinely see events whose
            # source domain has no registered saga (e.g. player events — no
            # player-sourced saga). That is not a failure: it is simply not ours
            # to act on. Return an empty response so the coordinator ACKs and
            # moves on; aborting UNIMPLEMENTED makes it NACK + requeue forever,
            # a redelivery storm that starves the events we DO handle.
            if exc.grpc == grpc.StatusCode.UNIMPLEMENTED.value[0]:
                return _saga.SagaResponse()
            context.abort(_grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


def build_router() -> _az.Router:
    """An FFI router with every poker saga registered. Caller owns close()."""
    router = _az.Router()
    register_table_hand_saga(router, TableHandSaga())
    register_table_player_saga(router, TablePlayerSaga())
    register_hand_table_saga(router, HandTableSaga())
    register_hand_player_saga(router, HandPlayerSaga())
    register_table_tournament_saga(router, TableTournamentSaga())
    register_tournament_table_saga(router, TournamentTableSaga())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            saga_pb2_grpc.add_SagaServiceServicer_to_server,
            SagaServicer(router),
            service_name="saga-poker",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
