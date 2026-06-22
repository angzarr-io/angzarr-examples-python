"""Behave environment for the poker unit stage.

Sits at the repo root so behave's ``--stage unit`` discovers it (and
``unit_steps/``) by walking up from the submodule feature files
(angzarr-project/features/example/...). Each scenario gets a fresh ``World``: an
FFI router with the ported component handlers registered. Business state never
crosses the FFI — it is rebuilt inside the core from the prior-events history the
steps seed.

Requires the angzarr_router_ffi binding importable (PYTHONPATH includes the
router binding's bindings/python) and its cdylib locatable (ANGZARR_ROUTER_LIB or
the in-repo build dir). The Python package + generated tree resolve from src/.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from unit_steps._harness import World  # noqa: E402 — after sys.path setup


def before_scenario(context, scenario):
    context.world = World()


def after_scenario(context, scenario):
    world = getattr(context, "world", None)
    if world is not None:
        world.close()
