"""Behave environment configuration."""

import sys
from pathlib import Path

# This file sits at the repo root (examples-python/main/) so behave finds it
# via --stage walk-up from submodule feature files.
root = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "prj-output"))
sys.path.insert(0, str(root / "hand-flow"))

# Add aggregate paths (both naming conventions for compatibility)
for agg in ["player/agg", "table/agg", "hand/agg", "sagas"]:
    path = root / agg
    if path.exists():
        sys.path.insert(0, str(path))

import re  # noqa: E402

from wip_scenarios import WIP_SCENARIOS  # noqa: E402

_OUTLINE_ROW_SUFFIX = re.compile(r"\s+--\s+@[\d.]+\s*$")


def before_scenario(context, scenario):
    feature_basename = Path(scenario.feature.filename).name
    # Scenario Outline rows carry a `-- @1.X` suffix on scenario.name; strip
    # for the wip lookup so the outline parent matches a single entry.
    base_name = _OUTLINE_ROW_SUFFIX.sub("", scenario.name).strip()
    if (feature_basename, base_name) in WIP_SCENARIOS:
        scenario.skip("WIP: matcher implementation pending; see wip_scenarios.py")
        return
    context.events = []
    context.output_lines = []
    context.cards_output = ""
    context.result = None
    context.error = None
    context.state = None
    context.commands_sent = []
    context.state_seeders = []
