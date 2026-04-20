"""Behave environment for acceptance tests.

Creates a CommandClient based on the PLAYER_URL env var:
- PLAYER_URL set: GrpcClient connecting to coordinator
- PLAYER_URL not set: InProcessClient using handler functions directly
"""

import sys
from pathlib import Path

# Add project paths so imports work
root = Path(__file__).parent.parent.parent.parent
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
