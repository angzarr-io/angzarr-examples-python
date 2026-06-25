"""Behave environment for the poker cluster-acceptance stage.

Sits at the repo root so ``behave --stage acceptance`` discovers it (and
``acceptance_steps/``) by walking up from the submodule feature files
(angzarr-project/features/example/acceptance/). Unlike the unit stage — which
runs every component in-process through the FFI router — this stage talks to a
DEPLOYED cluster over gRPC: one shared ``ClusterClient`` for the whole run, a
fresh ``World`` (scenario-unique root namespace + correlation id) per scenario.

Talks directly to each aggregate coordinator on its NodePort (player 31320 …
reservation 31324), which the kind cluster maps to the host — no
``kubectl port-forward``. Override a domain with its ``<DOMAIN>_URL`` env var to
target a different cluster. The Background step "the poker cluster is reachable"
fails fast with a clear message if the coordinators aren't up.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from acceptance_steps._client import ClusterClient  # noqa: E402 — after sys.path
from acceptance_steps._world import World  # noqa: E402


def before_all(context):
    context.cluster = ClusterClient()
    context.cluster_reachable = context.cluster.reachable(timeout=10.0)


def after_all(context):
    cluster = getattr(context, "cluster", None)
    if cluster is not None:
        cluster.close()


def before_scenario(context, scenario):
    context.world = World(context.cluster)


def after_scenario(context, scenario):
    pass
