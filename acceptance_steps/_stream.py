"""Scenario-scoped view of the cluster's event bus.

Consumes the ``angzarr.events`` topic exchange (every persisted EventBook) and
the ``angzarr.dlq`` exchange (dead letters) on an exclusive queue, and keeps
what belongs to the current scenario: books whose correlation id starts with
the scenario's nonce. Steps wait on it with :meth:`EventStreamSubscriber.wait`
instead of sleeping or keeping their own record.

The AMQP URL comes from ``AMQP_URL``, or from the ``angzarr-mq`` secret and a
``kubectl port-forward`` to ``svc/angzarr-mq``.
"""

from __future__ import annotations

import base64
import logging
import os
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

_LOG = logging.getLogger(__name__)
EVENTS_EXCHANGE = "angzarr.events"
DLQ_EXCHANGE = "angzarr.dlq"


@dataclass(frozen=True)
class Delivered:
    domain: str
    root: bytes
    correlation: str
    page: _t.EventPage


class EventStreamSubscriber:
    """Background AMQP consumer with a per-scenario buffer."""

    def __init__(self, amqp_url: str) -> None:
        self._url = amqp_url
        self._queue = f"blackjack-acceptance-{uuid.uuid4().hex}"
        self._cv = threading.Condition()
        self._prefix = ""
        self.events: list[Delivered] = []
        self.dead_letters: list[_t.AngzarrDeadLetter] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="event-stream", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def scope(self, prefix: str) -> None:
        """Keep only books whose correlation starts with ``prefix``; forget the rest."""
        with self._cv:
            self._prefix = prefix
            self.events.clear()
            self.dead_letters.clear()

    def wait(self, predicate: Callable[[list[Delivered]], object], within: float):
        """Block until ``predicate(events)`` is truthy; return its value."""
        deadline = time.monotonic() + within
        with self._cv:
            while True:
                result = predicate(list(self.events))
                if result:
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(
                        f"not seen on the event stream within {within}s"
                    )
                self._cv.wait(timeout=remaining)

    def _run(self) -> None:
        import pika

        while not self._stop.is_set():
            try:
                connection = pika.BlockingConnection(pika.URLParameters(self._url))
                channel = connection.channel()
                queue = channel.queue_declare(
                    queue=self._queue, exclusive=True, auto_delete=True
                ).method.queue
                channel.exchange_declare(
                    exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True
                )
                channel.exchange_declare(
                    exchange=DLQ_EXCHANGE, exchange_type="topic", durable=True
                )
                channel.queue_bind(
                    exchange=EVENTS_EXCHANGE, queue=queue, routing_key="#"
                )
                channel.queue_bind(exchange=DLQ_EXCHANGE, queue=queue, routing_key="#")
                channel.basic_consume(
                    queue=queue, on_message_callback=self._on_message, auto_ack=True
                )
                while not self._stop.is_set():
                    connection.process_data_events(time_limit=1)
                connection.close()
            except (
                Exception
            ) as exc:  # noqa: BLE001 — reconnect on any transport failure
                _LOG.warning("event stream reconnecting: %s", exc)
                self._stop.wait(1.0)

    def _on_message(self, _channel, method, _properties, body: bytes) -> None:
        with self._cv:
            if method.exchange == DLQ_EXCHANGE:
                letter = _t.AngzarrDeadLetter()
                letter.ParseFromString(body)
                if letter.cover.correlation_id.startswith(self._prefix):
                    self.dead_letters.append(letter)
            else:
                book = _t.EventBook()
                book.ParseFromString(body)
                corr = book.cover.correlation_id
                if not self._prefix or not corr.startswith(self._prefix):
                    return
                for page in book.pages:
                    self.events.append(
                        Delivered(book.cover.domain, book.cover.root.value, corr, page)
                    )
            self._cv.notify_all()


def amqp_url() -> tuple[str, subprocess.Popen | None]:
    """``AMQP_URL``, or a port-forward to ``svc/angzarr-mq`` with the password
    from ``secret/angzarr-mq``."""
    explicit = os.environ.get("AMQP_URL")
    if explicit:
        return explicit, None
    namespace = os.environ.get("ANGZARR_NAMESPACE", "angzarr")
    password = os.environ.get("AMQP_PASSWORD") or _secret_password(namespace)
    if not password:
        raise RuntimeError(
            f"no AMQP password: set AMQP_PASSWORD or allow reading secret/angzarr-mq in {namespace}"
        )
    with socket.socket() as probe:
        probe.bind(("", 0))
        port = probe.getsockname()[1]
    forward = subprocess.Popen(
        ["kubectl", "port-forward", "-n", namespace, "svc/angzarr-mq", f"{port}:5672"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("localhost", port)) == 0:
                user = os.environ.get("AMQP_USER", "angzarr")
                return f"amqp://{user}:{password}@localhost:{port}/", forward
        time.sleep(0.1)
    forward.terminate()
    raise RuntimeError("kubectl port-forward to svc/angzarr-mq did not come up")


def _secret_password(namespace: str) -> str:
    try:
        out = subprocess.run(
            [
                "kubectl",
                "get",
                "secret",
                "-n",
                namespace,
                "angzarr-mq",
                "-o",
                "jsonpath={.data.rabbitmq-password}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        return base64.b64decode(out).decode().strip()
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        return ""
