"""Shared step helpers for the poker unit stage.

Generic assertions over the last dispatch outcome captured on ``context.world``
(an FFI ``World``). Component step files import :func:`assert_rejected` /
:func:`assert_accepted` rather than re-deriving the outcome shape.
"""

from __future__ import annotations

from typing import Optional

from behave import then
from google.protobuf import symbol_database as _symbol_database

_SYM = _symbol_database.Default()


def decode_only_emitted(context):
    """Decode the single event the last command emitted, resolving its type from
    the descriptor pool (no per-type registry needed)."""
    fqs = context.world.emitted_fqs()
    assert fqs, "expected one emitted event, got none"
    full_name = fqs[0]
    return context.world.emitted(full_name, _SYM.GetSymbol(full_name)())


@then("the {what} is timestamped")
def _then_timestamped(context, what):
    """Generic across every component event: the emitted event carries a set
    ``*_at`` timestamp. Works for any single-event outcome."""
    ev = decode_only_emitted(context)
    at_fields = [f.name for f in ev.DESCRIPTOR.fields if f.name.endswith("_at")]
    assert any(
        ev.HasField(n) and getattr(ev, n).seconds > 0 for n in at_fields
    ), f"no timestamp set on {ev.DESCRIPTOR.name} (checked {at_fields})"


def assert_accepted(context) -> None:
    """The last command was accepted (no coded rejection)."""
    world = context.world
    assert world.err is None, f"expected acceptance, got rejection {world.err.code}: {world.err.message}"
    assert world.resp is not None, "expected a BusinessResponse"


def assert_rejected(context, code: Optional[str] = None) -> None:
    """The last command was rejected; optionally with a specific coded reason."""
    world = context.world
    assert world.err is not None, "expected a coded rejection, got acceptance"
    if code is not None:
        assert world.err.code == code, f"rejection code = {world.err.code!r}, want {code!r}"
