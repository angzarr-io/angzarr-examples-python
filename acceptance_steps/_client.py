"""gRPC client for the cluster acceptance harness.

Cluster-tier scenarios drive a DEPLOYED poker cluster over gRPC — real
coordinator sidecars, AMQP event propagation, postgres-backed state — not the
in-process FFI router the unit stage uses. This client speaks the two
coordinator surfaces the harness needs:

  * ``CommandHandlerCoordinatorService.HandleCommand`` (command port, 1310) to
    issue a command to an aggregate. The coordinator loads prior events itself,
    folds them, runs the business handler, persists, and publishes — so the
    client sends only a ``CommandRequest`` (no prior history).
  * ``EventQueryService.GetEventBook`` (query port, 1315) to read an aggregate's
    persisted EventBook. Cross-service effects (saga → command → event) land
    asynchronously over AMQP, so assertions poll the target aggregate's book
    until the expected event-type appears or a deadline expires.

There is no deployed EventStreamService in this topology; per-root GetEventBook
polling is the observation mechanism. Endpoints come from env vars (set by the
port-forward wiring); see ``ENDPOINTS`` for the defaults.
"""

from __future__ import annotations

import os
import time

import grpc

from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
from angzarr_poker._gen.io.angzarr.v1 import query_pb2_grpc as _q_grpc
from angzarr_poker._gen.io.angzarr.examples.v1 import (
    player_projection_query_pb2 as _pq,
)
from angzarr_poker._gen.io.angzarr.examples.v1 import (
    player_projection_query_pb2_grpc as _pq_grpc,
)

# Fully-qualified poker proto prefix; angzarr keys dispatch on a bare "/" Any
# type-URL prefix (not the type.googleapis.com default).
P = "io.angzarr.examples.v1."
_TYPE_URL_PREFIX = "/"

# Per-domain coordinator endpoint, reached directly on the host. The chart
# provisions a NodePort service per aggregate ("<domain>-aggregate-debug",
# nodePort 31320..31324) and the kind cluster maps those node ports straight to
# the host (see kind-config.yaml extraPortMappings) — explicitly "for cluster
# acceptance tests, which talk directly to the per-domain coordinator". So no
# `kubectl port-forward` is needed: the ports are stable and survive pod
# restarts (NodePort → service → any ready pod), which a forward does not.
# Both the command service and the EventQueryService are served on the
# coordinator's single gRPC port, so one endpoint per domain covers both.
# Overridable via the <DOMAIN>_URL env var (e.g. for a remote cluster).
_DEFAULT_PORTS = {
    "player": 31320,
    "table": 31321,
    "hand": 31322,
    "tournament": 31323,
    "reservation": 31324,
}

# The player projector's read-model query surface (PlayerProjectionQueryService)
# is served by the player-projector pod, exposed on its own debug NodePort —
# separate from the aggregate command/query ports above. Overridable via
# PLAYER_PROJECTOR_URL for a remote cluster.
_PLAYER_PROJECTOR_PORT = 31325


def type_url(fq: str) -> str:
    return _TYPE_URL_PREFIX + fq


def fq_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _endpoint(domain: str) -> str:
    # `... or default` (not get's default): the container passes an empty
    # <DOMAIN>_URL when the host hasn't set one, which should fall back to the
    # NodePort, not become an empty target.
    return (
        os.environ.get(f"{domain.upper()}_URL") or f"localhost:{_DEFAULT_PORTS[domain]}"
    )


