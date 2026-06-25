"""Player projector service entrypoint (PlayerProjector + read-model query).

Per-domain projector: the angzarr projector coordinator subscribes to the
``player`` topic and calls ``ProjectorService.Handle`` with player-domain
EventBooks, which fold through the FFI ``Router.dispatch_projector`` into the
PlayerProjector's bankroll read model.

This process ALSO serves the example-specific ``PlayerProjectionQueryService``
on the same gRPC port, reading that live read model — the read surface the
framework's fold-only ProjectorService does not provide. A client (the cluster
acceptance harness) queries it to observe read-model eventual consistency from
outside the write side (EA-0004).
"""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server

from angzarr_poker._gen.io.angzarr.v1 import projector_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1 import (
    player_projection_query_pb2 as _q,
)
from angzarr_poker._gen.io.angzarr.examples.v1 import (
    player_projection_query_pb2_grpc as _q_grpc,
)
from angzarr_poker._gen.io.angzarr.examples.v1.player_projector_angzarr import (
    register_player_projector,
)
from angzarr_poker.projectors.main import ProjectorServicer
from angzarr_poker.projectors.player_balance import PlayerProjector

DOMAIN = "player"
DEFAULT_PORT = "50492"


class PlayerBalanceQueryServicer(_q_grpc.PlayerProjectionQueryServiceServicer):
    """Serves the bankroll read model from the live PlayerProjector instance."""

    def __init__(self, projector: PlayerProjector) -> None:
        self._projector = projector

    def GetPlayerBalance(self, request, context):  # noqa: N802 — gRPC method name
        row = self._projector.balance_for(request.player_root)
        if row is None:
            return _q.PlayerBalanceView(player_root=request.player_root, found=False)
        return _q.PlayerBalanceView(
            player_root=row.player_root,
            display_name=row.display_name,
            balance=row.balance,
            found=True,
        )


def build_router(projector: PlayerProjector) -> _az.Router:
    """An FFI router with the Player projector registered. Caller owns close()."""
    router = _az.Router()
    register_player_projector(router, projector)
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    projector = PlayerProjector()
    with build_router(projector) as router:
        run_server(
            projector_pb2_grpc.add_ProjectorServiceServicer_to_server,
            ProjectorServicer(router),
            service_name="prj-player",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
            extra_servicers=[
                (
                    _q_grpc.add_PlayerProjectionQueryServiceServicer_to_server,
                    PlayerBalanceQueryServicer(projector),
                )
            ],
        )


if __name__ == "__main__":
    main()
