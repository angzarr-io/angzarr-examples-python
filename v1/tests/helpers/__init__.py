"""Shared test helpers for both unit tests and BDD step definitions.

This module provides reusable test utilities that can be used by:
- pytest unit tests (test_*.py)
- behave/pytest-bdd step definitions

The goal is to have one source of truth for test logic, reducing duplication
and ensuring consistent behavior verification across test styles.
"""

from .builders import (
    EventBookBuilder,
    PlayerStateBuilder,
    TableStateBuilder,
    HandStateBuilder,
)
from .proto_helpers import (
    pack_event,
    pack_command,
    unpack_event,
    make_cover,
    make_event_page,
    make_command_book,
    make_event_book,
    currency,
    uuid_for,
)
from .assertions import (
    assert_event_type,
    assert_event_field,
    assert_command_rejected,
    assert_state_field,
)
from .executors import (
    execute_command,
    apply_events,
    rebuild_state,
)

__all__ = [
    # Builders
    "EventBookBuilder",
    "PlayerStateBuilder",
    "TableStateBuilder",
    "HandStateBuilder",
    # Proto helpers
    "pack_event",
    "pack_command",
    "unpack_event",
    "make_cover",
    "make_event_page",
    "make_command_book",
    "make_event_book",
    "currency",
    "uuid_for",
    # Assertions
    "assert_event_type",
    "assert_event_field",
    "assert_command_rejected",
    "assert_state_field",
    # Executors
    "execute_command",
    "apply_events",
    "rebuild_state",
]
