"""Structured command-error base class for examples.

Subclasses are dataclasses that declare a stable ``CODE`` (SCREAMING_SNAKE),
a ``TEMPLATE`` containing ``{field}`` placeholders, a ``STATUS``
(``FAILED_PRECONDITION`` / ``INVALID_ARGUMENT`` / ``NOT_FOUND``), and the
runtime fields the template references.

Wire shape:
  - ``code``    = ``CODE`` — testable identifier, language-portable.
  - ``message`` = ``TEMPLATE`` (placeholders intact) — same exact string
    for every instance of the same predicate failure, suitable for log
    greppability and cross-language equality.
  - ``details`` = the dataclass field map — runtime context, structured.

``render()`` substitutes the field map into the template and returns a
human-readable string suitable for display or logging. Cucumber scenarios
assert on ``code`` and individual ``details`` fields — never on rendered
text — so wording changes don't break the spec.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar

from angzarr_client.errors import CommandRejectedError


class StructuredCommandError(CommandRejectedError):
    CODE: ClassVar[str] = ""
    TEMPLATE: ClassVar[str] = ""
    STATUS: ClassVar[str] = "FAILED_PRECONDITION"

    def __post_init__(self) -> None:
        CommandRejectedError.__init__(
            self,
            message=self.TEMPLATE,
            status_code=self.STATUS,
            code=self.CODE,
            details=self.fields_dict(),
        )

    def fields_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    def render(self) -> str:
        return self.TEMPLATE.format(**self.fields_dict())

    def shape_name(self) -> str:
        """Return the closest shape class in the MRO above this leaf.

        Used by cross-cutting observability (metrics dimensions, log
        tags, cucumber assertions) to dispatch on the structural shape
        of a rejection rather than its specific CODE — so e.g. all
        BoundViolation leaves report under one metric without enumerating
        every CODE that could fire.

        Returns the empty string for one-off leaves that inherit
        ``PreconditionError`` or ``ValidationError`` directly without a
        concrete shape (HandRootMismatch, NoPlayersInHand, etc.).
        """
        # Lazy import: ``error_shapes`` imports ``errors`` itself, so the
        # module is only available after both have finished loading. The
        # first call materialises the lookup; subsequent calls hit the
        # ClassVar set on the leaf's MRO.
        cached = getattr(type(self), "_SHAPE_NAME_CACHE", None)
        if cached is not None:
            return cached
        from poker import error_shapes as _shapes

        # The two tier-2 abstracts are NOT shapes — they're status defaults.
        # Any concrete shape is a strict subclass of one of these.
        skip = {
            _shapes.PreconditionError,
            _shapes.ValidationError,
            StructuredCommandError,
        }
        shape_classes = {
            cls
            for name in _shapes.__all__
            for cls in [getattr(_shapes, name)]
            if isinstance(cls, type) and cls not in skip
        }
        for cls in type(self).__mro__:
            if cls in shape_classes:
                type(self)._SHAPE_NAME_CACHE = cls.__name__
                return cls.__name__
        type(self)._SHAPE_NAME_CACHE = ""
        return ""


__all__ = ["StructuredCommandError"]
