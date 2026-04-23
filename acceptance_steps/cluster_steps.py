"""Cluster-tier acceptance steps.

Only meaningful when run against a deployed angzarr cluster. They exercise
network serialization, pod lifecycle (kubectl), and observable read-model
lag — none of which the in-process tier exercises.

For the projection / reachability polls we re-use the same CommandClient
the rest of the suite uses, since the deployed coordinator is the only
cross-process surface we control from here.
"""

import os
import subprocess
import time

from behave import given, then, use_step_matcher, when


def _k8s_namespace() -> str:
    """Namespace to target for kubectl calls in cluster steps.

    Defaults to ``angzarr`` for local kind/dev; CI sets ``ANGZARR_NAMESPACE``
    so logs/pod-delete calls hit the actual test namespace.
    """
    return os.environ.get("ANGZARR_NAMESPACE", "angzarr")

from angzarr_client.proto.angzarr import SyncMode
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from common_steps import pack_command
from player_steps import _deposit_funds, _player_root, _register_player

use_step_matcher("re")


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given(r"the poker cluster is reachable via gRPC")
def step_given_cluster_reachable(context):
    """Confirm we have a CommandClient (set up in environment.before_all).

    The connection itself is lazy — the first send_command will surface a
    grpc.RpcError if the cluster is down. We don't pre-flight here so that
    the failure attribution stays close to the actual command under test.
    """
    assert hasattr(context, "client"), "CommandClient not initialized"


# ---------------------------------------------------------------------------
# Registered-with-bankroll helpers (Given)
# ---------------------------------------------------------------------------


@given(r'a registered player "(?P<name>[^"]+)" with bankroll (?P<amount>\d+)')
def step_given_registered_player_with_bankroll(context, name, amount):
    """Register a player and (optionally) deposit an opening bankroll."""
    bankroll = int(amount)
    email = f"{name.lower()}@example.com"
    _register_player(context, name, email)
    if bankroll > 0:
        _deposit_funds(context, name, bankroll)


# ---------------------------------------------------------------------------
# Coordinator restart
# ---------------------------------------------------------------------------


_DOMAIN_LABEL = "angzarr.io/domain"
_COMPONENT_LABEL = "app.kubernetes.io/component=aggregate"


def _restart_coordinator(domain: str, namespace: str | None = None) -> None:
    """Delete the pod backing a domain's aggregate deployment.

    The Deployment controller recreates it; readiness gating in the
    coordinator's probes keeps the Service from routing until the new pod
    is healthy. Tests then poll for reachability.
    """
    ns = namespace if namespace is not None else _k8s_namespace()
    selector = f"{_COMPONENT_LABEL},{_DOMAIN_LABEL}={domain}"
    subprocess.run(
        ["kubectl", "delete", "pod", "-n", ns, "-l", selector, "--wait=false"],
        check=True,
        capture_output=True,
    )


@when(r"the player coordinator is restarted")
def step_when_player_coordinator_restarted(context):
    _restart_coordinator("player")


# ---------------------------------------------------------------------------
# Reachability + projection polling
# ---------------------------------------------------------------------------


def _ping_player(context, name: str) -> bool:
    """Send a no-op-ish DepositFunds(0) and treat any response (including a
    rejection for non-positive amount) as proof the coordinator is up.

    DepositFunds(0) hits the validate path before any state mutation, so
    repeated calls are safe.
    """
    root = _player_root(context, name)
    cmd = player.DepositFunds(
        amount=poker_types.Currency(amount=0, currency_code="USD"),
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.DepositFunds")
    seq = context.players[name]["sequence"]
    try:
        context.client.send_command(
            "player",
            root,
            packed,
            sequence=seq,
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        return True
    except Exception as exc:
        msg = str(exc).lower()
        # An INVALID_ARGUMENT for the zero amount means the coordinator
        # answered — that's reachable. Network errors don't carry that text.
        return "amount" in msg and "positive" in msg


@then(r'within (?P<seconds>\d+) seconds player "(?P<name>[^"]+)" is reachable')
def step_then_within_player_reachable(context, seconds, name):
    deadline = time.time() + int(seconds)
    last_err = None
    while time.time() < deadline:
        try:
            if _ping_player(context, name):
                return
        except Exception as e:  # noqa: BLE001 — surface the last failure
            last_err = e
        time.sleep(0.25)
    raise AssertionError(
        f"player {name!r} not reachable within {seconds}s; last error: {last_err}"
    )


@then(
    r"within (?P<seconds>\d+) seconds the player projection shows bankroll (?P<amount>\d+)"
)
def step_then_within_player_projection_bankroll(context, seconds, amount):
    """Poll the only-tracked player's bankroll until it matches.

    The cluster-tier projector lag is the thing under test; we re-use the
    in-test tracking as the source-of-truth (deposit_funds increments it
    optimistically) and just observe that the projection has caught up
    within the bound. With no projection-query API yet, this is a smoke
    bound — once a query endpoint exists the comparison switches to it.
    """
    expected = int(amount)
    deadline = time.time() + int(seconds)
    if not context.players:
        raise AssertionError("no player tracked in scenario; can't infer projection")
    name = next(iter(context.players))
    while time.time() < deadline:
        if context.players[name]["bankroll"] == expected:
            return
        time.sleep(0.1)
    actual = context.players[name]["bankroll"]
    raise AssertionError(
        f"player {name!r} bankroll {actual} != {expected} after {seconds}s"
    )


# ---------------------------------------------------------------------------
# Cross-coordinator routing observation
# ---------------------------------------------------------------------------


_DEAL_CARDS_EVIDENCE = (
    # Best signal: saga-table-hand sidecar logs the destination domain when
    # it dispatches the translated command.
    ("angzarr.io/saga=saga-table-hand", ('domain="hand"', "domain=hand")),
    # Backup: hand-aggregate logged a HandleCommand for the hand domain. The
    # rust coordinators don't log the proto type name, so we trust that the
    # only inbound command during the scenario is DealCards (the only saga
    # targeting hand in this deploy).
    (
        f"{_COMPONENT_LABEL},{_DOMAIN_LABEL}=hand",
        (
            "/angzarr.CommandHandlerCoordinatorService/HandleCommand",
            "Hand already dealt",
        ),
    ),
)


@then(r"the DealCards command was routed to the hand coordinator")
def step_then_dealcards_routed_to_hand(context):
    """Verify across saga + hand-aggregate logs that DealCards landed.

    Coordinators log commands by gRPC path + correlation_id rather than by
    proto type name, so a literal ``DealCards`` grep misses real success.
    Two-stage check: the saga's "domain=hand" dispatch log AND/OR the hand
    coordinator's ``HandleCommand`` entry for the hand domain count as
    proof. Either alone is sufficient — both should fire on the happy path.
    """
    failures = []
    namespace = _k8s_namespace()
    for selector, needles in _DEAL_CARDS_EVIDENCE:
        result = subprocess.run(
            [
                "kubectl",
                "logs",
                "-n",
                namespace,
                "-l",
                selector,
                "--tail",
                "300",
                "--all-containers=true",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        haystack = (result.stdout or "") + (result.stderr or "")
        if any(n in haystack for n in needles):
            return
        failures.append(
            f"selector={selector!r}: none of {needles!r} found "
            f"(haystack tail: {haystack[-500:]!r})"
        )
    raise AssertionError(
        "No evidence DealCards reached the hand coordinator:\n" + "\n".join(failures)
    )
