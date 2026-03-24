"""AI Player gRPC server entry point."""

from __future__ import annotations

import os
import signal
import sys
from concurrent import futures
from typing import NoReturn

import grpc
import structlog
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from ai_player.service import AiPlayerServicer, ServiceConfig

logger = structlog.get_logger()

# Default configuration
DEFAULT_PORT = 50500
DEFAULT_MAX_WORKERS = 10


def configure_logging() -> None:
    """Configure structlog for JSON output."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_server(config: ServiceConfig, port: int, max_workers: int) -> grpc.Server:
    """Create and configure the gRPC server.

    Args:
        config: Service configuration.
        port: Port to listen on.
        max_workers: Maximum number of worker threads.

    Returns:
        Configured gRPC server (not yet started).
    """
    # Import proto modules (generated from buf)
    # Using ai_sidecar proto until ai_player.proto is created
    from ai_player.proto.examples import ai_sidecar_pb2_grpc

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))

    # Register AI Player service (using ai_sidecar service definition)
    servicer = AiPlayerServicer(config)
    ai_sidecar_pb2_grpc.add_AiSidecarServicer_to_server(servicer, server)

    # Register health service
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("AiPlayer", health_pb2.HealthCheckResponse.SERVING)

    # Add insecure port
    server.add_insecure_port(f"[::]:{port}")

    return server


def run_server() -> NoReturn:
    """Run the AI Player gRPC server."""
    configure_logging()

    # Load configuration from environment
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    max_workers = int(os.environ.get("MAX_WORKERS", DEFAULT_MAX_WORKERS))

    config = ServiceConfig(
        model_path=os.environ.get("MODEL_PATH"),
        database_url=os.environ.get("DATABASE_URL"),
        device=os.environ.get("DEVICE", "cpu"),
    )

    logger.info(
        "starting_server",
        port=port,
        max_workers=max_workers,
        model_path=config.model_path,
        database_url=config.database_url is not None,
        device=config.device,
    )

    server = create_server(config, port, max_workers)
    server.start()

    logger.info("server_started", port=port)

    # Handle shutdown signals
    shutdown_event = False

    def handle_shutdown(signum: int, frame: object) -> None:
        nonlocal shutdown_event
        if not shutdown_event:
            shutdown_event = True
            logger.info("shutdown_requested", signal=signum)
            server.stop(grace=5)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Wait for termination
    server.wait_for_termination()
    logger.info("server_stopped")
    sys.exit(0)


if __name__ == "__main__":
    run_server()
