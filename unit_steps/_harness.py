"""Shared FFI harness for the poker unit step definitions.

Unit scenarios drive the angzarr-cli generated dispatch wiring through the real
``angzarr_router_ffi`` FFI core (a C-ABI cdylib), not by calling handler methods
directly. One ``World`` per scenario owns a ``Router`` with the ported component
handlers registered; steps build commands, seed prior state as an event history
the core folds, dispatch, and assert the emitted events or the coded rejection.

State is seeded as PRIOR EVENTS, not injected objects: the core rebuilds
aggregate state by folding the prior EventBook through the handler's appliers
before running the command — the same path production takes. "Given a table with
seated players" is therefore a TableCreated + PlayerJoined* history.

Only components whose handlers are ported onto the generated seam are registered
here (Table today); others are added as they land.
"""

from __future__ import annotations

import hashlib
from typing import Optional

import angzarr_router_ffi as _az
from angzarr_poker._gen.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t

# The framework's canonical Any type-URL prefix is a bare "/" (not the
# type.googleapis.com Any default); angzarr keys dispatch on it.
_TYPE_URL_PREFIX = "/"


def type_url(fq: str) -> str:
    return _TYPE_URL_PREFIX + fq


def fq_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def uuid_for(name: str) -> bytes:
    """A deterministic 16-byte root id for a named entity ("player-1"), so the
    same name maps to the same root across a scenario's steps."""
    return hashlib.sha256(name.encode()).digest()[:16]


class World:
    """One scenario's dispatch context: a router with the ported components
    registered, a prior-events history to rebuild over, and the last outcome."""

    def __init__(self) -> None:
        self.router = _az.Router()
        self._register_components()
        # Per-aggregate prior history, keyed by domain. Each is an EventBook the
        # next dispatch to that domain folds to rebuild state.
        self._prior: dict[str, _t.EventBook] = {}
        self.resp = None  # BusinessResponse from the last successful dispatch
        self.err: Optional[_az.CodedError] = None  # coded rejection, if any

    def _register_components(self) -> None:
        """Register every ported component handler. Extend as components land."""
        from angzarr_poker._gen.io.angzarr.examples.v1.hand_aggregate_angzarr import (
            register_hand_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
            register_table_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_hand_saga_angzarr import (
            register_table_hand_saga,
        )
        from angzarr_poker.hand.handler import HandAggregate
        from angzarr_poker.sagas.table_hand import TableHandSaga
        from angzarr_poker.table.handler import TableAggregate

        register_table_aggregate(self.router, TableAggregate())
        register_hand_aggregate(self.router, HandAggregate())
        register_table_hand_saga(self.router, TableHandSaga())

    # --- state seeding (prior events the core folds) ---

    def seed_event(self, domain: str, fq: str, event_msg) -> None:
        """Append one prior event to ``domain``'s rebuild history."""
        book = self._prior.get(domain)
        if book is None:
            book = _t.EventBook()
            book.cover.domain = domain
            self._prior[domain] = book
        page = book.pages.add()
        page.header.sequence = len(book.pages) - 1
        page.event.type_url = type_url(fq)
        page.event.value = event_msg.SerializeToString()
        book.next_sequence = len(book.pages)

    # --- dispatch + outcome ---

    def dispatch(self, domain: str, fq: str, cmd_msg) -> None:
        """Run one command through the core against the seeded history. Captures
        the BusinessResponse in ``resp`` or the rejection in ``err``."""
        self.resp = None
        self.err = None
        cc = _t.ContextualCommand()
        cc.command.cover.domain = domain
        page = cc.command.pages.add()
        page.command.type_url = type_url(fq)
        page.command.value = cmd_msg.SerializeToString()
        prior = self._prior.get(domain)
        if prior is not None:
            cc.events.CopyFrom(prior)
        try:
            self.resp = self.router.dispatch(cc)
        except _az.CodedError as exc:
            self.err = exc

    # --- saga dispatch (stateless event -> commands/events) ---

    def dispatch_saga(self, input_domain: str, fq: str, event_msg, dest_sequences=None) -> None:
        """Run one source event through a registered saga. Captures the
        SagaResponse in ``resp`` or the rejection in ``err``."""
        self.resp = None
        self.err = None
        req = _saga.SagaHandleRequest()
        req.source.cover.domain = input_domain
        page = req.source.pages.add()
        page.event.type_url = type_url(fq)
        page.event.value = event_msg.SerializeToString()
        for domain, seq in (dest_sequences or {}).items():
            req.destination_sequences[domain] = seq
        try:
            self.resp = self.router.dispatch_saga(req)
        except _az.CodedError as exc:
            self.err = exc

    def emitted_commands(self):
        """(domain, fq, command_page) for every command the last saga emitted."""
        out = []
        if self.resp is None:
            return out
        for book in self.resp.commands:
            for page in book.pages:
                out.append((book.cover.domain, fq_from_url(page.command.type_url), page.command))
        return out

    # --- emitted-event accessors ---

    def emitted_pages(self):
        return list(self.resp.events.pages) if self.resp is not None else []

    def emitted_fqs(self) -> list[str]:
        return [fq_from_url(p.event.type_url) for p in self.emitted_pages()]

    def emitted(self, fq: str, message):
        """Decode the first emitted event of type ``fq`` into ``message``."""
        for page in self.emitted_pages():
            if fq_from_url(page.event.type_url) == fq:
                message.ParseFromString(page.event.value)
                return message
        raise AssertionError(f"no emitted {fq}; got {self.emitted_fqs()}")

    def close(self) -> None:
        self.router.close()
