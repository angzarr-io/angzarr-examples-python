"""Registration process manager gRPC server.

This module runs the registration PM that coordinates Player <-> Tournament registrations.
"""

import structlog

from angzarr_client.process_manager_handler import (
    ProcessManagerHandler,
    run_process_manager_server,
)
from handlers import RegistrationPM

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


if __name__ == "__main__":
    handler = ProcessManagerHandler(RegistrationPM)
    run_process_manager_server(handler, "50394", logger=logger)
