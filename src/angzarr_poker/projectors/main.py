"""Projector service entrypoint (OutputProjector).

Transport model: the angzarr **projector coordinator** subscribes to the bus and
calls this service's ``ProjectorService.Handle`` with an ``EventBook``. The
servicer folds it through the in-process FFI ``Router.dispatch_projector`` and
returns a ``Projection`` envelope. The rendered read model lives in the
projector handler's own sink, not in the projection payload, so the response is
an acknowledgement; ``HandleSpeculative`` folds the same way for read-your-writes
previews.
"""

from __future__ import annotations

import grpc
import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server

from angzarr_poker._gen.io.angzarr.v1 import projector_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.output_projector_angzarr import (
    register_output_projector,
)
from angzarr_poker.projectors.output import OutputProjector

DOMAIN = "hand"
DEFAULT_PORT = "50491"

_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}


def _grpc_status(code: int) -> grpc.StatusCode:
    return _STATUS_BY_CODE.get(int(code), grpc.StatusCode.INTERNAL)


class ProjectorServicer(projector_pb2_grpc.ProjectorServiceServicer):
    """gRPC adapter over the FFI router's projector dispatch. ``Handle`` /
    ``HandleSpeculative`` both fold one ``EventBook`` through
    ``Router.dispatch_projector`` and translate a business ``CodedError`` into
    its carried gRPC status."""

    def __init__(self, router: _az.Router) -> None:
        self._router = router

    def Handle(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def HandleSpeculative(self, request, context):  # noqa: N802 — gRPC method name
        return self._dispatch(request, context)

    def _dispatch(self, request, context):
        try:
            return self._router.dispatch_projector(request)
        except _az.CodedError as exc:
            context.abort(_grpc_status(exc.grpc), exc.message)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            context.abort(grpc.StatusCode.INTERNAL, str(exc))


def build_router() -> _az.Router:
    """An FFI router with the Output projector registered. Caller owns close()."""
    router = _az.Router()
    register_output_projector(router, OutputProjector())
    return router


def main() -> None:
    configure_logging()
    logger = structlog.get_logger()
    with build_router() as router:
        run_server(
            projector_pb2_grpc.add_ProjectorServiceServicer_to_server,
            ProjectorServicer(router),
            service_name="prj-output",
            domain=DOMAIN,
            default_port=DEFAULT_PORT,
            logger=logger,
        )


if __name__ == "__main__":
    main()
