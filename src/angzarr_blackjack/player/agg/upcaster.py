"""PlayerUpcaster: rewrites stored legacy player events into today's shapes.

``FundsDepositedV1{amount_chips}`` becomes ``FundsDeposited{amount}``. Every
other event passes through untouched. Served by the agg-player process through
``UpcasterService`` on the same address as the aggregate.
"""

from __future__ import annotations

import angzarr_client.router as _az

from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2 as _up
from angzarr_blackjack._runtime.books import is_type, unpack


def upcast_page(page: _t.EventPage) -> _t.EventPage:
    """The page in today's shape (a copy; the input is not modified)."""
    out = _t.EventPage()
    out.CopyFrom(page)
    if page.HasField("event") and is_type(page.event, _p.FundsDepositedV1):
        legacy = unpack(page.event, _p.FundsDepositedV1)
        out.event.CopyFrom(_az.pack(_p.FundsDeposited(amount=legacy.amount_chips)))
    return out


def upcast_book(book: _t.EventBook) -> _t.EventBook:
    out = _t.EventBook()
    out.CopyFrom(book)
    del out.pages[:]
    out.pages.extend(upcast_page(page) for page in book.pages)
    return out


class PlayerUpcaster:
    """``UpcasterService.Upcast`` for the player domain."""

    def upcast(self, request: _up.UpcastRequest) -> _up.UpcastResponse:
        return _up.UpcastResponse(events=[upcast_page(page) for page in request.events])
