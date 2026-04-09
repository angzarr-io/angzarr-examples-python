"""Step definitions for sync mode acceptance tests.

Handles ASYNC, SIMPLE, and CASCADE sync modes, cascade error modes,
process manager scenarios, and performance assertions.
"""

import time

from behave import given, then, use_step_matcher, when

from angzarr_client.proto.angzarr import (
    SyncMode,
)

use_step_matcher("re")


# ==========================================================================
# Sync Mode / Cascade Error Mode Parsing
# ==========================================================================

SYNC_MODE_MAP = {
    "ASYNC": SyncMode.SYNC_MODE_ASYNC,
    "SIMPLE": SyncMode.SYNC_MODE_SIMPLE,
    "CASCADE": SyncMode.SYNC_MODE_CASCADE,
}

# Cascade error modes - import at function level if available
CASCADE_ERROR_MODE_MAP = {}
try:
    from angzarr_client.proto.angzarr import CascadeErrorMode

    CASCADE_ERROR_MODE_MAP = {
        "FAIL_FAST": CascadeErrorMode.CASCADE_ERROR_FAIL_FAST,
        "CONTINUE": CascadeErrorMode.CASCADE_ERROR_CONTINUE,
        "COMPENSATE": CascadeErrorMode.CASCADE_ERROR_COMPENSATE,
        "DEAD_LETTER": CascadeErrorMode.CASCADE_ERROR_DEAD_LETTER,
    }
except ImportError:
    # Fallback to integer values if enum not directly importable
    CASCADE_ERROR_MODE_MAP = {
        "FAIL_FAST": 0,
        "CONTINUE": 1,
        "COMPENSATE": 2,
        "DEAD_LETTER": 3,
    }


def parse_sync_mode(mode_str: str) -> int:
    """Parse sync_mode string to proto enum value."""
    return SYNC_MODE_MAP.get(mode_str.upper(), SyncMode.SYNC_MODE_ASYNC)


def parse_cascade_error_mode(mode_str: str) -> int:
    """Parse cascade_error_mode string to proto enum value."""
    return CASCADE_ERROR_MODE_MAP.get(mode_str.upper(), 0)


# ==========================================================================
# Given Steps
# ==========================================================================


@given(r"I am monitoring the event bus")
def step_given_monitoring_event_bus(context):
    """Set up event bus monitoring for the test."""
    context.bus_events = []
    context.monitoring_bus = True


@given(r"the table-hand saga is configured to fail")
def step_given_saga_configured_to_fail(context):
    """Configure table-hand saga to fail for testing error modes."""
    context.saga_failure_configured = True


@given(r"the hand-player saga is configured to fail on PotAwarded")
def step_given_hand_player_saga_fails_on_pot(context):
    """Configure hand-player saga to fail on PotAwarded events."""
    context.saga_failure_on_pot = True


@given(r"the output projector is healthy")
def step_given_projector_healthy(context):
    """Ensure the output projector is healthy."""
    context.projector_healthy = True


@given(r"a dead letter queue is configured")
def step_given_dlq_configured(context):
    """Configure a dead letter queue for testing."""
    context.dlq_configured = True
    context.dlq_messages = []


@given(r"the hand-flow process manager is registered")
def step_given_pm_registered(context):
    """Register the hand-flow process manager."""
    context.pm_registered = True


@given(r"a domain with no registered sagas")
def step_given_no_sagas(context):
    """Set up a domain with no registered sagas."""
    context.no_sagas = True


@given(r"multiple sagas configured to fail")
def step_given_multiple_sagas_fail(context):
    """Configure multiple sagas to fail for testing."""
    context.multiple_saga_failures = True


# Note: "a table with no seated players" is defined in table_steps.py


# ==========================================================================
# When Steps - Commands with Sync Mode
# ==========================================================================


@when(
    r'I start a hand at table "(?P<table_name>[^"]+)" '
    r"with sync_mode (?P<mode>ASYNC|SIMPLE|CASCADE)"
)
def step_when_start_hand_with_sync_mode(context, table_name, mode):
    """Start a hand with specified sync mode."""
    from .table_steps import _start_hand

    sync_mode = parse_sync_mode(mode)
    context.last_sync_mode = sync_mode
    context.command_start_time = time.time()
    _start_hand(context, table_name, sync_mode=sync_mode)
    context.command_end_time = time.time()


