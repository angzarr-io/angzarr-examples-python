"""Tournament bounded context gRPC server.

Uses the OO-style CommandHandler pattern with @handles/@applies decorators.
"""

import structlog

from angzarr_client import run_command_handler_server
from handlers import Tournament

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
    run_command_handler_server(Tournament, "50304", logger=logger)
