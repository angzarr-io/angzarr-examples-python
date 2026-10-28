"""pytest -> behave bridge for the in-process scenario tier.

Runs the stage-1 scenarios (table creation and the golden shoe vectors; the
same selection as ``just test-example-unit``) as one pytest test, in this
process, so that

* ``just mutation-test`` (mutmut drives pytest) kills a mutant that breaks a
  scenario, and sees which business functions the scenarios call; and
* a plain ``pytest`` run covers the scenario tier as well as the native tests.

The run is rooted at this file's repository (``parents[2]``): when mutmut
copies the tree into ``mutants/`` the bridge runs the mutated copy.
"""

from __future__ import annotations

import os
from pathlib import Path

from behave.__main__ import main as behave_main

_REPO = Path(__file__).resolve().parents[2]
_FEATURES = [
    "angzarr-project/features/example/blackjack/table.feature",
    "angzarr-project/features/example/blackjack/shoe.feature",
]
# The stage-1 slice: EU-1440..1442 and EU-1520..1525. Keep in step with
# UNIT_TAGS in justfile.container.
_SLICE = [f"@EU-{n}" for n in (*range(1440, 1443), *range(1520, 1526))]
_TAGS = f"not @wip and ({' or '.join(_SLICE)})"


def test_behave_unit_suite() -> None:
    """Every stage-1 scenario passes; undefined or pending steps fail."""
    cwd = os.getcwd()
    os.chdir(_REPO)
    try:
        status = behave_main(
            [
                "--stage",
                "unit",
                "--format",
                "progress",
                "--no-capture",
                "--tags",
                _TAGS,
                *_FEATURES,
            ]
        )
    finally:
        os.chdir(cwd)
    assert status == 0, "behave unit suite failed"
