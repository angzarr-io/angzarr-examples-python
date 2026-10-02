"""pytest -> behave bridge for the in-process scenario tier.

Runs every blackjack and blackjack-framework scenario as one pytest test, in
this process, so that

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
    "angzarr-project/features/example/blackjack",
    "angzarr-project/features/example/blackjack-framework",
]


def test_behave_unit_suite() -> None:
    """Every in-process scenario passes; undefined or pending steps fail."""
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
                "not @wip",
                *_FEATURES,
            ]
        )
    finally:
        os.chdir(cwd)
    assert status == 0, "behave unit suite failed"