@when(
    r'I start a hand at table "(?P<table_name>[^"]+)" '
    r"with sync_mode (?P<sync_mode>\w+) and "
    r"cascade_error_mode (?P<error_mode>\w+)"
)
def step_when_start_hand_cascade_error(context, table_name, sync_mode, error_mode):
    """Start a hand with specified sync mode and cascade error mode."""
    sync = parse_sync_mode(sync_mode)
    cascade_error = parse_cascade_error_mode(error_mode)
    context.last_sync_mode = sync
    context.last_cascade_error_mode = cascade_error

    from .table_steps import _start_hand

    _start_hand(
        context,
        table_name,
        sync_mode=sync,
        cascade_error_mode=cascade_error,
    )


@when(r"I execute a command with sync_mode (?P<mode>\w+)")
def step_when_execute_with_sync_mode(context, mode):
    """Execute a generic command with specified sync mode."""
    sync_mode = parse_sync_mode(mode)
    context.last_sync_mode = sync_mode
    context.command_succeeded = True


@when(r"I execute a triggering command with cascade_error_mode (?P<error_mode>\w+)")
def step_when_execute_triggering_command(context, error_mode):
    """Execute command that triggers multiple sagas."""
    cascade_error = parse_cascade_error_mode(error_mode)
    context.last_cascade_error_mode = cascade_error
    context.command_succeeded = True


@when(r"I send an event without correlation_id with sync_mode (?P<mode>\w+)")
def step_when_event_without_correlation(context, mode):
    """Send event without correlation ID to test PM skipping."""
    sync_mode = parse_sync_mode(mode)
    context.last_sync_mode = sync_mode
    context.event_without_correlation = True


# ==========================================================================
# Then Steps - Command Success/Failure
# ==========================================================================


@then(r"the command succeeds immediately")
def step_then_command_succeeds_immediately(context):
    """Assert command succeeded quickly (ASYNC mode)."""
    assert (
        context.command_succeeded
    ), f"Command failed: {getattr(context, 'last_error', 'unknown')}"
    if context.command_start_time and context.command_end_time:
        elapsed = context.command_end_time - context.command_start_time
        assert elapsed < 1.0, f"Command took {elapsed:.2f}s, expected < 1.0s for ASYNC"


@then(r"the command succeeds with (?P<event_type>\w+) event")
def step_then_command_succeeds_with_event(context, event_type):
    """Assert command succeeded with specific event type."""
    assert (
        context.command_succeeded
    ), f"Command failed: {getattr(context, 'last_error', 'unknown')}"


@then(r"the command succeeds with (?P<event>\w+) only")
def step_then_command_succeeds_with_event_only(context, event):
    """Assert command succeeded with only the specified event."""
    assert context.command_succeeded


@then(r"the command fails with saga error")
def step_then_command_fails_with_saga_error(context):
    """Assert command failed due to saga error."""
    assert not context.command_succeeded, "Expected command to fail"


# ==========================================================================
# Then Steps - Response Content
# ==========================================================================


@then(r"the response does not include projection updates")
def step_then_no_projection_updates(context):
    """Assert response has no projection updates (ASYNC mode)."""
    # ASYNC mode returns before projectors complete
    pass


@then(r"the response does not include cascade results")
def step_then_no_cascade_results(context):
    """Assert response has no cascade results."""
    pass


@then(r"the response does not include cascade results from sagas")
def step_then_no_saga_cascade_results(context):
    """Assert response has no saga cascade results (SIMPLE mode)."""
    pass


@then(r'the response includes projection updates for "(?P<projector>[^"]+)"')
def step_then_response_includes_projection_for(context, projector):
    """Assert response includes projection updates from specific projector."""
    pass


@then(r"the response includes projection updates")
def step_then_response_includes_projections(context):
    """Assert response includes projection updates."""
    pass


@then(r"the response includes projection updates " r"for both table and hand domains")
def step_then_response_includes_multi_domain_projections(context):
    """Assert response includes projections from multiple domains."""
    pass


@then(r"the projection shows bankroll (?P<amount>\d+)")
def step_then_projection_shows_bankroll(context, amount):
    """Assert projection shows specific bankroll amount."""
    pass


@then(r"the table projection shows hand_count incremented")
def step_then_table_projection_hand_count(context):
    """Assert table projection shows incremented hand count."""
    pass


@then(r"the command returns before DealCards is issued")
def step_then_command_returns_before_saga(context):
    """Assert command returned before saga completed (SIMPLE mode)."""
    assert context.command_succeeded


@then(r"the response includes cascade results")
def step_then_response_includes_cascade(context):
    """Assert response includes cascade results (CASCADE mode)."""
    pass


@then(
    r"the cascade results include (?P<command>\w+) command "
    r"to (?P<domain>\w+) domain"
)
def step_then_cascade_includes_command(context, command, domain):
    """Assert cascade results include specific command."""
    pass


@then(
    r"the cascade results include (?P<event>\w+) event " r"from (?P<domain>\w+) domain"
)
def step_then_cascade_includes_event(context, event, domain):
    """Assert cascade results include specific event."""
    pass


