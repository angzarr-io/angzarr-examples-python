"""Buy-in process manager gRPC server.

This module runs the buy-in PM that coordinates Player <-> Table buy-ins.
"""

import structlog

from angzarr_client.process_manager_handler import (
    ProcessManagerHandler,
    run_process_manager_server,
)
from handlers import BuyInPM

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
    handler = ProcessManagerHandler(BuyInPM)
    run_process_manager_server(handler, "50392", logger=logger)
