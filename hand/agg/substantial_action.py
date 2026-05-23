"""Substantial Action detector — TDA Rule 36.

Per TDA Rule 36 (2024):
    Substantial Action is either
      A) any 2 actions in turn, at least one of which puts chips in the
         pot (i.e. any 2 actions except 2 checks or 2 folds), or
      B) any combination of 3 actions in turn (check, bet, raise, call,
         fold). Posted blinds do not count towards SA.

Why this matters: Rule 35-D says a misdeal cannot be declared once SA
has occurred. Rule 38 likewise locks in a single burn-per-street after
SA. Several other rules use SA as a "point of no return" — declaring a
hand kills, refunding bets, etc. all gate on this state.

This module is a pure helper. The Hand aggregate calls it with the
sequence of post-blind actions to determine whether SA has been
reached. Mirrors ``examples-rust/main/hand/agg/src/substantial_action.rs``.
"""

from typing import Sequence

from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types

# ActionType enum values that put chips in the pot. Posted blinds are
# explicitly excluded by Rule 36 — those are emitted as BlindPosted
# events, not ActionTaken events with these action codes.
_CHIP_ACTIONS: frozenset[int] = frozenset(
    {
        poker_types.CALL,
        poker_types.BET,
        poker_types.RAISE,
        poker_types.ALL_IN,
    }
)


def is_substantial_action(actions: Sequence[int]) -> bool:
    """Return True if ``actions`` constitutes substantial action.

    ``actions`` is the ordered sequence of ActionType enum values for
    post-blind actions on the current street. Posted blinds must NOT be
    included — Rule 36 explicitly excludes them.

    Rules:
      - 0 or 1 actions: not yet SA.
      - Exactly 2 actions: SA if at least one is a chip action (CALL,
        BET, RAISE, ALL_IN). Two checks or two folds (or check+fold
        / fold+check) are NOT SA.
      - 3 or more actions: SA regardless of mix.

    Args:
        actions: ordered ActionType enum values for the current street.

    Returns:
        True if SA has been reached; False otherwise.
    """
    n = len(actions)
    if n < 2:
        return False
    if n >= 3:
        return True
    # Exactly 2 actions: SA iff at least one is a chip action.
    return any(a in _CHIP_ACTIONS for a in actions)
