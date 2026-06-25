"""gRPC server bootstrap for the poker example's bounded-context services.

Self-contained: depends only on ``grpcio`` + ``grpcio-health-checking`` +
``structlog`` (no external client library). Supports TCP (default) and Unix
Domain Socket transports, and registers a standard ``grpc.health.v1.Health``
service so the cluster can probe readiness.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent import futures

import grpc
import structlog
from grpc_health.v1 import health, health_pb2, health_pb2_grpc


def configure_logging() -> None:
    """Configure structlog with JSON rendering and ISO timestamps."""
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


def _transport_config() -> tuple[str, str]:
    """Resolve (transport_type, bind_address) from the environment.

    TRANSPORT_TYPE=tcp (default) binds ``[::]:$PORT``; TRANSPORT_TYPE=uds binds
    a Unix socket under UDS_BASE_PATH (default /tmp/angzarr), named by
    SERVICE_NAME and the DOMAIN/SAGA_NAME/PROJECTOR_NAME qualifier.
    """
    transport = os.environ.get("TRANSPORT_TYPE", "tcp").lower()
    if transport != "uds":
        return ("tcp", f"[::]:{os.environ.get('PORT', '50052')}")

    base_path = os.environ.get("UDS_BASE_PATH", "/tmp/angzarr")
    service_name = os.environ.get("SERVICE_NAME", "business")
    qualifier = (
        os.environ.get("DOMAIN")
        or os.environ.get("SAGA_NAME")
        or os.environ.get("PROJECTOR_NAME")
        or ""
    )
    socket_path = (
        f"{base_path}/{service_name}-{qualifier}.sock"
        if qualifier
        else f"{base_path}/{service_name}.sock"
    )
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)
    if os.path.exists(socket_path):
        os.remove(socket_path)
    return ("uds", f"unix:{socket_path}")


def create_server(
    add_servicer_func: Callable,
    servicer: object,
    service_name: str = "",
    max_workers: int = 10,
    extra_servicers: list[tuple[Callable, object]] | None = None,
) -> tuple[grpc.Server, str]:
    """Build a gRPC server with the servicer + a health service registered.

    Returns (server, bind_address). The health service reports SERVING for the
    empty service name and, when given, for ``service_name``.

    ``extra_servicers`` registers additional (add_func, servicer) pairs on the
    same port — e.g. a projector process serving both the framework
    ProjectorService and an example read-model query service.
    """
    _, address = _transport_config()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    add_servicer_func(servicer, server)
    for add_func, extra in extra_servicers or ():
        add_func(extra, server)

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    if service_name:
        health_servicer.set(service_name, health_pb2.HealthCheckResponse.SERVING)

    server.add_insecure_port(address)
    return server, address


def run_server(
    add_servicer_func: Callable,
    servicer: object,
    service_name: str = "",
    domain: str = "",
    default_port: str = "50052",
    logger=None,
    extra_servicers: list[tuple[Callable, object]] | None = None,
) -> None:
    """Run a gRPC server until termination.

    PORT defaults to ``default_port`` when unset. ``domain`` is for logging only.
    ``extra_servicers`` co-hosts additional (add_func, servicer) pairs.
    """
    if "PORT" not in os.environ:
        os.environ["PORT"] = default_port

    server, address = create_server(
        add_servicer_func, servicer, service_name, extra_servicers=extra_servicers
    )
    transport_type = os.environ.get("TRANSPORT_TYPE", "tcp").lower()

    if logger:
        logger.info(
            "server_started",
            service=service_name,
            domain=domain,
            transport=transport_type,
            address=address,
        )
    else:
        print(
            f"Server started: {service_name} ({domain}) on {address} ({transport_type})"
        )

    server.start()
    server.wait_for_termination()
