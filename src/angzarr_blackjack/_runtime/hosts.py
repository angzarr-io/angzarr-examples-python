"""Hosts: one component registered on the router binding, with the entry
points its framework service calls.

Commands, notifications (rejections and undo), facts and Replay all go
through the binding: the generated dispatch, plus the fact handlers
registered on it here.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack

FactThunk = Callable[[object, object], object]

# STAND-IN (remove when the router hands aggregate appliers a PageContext):
# the page sequences of the events an applier that needs its own page
# sequence is about to fold, in fold order. AggregateHost fills it from the
# book it hands the router; `applied_page_sequence()` reads it.
_PENDING_SEQUENCES: ContextVar[deque | None] = ContextVar(
    "angzarr_blackjack_pending_sequences", default=None
)


def applied_page_sequence() -> int:
    """The page sequence of the event the running applier folds."""
    pending = _PENDING_SEQUENCES.get()
    if pending:
        return pending.popleft()
    return _az.current_page().sequence


@contextmanager
def _sequences_of(pages, sequenced: frozenset[str]) -> Iterator[None]:
    token = _PENDING_SEQUENCES.set(
        deque(
            p.header.sequence for p in pages if type_name(p.event.type_url) in sequenced
        )
    )
    try:
        yield
    finally:
        _PENDING_SEQUENCES.reset(token)


def fold(rebuilder: _az.Rebuilder, book: _t.EventBook | None):
    """Fold ``book`` (snapshot, then pages) through a component's appliers.
    Event types the component does not apply are skipped."""
    state = rebuilder.factory()
    if book is None:
        return state
    if (
        book.HasField("snapshot")
        and book.snapshot.HasField("state")
        and rebuilder.snapshot
    ):
        rebuilder.snapshot(state, book.snapshot.state)
    for page in book.pages:
        thunk = rebuilder.appliers.get(type_name(page.event.type_url))
        if page.HasField("event") and thunk is not None:
            thunk(state, page.event)
    return state


def typed_fact(message_class, handler: Callable[[object, object], object]) -> FactThunk:
    """Adapt a typed fact handler ``(fact, state) -> fact`` to the Any boundary."""

    def thunk(event_any, state):
        return handler(unpack(event_any, message_class), state)

    return thunk


class AggregateHost:
    """An aggregate registered on the router with its fact handlers.
    ``sequenced`` names the events whose appliers read their page sequence."""

    def __init__(
        self,
        router: _az.Router,
        dispatch: _az.AggregateDispatch,
        *,
        facts: dict[str, FactThunk] | None = None,
        sequenced: frozenset[str] = frozenset(),
    ) -> None:
        for fq, thunk in (facts or {}).items():
            dispatch.on_fact(fq, thunk)
        router.register_aggregate(dispatch)
        self.router = router
        self.dispatch = dispatch
        self.domain = dispatch.domain
        self._sequenced = sequenced

    def handle(self, command: _t.ContextualCommand) -> _ch.BusinessResponse:
        """``CommandHandlerService.Handle``: a command, or a notification
        delivery envelope (rejection or undo)."""
        with _sequences_of(command.events.pages, self._sequenced):
            return self.router.dispatch(command)

    def handle_fact(self, request: _ch.FactRequest) -> _t.EventBook:
        """``CommandHandlerService.HandleFact``: the facts to record."""
        with _sequences_of(request.prior_events.pages, self._sequenced):
            return self.router.dispatch_fact(request)

    def replay(self, request: _ch.ReplayRequest) -> _ch.ReplayResponse:
        """``CommandHandlerService.Replay``: the state after ``events``."""
        with _sequences_of(request.events, self._sequenced):
            return self.router.dispatch_replay(self.domain, request)

    def rebuild(self, book: _t.EventBook | None):
        """The state after ``book`` (its snapshot, then its pages)."""
        request = _ch.ReplayRequest()
        if book is not None:
            if book.HasField("snapshot"):
                request.base_snapshot.CopyFrom(book.snapshot)
            request.events.extend(book.pages)
        return unpack(
            self.replay(request).state, type(self.dispatch.rebuilder.factory())
        )


class ProcessManagerHost:
    """A process manager registered on the router."""

    def __init__(
        self, router: _az.Router, dispatch: _az.ProcessManagerDispatch
    ) -> None:
        router.register_process_manager(dispatch)
        self.router = router
        self.dispatch = dispatch

    def handle(
        self, request: _pm.ProcessManagerHandleRequest
    ) -> _pm.ProcessManagerHandleResponse:
        return self.router.dispatch_process_manager(request)

    def rebuild(self, book: _t.EventBook | None):
        """The process state after ``book``."""
        return fold(self.dispatch.rebuilder, book)
