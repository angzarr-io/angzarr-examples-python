"""Hosts: one component's registration on the router plus the parts of its
contract the router binding does not dispatch.

Everything the router dispatches goes through it unchanged. The host adds:

* the current cover (``context.handling``) around every dispatch;
* fact handling (``CommandHandlerService.HandleFact``): the binding has no
  fact dispatch, so the host folds the prior events with the component's own
  generated appliers and runs its typed fact handlers;
* ``Replay`` (state after a run of events, for MERGE_COMMUTATIVE): the same
  fold;
* undo (``Compensate`` notifications, ``ComponentOptions.undoes``): the
  binding has no undo dispatch, so the host routes a Compensate to the
  aggregate's undo handler for its ``command_type``;
* process-manager compensation: the binding keeps only process events and an
  escalation from a PM compensator, but a buy-in compensation must also send
  commands, so the host runs PM compensators itself and returns their whole
  response.
"""

from __future__ import annotations

from collections.abc import Callable

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import is_type, type_name, unpack
from angzarr_blackjack._runtime.context import handling

UndoThunk = Callable[
    [_t.Notification, _t.Compensate, object, _az.CommandContext], object
]
FactThunk = Callable[[object, object], object]


def fold(rebuilder: _az.Rebuilder, book: _t.EventBook | None, state=None):
    """Fold ``book`` (snapshot, then pages) through the rebuilder's appliers.
    Event types the component does not apply are skipped."""
    if state is None:
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
        apply_page(rebuilder, state, page)
    return state


def apply_page(rebuilder: _az.Rebuilder, state, page: _t.EventPage) -> None:
    if not page.HasField("event"):
        return
    thunk = rebuilder.appliers.get(type_name(page.event.type_url))
    if thunk is not None:
        thunk(state, page.event)


def next_sequence(book: _t.EventBook) -> int:
    """The sequence the next event of ``book``'s aggregate will get."""
    if book.next_sequence:
        return book.next_sequence
    if book.pages:
        return book.pages[-1].header.sequence + 1
    if book.HasField("snapshot"):
        return book.snapshot.sequence + 1
    return 0


def typed_fact(message_class, handler: Callable[[object, object], object]) -> FactThunk:
    """Adapt a typed fact handler ``(fact, state) -> fact`` to the Any boundary."""

    def thunk(event_any, state):
        return handler(unpack(event_any, message_class), state)

    return thunk


def is_notification(any_msg) -> bool:
    return is_type(any_msg, _t.Notification)


class AggregateHost:
    """An aggregate registered on the router, plus facts, replay and undo."""

    def __init__(
        self,
        router: _az.Router,
        dispatch: _az.AggregateDispatch,
        *,
        facts: dict[str, FactThunk] | None = None,
        undo: dict[str, UndoThunk] | None = None,
    ) -> None:
        router.register_aggregate(dispatch)
        self.router = router
        self.dispatch = dispatch
        self.domain = dispatch.domain
        self.facts = dict(facts or {})
        self.undo = dict(undo or {})

    def rebuild(self, book: _t.EventBook | None):
        return fold(self.dispatch.rebuilder, book)

    def handle(self, command: _t.ContextualCommand) -> _ch.BusinessResponse:
        """``CommandHandlerService.Handle``: a command, or a notification
        delivery envelope (rejection or undo)."""
        with handling(command.command.cover):
            pages = command.command.pages
            if pages and is_notification(pages[0].command):
                notification = unpack(pages[0].command, _t.Notification)
                if is_type(notification.payload, _t.Compensate):
                    return self._undo(notification, command.events)
            return self.router.dispatch(command)

    def _undo(
        self, notification: _t.Notification, prior: _t.EventBook
    ) -> _ch.BusinessResponse:
        compensate = unpack(notification.payload, _t.Compensate)
        thunk = self.undo.get(compensate.command_type)
        if thunk is None:
            raise _az.CodedError(
                code="NO_UNDO_HANDLER",
                message=f"{self.dispatch.name} has no undo handler for {compensate.command_type}",
                grpc=_az.GrpcCode.UNIMPLEMENTED,
            )
        state = self.rebuild(prior)
        cctx = _az.CommandContext(
            next_sequence=next_sequence(prior), had_prior_events=len(prior.pages) > 0
        )
        response = thunk(notification, compensate, state, cctx)
        return response if response is not None else _ch.BusinessResponse()

    def handle_fact(self, request: _ch.FactRequest) -> _t.EventBook:
        """``CommandHandlerService.HandleFact``: run each fact through its
        typed handler against the rebuilt state. A fact cannot be refused; the
        handler may only annotate it."""
        state = self.rebuild(request.prior_events)
        out = _t.EventBook()
        out.cover.CopyFrom(request.facts.cover)
        for page in request.facts.pages:
            recorded = out.pages.add()
            recorded.CopyFrom(page)
            thunk = self.facts.get(type_name(page.event.type_url))
            if thunk is not None:
                recorded.event.CopyFrom(_az.pack(thunk(page.event, state)))
            apply_page(self.dispatch.rebuilder, state, recorded)
        return out

    def replay(self, request: _ch.ReplayRequest) -> _ch.ReplayResponse:
        """``CommandHandlerService.Replay``: the state after ``events``."""
        book = _t.EventBook()
        if request.HasField("base_snapshot"):
            book.snapshot.CopyFrom(request.base_snapshot)
        book.pages.extend(request.events)
        return _ch.ReplayResponse(state=_az.pack(self.rebuild(book)))


class ProcessManagerHost:
    """A process manager registered on the router. Notification triggers go
    to the PM's compensators directly, so their commands are kept."""

    def __init__(
        self, router: _az.Router, dispatch: _az.ProcessManagerDispatch
    ) -> None:
        router.register_process_manager(dispatch)
        self.router = router
        self.dispatch = dispatch

    def rebuild(self, book: _t.EventBook | None):
        return fold(self.dispatch.rebuilder, book)

    def handle(
        self, request: _pm.ProcessManagerHandleRequest
    ) -> _pm.ProcessManagerHandleResponse:
        with handling(request.trigger.cover):
            pages = request.trigger.pages
            if pages and is_notification(pages[-1].event):
                return self._compensate(
                    unpack(pages[-1].event, _t.Notification), request
                )
            return self.router.dispatch_process_manager(request)

    def _compensate(
        self, notification: _t.Notification, request: _pm.ProcessManagerHandleRequest
    ) -> _pm.ProcessManagerHandleResponse:
        rejection = unpack(notification.payload, _t.RejectionNotification)
        rejected = rejection.rejected_command
        command_type = (
            type_name(rejected.pages[0].command.type_url) if rejected.pages else ""
        )
        response = _pm.ProcessManagerHandleResponse()
        for thunk in self.dispatch.rejections.get(command_type, []):
            state = self.rebuild(request.process_state)
            response.MergeFrom(thunk(notification, rejection, state))
        return response
