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
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
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
        # next dispatch to that (domain, root) folds to rebuild state. Keyed by
        # (domain, root_hex) so multiple instances of one domain (e.g. several
        # tables) don't collide; the default root b"" serves single-instance
        # scenarios unchanged.
        self._prior: dict[tuple[str, str], _t.EventBook] = {}
        self.resp = None  # BusinessResponse from the last successful dispatch
        self.err: Optional[_az.CodedError] = None  # coded rejection, if any

    def _register_components(self) -> None:
        """Register every ported component handler. Extend as components land."""
        from angzarr_poker._gen.io.angzarr.examples.v1.hand_aggregate_angzarr import (
            register_hand_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.player_aggregate_angzarr import (
            register_player_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.reservation_aggregate_angzarr import (
            register_reservation_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.tournament_aggregate_angzarr import (
            register_tournament_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_tournament_saga_angzarr import (
            register_table_tournament_saga,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.tournament_table_saga_angzarr import (
            register_tournament_table_saga,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
            register_table_aggregate,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.hand_flow_process_manager_angzarr import (
            register_hand_flow_process_manager,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.reservation_process_manager_angzarr import (
            register_reservation_process_manager,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.output_projector_angzarr import (
            register_output_projector,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_hand_saga_angzarr import (
            register_table_hand_saga,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.hand_table_saga_angzarr import (
            register_hand_table_saga,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.table_player_saga_angzarr import (
            register_table_player_saga,
        )
        from angzarr_poker._gen.io.angzarr.examples.v1.hand_player_saga_angzarr import (
            register_hand_player_saga,
        )
        from angzarr_poker.hand.handler import HandAggregate
        from angzarr_poker.player.handler import PlayerAggregate
        from angzarr_poker.process_managers.hand_flow import HandFlowProcessManager
        from angzarr_poker.process_managers.reservation import ReservationProcessManager
        from angzarr_poker.projectors.output import OutputProjector
        from angzarr_poker.reservation.handler import ReservationAggregate
        from angzarr_poker.sagas.hand_player import HandPlayerSaga
        from angzarr_poker.sagas.hand_table import HandTableSaga
        from angzarr_poker.sagas.table_hand import TableHandSaga
        from angzarr_poker.sagas.table_player import TablePlayerSaga
        from angzarr_poker.sagas.table_tournament import TableTournamentSaga
        from angzarr_poker.sagas.tournament_table import TournamentTableSaga
        from angzarr_poker.table.handler import TableAggregate
        from angzarr_poker.tournament.handler import TournamentAggregate

        register_table_aggregate(self.router, TableAggregate())
        register_hand_aggregate(self.router, HandAggregate())
        register_player_aggregate(self.router, PlayerAggregate())
        register_reservation_aggregate(self.router, ReservationAggregate())
        register_tournament_aggregate(self.router, TournamentAggregate())
        register_table_tournament_saga(self.router, TableTournamentSaga())
        register_tournament_table_saga(self.router, TournamentTableSaga())
        register_table_hand_saga(self.router, TableHandSaga())
        register_hand_table_saga(self.router, HandTableSaga())
        register_table_player_saga(self.router, TablePlayerSaga())
        register_hand_player_saga(self.router, HandPlayerSaga())
        # Held so steps can fold the PM's emitted own-events through its applier.
        self.hand_flow_pm = HandFlowProcessManager()
        register_hand_flow_process_manager(self.router, self.hand_flow_pm)
        # Reservation PM co-resides with hand-flow on the `table` source domain;
        # the core routes each trigger to the PM declaring its event type.
        self.reservation_pm = ReservationProcessManager()
        register_reservation_process_manager(self.router, self.reservation_pm)
        # Held so steps can read the rendered display sink (presentation lives on
        # the projector, not in the projection proto).
        self.output_projector = OutputProjector()
        register_output_projector(self.router, self.output_projector)

    # --- state seeding (prior events the core folds) ---

    def seed_event(self, domain: str, fq: str, event_msg, root: bytes = b"") -> None:
        """Append one prior event to the ``(domain, root)`` rebuild history."""
        key = (domain, root.hex())
        book = self._prior.get(key)
        if book is None:
            book = _t.EventBook()
            book.cover.domain = domain
            book.cover.root.value = root
            self._prior[key] = book
        page = book.pages.add()
        page.header.sequence = len(book.pages) - 1
        page.event.type_url = type_url(fq)
        page.event.value = event_msg.SerializeToString()
        book.next_sequence = len(book.pages)

    def prior_pages(self, domain: str, root: bytes = b""):
        """The seeded prior event pages for ``(domain, root)`` (empty if none).
        Lets a step collect facts an aggregate already holds — e.g. the seated
        players a final-table combine gathers from its breaking source tables."""
        book = self._prior.get((domain, root.hex()))
        return list(book.pages) if book is not None else []

    def fold_emitted(self, domain: str, root: bytes = b"") -> None:
        """Append the last dispatch's emitted events to the ``(domain, root)``
        history, so a subsequent command in the same scenario rebuilds over them
        (e.g. a CloseRegistration before a late enrollment)."""
        if self.resp is None:
            return
        key = (domain, root.hex())
        book = self._prior.get(key)
        if book is None:
            book = _t.EventBook()
            book.cover.domain = domain
            book.cover.root.value = root
            self._prior[key] = book
        for page in self.resp.events.pages:
            new = book.pages.add()
            new.header.sequence = len(book.pages) - 1
            new.event.CopyFrom(page.event)
        book.next_sequence = len(book.pages)

    # --- dispatch + outcome ---

    def dispatch(self, domain: str, fq: str, cmd_msg, root: bytes = b"") -> None:
        """Run one command through the core against the ``(domain, root)`` seeded
        history. Captures the BusinessResponse in ``resp`` or the rejection in
        ``err``."""
        self.resp = None
        self.err = None
        cc = _t.ContextualCommand()
        cc.command.cover.domain = domain
        cc.command.cover.root.value = root
        page = cc.command.pages.add()
        page.command.type_url = type_url(fq)
        page.command.value = cmd_msg.SerializeToString()
        prior = self._prior.get((domain, root.hex()))
        if prior is not None:
            cc.events.CopyFrom(prior)
        try:
            self.resp = self.router.dispatch(cc)
        except _az.CodedError as exc:
            self.err = exc

    # --- saga dispatch (stateless event -> commands/events) ---

    def dispatch_saga(
        self,
        input_domain: str,
        fq: str,
        event_msg,
        dest_sequences=None,
        source_root: bytes = b"",
    ) -> None:
        """Run one source event through a registered saga. ``source_root`` is the
        trigger aggregate's id, passed on the source cover so the saga can route
        emitted commands by it (e.g. PlayerJoined carries no table_root — the
        table id comes from here). Captures the SagaResponse in ``resp``."""
        self.resp = None
        self.err = None
        req = _saga.SagaHandleRequest()
        req.source.cover.domain = input_domain
        req.source.cover.root.value = source_root
        page = req.source.pages.add()
        page.event.type_url = type_url(fq)
        page.event.value = event_msg.SerializeToString()
        for domain, seq in (dest_sequences or {}).items():
            req.destination_sequences[domain] = seq
        try:
            self.resp = self.router.dispatch_saga(req)
        except _az.CodedError as exc:
            self.err = exc

    # --- process-manager dispatch (stateful trigger -> process_events/commands) ---

    def dispatch_process_manager(
        self,
        input_domain: str,
        fq: str,
        event_msg,
        dest_sequences=None,
        prior_events=None,
        process_root: bytes = b"",
    ) -> None:
        """Run one trigger event through a registered PM. Captures the
        ProcessManagerHandleResponse in ``resp`` or the rejection in ``err``.

        ``prior_events`` (list of ``(fq, message)``) seeds the PM's event-sourced
        state: the core folds them through the PM's appliers before the trigger
        fires — the PM's own prior history and, for an orchestrator, the folded
        cross-domain facts it decides against. The same rebuild path production
        takes."""
        self.resp = None
        self.err = None
        req = _pm.ProcessManagerHandleRequest()
        req.trigger.cover.domain = input_domain
        page = req.trigger.pages.add()
        page.event.type_url = type_url(fq)
        page.event.value = event_msg.SerializeToString()
        for prior_fq, prior_msg in prior_events or []:
            prior_page = req.process_state.pages.add()
            prior_page.event.type_url = type_url(prior_fq)
            prior_page.event.value = prior_msg.SerializeToString()
        if process_root:
            req.process_state.cover.root.value = process_root
        for domain, seq in (dest_sequences or {}).items():
            req.destination_sequences[domain] = seq
        try:
            self.resp = self.router.dispatch_process_manager(req)
        except _az.CodedError as exc:
            self.err = exc

    def process_event(self, fq: str, message):
        """Decode the first emitted process-event of type ``fq`` from the PM's
        response (the PM's own event-sourced output)."""
        for book in self.resp.process_events:
            for page in book.pages:
                if fq_from_url(page.event.type_url) == fq:
                    message.ParseFromString(page.event.value)
                    return message
        raise AssertionError(f"no emitted {fq} process-event")

    # --- projector dispatch (fold an event book -> Projection) ---

    def dispatch_projector(self, domain: str, events) -> None:
        """Fold ``events`` (list of (fq, message)) through the registered
        projector. Captures the Projection in ``resp``."""
        self.resp = None
        self.err = None
        book = _t.EventBook()
        book.cover.domain = domain
        for seq, (fq, msg) in enumerate(events):
            page = book.pages.add()
            page.header.sequence = seq
            page.event.type_url = type_url(fq)
            page.event.value = msg.SerializeToString()
        try:
            self.resp = self.router.dispatch_projector(book)
        except _az.CodedError as exc:
            self.err = exc

    def projection(self, message):
        """Decode the projection payload from the last dispatch_projector."""
        message.ParseFromString(self.resp.projection.value)
        return message

    def emitted_commands(self):
        """(domain, fq, command_page) for every command the last saga emitted."""
        out = []
        if self.resp is None:
            return out
        for book in self.resp.commands:
            for page in book.pages:
                out.append(
                    (
                        book.cover.domain,
                        fq_from_url(page.command.type_url),
                        page.command,
                    )
                )
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
