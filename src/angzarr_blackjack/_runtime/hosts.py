"""Hosts: one component registered on the router binding, with the entry
points its framework service calls.

Commands, notifications (rejections and undo), facts and Replay all go
through the binding: the generated dispatch, plus the fact handlers
registered on it here.
"""

from __future__ import annotations

from collections.abc import Callable

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import unpack

FactThunk = Callable[[object, object], object]


def _replayed(router: _az.Router, domain: str, rebuilder: _az.Rebuilder, book):
    """The state a component registered for ``domain`` rebuilds from ``book``."""
    request = _ch.ReplayRequest()
    if book is not None:
        if book.HasField("snapshot"):
            request.base_snapshot.CopyFrom(book.snapshot)
        request.events.extend(book.pages)
    state = router.dispatch_replay(domain, request).state
    return unpack(state, type(rebuilder.factory()))


def typed_fact(message_class, handler: Callable[[object, object], object]) -> FactThunk:
    """Adapt a typed fact handler ``(fact, state) -> fact`` to the Any boundary."""

    def thunk(event_any, state):
        return handler(unpack(event_any, message_class), state)

    return thunk


class AggregateHost:
    """An aggregate registered on the router with its fact handlers."""

    def __init__(
        self,
        router: _az.Router,
        dispatch: _az.AggregateDispatch,
        *,
        facts: dict[str, FactThunk] | None = None,
    ) -> None:
        for fq, thunk in (facts or {}).items():
            dispatch.on_fact(fq, thunk)
        router.register_aggregate(dispatch)
        self.router = router
        self.dispatch = dispatch
        self.domain = dispatch.domain

    def handle(self, command: _t.ContextualCommand) -> _ch.BusinessResponse:
        """``CommandHandlerService.Handle``: a command, or a notification
        delivery envelope (rejection or undo)."""
        return self.router.dispatch(command)

    def handle_fact(self, request: _ch.FactRequest) -> _t.EventBook:
        """``CommandHandlerService.HandleFact``: the facts to record."""
        return self.router.dispatch_fact(request)

    def replay(self, request: _ch.ReplayRequest) -> _ch.ReplayResponse:
        """``CommandHandlerService.Replay``: the state after ``events``."""
        return self.router.dispatch_replay(self.domain, request)

    def rebuild(self, book: _t.EventBook | None):
        """The state after ``book`` (its snapshot, then its pages)."""
        return _replayed(self.router, self.domain, self.dispatch.rebuilder, book)


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
        """The process state after ``book`` (its snapshot, then its pages)."""
        return _replayed(
            self.router, self.dispatch.pm_domain, self.dispatch.rebuilder, book
        )
