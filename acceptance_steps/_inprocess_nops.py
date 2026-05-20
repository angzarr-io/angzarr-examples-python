"""In-process-only step impls — no-op in the cluster tier.

Counterpart to ``unit_steps/_cluster_nops.py``. The same `.feature` files
in ``angzarr-project/features/example/poker/`` run at both tiers.
Phrasings that inspect aggregate-internal state (private dicts,
event-replay invariants, in-memory snapshots) aren't observable through
gRPC at the cluster tier; this module no-ops them so behave can resolve
the steps without raising StepNotImplementedError.

Each step here has a real counterpart in ``unit_steps/`` that performs
the actual aggregate-state inspection.
"""

from behave import then


@then("the aggregate state has {field} equal to {value}")
def step_then_state_field_nop(context, field, value):
    """Cluster: aggregate internals aren't exposed via gRPC. Skip."""


@then("the aggregate state has no {field}")
def step_then_state_missing_field_nop(context, field):
    """Cluster: see above."""


@then("the event book contains exactly {n:d} pages")
def step_then_book_size_nop(context, n):
    """Cluster: per-aggregate-root book is server-side; tested via the
    poker scenarios' externally-visible outcomes instead."""


@then("the rebuilt aggregate has {field} equal to {value}")
def step_then_rebuilt_field_nop(context, field, value):
    """Cluster: rebuild happens server-side automatically; the externally
    observable behavior is what we assert on at this tier."""