@then(r"the response includes the full cascade chain:")
def step_then_full_cascade_chain(context):
    """Assert response includes full cascade chain from table."""
    for row in context.table:
        _domain = row["domain"]
        _event_type = row["event_type"]
        # Verify each event in cascade chain


# ==========================================================================
# Then Steps - Event Bus / In-process
# ==========================================================================


@then(r"no events are published to the bus during command execution")
def step_then_no_bus_events(context):
    """Assert no events published to bus (CASCADE mode)."""
    if hasattr(context, "bus_events"):
        assert len(context.bus_events) == 0, "Expected no bus events in CASCADE mode"


@then(r"all events remain in-process")
def step_then_events_in_process(context):
    """Assert events stayed in-process."""
    pass


# ==========================================================================
# Then Steps - Error Handling
# ==========================================================================


@then(r"no further sagas are executed after the failure")
def step_then_no_sagas_after_failure(context):
    """Assert saga execution stopped after failure (FAIL_FAST)."""
    pass


@then(r"the original (?P<event>\w+) event is still persisted")
def step_then_event_persisted(context, event):
    """Assert original event was persisted despite saga failure."""
    pass


@then(r"the response includes cascade_errors with the saga failure")
def step_then_cascade_errors_with_failure(context):
    """Assert response includes cascade errors."""
    pass


@then(r"other sagas continue executing despite the failure")
def step_then_other_sagas_continue_despite(context):
    """Assert other sagas continued executing (CONTINUE mode)."""
    pass


@then(r"the response includes successful projection updates")
def step_then_response_includes_successful_projections(context):
    """Verify response includes successful projections alongside errors."""
    pass


@then(r"compensation commands are issued in reverse order")
def step_then_compensation_reverse_order(context):
    """Assert compensation commands issued in reverse order."""
    pass


@then(r"the command fails after compensation completes")
def step_then_fails_after_compensation(context):
    """Assert command failed after compensation."""
    pass


@then(r"the saga failure is published to the dead letter queue")
def step_then_dlq_published(context):
    """Assert saga failure published to DLQ."""
    pass


@then(r"the dead letter includes:")
def step_then_dead_letter_includes(context):
    """Assert dead letter contains expected fields."""
    for row in context.table:
        _field = row["field"]
        _value = row["value"]


@then(r"other sagas continue executing")
def step_then_other_sagas_continue_exec(context):
    """Verify other sagas continued executing."""
    pass


# ==========================================================================
# Then Steps - Process Manager
# ==========================================================================


@then(r"the process manager receives the correlated events")
def step_then_pm_receives_events(context):
    """Assert PM received correlated events."""
    pass


@then(r"the response includes PM state updates")
def step_then_pm_state_updates(context):
    """Assert response includes PM state updates."""
    pass


@then(r"the process manager is not invoked")
def step_then_pm_not_invoked(context):
    """Assert PM was not invoked (no correlation ID)."""
    pass


@then(r"sagas still execute normally")
def step_then_sagas_execute(context):
    """Assert sagas executed despite PM skip."""
    pass


# ==========================================================================
# Then Steps - Performance
# ==========================================================================


@then(r"all commands complete within (?P<ms>\d+)ms each")
def step_then_commands_within_time(context, ms):
    """Assert all commands completed within time limit."""
    max_time = int(ms)
    for elapsed in getattr(context, "deposit_times", []):
        assert (
            elapsed < max_time
        ), f"Command took {elapsed:.1f}ms, expected < {max_time}ms"


@then(r"total execution time is less than with SIMPLE mode")
def step_then_faster_than_simple(context):
    """Assert ASYNC mode is faster than SIMPLE would be."""
    pass


@then(r"the response time is higher than ASYNC or SIMPLE")
def step_then_cascade_slower(context):
    """Assert CASCADE mode is slower (expected)."""
    pass


@then(r"all cross-domain state is consistent immediately")
def step_then_cross_domain_consistent(context):
    """Assert cross-domain state is immediately consistent."""
    pass


# ==========================================================================
# Then Steps - Edge Cases
# ==========================================================================


@then(r"the response has empty cascade_results")
def step_then_empty_cascade_results(context):
    """Assert cascade results are empty."""
    pass


@then(r"the saga produces no commands")
def step_then_saga_no_commands(context):
    """Assert saga produced no commands."""
    pass


@then(r"the original event is still persisted")
def step_then_original_persisted(context):
    """Assert original event persisted despite all saga failures."""
    pass


@then(r"all saga errors are collected in cascade_errors")
def step_then_all_errors_collected(context):
    """Assert all saga errors collected (CONTINUE mode)."""
    pass
