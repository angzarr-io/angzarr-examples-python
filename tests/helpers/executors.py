"""Command execution and state rebuilding helpers.

Provides utilities for executing commands and rebuilding state from events,
used by both unit tests and BDD step definitions.
"""

from typing import Any, Callable, TypeVar

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr import types_pb2 as types

from .proto_helpers import pack_event

S = TypeVar("S")  # State type
E = TypeVar("E", bound=Message)  # Event type


def execute_command(
    handler: Callable[..., E],
    cmd: Message,
    state: S,
    seq: int = 0,
) -> E:
    """Execute a command handler and return the result event.

    This is the simple form that just calls the handler directly.
    Used for functional handlers decorated with @command_handler.

    Args:
        handler: Command handler function.
        cmd: Command proto.
        state: Current state.
        seq: Sequence number.

    Returns:
        Result event from handler.

    Raises:
        CommandRejectedError: If command is rejected.
    """
    return handler(cmd, state, seq)


def execute_and_apply(
    handler: Callable[..., E],
    cmd: Message,
    state: S,
    applier: Callable[[S, E], None],
    seq: int = 0,
) -> tuple[E, S]:
    """Execute a command and apply the resulting event to state.

    Args:
        handler: Command handler function.
        cmd: Command proto.
        state: Current state (will be mutated).
        applier: Event applier function.
        seq: Sequence number.

    Returns:
        Tuple of (event, updated_state).

    Raises:
        CommandRejectedError: If command is rejected.
    """
    event = handler(cmd, state, seq)
    applier(state, event)
    return event, state


def apply_events(
    state: S,
    events: list[Message],
    appliers: dict[str, Callable[[S, Any], None]],
) -> S:
    """Apply a list of events to state.

    Args:
        state: State to mutate.
        events: List of event protos.
        appliers: Dict mapping event type name to applier function.

    Returns:
        The mutated state.
    """
    for event in events:
        type_name = type(event).__name__
        if type_name in appliers:
            appliers[type_name](state, event)
    return state


def apply_event_book(
    state: S,
    event_book: types.EventBook,
    appliers: dict[str, tuple[type, Callable[[S, Any], None]]],
) -> S:
    """Apply events from an EventBook to state.

    Args:
        state: State to mutate.
        event_book: EventBook containing events.
        appliers: Dict mapping type_url suffix to (proto_class, applier).

    Returns:
        The mutated state.
    """
    for page in event_book.pages:
        if not page.HasField("event"):
            continue

        event_any = page.event
        type_url = event_any.type_url

        for suffix, (proto_cls, applier) in appliers.items():
            if type_url.endswith(suffix):
                event = proto_cls()
                event_any.Unpack(event)
                applier(state, event)
                break

    return state


def rebuild_state(
    state_cls: type[S],
    event_book: types.EventBook,
    appliers: dict[str, tuple[type, Callable[[S, Any], None]]],
) -> S:
    """Rebuild state from an EventBook.

    Args:
        state_cls: State class to instantiate.
        event_book: EventBook containing events.
        appliers: Dict mapping type_url suffix to (proto_class, applier).

    Returns:
        Newly constructed state with events applied.
    """
    state = state_cls()
    return apply_event_book(state, event_book, appliers)


class CommandExecutor:
    """Helper class for executing commands in tests.

    Wraps handler execution with state management and result tracking.
    """

    def __init__(self, state: S):
        """Initialize with initial state.

        Args:
            state: Initial aggregate state.
        """
        self.state = state
        self.events: list[Message] = []
        self.last_result: Message | None = None
        self.last_error: CommandRejectedError | None = None

    def execute(
        self,
        handler: Callable[..., E],
        cmd: Message,
        applier: Callable[[S, E], None] | None = None,
    ) -> "CommandExecutor":
        """Execute a command.

        Args:
            handler: Command handler function.
            cmd: Command proto.
            applier: Optional event applier to update state.

        Returns:
            Self for chaining.
        """
        self.last_error = None
        try:
            seq = len(self.events)
            event = handler(cmd, self.state, seq)
            self.last_result = event
            self.events.append(event)

            if applier:
                applier(self.state, event)

        except CommandRejectedError as e:
            self.last_error = e
            self.last_result = None

        return self

    def succeeded(self) -> bool:
        """Check if last command succeeded."""
        return self.last_error is None and self.last_result is not None

    def failed(self) -> bool:
        """Check if last command failed."""
        return self.last_error is not None

    def get_event(self) -> Message:
        """Get the last result event.

        Raises:
            AssertionError: If no event or command failed.
        """
        assert self.last_result is not None, (
            f"No event - command failed: {self.last_error}"
        )
        return self.last_result

    def get_error(self) -> CommandRejectedError:
        """Get the last error.

        Raises:
            AssertionError: If command succeeded.
        """
        assert self.last_error is not None, "Command succeeded, no error"
        return self.last_error
