"""In-process coordinator over the real blackjack components.

Every component — wallet, table, buy-in process, the four translators and the
ledger — is registered on one ``angzarr_router_ffi.Router`` exactly as its
deployable registers it (each ``main.build_host`` / ``register``). The
:class:`World` plays the coordinators' part in memory: it keeps each
aggregate's event stream, loads prior history (from the latest snapshot, with
legacy player events upcast) for every command, persists what the component
returns with framework-stamped sequences, and — when wired — delivers every
persisted book to the ledger, the sagas and the buy-in process, routes their
deferred commands (deduplicated by provenance), injects their facts
(deduplicated by external id), and turns a refused saga or process command into
a Notification for its source. Nothing in it decides a business outcome; it
only moves messages between the components.

Entity roots are ``uuid5(NAMESPACE_OID, "<kind>:<label>")`` with kinds
``player``, ``table`` and ``request`` (client request ids: buy-ins and
top-ups), so every language derives the same bytes from the same scenario.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_blackjack._gen.io.angzarr.v1 import saga_pb2 as _saga
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack._runtime.hosts import AggregateHost
from angzarr_blackjack.errors import status_message
from angzarr_blackjack.player.agg import main as player_main
from angzarr_blackjack.player.agg.upcaster import upcast_book
from angzarr_blackjack.player.saga_table import main as player_table_main
from angzarr_blackjack.pmg_buy_in import main as buy_in_main
from angzarr_blackjack.prj_ledger import main as ledger_main
from angzarr_blackjack.table.agg import main as table_main
from angzarr_blackjack.table.saga_player import main as table_player_main

PLAYER, TABLE, BUY_IN = "player", "table", "buy-in"
SAGAS = "sagas"
BUY_IN_PM = "BuyInProcessManager"
DEFAULT_CORRELATION = "scenario"


def root_of(kind: str, label: str) -> bytes:
    return uuid.uuid5(uuid.NAMESPACE_OID, f"{kind}:{label}").bytes


def player_root(name: str) -> bytes:
    return root_of(PLAYER, name)


def table_root(name: str) -> bytes:
    return root_of(TABLE, name)


def request_id(label: str) -> bytes:
    return root_of("request", label)


def cover(domain: str, root: bytes, correlation: str = "") -> _t.Cover:
    c = _t.Cover(domain=domain, correlation_id=correlation)
    c.root.value = root
    return c


@dataclass
class Outcome:
    """What one command, fact or notification did to its aggregate."""

    events: list = field(default_factory=list)  # persisted EventPages
    error: _az.CodedError | None = None
    already_processed: bool = False
    notified: bool = False  # a refusal was sent back to the source

    def decoded(self, message_class) -> list:
        name = message_class.DESCRIPTOR.full_name
        return [
            unpack(p.event, message_class)
            for p in self.events
            if type_name(p.event.type_url) == name
        ]

    def types(self) -> list[str]:
        return [type_name(p.event.type_url).rsplit(".", 1)[-1] for p in self.events]


@dataclass
class Sent:
    """One command a saga or the process manager emitted, as emitted and as delivered."""

    origin: str  # "saga" or "pm"
    emitted: _t.CommandBook
    delivered: _t.CommandBook
    outcome: Outcome | None = None

    @property
    def domain(self) -> str:
        return self.delivered.cover.domain

    @property
    def root(self) -> bytes:
        return self.delivered.cover.root.value

    @property
    def command(self):
        return self.delivered.pages[0].command

    def is_a(self, message_class) -> bool:
        return type_name(self.command.type_url) == message_class.DESCRIPTOR.full_name


class World:
    """One scenario's in-process deployment."""

    def __init__(self) -> None:
        self.router = _az.Router()
        self.player = player_main.build_host(self.router)
        self.table = table_main.build_host(self.router)
        self.buy_in = buy_in_main.build_host(self.router)
        player_table_main.register(self.router)
        table_player_main.register(self.router)
        self.ledger_host = ledger_main.build_host(self.router)
        self.ledger = self.ledger_host.ledger
        self.hosts: dict[str, AggregateHost] = {PLAYER: self.player, TABLE: self.table}

        self.streams: dict[tuple[str, bytes], list[_t.EventPage]] = {}
        self.snapshots: dict[tuple[str, bytes], list[_t.Snapshot]] = {}
        self.process_streams: dict[str, list[_t.EventPage]] = {}
        self.processed: dict[tuple, Outcome] = {}
        self.facts_seen: dict[tuple, Outcome] = {}
        self.sent: list[Sent] = []
        self.sent_mark = 0  # len(sent) when the last client command was sent
        self.log: list[tuple[str, bytes, _t.EventPage]] = (
            []
        )  # every persisted page, in order
        self.paused: set[str] = set()  # command types held back in flight
        self.in_flight: list = []  # (Sent, deliver) held back, in arrival order
        self.last = Outcome()

        self.wired = False  # deliver persisted books to the ledger, sagas and PM
        self.deliveries = 1  # how many times each message is delivered
        self.snapshot_every: int | None = None  # routine snapshot interval
        self.use_snapshots = True  # load aggregates from their latest snapshot
        self.correlation = DEFAULT_CORRELATION
        self.labels: dict[str, object] = {}  # scenario-scoped notes keyed by label

    def close(self) -> None:
        self.router.close()

    # --- streams --------------------------------------------------------------

    def stream(self, domain: str, root: bytes) -> list[_t.EventPage]:
        return self.streams.setdefault((domain, root), [])

    def book(
        self, domain: str, root: bytes, *, from_snapshot: bool | None = None
    ) -> _t.EventBook:
        """What a coordinator loads for ``(domain, root)``: the latest snapshot
        and the pages after it (or every page), legacy player events upcast."""
        book = _t.EventBook(cover=cover(domain, root))
        pages = self.stream(domain, root)
        snaps = self.snapshots.get((domain, root), [])
        use = self.use_snapshots if from_snapshot is None else from_snapshot
        if use and snaps:
            snap = snaps[-1]
            book.snapshot.CopyFrom(snap)
            pages = [p for p in pages if p.header.sequence > snap.sequence]
        book.pages.extend(pages)
        book.next_sequence = len(self.stream(domain, root))
        return upcast_book(book) if domain == PLAYER else book

    def state(self, domain: str, root: bytes, *, from_snapshot: bool | None = None):
        return self.hosts[domain].rebuild(
            self.book(domain, root, from_snapshot=from_snapshot)
        )

    def events(self, domain: str, root: bytes, message_class) -> list:
        name = message_class.DESCRIPTOR.full_name
        return [
            unpack(p.event, message_class)
            for p in self.stream(domain, root)
            if type_name(p.event.type_url) == name
        ]

    def seed(self, domain: str, root: bytes, *events) -> list[_t.EventPage]:
        """Record prior history directly (no handler runs, nothing reacts)."""
        book = _t.EventBook()
        for event in events:
            book.pages.add().event.CopyFrom(_az.pack(event))
        return self._persist(domain, root, book, self.correlation)

    def seed_page(self, domain: str, root: bytes, any_event) -> None:
        book = _t.EventBook()
        book.pages.add().event.CopyFrom(any_event)
        self._persist(domain, root, book, self.correlation)

    def _persist(self, domain: str, root: bytes, book: _t.EventBook, correlation: str):
        stream = self.stream(domain, root)
        before = len(stream)
        out = []
        now = Timestamp()
        now.GetCurrentTime()
        for source in book.pages:
            page = _t.EventPage()
            page.CopyFrom(source)
            page.header.sequence = len(stream)
            page.created_at.CopyFrom(now)
            stream.append(page)
            out.append(page)
            self.log.append((domain, root, page))
        if out and book.HasField("snapshot"):
            self._snapshot(domain, root, book.snapshot.state, book.snapshot.retention)
        elif (
            out
            and self.snapshot_every
            and len(stream) // self.snapshot_every > before // self.snapshot_every
        ):
            state = self.hosts[domain].rebuild(self.book(domain, root))
            self._snapshot(
                domain, root, _az.pack(state), _t.SnapshotRetention.RETENTION_DEFAULT
            )
        return out

    def _snapshot(self, domain: str, root: bytes, state_any, retention) -> None:
        snap = _t.Snapshot(
            sequence=len(self.stream(domain, root)) - 1,
            state=state_any,
            retention=retention,
        )
        self.snapshots.setdefault((domain, root), []).append(snap)

    # --- commands -------------------------------------------------------------

    def command(
        self, domain: str, root: bytes, message, *, correlation: str | None = None
    ) -> Outcome:
        """A client command: explicit expected sequence, answered once its
        reactions (when wired) have run."""
        corr = self.correlation if correlation is None else correlation
        book = _t.CommandBook(cover=cover(domain, root, corr))
        page = book.pages.add()
        page.header.sequence = len(self.stream(domain, root))
        page.command.CopyFrom(_az.pack(message))
        self.sent_mark = len(self.sent)
        self.last = self._execute(book)
        return self.last

    def _execute(self, book: _t.CommandBook) -> Outcome:
        domain, root = book.cover.domain, book.cover.root.value
        contextual = _t.ContextualCommand(events=self.book(domain, root), command=book)
        try:
            response = self.hosts[domain].handle(contextual)
        except _az.CodedError as err:
            return Outcome(error=err)
        return self._record(domain, root, response, book.cover.correlation_id)

    def _record(
        self, domain: str, root: bytes, response: _ch.BusinessResponse, corr: str
    ) -> Outcome:
        pages = (
            self._persist(domain, root, response.events, corr)
            if response.HasField("events")
            else []
        )
        outcome = Outcome(events=pages)
        if pages:
            self.react(domain, root, pages, corr)
        return outcome

    # --- facts ----------------------------------------------------------------

    def inject(
        self, fact_book: _t.EventBook, correlation: str | None = None
    ) -> Outcome:
        """Inject a fact; a repeated external id returns the first result."""
        corr = self.correlation if correlation is None else correlation
        domain, root = fact_book.cover.domain, fact_book.cover.root.value
        external_id = fact_book.pages[0].header.external_deferred.external_id
        key = (domain, root, external_id)
        if key in self.facts_seen:
            first = self.facts_seen[key]
            self.last = Outcome(events=first.events, already_processed=True)
            return self.last
        request = _ch.FactRequest(facts=fact_book, prior_events=self.book(domain, root))
        recorded = self.hosts[domain].handle_fact(request)
        pages = self._persist(domain, root, recorded, corr)
        self.last = self.facts_seen[key] = Outcome(events=pages)
        self.react(domain, root, pages, corr)
        return self.last

    # --- reactions ------------------------------------------------------------

    def react(self, domain: str, root: bytes, pages, corr: str) -> None:
        if not self.wired or domain not in self.hosts:
            return
        book = _t.EventBook(cover=cover(domain, root, corr))
        book.pages.extend(pages)
        for _ in range(self.deliveries):
            self.project(book)
            for page in pages:
                single = _t.EventBook(cover=book.cover, pages=[page])
                self.run_sagas(single)
                self.run_process_manager(single)

    def project(self, book: _t.EventBook):
        return self.ledger_host.project(
            upcast_book(book) if book.cover.domain == PLAYER else book
        )

    def run_sagas(
        self, source: _t.EventBook, *, route: bool = True
    ) -> _saga.SagaResponse:
        response = self.router.dispatch_saga(_saga.SagaHandleRequest(source=source))
        if route:
            corr = source.cover.correlation_id
            for index, command in enumerate(response.commands):
                self.deliver(command, source, index, "saga", SAGAS, corr)
            for fact_book in response.events:
                for _ in range(self.deliveries):
                    self.inject(fact_book, corr)
        return response

    def process_state(self, corr: str) -> _t.EventBook:
        book = _t.EventBook(cover=cover(BUY_IN, root_of("conversation", corr), corr))
        book.pages.extend(self.process_streams.get(corr, []))
        return book

    def run_process_manager(
        self, trigger: _t.EventBook, *, route: bool = True
    ) -> _pm.ProcessManagerHandleResponse:
        corr = trigger.cover.correlation_id
        if not corr:
            return _pm.ProcessManagerHandleResponse()
        request = _pm.ProcessManagerHandleRequest(
            trigger=trigger, process_state=self.process_state(corr)
        )
        response = self.buy_in.handle(request)
        stream = self.process_streams.setdefault(corr, [])
        for events in response.process_events:
            for source in events.pages:
                page = _t.EventPage()
                page.CopyFrom(source)
                page.header.sequence = len(stream)
                stream.append(page)
        for index, command in enumerate(response.commands):
            self.deliver(command, trigger, index, "pm", BUY_IN_PM, corr, route=route)
        return response

    def deliver(
        self,
        emitted: _t.CommandBook,
        source: _t.EventBook,
        index: int,
        origin: str,
        component: str,
        corr: str,
        *,
        route: bool = True,
    ) -> Sent:
        """Deliver a deferred saga/PM command: stamp provenance and the trigger's
        correlation, deduplicate by provenance, and send a refusal back. With
        ``route`` false the command is only recorded; a paused command type is
        held in flight until :meth:`release`."""
        delivered = _t.CommandBook()
        delivered.CopyFrom(emitted)
        if not delivered.cover.correlation_id:
            delivered.cover.correlation_id = corr
        deferred = delivered.pages[0].header.angzarr_deferred
        deferred.source.CopyFrom(source.cover)
        deferred.source_seq = source.pages[-1].header.sequence if source.pages else 0
        deferred.source_component = component
        deferred.command_index = index
        sent = Sent(origin=origin, emitted=emitted, delivered=delivered)
        self.sent.append(sent)
        if not route:
            return sent
        key = (
            "command",
            delivered.cover.domain,
            delivered.cover.root.value,
            source.cover.domain,
            source.cover.root.value,
            deferred.source_seq,
            component,
            index,
        )

        def arrive() -> None:
            for _ in range(self.deliveries):
                if key in self.processed:
                    sent.outcome = self.processed[key]
                    continue
                outcome = self._execute(delivered)
                self.processed[key] = sent.outcome = outcome
                if outcome.error is not None:
                    outcome.notified = True
                    self.refuse(delivered, outcome.error, origin)

        if type_name(delivered.pages[0].command.type_url) in self.paused:
            self.in_flight.append((sent, arrive))
        else:
            arrive()
        return sent

    def release(self, order=None) -> None:
        """Let the held-back commands arrive, in ``order`` (a key on Sent) or
        in arrival order, and stop holding their types back."""
        held = (
            sorted(self.in_flight, key=lambda item: order(item[0]))
            if order
            else list(self.in_flight)
        )
        self.in_flight.clear()
        self.paused.clear()
        for _, arrive in held:
            arrive()

    def rejection(self, rejected: _t.CommandBook, reason: str) -> _t.Notification:
        source = rejected.pages[0].header.angzarr_deferred.source
        notification = _t.Notification(cover=source)
        notification.payload.CopyFrom(
            _az.pack(
                _t.RejectionNotification(
                    rejected_command=rejected, rejection_reason=reason
                )
            )
        )
        return notification

    def refuse(
        self,
        rejected: _t.CommandBook,
        error: _az.CodedError,
        origin: str,
        *,
        route: bool = True,
    ) -> Outcome:
        """Send a refused deferred command's RejectionNotification to its
        source: the aggregate whose event triggered a saga, or the process."""
        notification = self.rejection(rejected, status_message(error))
        if origin == "pm":
            trigger = _t.EventBook(cover=rejected.cover)
            trigger.cover.domain = rejected.cover.domain
            trigger.pages.add().event.CopyFrom(_az.pack(notification))
            self.run_process_manager(trigger, route=route)
            return Outcome()
        return self.notify(
            notification,
            rejected.pages[0].header.angzarr_deferred,
            rejected.cover.correlation_id,
        )

    def notify(
        self,
        notification: _t.Notification,
        deferred: _t.AngzarrDeferredSequence,
        corr: str,
        kind: str = "rejection-notification",
    ) -> Outcome:
        """Deliver a Notification envelope to the aggregate it is addressed to."""
        target = notification.cover
        envelope = _t.CommandBook(cover=cover(target.domain, target.root.value, corr))
        page = envelope.pages.add()
        page.header.angzarr_deferred.CopyFrom(deferred)
        page.command.CopyFrom(_az.pack(notification))
        key = (
            kind,
            target.domain,
            target.root.value,
            deferred.source.domain,
            deferred.source.root.value,
            deferred.source_seq,
            deferred.source_component,
            deferred.command_index,
        )
        if key in self.processed:
            return self.processed[key]
        self.processed[key] = outcome = self._execute(envelope)
        return outcome

    def sent_of(self, message_class, origin: str | None = None) -> list[Sent]:
        return [
            s
            for s in self.sent
            if s.is_a(message_class) and (origin is None or s.origin == origin)
        ]
