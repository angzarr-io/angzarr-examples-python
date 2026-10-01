"""Builders for the framework envelopes components emit.

Type URLs always come from the binding's ``pack`` ("/" + full name). Saga and
process-manager commands are deferred: they carry an empty
``angzarr_deferred`` header (the coordinator fills the provenance) and never a
sequence or a correlation id.
"""

from __future__ import annotations

import angzarr_client.router as _az

from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t


def type_name(type_url: str) -> str:
    """The fully-qualified message name a type URL identifies (text after the last "/")."""
    return type_url.rsplit("/", 1)[-1]


def is_type(any_msg, message_class) -> bool:
    return type_name(any_msg.type_url) == message_class.DESCRIPTOR.full_name


def unpack(any_msg, message_class):
    """Decode ``any_msg`` as ``message_class`` (whatever its type-URL prefix)."""
    msg = message_class()
    msg.ParseFromString(any_msg.value)
    return msg


def event_book(*events) -> _t.EventBook:
    """An EventBook of ``events`` in order; the framework stamps sequences."""
    book = _t.EventBook()
    for event in events:
        book.pages.add().event.CopyFrom(_az.pack(event))
    return book


def deferred_command(
    domain: str, root: bytes, command, sync_mode: int | None = None
) -> _t.CommandBook:
    """A saga/PM command to ``(domain, root)``: deferred, no correlation id."""
    book = _t.CommandBook()
    book.cover.domain = domain
    book.cover.root.value = root
    page = book.pages.add()
    page.header.angzarr_deferred.SetInParent()
    if sync_mode is not None:
        page.header.sync_mode = sync_mode
    page.command.CopyFrom(_az.pack(command))
    return book


def fact(
    domain: str, root: bytes, event, external_id: str, description: str
) -> _t.EventBook:
    """A fact for ``(domain, root)``, deduplicated by ``external_id``."""
    book = _t.EventBook()
    book.cover.domain = domain
    book.cover.root.value = root
    page = book.pages.add()
    page.header.external_deferred.external_id = external_id
    page.header.external_deferred.description = description
    page.event.CopyFrom(_az.pack(event))
    return book
