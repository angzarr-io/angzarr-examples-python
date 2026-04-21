"""Behave environment for acceptance tests.

Creates a CommandClient for the suite: gRPC channels to the coordinator(s)
selected by PLAYER_URL / TABLE_URL / HAND_URL (defaults to localhost:1310).
"""

import sys
from pathlib import Path

# This file sits at the repo root (examples-python/main/) so behave finds it
# via --stage walk-up from submodule feature files. Add aggregate paths for
# handler imports.
root = Path(__file__).parent
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
    context.hands = {}


def before_scenario(context, scenario):
    """Reset per-scenario state.

    Recreate the CommandClient too: the cluster-tier ``coordinator
    restarted`` scenario kills a pod mid-suite, leaving the next
    scenario's grpc channel pointed at a draining endpoint and
    surfacing as ``Connection reset by peer``. Cheap to rebuild.
    """
    if hasattr(context, "client"):
        context.client.close()
    context.client = create_client()
    context.players = {}
    context.tables = {}
    context.hands = {}
    context.tournaments = {}
    context.last_response = None
    context.last_error = None
    context.last_sync_mode = None
    context.last_cascade_error_mode = None
    context.current_hand_root = None
    context.current_table_name = None
    context.deck_seed = None
    context.deck_config = None
    context.hand_count = 0
    context.command_start_time = None
    context.command_end_time = None
    context.command_succeeded = None
    context.bus_events = []
    context.monitoring_bus = False
    context.saga_failure_configured = False
    context.saga_failure_on_pot = False
    context.projector_healthy = False
    context.dlq_configured = False
    context.dlq_messages = []
    context.pm_registered = False
    context.no_sagas = False
    context.multiple_saga_failures = False
    context.test_players = []
    context.deposit_times = []
    context.event_without_correlation = False


def after_all(context):
    """Clean up the command client."""
    if hasattr(context, "client"):
        context.client.close()
