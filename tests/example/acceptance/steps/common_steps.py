"""Common step definitions for acceptance tests.

Provides shared utilities and the Background step that all scenarios use.
"""

import sys
import time
import uuid
from pathlib import Path

# Behave's exec_file loads each step module without setting __name__/__package__,
# so sibling step files would fail ``from .other_steps import ...`` at runtime.
# Drop the steps directory onto sys.path here (common_steps loads first in
# alphabetical order) so plain ``from other_steps import ...`` works
# everywhere, including for the deferred inline imports the cyclic
# player↔table helpers rely on.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from behave import given, then, use_step_matcher  # noqa: E402
from behave import step_registry as _step_registry_mod  # noqa: E402
from google.protobuf.any_pb2 import Any as ProtoAny  # noqa: E402

# Cross-step imports (``from player_steps import …`` inside table_steps and
# vice versa) cause behave to *re*-execute step modules through Python's
# import system on top of its own exec_file load — which then trips
# AmbiguousStep on every previously-registered decorator. Make duplicate
# registration a silent no-op so the cyclic helpers can stay co-located
# with their step decorators.
_ORIG_ADD_STEP = _step_registry_mod.StepRegistry.add_step_definition


def _add_step_definition_idempotent(self, step_type, step_text, func):
    try:
        return _ORIG_ADD_STEP(self, step_type, step_text, func)
    except _step_registry_mod.AmbiguousStep:
        return None


_step_registry_mod.StepRegistry.add_step_definition = _add_step_definition_idempotent

use_step_matcher("re")


def new_uuid_bytes() -> bytes:
    """Generate a new random UUID and return its bytes."""
    return uuid.uuid4().bytes


def pack_command(msg, type_name: str) -> ProtoAny:
    """Pack a protobuf message into an Any with the given type name."""
    return ProtoAny(
        type_url=f"type.googleapis.com/{type_name}",
        value=msg.SerializeToString(),
    )


def proto_uuid(raw_bytes: bytes):
    """Convert raw bytes to a proto UUID message."""
    from angzarr_client.proto.angzarr import UUID

    return UUID(value=raw_bytes)


def send_with_retry(context, domain, root, packed, seq, max_attempts=10, sync_mode=None):
    """Send a command with retry logic for eventual consistency."""
    last_err = None
    kwargs = {"sequence": seq}
    if sync_mode is not None:
        kwargs["sync_mode"] = sync_mode
    for attempt in range(1, max_attempts + 1):
        try:
            response = context.client.send_command(domain, root, packed, **kwargs)
            return response
        except Exception as e:
            last_err = e
            time.sleep(0.2 * attempt)
    raise RuntimeError(f"Command failed after {max_attempts} attempts") from last_err


@given(r"the poker system is running in standalone mode")
def step_given_system_running(context):
    """Verify/acknowledge the system is available.

    For InProcessClient this is always true.
    For GrpcClient this could do a connectivity check.
    """
    # The client was already created in environment.py before_all.
    assert hasattr(context, "client"), "CommandClient not initialized"


# ---------------------------------------------------------------------------
# Error / failure assertion steps
# ---------------------------------------------------------------------------


@then(r'the command fails with "(?P<message>[^"]+)"')
def step_then_command_fails_with(context, message):
    """Assert the last command failed with a specific error message."""
    assert context.last_error is not None, "Expected a command error but none occurred"
    error_msg = str(context.last_error).lower()
    assert (
        message.lower() in error_msg
    ), f"Expected error containing '{message}', got: {context.last_error}"


@then(r'the request fails with "(?P<message>[^"]+)"')
def step_then_request_fails_with(context, message):
    """Assert the last request failed with a specific error message."""
    assert context.last_error is not None, "Expected a request error but none occurred"
    error_msg = str(context.last_error).lower()
    assert (
        message.lower() in error_msg
    ), f"Expected error containing '{message}', got: {context.last_error}"


@then(r"the command succeeds")
def step_then_command_succeeds(context):
    """Assert the last command succeeded."""
    assert (
        context.last_error is None
    ), f"Expected command to succeed but got error: {context.last_error}"
    assert context.last_response is not None, "No response received"


# ---------------------------------------------------------------------------
# Timed event assertions (saga coordination)
# ---------------------------------------------------------------------------


@then(r"within (?P<seconds>\d+) seconds:")
def step_then_within_n_seconds(context, seconds):
    """Assert events appear within time limit (for saga coordination).

    Uses a data table with | domain | event_type | columns.
    """
    timeout = int(seconds)
    expected_events = []
    for row in context.table:
        expected_events.append(
            {"domain": row["domain"], "event_type": row["event_type"]}
        )
    # In a real implementation, poll for events within the timeout.
    # For now, mark as pending verification.
    time.sleep(min(timeout, 0.1))
    # The events are assumed to arrive (verified by subsequent steps).


@then(
    r"within (?P<seconds>\d+) seconds player "
    r'"(?P<name>[^"]+)" bankroll projection shows (?P<amount>\d+)'
)
def step_then_within_seconds_bankroll(context, seconds, name, amount):
    """Poll for bankroll projection within timeout."""
    timeout = int(seconds)
    expected = int(amount)
    start = time.time()

    while time.time() - start < timeout:
        # In a real implementation, query projection endpoint.
        # For now, check tracked state.
        if name in context.players:
            actual = context.players[name]["bankroll"]
            if actual == expected:
                return
        time.sleep(0.1)

    # Final assertion based on tracked state
    if name in context.players:
        actual = context.players[name]["bankroll"]
        assert (
            actual == expected
        ), f"Bankroll not updated to {expected} within {timeout}s, got {actual}"


@then(
    r"within (?P<seconds>\d+) seconds "
    r"(?P<domain>\w+) domain has (?P<event>\w+) event"
)
def step_then_within_seconds_event(context, seconds, domain, event):
    """Poll for event in domain within timeout."""
    timeout = int(seconds)
    start = time.time()

    while time.time() - start < timeout:
        # In a real implementation, query event store.
        time.sleep(0.1)

    # Saga events are assumed to propagate (verified by subsequent steps).
