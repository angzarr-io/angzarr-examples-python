"""gRPC client for the cluster acceptance tier.

Talks to a deployed blackjack example:

* each aggregate's coordinator (``CommandHandlerCoordinatorService`` and
  ``EventQueryService`` on one port): PLAYER_URL, TABLE_URL — by default the
  kind NodePorts localhost:31320 / localhost:31321;
* the ledger projector's ``LedgerQueryService``: LEDGER_URL, by default
  localhost:31325.

It never keeps its own record of what happened: state is always read back
from the cluster (stored history, the ledger) or the event bus.
"""

from __future__ import annotations

import os
import subprocess

import angzarr_router_ffi as _az
import grpc
from google.protobuf import empty_pb2 as _empty

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import ledger_pb2 as _l
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import (
    ledger_pb2_grpc as _l_grpc,
)
from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_blackjack._gen.io.angzarr.v1 import command_handler_pb2_grpc as _ch_grpc
from angzarr_blackjack._gen.io.angzarr.v1 import query_pb2_grpc as _q_grpc
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack.player.agg import main as player_main
from angzarr_blackjack.table.agg import main as table_main

PLAYER, TABLE = "player", "table"
ENDPOINTS = {PLAYER: ("PLAYER_URL", 31320), TABLE: ("TABLE_URL", 31321)}
LEDGER = ("LEDGER_URL", 31325)
NAMESPACE = os.environ.get("ANGZARR_NAMESPACE", "angzarr")
SYNC = _t.SyncMode
CASCADE_ERROR = _t.CascadeErrorMode
MERGE = _t.MergeStrategy


def _endpoint(variable: str, port: int) -> str:
    # `or`, not a get() default: the dev container passes an empty variable
    # when the host has none set.
    return os.environ.get(variable) or f"localhost:{port}"


