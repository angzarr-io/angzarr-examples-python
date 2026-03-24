"""Semantic test assertions.

Provides high-level assertion functions that make tests more readable
and provide better error messages.
"""

from typing import Any, Callable, TypeVar

from google.protobuf.message import Message

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr import types_pb2 as types

from .proto_helpers import event_type_name, unpack_event

T = TypeVar("T", bound=Message)


def assert_event_type(result: types.EventBook, expected_type: str) -> None:
    """Assert that the first event in the result has the expected type.

    Args:
        result: EventBook containing events.
        expected_type: Expected event type name (e.g., "PlayerRegistered").

    Raises:
        AssertionError: If no events or type doesn't match.
    """
    assert result.pages, "EventBook has no events"

    first_page = result.pages[0]
    assert first_page.HasField("event"), "First page has no event"

    actual_type = event_type_name(first_page.event)
    assert expected_type in actual_type, (
        f"Expected event type '{expected_type}' but got '{actual_type}'"
    )


def assert_event_field(
    result: types.EventBook,
    event_cls: type[T],
    field_path: str,
    expected: Any,
) -> None:
    """Assert that an event field has the expected value.

    Args:
        result: EventBook containing events.
        event_cls: Event class to unpack as.
        field_path: Dot-separated field path (e.g., "amount.value").
        expected: Expected value.

    Raises:
        AssertionError: If field doesn't match.
    """
    assert result.pages, "EventBook has no events"

    first_page = result.pages[0]
    event = unpack_event(first_page.event, event_cls)

    # Navigate field path
    value = event
    for field_name in field_path.split("."):
        if hasattr(value, field_name):
            value = getattr(value, field_name)
        else:
            raise AssertionError(f"Event has no field '{field_name}'")

    assert value == expected, f"Expected {field_path}={expected} but got {value}"


def assert_event_count(result: types.EventBook, expected_count: int) -> None:
    """Assert the number of events in the result.

    Args:
        result: EventBook containing events.
        expected_count: Expected number of events.

    Raises:
        AssertionError: If count doesn't match.
    """
    actual_count = len(result.pages)
    assert actual_count == expected_count, (
        f"Expected {expected_count} events but got {actual_count}"
    )


def assert_command_rejected(
    exc_info: Any,
    expected_message: str | None = None,
) -> None:
    """Assert that a command was rejected with expected message.

    Args:
        exc_info: pytest.raises exception info.
        expected_message: Optional substring to find in error message.

    Raises:
        AssertionError: If not CommandRejectedError or message doesn't match.
    """
    assert exc_info.type is CommandRejectedError, (
        f"Expected CommandRejectedError but got {exc_info.type}"
    )

    if expected_message:
        actual_message = str(exc_info.value)
        assert expected_message.lower() in actual_message.lower(), (
            f"Expected error message containing '{expected_message}' "
            f"but got '{actual_message}'"
        )


def assert_state_field(state: Any, field_name: str, expected: Any) -> None:
    """Assert that a state field has the expected value.

    Args:
        state: State object.
        field_name: Field name.
        expected: Expected value.

    Raises:
        AssertionError: If field doesn't match.
    """
    actual = getattr(state, field_name)
    assert actual == expected, (
        f"Expected {field_name}={expected} but got {actual}"
    )


def assert_no_events(result: types.EventBook) -> None:
    """Assert that the result has no events.

    Args:
        result: EventBook to check.

    Raises:
        AssertionError: If events exist.
    """
    assert len(result.pages) == 0, (
        f"Expected no events but got {len(result.pages)}"
    )


def assert_event_matches(
    result: types.EventBook,
    event_cls: type[T],
    predicate: Callable[[T], bool],
    message: str = "Event predicate failed",
) -> None:
    """Assert that an event matches a predicate function.

    Args:
        result: EventBook containing events.
        event_cls: Event class to unpack as.
        predicate: Function that returns True if event matches.
        message: Error message if predicate fails.

    Raises:
        AssertionError: If predicate returns False.
    """
    assert result.pages, "EventBook has no events"

    first_page = result.pages[0]
    event = unpack_event(first_page.event, event_cls)

    assert predicate(event), message
