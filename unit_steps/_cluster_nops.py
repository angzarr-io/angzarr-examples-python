"""Cluster-only step impls — no-op in the in-process tier.

The same `.feature` files in `angzarr-project/features/example/poker/`
run at both tiers. Phrasings that assert on cluster-level behavior
(saga propagation timing, coordinator restart, k8s pod state, sync-mode
fan-out timing) only make sense against deployed coordinators. The
in-process backend executes sagas/PMs inline so the wait-and-poll
semantics are trivially met; these no-op impls let behave register the
phrasings without raising StepNotImplementedError on the unit tier.

Each step here has a real counterpart in
``acceptance_steps/cluster_steps.py`` (or similar) that performs the
actual cluster-side check.
"""

from behave import then, when


@then('the saga propagates from "{source_domain}" to "{target_domain}" within {n:d} seconds')
def step_then_saga_propagates_nop(context, source_domain, target_domain, n):
    """In-process: sagas run inline during send_command. Already done."""


@then("the saga propagates within {n:d} seconds")
def step_then_saga_propagates_simple_nop(context, n):
    """In-process: see above."""


@when('the "{coordinator}" coordinator is restarted')
def step_when_coordinator_restarted_nop(context, coordinator):
    """In-process: no coordinators. State persists in the in-memory
    EventBook regardless."""


@then('the "{coordinator}" coordinator recovers state from the event store within {n:d} seconds')
def step_then_coordinator_recovers_nop(context, coordinator, n):
    """In-process: state never left memory."""


@then("the cluster has {n:d} instances of {coordinator}")
def step_then_cluster_pod_count_nop(context, n, coordinator):
    """In-process: no cluster — trivially the assertion doesn't apply."""


@when("I wait for {n:d} seconds")
def step_when_wait_nop(context, n):
    """In-process: no temporal sequencing needed; everything was already
    synchronous. Real wait happens at the cluster tier."""


@then("the projector reports the event within {n:d} seconds")
def step_then_projector_reports_nop(context, n):
    """In-process: projectors haven't been wired into the inprocess
    backend (yet); the assertion is acceptance-tier-only."""


@then("the fact stream emits {event} within {n:d} seconds")
def step_then_fact_stream_emits_nop(context, event, n):
    """In-process: facts emit inline as part of send_command return."""