class ClusterClient:
    """Channels to the deployed services, shared by a whole run."""

    def __init__(self) -> None:
        self._channels: dict[str, grpc.Channel] = {}
        self._connect()
        # The components' own appliers fold stored history into state.
        self._router = _az.Router()
        self._hosts = {
            PLAYER: player_main.build_host(self._router),
            TABLE: table_main.build_host(self._router),
        }

    def _connect(self) -> None:
        for channel in self._channels.values():
            channel.close()
        self._channels = {
            d: grpc.insecure_channel(_endpoint(*ENDPOINTS[d])) for d in ENDPOINTS
        }
        self._channels["ledger"] = grpc.insecure_channel(_endpoint(*LEDGER))
        self._commands = {
            d: _ch_grpc.CommandHandlerCoordinatorServiceStub(self._channels[d])
            for d in ENDPOINTS
        }
        self._queries = {
            d: _q_grpc.EventQueryServiceStub(self._channels[d]) for d in ENDPOINTS
        }
        self._ledger = _l_grpc.LedgerQueryServiceStub(self._channels["ledger"])

    def close(self) -> None:
        for channel in self._channels.values():
            channel.close()
        self._router.close()

    def reachable(self, timeout: float = 10.0) -> bool:
        try:
            for channel in self._channels.values():
                grpc.channel_ready_future(channel).result(timeout=timeout)
        except grpc.FutureTimeoutError:
            return False
        return True

    # --- commands ---------------------------------------------------------------

    def command(
        self,
        domain: str,
        root: bytes,
        message,
        *,
        correlation: str,
        sync_mode: int = SYNC.SYNC_MODE_SIMPLE,
        cascade_error_mode: int = CASCADE_ERROR.CASCADE_ERROR_UNSPECIFIED,
        expected: int | None = None,
        merge: int = MERGE.MERGE_UNSPECIFIED,
        edition: _t.Edition | None = None,
        timeout: float = 30.0,
    ) -> _ch.CommandResponse:
        """Send one client command. Without ``expected`` it is sent against the
        aggregate's current head. Raises grpc.RpcError on a refusal."""
        if expected is None:
            expected = self.book(domain, root, edition=edition).next_sequence
        request = _t.CommandRequest(
            sync_mode=sync_mode, cascade_error_mode=cascade_error_mode
        )
        request.command.cover.CopyFrom(cover(domain, root, correlation, edition))
        page = request.command.pages.add(merge_strategy=merge)
        page.header.sequence = expected
        page.command.CopyFrom(_az.pack(message))
        return self._commands[domain].HandleCommand(request, timeout=timeout)

    def speculate(
        self, domain: str, root: bytes, message, *, correlation: str
    ) -> _ch.CommandResponse:
        """Run a command against the current state without persisting it."""
        request = _ch.SpeculateCommandHandlerRequest()
        request.command.cover.CopyFrom(cover(domain, root, correlation))
        page = request.command.pages.add()
        page.header.sequence = self.book(domain, root).next_sequence
        page.command.CopyFrom(_az.pack(message))
        return self._commands[domain].HandleSyncSpeculative(request, timeout=30.0)

    def store_fact(
        self, domain: str, root: bytes, event, *, external_id: str, correlation: str
    ):
        """Store an event as a fact, persisted without the handler."""
        request = _t.EventRequest(skip_handler=True, sync_mode=SYNC.SYNC_MODE_SIMPLE)
        request.events.cover.CopyFrom(cover(domain, root, correlation))
        page = request.events.pages.add()
        page.header.external_deferred.external_id = external_id
        page.header.external_deferred.description = "acceptance seed"
        page.event.CopyFrom(_az.pack(event))
        return self._commands[domain].HandleEvent(request, timeout=30.0)

    # --- stored history -----------------------------------------------------------

    def book(
        self,
        domain: str,
        root: bytes,
        *,
        temporal: _t.TemporalQuery | None = None,
        edition: _t.Edition | None = None,
    ) -> _t.EventBook:
        query = _t.Query(cover=cover(domain, root, "", edition))
        if temporal is not None:
            query.temporal.CopyFrom(temporal)
        return self._queries[domain].GetEventBook(query, timeout=30.0)

    def books(self, domain: str, root: bytes) -> list[_t.EventBook]:
        """Every book the store streams for ``(domain, root)``, snapshots included."""
        query = _t.Query(cover=cover(domain, root))
        query.range.lower = 0
        return list(self._queries[domain].GetEvents(query, timeout=30.0))

    def conversation(self, domain: str, correlation: str) -> _t.EventBook:
        """Stored events of ``domain`` in one conversation (correlation query)."""
        return self._queries[domain].GetEventBook(
            _t.Query(cover=_t.Cover(domain=domain, correlation_id=correlation)),
            timeout=30.0,
        )

    def roots(self, domain: str) -> list[bytes]:
        """Every aggregate root the store holds for ``domain``."""
        stream = self._queries[domain].GetAggregateRoots(_empty.Empty(), timeout=30.0)
        return [r.root.value for r in stream if r.domain == domain]

    def state(self, domain: str, root: bytes, **query):
        """The aggregate's state, folded from stored history by its own appliers."""
        return self._hosts[domain].rebuild(self.book(domain, root, **query))

    def fold(self, domain: str, book: _t.EventBook):
        return self._hosts[domain].rebuild(book)

    # --- the ledger --------------------------------------------------------------

    def balance(self, player_root: bytes) -> _l.PlayerBalanceView:
        return self._ledger.GetPlayerBalance(
            _l.GetPlayerBalanceRequest(player_root=player_root), timeout=10.0
        )

    def ledger(self) -> _l.LedgerView:
        return self._ledger.GetLedger(_l.GetLedgerRequest(), timeout=10.0)

    # --- operations ----------------------------------------------------------------

    def restart(self, *deployments: str, wait: bool = True) -> None:
        """Restart deployments (``kubectl rollout restart``) and reconnect."""
        prefix = os.environ.get("ANGZARR_DEPLOYMENT_PREFIX", "")
        names = [f"deployment/{prefix}{name}" for name in deployments]
        subprocess.run(
            ["kubectl", "rollout", "restart", "-n", NAMESPACE, *names], check=True
        )
        if wait:
            for name in names:
                subprocess.run(
                    [
                        "kubectl",
                        "rollout",
                        "status",
                        "-n",
                        NAMESPACE,
                        name,
                        "--timeout=120s",
                    ],
                    check=True,
                )
            self._connect()


def cover(
    domain: str, root: bytes, correlation: str = "", edition: _t.Edition | None = None
) -> _t.Cover:
    c = _t.Cover(domain=domain, correlation_id=correlation)
    c.root.value = root
    if edition is not None:
        c.edition.CopyFrom(edition)
    return c
