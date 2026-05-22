"""Common step definitions shared across test features."""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_client.helpers import type_name_from_url
from angzarr_client.proto.angzarr.v1 import types_pb2 as types

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, num: int = 0, time_str: str = None) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")

    created_at = None
    if time_str:
        h, m, s = map(int, time_str.split(":"))
        dt = datetime(2024, 1, 1, h, m, s, tzinfo=timezone.utc)
        created_at = Timestamp(seconds=int(dt.timestamp()))
    else:
        created_at = make_timestamp()

    return types.EventPage(
        num=num,
        event=event_any,
        created_at=created_at,
    )


# --- Then steps for result event assertions ---
# These handle the `examples.EventType` format used in feature files


@then(
    r"the result is an? angzarr_client\.proto\.examples\.v1\.(?P<event_type>\w+) event"
)
def step_then_result_is_examples_event(context, event_type):
    """Verify the result event type.

    Matches feature-file assertions like:
    - Then the result is a angzarr_client.proto.examples.v1.CardsDealt event
    - Then the result is an angzarr_client.proto.examples.v1.ActionTaken event
    """
    assert (
        context.result is not None
    ), f"Expected {event_type} event but got error: {getattr(context, 'error_message', context.error)}"
    assert context.result.pages, "No event pages in result"
    event_any = context.result.pages[0].event
    actual_type = type_name_from_url(event_any.type_url)
    expected = f"angzarr_client.proto.examples.v1.{event_type}"
    assert actual_type == expected, f"Expected {expected} but got {actual_type}"


@then(r"a angzarr_client\.proto\.examples\.v1\.(?P<event_type>\w+) event is emitted")
def step_then_examples_event_is_emitted(context, event_type):
    """Verify that an event of the given type is among emitted pages.

    Sibling to ``the result is an X event`` for scenarios that prefer
    the ``is emitted`` phrasing — looks across all newly emitted pages
    rather than only the first.
    """
    assert (
        context.result is not None
    ), f"Expected {event_type} event but got error: {getattr(context, 'error_message', context.error)}"
    assert context.result.pages, "No event pages emitted"
    expected = f"angzarr_client.proto.examples.v1.{event_type}"
    types = [type_name_from_url(p.event.type_url) for p in context.result.pages]
    assert expected in types, f"Expected an emitted {expected} event; got {types}"


# --- Then steps for structured-rejection assertions ---
# Cucumber asserts rejections by stable code + structured details, never by
# rendered message text. See ``poker.errors.StructuredCommandError``.


@then(r'the command is rejected with code "(?P<code>[^"]+)"')
def step_then_rejected_with_code(context, code):
    assert context.error is not None, "Expected command to be rejected but it succeeded"
    actual = getattr(context.error, "code", "")
    assert actual == code, f"Expected rejection code {code!r}, got {actual!r}"


@then(r'the rejection has shape "(?P<shape>[^"]*)"')
def step_then_rejection_has_shape(context, shape):
    """Assert the rejection's structural shape (e.g. ``BoundViolation``).

    The shape is derived from the leaf's class hierarchy via
    ``StructuredCommandError.shape_name()``. Lets a scenario verify that
    a NEW leaf added in the future is wired into the right shape without
    asserting on its specific CODE — cross-cutting safeguard.
    """
    assert context.error is not None, "Expected command to be rejected but it succeeded"
    actual = ""
    if hasattr(context.error, "shape_name"):
        actual = context.error.shape_name()
    assert actual == shape, f"Rejection shape: expected {shape!r}, got {actual!r}"


@then(r'the rejection field "(?P<field>[^"]+)" equals "(?P<value>[^"]*)"')
def step_then_rejection_field_equals(context, field, value):
    assert context.error is not None, "Expected command to be rejected but it succeeded"
    details = getattr(context.error, "details", {}) or {}
    assert (
        field in details
    ), f"Rejection has no field {field!r}; available fields: {sorted(details)}"
    actual = details[field]
    if actual == value:
        return
    # Mirror the ``contains`` step's uuid_for translation: scenarios assert
    # on human-readable player names ("Alice"); handlers store hex of the
    # uuid_for() bytes. Try the translation as a fallback so the spec stays
    # readable without forcing every handler to plumb a name back through.
    from tests.helpers import uuid_for as _uuid_for

    try:
        translated = _uuid_for(value).hex()
        if str(actual) == translated:
            return
    except Exception:
        pass
    raise AssertionError(
        f"Rejection field {field!r}: expected {value!r}, got {actual!r}"
    )


