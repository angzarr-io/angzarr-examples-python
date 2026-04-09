"""Behave environment for acceptance tests.

Creates a CommandClient based on the PLAYER_URL env var:
- PLAYER_URL set: GrpcClient connecting to coordinator
- PLAYER_URL not set: InProcessClient using handler functions directly
"""

import sys
from pathlib import Path

# Add project paths so imports work
root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))
for agg in ["player/agg", "table/agg", "hand/agg", "sagas"]:
    path = root / agg
    if path.exists():
        sys.path.insert(0, str(path))

from tests.command_client import create_client  # noqa: E402


def before_all(context):
    """Create the command client for the entire test run."""
    context.client = create_client()
    # Track named entities across scenarios (reset per scenario)
    context.players = {}
    context.tables = {}


def before_scenario(context, scenario):
    """Reset per-scenario state."""
    context.players = {}
    context.tables = {}
    context.last_response = None
    context.last_error = None


def after_all(context):
    """Clean up the command client."""
    if hasattr(context, "client"):
        context.client.close()
