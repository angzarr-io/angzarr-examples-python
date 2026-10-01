"""Business reasons in the features and the rejection codes they stand for.

The exact codes and messages are pinned in the native unit tests; a feature
names the reason in words.
"""

from __future__ import annotations

import re

# (reason pattern, code) — first match wins.
_REASONS: list[tuple[str, str]] = [
    (r'^"(?P<name>[^"]+)" already exists$', "ALREADY_EXISTS"),
    (r"^a display name is required$", "DISPLAY_NAME_REQUIRED"),
    (r'^"[^"]+" is not registered$', "PLAYER_NOT_FOUND"),
    (r"^the amount must be positive$", "AMOUNT_NOT_POSITIVE"),
    (
        r'^"[^"]+" has only (?P<available>-?\d+) available$',
        "INSUFFICIENT_AVAILABLE_FUNDS",
    ),
    (r"^only (?P<available>-?\d+) is available$", "INSUFFICIENT_AVAILABLE_FUNDS"),
    (r"^the funds are not available$", "INSUFFICIENT_AVAILABLE_FUNDS"),
    (r'^buy-in "[^"]+" is already held for a different amount$', "HOLD_CONFLICT"),
    (r'^there is no hold "[^"]+"$', "HOLD_NOT_FOUND"),
    (r'^"[^"]+" is not a loyalty member$', "LOYALTY_NOT_ENROLLED"),
    (r"^its configuration is invalid$", "INVALID_TABLE_CONFIG"),
    (r"^seat -?\d+ is taken$", "SEAT_TAKEN"),
    (r"^seat -?\d+ does not exist$", "SEAT_OUT_OF_RANGE"),
    (r"^the buy-in is outside \d+ to \d+$", "BUY_IN_OUT_OF_RANGE"),
    (r'^"[^"]+" is already seated$', "PLAYER_ALREADY_SEATED"),
    (r'^buy-in "[^"]+" holds no seat$', "SEAT_HOLD_NOT_FOUND"),
    (r"^a wager is in play$", "WAGER_IN_PLAY"),
    (r"^the stack would exceed \d+$", "TOP_UP_EXCEEDS_MAX"),
    (r'^"[^"]+" is not seated$', "NOT_SEATED"),
    (r"^seat -?\d+ is not occupied$", "NOT_SEATED"),
    (r"^it is outside the limits \d+ to \d+$", "BET_OUT_OF_RANGE"),
    (r"^it is not an even amount$", "BET_NOT_EVEN"),
    (r"^seat \d+ has already bet this round$", "ALREADY_BET"),
    (r"^the stack is too small$", "INSUFFICIENT_STACK"),
    (r"^a round is in progress$", "ROUND_IN_PROGRESS"),
    (r"^nobody has bet$", "NO_BETS"),
    (r"^it is not seat \d+'s turn$", "NOT_YOUR_TURN"),
    (r"^doubling is only allowed on the first two cards$", "DOUBLE_NOT_ALLOWED"),
    (r"^no round is in progress$", "NO_ROUND_IN_PROGRESS"),
]


def reason_code(reason: str, subject: str = "") -> str:
    """The rejection code a business reason stands for."""
    for pattern, code in _REASONS:
        if re.match(pattern, reason):
            if code == "ALREADY_EXISTS":
                return (
                    "TABLE_ALREADY_EXISTS"
                    if "table" in subject
                    else "PLAYER_ALREADY_EXISTS"
                )
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


def refused_outcome(w):
    """The refused request a scenario's last action led to: the client
    command itself, or else the first command it set off that was refused."""
    if w.last.error is not None:
        return w.last
    for sent in w.sent[w.sent_mark :]:
        if sent.outcome is not None and sent.outcome.error is not None:
            return sent.outcome
    return w.last
