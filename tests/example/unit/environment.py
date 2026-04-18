"""Behave environment configuration."""

import sys
from pathlib import Path

# Add project paths. Resolve symlinks so sys.path is correct when this module
# is loaded via a symlink (e.g. under angzarr-project/features/example/unit/).
root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "prj-output"))
sys.path.insert(0, str(root / "hand-flow"))

# Add aggregate paths (both naming conventions for compatibility)
for agg in ["player/agg", "table/agg", "hand/agg", "sagas"]:
    path = root / agg
    if path.exists():
        sys.path.insert(0, str(path))


def before_scenario(context, scenario):
    """Reset context before each scenario."""
    context.events = []
    context.output_lines = []
    context.cards_output = ""
    context.result = None
    context.error = None
    context.state = None
    context.commands_sent = []
    context.state_seeders = []
