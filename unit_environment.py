"""Behave environment for the in-process (unit) stage.

Sits at the repository root so ``behave --stage unit`` finds it and
``unit_steps/`` by walking up from the feature files in the angzarr-project
submodule. Each scenario gets a fresh :class:`unit_steps._harness.World`: every
component registered on one router binding, driven in process.

A scenario with an undefined or pending step fails the run: behave already
counts undefined steps as failures, and ``after_step`` turns a step left
untested inside an executed scenario into a failure too.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _path in (_ROOT, _ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from behave.model_core import Status  # noqa: E402

from unit_steps._harness import World  # noqa: E402

_NOT_IMPLEMENTED = {
    Status.undefined,
    Status.pending,
    Status.pending_warn,
    Status.untested_pending,
    Status.untested_undefined,
}


def before_scenario(context, scenario):
    context.world = World()


def before_step(context, step):
    context.step_type = step.step_type


def after_scenario(context, scenario):
    world = getattr(context, "world", None)
    if world is not None:
        world.close()
    if any(step.status in _NOT_IMPLEMENTED for step in scenario.steps):
        scenario.set_status(Status.failed)
