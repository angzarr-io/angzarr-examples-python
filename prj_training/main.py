"""Training data projector gRPC service.

Subscribes to hand domain events and materializes training states
to PostgreSQL for AI model training.
"""

import os
import sys
from pathlib import Path

import grpc
import structlog

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from prj_training.projector import TrainingProjector

from angzarr_client import run_server
from angzarr_client.proto.angzarr import projector_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# Configuration from environment
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://angzarr:angzarr@localhost:5432/angzarr",
)
PORT = os.environ.get("PORT", "50491")


class _TrainingProjectorServicer(projector_pb2_grpc.ProjectorServiceServicer):
    """gRPC adapter for the stateful TrainingProjector.

    The TrainingProjector requires book-level cover metadata (hand_root,
    edition) that the generic Router per-event dispatch does not propagate.
    This servicer forwards whole EventBooks to the projector's handle method.
    """

    def __init__(self, projector: TrainingProjector) -> None:
        self._projector = projector

    def Handle(
        self, request: types.EventBook, context: grpc.ServicerContext
    ) -> types.Projection:
        return self._projector.handle(request)

    def HandleSpeculative(
        self, request: types.EventBook, context: grpc.ServicerContext
    ) -> types.Projection:
        return self._projector.handle(request)


def main():
    """Run the training projector gRPC service."""
    logger.info(
        "training_projector_starting",
        database=DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        port=PORT,
    )

    projector_instance = TrainingProjector(DATABASE_URL)
    servicer = _TrainingProjectorServicer(projector_instance)

    run_server(
        projector_pb2_grpc.add_ProjectorServiceServicer_to_server,
        servicer,
        service_name="prj-training",
        domain="hand",
        default_port=PORT,
        logger=logger,
    )


if __name__ == "__main__":
    main()
