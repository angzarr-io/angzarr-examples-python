"""Builders and readers for the framework envelopes components emit.

Type URLs always come from the binding's ``pack`` ("/" + full name).
"""

from __future__ import annotations

import angzarr_client.router as _az

from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t


def type_name(type_url: str) -> str:
    """The fully-qualified message name a type URL identifies (text after the last "/")."""
    return type_url.rpartition("/")[2]


def unpack(any_msg, message_class):
    """Decode ``any_msg`` as ``message_class`` (whatever its type-URL prefix)."""
    msg = message_class()
    msg.ParseFromString(any_msg.value)
    return msg


def event_book(*events) -> _t.EventBook:
    """An EventBook of ``events`` in order; the framework stamps sequences."""
    book = _t.EventBook()
    for event in events:
        book.pages.add().payload.CopyFrom(_az.pack(event))
    return book
