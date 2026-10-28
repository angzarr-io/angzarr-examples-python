"""In-process coordinator over the real blackjack components.

Every component on this branch (the table, the stage-1 slice) is registered
on one router (``angzarr_blackjack._runtime.inprocess``) exactly as its
deployable registers it (each ``main.register``). The :class:`World` plays
the aggregate coordinator's part in memory: it keeps each aggregate's event
stream, loads the prior history for every command, persists what the
component returns with framework-stamped sequences, and keeps the post-command
state every response carries (``events.snapshot.state``) as the aggregate's
current state. Nothing in it decides a
business outcome; it only moves messages to the component and back.

Entity roots are ``uuid5(NAMESPACE_OID, "<kind>:<label>")`` (kind ``table``
here), so every language derives the same bytes from the same scenario.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import angzarr_client.router as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack._runtime.inprocess import InProcess

TABLE = "table"
STATES = {TABLE: _table.TableState}


def root_of(kind: str, label: str) -> bytes:
    return uuid.uuid5(uuid.NAMESPACE_OID, f"{kind}:{label}").bytes


def table_root(name: str) -> bytes:
    return root_of(TABLE, name)


def cover(domain: str, root: bytes) -> _t.Cover:
    c = _t.Cover(domain=domain)
    c.root.value = root
    return c


@dataclass
class Outcome:
    """What one command did to its aggregate."""

    events: list = field(default_factory=list)  # persisted EventPages
    error: _az.CodedError | None = None

    def decoded(self, message_class) -> list:
        name = message_class.DESCRIPTOR.full_name
        return [
            unpack(p.payload, message_class)
            for p in self.events
            if type_name(p.payload.type_url) == name
        ]

    def types(self) -> list[str]:
        return [type_name(p.payload.type_url).rsplit(".", 1)[-1] for p in self.events]


class World:
    """One scenario's in-process deployment."""

    def __init__(self) -> None:
        self.components = InProcess()
        self.streams: dict[tuple[str, bytes], list[_t.EventPage]] = {}
        self.states: dict[tuple[str, bytes], object] = {}
        self.last = Outcome()

    def close(self) -> None:
        self.components.close()

    # --- streams --------------------------------------------------------------

    def stream(self, domain: str, root: bytes) -> list[_t.EventPage]:
        return self.streams.setdefault((domain, root), [])

    def book(self, domain: str, root: bytes) -> _t.EventBook:
        """What a coordinator loads for ``(domain, root)``: every page."""
        book = _t.EventBook(cover=cover(domain, root))
        book.pages.extend(self.stream(domain, root))
        book.next_sequence = len(self.stream(domain, root))
        return book

    def state(self, domain: str, root: bytes):
        """The aggregate's state after its last command (empty before any)."""
        return self.states.get((domain, root)) or STATES[domain]()

    def _persist(self, domain: str, root: bytes, book: _t.EventBook):
        stream = self.stream(domain, root)
        out = []
        now = Timestamp()
        now.GetCurrentTime()
        for source in book.pages:
            page = _t.EventPage()
            page.CopyFrom(source)
            page.sequence = len(stream)
            page.meta.recorded_at.CopyFrom(now)
            stream.append(page)
            out.append(page)
        if book.HasField("snapshot"):
            self.states[(domain, root)] = unpack(book.snapshot.state, STATES[domain])
        return out

    # --- commands -------------------------------------------------------------

    def command(self, domain: str, root: bytes, message) -> Outcome:
        """A client command with an explicit expected sequence."""
        book = _t.CommandBook(cover=cover(domain, root))
        book.handling.expected_sequence = len(self.stream(domain, root))
        book.page.command.payload.CopyFrom(_az.pack(message))
        contextual = _t.ContextualCommand(events=self.book(domain, root), command=book)
        try:
            response = self.components.handle(contextual)
        except _az.CodedError as err:
            self.last = Outcome(error=err)
            return self.last
        pages = (
            self._persist(domain, root, response.events)
            if response.HasField("events")
            else []
        )
        self.last = Outcome(events=pages)
        return self.last
