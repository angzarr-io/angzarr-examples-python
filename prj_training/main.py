"""Training data projector gRPC service.

Subscribes to hand domain events and materializes training states
to PostgreSQL for AI model training.
"""

import os
import sys
from pathlib import Path

import structlog

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from prj_training.projector import TrainingProjector

from angzarr_client.projector_handler import ProjectorHandler, run_projector_server

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


def main():
    """Run the training projector gRPC service."""
    logger.info(
        "training_projector_starting",
        database=DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        port=PORT,
    )

    # Create the projector with database connection
    projector = TrainingProjector(DATABASE_URL)

    # Create handler that subscribes to hand domain
    handler = ProjectorHandler(
        "prj-training",
        "hand",  # Subscribe to hand domain events
    ).with_handle(projector.handle)

    run_projector_server(
        name="prj-training",
        default_port=PORT,
        handler=handler,
        logger=logger,
    )


if __name__ == "__main__":
    main()
