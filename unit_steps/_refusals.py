"""Business reasons in the features and the rejection codes they stand for.

The exact codes and messages are pinned in the native unit tests; a feature
names the reason in words.
"""

from __future__ import annotations

import re

# (reason pattern, code) — first match wins.
_REASONS: list[tuple[str, str]] = [
    (r'^"[^"]+" already exists$', "TABLE_ALREADY_EXISTS"),
    (r"^its configuration is invalid$", "INVALID_TABLE_CONFIG"),
]


def reason_code(reason: str) -> str:
    """The rejection code a business reason stands for."""
    for pattern, code in _REASONS:
        if re.match(pattern, reason):
            return code
    raise AssertionError(f"no rejection code is known for the reason {reason!r}")


def assert_refused(outcome, code: str) -> None:
    assert (
        outcome.error is not None
    ), f"expected a refusal with {code}, but it succeeded"
    assert (
        outcome.error.code == code
    ), f"expected {code}, got {outcome.error.code}: {outcome.error.message}"
    assert not outcome.events, "a refused request must record no events"
