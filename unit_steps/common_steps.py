"""Steps shared by every in-process feature: refusals and no-op requests.

A refusal's business reason maps to the rejection code the component must
report; the exact codes and messages are pinned in the native unit tests.
"""

from __future__ import annotations

import parse
from behave import register_type, then

from unit_steps._refusals import assert_refused, reason_code, refused_outcome


@parse.with_pattern(r'[^"]*')
def _text(value: str) -> str:
    """Quoted text that may be empty: ``"{name:Text}"``."""
    return value


register_type(Text=_text)


@then("{subject} is refused because {reason}")
def step_refused(context, subject, reason):
    assert_refused(refused_outcome(context.world), reason_code(reason, subject))


@then("the request succeeds without any change to the {what}")
def step_no_change(context, what):
    last = context.world.last
    assert last.error is None, f"expected success, got {last.error}"
    assert not last.events, f"expected no change, got {last.types()}"
