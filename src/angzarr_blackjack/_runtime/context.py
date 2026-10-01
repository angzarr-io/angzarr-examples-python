"""The cover of the book a component is currently handling.

Handlers on the generated seam see only the typed message, their state and a
CommandContext; none of those carries the aggregate's own cover (the table
derives a cash-out id from its root) or the process manager's trigger cover
(the buy-in takes its table root from it). The host that dispatches a book sets
it here for the duration of that synchronous dispatch; the router calls the
handlers back on the same thread, so they read it with ``current_root()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t

_COVER: ContextVar[_t.Cover | None] = ContextVar(
    "angzarr_blackjack_cover", default=None
)


@contextmanager
def handling(cover: _t.Cover) -> Iterator[None]:
    """Make ``cover`` the current cover while the block runs."""
    token = _COVER.set(cover)
    try:
        yield
    finally:
        _COVER.reset(token)


def current_cover() -> _t.Cover:
    cover = _COVER.get()
    if cover is None:
        raise RuntimeError("no cover is being handled")
    return cover


def current_root() -> bytes:
    return current_cover().root.value
