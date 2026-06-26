"""Output projector service entrypoint (cross-domain narrator).

The cross-domain OutputProjector narrator (auxiliary rendered view). The angzarr
projector coordinator calls ProjectorService.Handle with an EventBook, folded
through Router.dispatch_projector; the rendered display lives in the handler's
in-process sink, so the response is an acknowledgement.
"""

from __future__ import annotations

import structlog

import angzarr_router_ffi as _az
from angzarr_poker._runtime.server import configure_logging, run_server
from angzarr_poker._runtime.servicers import ProjectorServicer

from angzarr_poker._gen.io.angzarr.v1 import projector_pb2_grpc
from angzarr_poker._gen.io.angzarr.examples.v1.output_projector_angzarr import (
    register_output_projector,
)
from angzarr_poker._shared.projectors.output.handler import OutputProjector

DOMAIN = "hand"
DEFAULT_PORT = "50491"


def build_router() -> _az.Router:
    """An FFI router with the OutputProjector registered. Caller owns close()."""
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
