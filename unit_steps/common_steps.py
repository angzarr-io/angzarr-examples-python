"""Steps shared by every in-process feature: refusals.

A refusal's business reason maps to the rejection code the component must
report; the exact codes and messages are pinned in the native unit tests.
"""

from __future__ import annotations

from behave import then

from unit_steps._refusals import assert_refused, reason_code


@then("{subject} is refused because {reason}")
def step_refused(context, subject, reason):
    assert_refused(context.world.last, reason_code(reason))