# --- Then steps for rejection cover (addressing envelope) ---
# The router stamps the originating CommandRequest's Cover onto every
# rejection that propagates from a handler. Cucumber reads cover.domain,
# cover.root.value (as hex), and cover.correlation_id directly.


@then(r"the rejection cover has (?P<spec>.+)")
def step_then_rejection_cover_has(context, spec):
    """Compound assertion accepting one or more `field "value"` pairs joined
    by ` and `, e.g.::

        Then the rejection cover has domain "player" and correlation_id "X"
        Then the rejection cover has root_hex "abc..."

    Each pair is checked against the propagated cover; first mismatch fails.
    """
    cover = _rejection_cover_or_fail(context)
    for field, value in _parse_cover_spec(spec):
        actual = _read_cover_field(cover, field)
        assert (
            actual == value
        ), f"Rejection cover {field}: expected {value!r}, got {actual!r}"


def _rejection_cover_or_fail(context):
    assert context.error is not None, "Expected command to be rejected but it succeeded"
    cover = getattr(context.error, "cover", None)
    assert cover is not None, (
        "Rejection has no cover stamped — the router should populate it from "
        "the CommandRequest at the dispatch boundary"
    )
    return cover


# --- Given steps for cucumber-controlled cover contents ---
# Unit-tier tests call handlers directly (bypassing the router), so the
# dispatch-boundary stamping never fires. These steps let a scenario declare
# what cover should ride alongside the command; the per-domain ``_execute_*``
# helpers stamp it onto any caught rejection.


_COVER_FIELD_RE = __import__("re").compile(r'(?P<field>\w+)\s+"(?P<value>[^"]*)"')


def _ensure_command_cover(context):
    if not hasattr(context, "command_cover") or context.command_cover is None:
        context.command_cover = types.Cover()
    return context.command_cover


def _parse_cover_spec(spec):
    """Yield ``(field, value)`` pairs from a compound spec like::

    domain "player" and correlation_id "X" and root_hex "abc"
    """
    pairs = list(_COVER_FIELD_RE.finditer(spec))
    assert pairs, f'No `field "value"` pairs found in cover spec: {spec!r}'
    for match in pairs:
        yield match.group("field"), match.group("value")


def _write_cover_field(cover, field, value):
    if field == "domain":
        cover.domain = value
    elif field == "correlation_id":
        cover.correlation_id = value
    elif field == "root_hex":
        cover.root.value = bytes.fromhex(value)
    else:
        raise AssertionError(
            f"Unknown cover field {field!r}; supported: domain, correlation_id, root_hex"
        )


def _read_cover_field(cover, field):
    if field == "domain":
        return cover.domain
    if field == "correlation_id":
        return cover.correlation_id
    if field == "root_hex":
        return cover.root.value.hex() if cover.HasField("root") else ""
    raise AssertionError(
        f"Unknown cover field {field!r}; supported: domain, correlation_id, root_hex"
    )


@given(r"the command cover has (?P<spec>.+)")
def step_given_cover_has(context, spec):
    """Compound setter accepting one or more `field "value"` pairs joined
    by ` and `, e.g.::

        Given the command cover has domain "player"
        Given the command cover has domain "player" and correlation_id "X"
    """
    cover = _ensure_command_cover(context)
    for field, value in _parse_cover_spec(spec):
        _write_cover_field(cover, field, value)


# Each domain's ``unit_steps/*_steps.py`` defines its own
# ``_stamp_scenario_cover(context, err)`` helper that the relevant
# ``_execute_*`` calls after catching a ``CommandRejectedError``. Inlining
# avoids cross-module imports that don't work cleanly under behave's
# step-loader (it loads each file as a top-level module without a package
# context).
