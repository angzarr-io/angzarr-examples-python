"""pytest -> behave bridge for the unit (gherkin) tier.

There is no native-pytest test tier in this example; the unit tests are behave
scenarios driven through the in-process FFI router. This bridge runs the behave
unit stage as a single pytest test so:

  * ``just test-pytest`` (and the combined ``just test``) exercise the gherkin
    tier, and
  * mutmut — which drives pytest — has a test that folds every poker +
    framework feature through the mutated handlers.

The behave run is rooted at this file's repo (``parents[2]`` = examples-python
``main``). That is deliberate: when mutmut copies the source tree into its
``mutants/`` workdir, this file is copied too, so ``parents[2]`` resolves to the
MUTATED copy and behave folds the mutated handler — which is what lets a mutant
be caught. Run normally, it resolves to the real repo.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_LIB = _REPO / "vendor" / "angzarr-router-ffi" / "libangzarr_router_ffi.so"
_FEATURES = [
    "angzarr-project/features/example/poker",
    "angzarr-project/features/example/framework",
]


def test_behave_unit_suite() -> None:
    """The behave unit suite must pass (0 failed). A surviving mutant breaks a
    scenario, behave exits non-zero, and the mutant is killed."""
    env = {**os.environ, "ANGZARR_ROUTER_LIB": str(_LIB)}
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "behave",
            "--stage",
            "unit",
            *_FEATURES,
            "--tags=~@wip",
        ],
        cwd=_REPO,
        env=env,
    )
    assert result.returncode == 0, "behave unit suite failed"
