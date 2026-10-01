"""Behave environment for the cluster acceptance stage.

Sits at the repository root so ``behave --stage acceptance`` finds it and
``acceptance_steps/`` from the feature files in the angzarr-project submodule.
One gRPC client and one event-stream subscriber serve the whole run; each
scenario gets a fresh :class:`acceptance_steps._world.World` (unique roots
and conversations).
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _path in (_ROOT, _ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance_steps._client import ClusterClient  # noqa: E402
from acceptance_steps._stream import EventStreamSubscriber, amqp_url  # noqa: E402
from acceptance_steps._world import World  # noqa: E402


def before_all(context):
    context.client = ClusterClient()
    context.stream = None
    context.port_forward = None
    if context.config.dry_run:
        return
    try:
        url, context.port_forward = amqp_url()
        context.stream = EventStreamSubscriber(url)
        context.stream.start()
    except RuntimeError as exc:
        print(f"[acceptance] event stream unavailable: {exc}", file=sys.stderr)


def after_all(context):
    if context.stream is not None:
        context.stream.stop()
    if context.port_forward is not None:
        context.port_forward.terminate()
    context.client.close()


def before_scenario(context, scenario):
    context.world = World(context.client, context.stream)