class ClusterClient:
    """Per-domain command + query channels into the deployed cluster. One
    instance is shared across a behave run; scenarios isolate themselves via
    fresh roots/correlation ids, not fresh channels."""

    def __init__(self) -> None:
        # Per-aggregate next-sequence, keyed by (domain, root_hex). Commands
        # carry the expected current sequence for optimistic concurrency; the
        # coordinator rejects a stale one (FAILED_PRECONDITION "sequence
        # mismatch"). Roots are scenario-unique (nonce-salted), so tracking on
        # the shared client never crosses scenarios.
        self._seq: dict[tuple[str, str], int] = {}
        self._channels: list[grpc.Channel] = []
        self._cmd_channels: dict[str, grpc.Channel] = {}
        self._cmd: dict[str, _ch_grpc.CommandHandlerCoordinatorServiceStub] = {}
        self._query: dict[str, _q_grpc.EventQueryServiceStub] = {}
        for domain in _DEFAULT_PORTS:
            # The aggregate coordinator serves CommandHandlerCoordinatorService
            # AND EventQueryService on the same gRPC server (the command port);
            # there is no separate query-port listener in current core. One
            # channel backs both stubs.
            cmd_ch = grpc.insecure_channel(_endpoint(domain))
            self._channels.append(cmd_ch)
            self._cmd_channels[domain] = cmd_ch
            self._cmd[domain] = _ch_grpc.CommandHandlerCoordinatorServiceStub(cmd_ch)
            self._query[domain] = _q_grpc.EventQueryServiceStub(cmd_ch)

        # The player projector read-model query surface lives on its own pod
        # (separate NodePort), so it gets its own channel + stub.
        proj_ep = (
            os.environ.get("PLAYER_PROJECTOR_URL")
            or f"localhost:{_PLAYER_PROJECTOR_PORT}"
        )
        proj_ch = grpc.insecure_channel(proj_ep)
        self._channels.append(proj_ch)
        self._player_projection = _pq_grpc.PlayerProjectionQueryServiceStub(proj_ch)

    def close(self) -> None:
        for ch in self._channels:
            ch.close()

    def reset_channel(self, domain: str) -> None:
        """Drop and re-create a domain's channel + stubs. After a coordinator
        restart the existing channel is pinned (via kube-proxy DNAT) to the
        now-dead pod and its reconnect backoff can outlast a short retry window;
        a fresh channel dials cleanly through the NodePort to the new pod."""
        old = self._cmd_channels.get(domain)
        if old is not None:
            old.close()
        ch = grpc.insecure_channel(_endpoint(domain))
        self._channels.append(ch)
        self._cmd_channels[domain] = ch
        self._cmd[domain] = _ch_grpc.CommandHandlerCoordinatorServiceStub(ch)
        self._query[domain] = _q_grpc.EventQueryServiceStub(ch)

    # --- reachability -------------------------------------------------------

    def reachable(self, timeout: float = 10.0) -> bool:
        """True once every aggregate command channel reports READY. ``timeout``
        is applied PER channel — a cold ``kubectl port-forward`` only dials its
        backend pod on the first connection, so the first handshake can take a
        few seconds; a shared deadline across all five would starve the later
        channels."""
        for domain in _DEFAULT_PORTS:
            ch = self._cmd_channels[domain]
            try:
                grpc.channel_ready_future(ch).result(timeout=timeout)
            except Exception:
                return False
        return True

    # --- commands -----------------------------------------------------------

    def send(
        self,
        domain: str,
        name: str,
        message,
        root: bytes,
        correlation_id: str,
        sync_mode: int = _t.SyncMode.SYNC_MODE_SIMPLE,
        timeout: float = 15.0,
    ):
        """Issue command ``name`` (a poker proto, e.g. "CreateTable") to the
        ``domain`` aggregate at ``root``. Returns the CommandResponse; raises
        grpc.RpcError on a coded rejection."""
        key = (domain, root.hex())
        if key not in self._seq:
            # This client hasn't written to this aggregate yet, but it may have
            # been advanced out-of-band (e.g. a saga dealt to the hand). Seed the
            # cursor from its persisted head so the first direct command carries
            # the right expected sequence instead of a stale 0.
            try:
                self._seq[key] = self.event_book(domain, root).next_sequence
            except grpc.RpcError:
                self._seq[key] = 0

        def _build(seq: int) -> _t.CommandRequest:
            req = _t.CommandRequest()
            req.command.cover.domain = domain
            req.command.cover.root.value = root
            req.command.cover.correlation_id = correlation_id
            page = req.command.pages.add()
            page.header.sequence = seq
            page.command.type_url = type_url(P + name)
            page.command.value = message.SerializeToString()
            req.sync_mode = sync_mode
            return req

        try:
            resp = self._cmd[domain].HandleCommand(
                _build(self._seq.get(key, 0)), timeout=timeout
            )
        except grpc.RpcError as exc:
            # A saga may have advanced this aggregate out-of-band (e.g. the
            # TournamentTableSaga parking a table for hand-for-hand), leaving our
            # optimistic cursor stale. On a sequence mismatch, re-seed from the
            # aggregate's persisted head and retry once before giving up.
            if exc.code() != grpc.StatusCode.FAILED_PRECONDITION or (
                "Sequence mismatch" not in (exc.details() or "")
            ):
                raise
            self._seq[key] = self.event_book(domain, root).next_sequence
            resp = self._cmd[domain].HandleCommand(
                _build(self._seq[key]), timeout=timeout
            )
        # Advance our optimistic-concurrency cursor to the aggregate's new head
        # so the next command to this root carries the right expected sequence.
        if resp.events.next_sequence:
            self._seq[key] = resp.events.next_sequence
        else:
            self._seq[key] = self._seq.get(key, 0) + len(resp.events.pages)
        return resp

    # --- queries ------------------------------------------------------------

    def event_book(self, domain: str, root: bytes, timeout: float = 10.0):
        """The aggregate's persisted EventBook at ``root`` (empty pages if the
        aggregate doesn't exist yet)."""
        query = _t.Query()
        query.cover.domain = domain
        query.cover.root.value = root
        return self._query[domain].GetEventBook(query, timeout=timeout)

    def find_event(self, domain: str, root: bytes, fq: str):
        """The first persisted event of type ``fq`` (bare proto name) at
        ``(domain, root)``, or None. Returns the EventPage so callers can decode
        the payload (e.g. to chase a child aggregate's root)."""
        book = self.event_book(domain, root)
        for page in book.pages:
            if (
                fq_from_url(page.event.type_url) == P + fq
                or fq_from_url(page.event.type_url) == fq
            ):
                return page
        return None

    def wait_for_event(
        self,
        domain: str,
        root: bytes,
        fq: str,
        within: float,
        poll: float = 0.2,
    ):
        """Poll ``(domain, root)``'s EventBook until an event of type ``fq``
        appears or ``within`` seconds elapse. Returns the EventPage or None."""
        deadline = time.time() + within
        while True:
            try:
                page = self.find_event(domain, root, fq)
            except grpc.RpcError:
                page = None
            if page is not None:
                return page
            if time.time() >= deadline:
                return None
            time.sleep(poll)

    # --- projector read-model query -----------------------------------------

    def player_balance(self, player_root: bytes, timeout: float = 10.0):
        """The PlayerProjector's materialized bankroll view for ``player_root``
        (``found`` is False until the projection has observed that player)."""
        return self._player_projection.GetPlayerBalance(
            _pq.GetPlayerBalanceRequest(player_root=player_root), timeout=timeout
        )

    def wait_for_balance(
        self,
        player_root: bytes,
        amount: int,
        within: float,
        poll: float = 0.2,
    ):
        """Poll the player projector's read model until it reports ``amount`` for
        ``player_root`` or ``within`` seconds elapse. Returns the matching
        PlayerBalanceView, or the last view/None on timeout. This observes the
        ACTUAL projector folding the deposit event off the bus — the read-model
        eventual-consistency bound EA-0004 asserts."""
        deadline = time.time() + within
        last = None
        while True:
            try:
                view = self.player_balance(player_root)
                last = view
                if view.found and view.balance.amount == amount:
                    return view
            except grpc.RpcError:
                pass
            if time.time() >= deadline:
                return last
            time.sleep(poll)
