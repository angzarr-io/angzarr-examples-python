"""Protocol buffer helpers for test utilities.

Provides functions for packing/unpacking protobufs, creating event books,
and other proto-related test utilities.
"""

import hashlib
from typing import TypeVar

from google.protobuf.any_pb2 import Any as AnyProto
from google.protobuf.message import Message

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

T = TypeVar("T", bound=Message)


def uuid_for(seed: str) -> bytes:
    """Generate a deterministic 16-byte UUID from a seed string.

    Args:
        seed: String to hash into a UUID.

    Returns:
        16-byte deterministic UUID.

    Example:
        >>> player_id = uuid_for("player-alice")
        >>> len(player_id)
        16
    """
    hash_bytes = hashlib.sha256(seed.encode()).digest()
    return hash_bytes[:16]


def currency(amount: int, code: str = "CHIPS") -> poker_types.Currency:
    """Create a Currency proto.

    Args:
        amount: Amount in smallest units.
        code: Currency code (default: CHIPS).

    Returns:
        Currency proto.
    """
    return poker_types.Currency(amount=amount, currency_code=code)


def pack_event(event: Message, type_prefix: str = "examples") -> AnyProto:
    """Pack an event proto into Any.

    Args:
        event: Protobuf message to pack.
        type_prefix: Type URL prefix (default: examples).

    Returns:
        Any-wrapped event.
    """
    any_pb = AnyProto()
    any_pb.Pack(event, type_url_prefix=f"type.googleapis.com/{type_prefix}")
    return any_pb


def pack_command(cmd: Message, type_prefix: str = "examples") -> AnyProto:
    """Pack a command proto into Any.

    Args:
        cmd: Protobuf command message to pack.
        type_prefix: Type URL prefix (default: examples).

    Returns:
        Any-wrapped command.
    """
    any_pb = AnyProto()
    any_pb.Pack(cmd, type_url_prefix=f"type.googleapis.com/{type_prefix}")
    return any_pb


def unpack_event(any_pb: AnyProto, event_cls: type[T]) -> T:
    """Unpack an Any proto into a specific event type.

    Args:
        any_pb: Any-wrapped proto.
        event_cls: Expected event class.

    Returns:
        Unpacked event.

    Raises:
        ValueError: If type_url doesn't match expected type.
    """
    event = event_cls()
    if not any_pb.Unpack(event):
        raise ValueError(
            f"Failed to unpack {any_pb.type_url} as {event_cls.DESCRIPTOR.full_name}"
        )
    return event


def make_cover(domain: str, root: bytes | None = None) -> types.Cover:
    """Create a Cover proto.

    Args:
        domain: Domain name (e.g., "player", "table").
        root: Optional aggregate root UUID.

    Returns:
        Cover proto.
    """
    cover = types.Cover(domain=domain)
    if root:
        cover.root.CopyFrom(types.UUID(value=root))
    return cover


def make_event_page(
    event: Message,
    sequence: int = 0,
    type_prefix: str = "examples",
) -> types.EventPage:
    """Create an EventPage wrapping an event.

    Args:
        event: Event proto to wrap.
        sequence: Sequence number.
        type_prefix: Type URL prefix.

    Returns:
        EventPage proto.
    """
    return types.EventPage(
        header=types.PageHeader(sequence=sequence),
        event=pack_event(event, type_prefix),
    )


def make_event_book(
    domain: str,
    root: bytes,
    events: list[Message] | None = None,
    type_prefix: str = "examples",
) -> types.EventBook:
    """Create an EventBook with events.

    Args:
        domain: Domain name.
        root: Aggregate root UUID.
        events: List of event protos.
        type_prefix: Type URL prefix.

    Returns:
        EventBook proto.
    """
    pages = []
    if events:
        for i, event in enumerate(events):
            pages.append(make_event_page(event, sequence=i, type_prefix=type_prefix))

    return types.EventBook(
        cover=make_cover(domain, root),
        pages=pages,
        next_sequence=len(pages),
    )


def make_command_book(
    domain: str,
    root: bytes,
    command: Message | None = None,
    sequence: int = 0,
    type_prefix: str = "examples",
) -> types.CommandBook:
    """Create a CommandBook with a command.

    Args:
        domain: Domain name.
        root: Aggregate root UUID.
        command: Command proto.
        sequence: Sequence number.
        type_prefix: Type URL prefix.

    Returns:
        CommandBook proto.
    """
    pages = []
    if command:
        pages.append(
            types.CommandPage(
                header=types.PageHeader(
                    sequence_type=types.page_header.SequenceType(sequence=sequence),
                ),
                command=pack_command(command, type_prefix),
            )
        )

    return types.CommandBook(
        cover=make_cover(domain, root),
        pages=pages,
    )


def event_type_name(any_pb: AnyProto) -> str:
    """Extract type name from Any type_url.

    Args:
        any_pb: Any proto.

    Returns:
        Type name (e.g., "PlayerRegistered").
    """
    return any_pb.type_url.split(".")[-1]
