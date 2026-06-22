"""Shared step helpers for the poker unit stage.

Generic assertions over the last dispatch outcome captured on ``context.world``
(an FFI ``World``). Component step files import :func:`assert_rejected` /
:func:`assert_accepted` rather than re-deriving the outcome shape.
"""

from __future__ import annotations

from typing import Optional


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
