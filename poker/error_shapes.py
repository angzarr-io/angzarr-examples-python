"""Shape hierarchy for ``StructuredCommandError`` leaves.

Every leaf in the per-domain catalogs (``player/agg/errors.py``,
``table/agg/errors.py``, ``tournament/agg/errors.py``, ``hand/agg/errors.py``)
inherits from one of these shape classes. Shapes give cross-cutting code a
way to classify rejections without enumerating leaf codes:

    if isinstance(err, AggregateNotFound):
        metrics.aggregate_not_found.inc(domain=err.cover.domain)

    if isinstance(err, BoundViolation):
        log.warning("bound exceeded", got=err.got, bound=err.bound, kind=err.KIND)

The tree:

    StructuredCommandError
      ├── PreconditionError                  (FAILED_PRECONDITION default)
      │     ├── AggregateLifecycle
      │     │     ├── AggregateNotFound
      │     │     └── AggregateAlreadyExists
      │     ├── State
      │     │     ├── StateMismatch
      │     │     ├── StateAlreadyEntered
      │     │     └── InvalidOperationInState
      │     ├── EntityRole
      │     │     ├── EntityNotInContainer
      │     │     └── EntityKeyedConflict
      │     ├── Capacity
      │     │     ├── InsufficientCapacity   {requested, available}
      │     │     ├── Exhausted              {current, max_value}
      │     │     └── ContainerFull
      │     ├── BoundViolation               {got, bound}        + KIND="min"|"max"
      │     ├── RelationViolation            {lhs, rhs}
      │     ├── IdentityMismatch             {expected, got}
      │     └── VariantMismatch
      └── ValidationError                    (INVALID_ARGUMENT default)
            ├── FieldRequired
            ├── MustBePositive               {value}
            ├── MustBeNonZero                {value}
            └── ValueOutOfRange              {got}

Field-bearing shapes provide DRY: their leaves don't redeclare
``got``/``bound``/``value``/etc. — they inherit. Marker shapes (no fields)
exist for ``isinstance``-based classification only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from poker.errors import StructuredCommandError

# =============================================================================
# Tier 2 — status defaults
# =============================================================================


@dataclass
class PreconditionError(StructuredCommandError):
    """All FAILED_PRECONDITION rejections inherit from this (directly or via
    a shape mid-level). Domain leaves rarely subclass this directly — pick
    the shape that fits."""

    STATUS: ClassVar[str] = "FAILED_PRECONDITION"


@dataclass
class ValidationError(StructuredCommandError):
    """All INVALID_ARGUMENT rejections inherit from this (directly or via
    a shape mid-level)."""

    STATUS: ClassVar[str] = "INVALID_ARGUMENT"


# =============================================================================
# Tier 3 — Aggregate lifecycle
# =============================================================================


@dataclass
class AggregateNotFound(PreconditionError):
    """The targeted aggregate does not exist (root never created)."""


@dataclass
class AggregateAlreadyExists(PreconditionError):
    """The targeted aggregate already exists; create-twice rejected."""


# =============================================================================
# Tier 3 — State / status gates
# =============================================================================


@dataclass
class StateMismatch(PreconditionError):
    """Aggregate is in a state that doesn't permit this command."""


@dataclass
class StateAlreadyEntered(PreconditionError):
    """Aggregate is already in the state the command was trying to enter."""


@dataclass
class InvalidOperationInState(PreconditionError):
    """The command itself is structurally invalid for the current state
    (e.g. ``Cannot check, there is a bet to call``)."""


# =============================================================================
# Tier 3 — Entity-in-container gates
# =============================================================================


@dataclass
class EntityNotInContainer(PreconditionError):
    """Inner entity (player, hand, etc.) is not present in the aggregate."""


@dataclass
class EntityKeyedConflict(PreconditionError):
    """Operation keyed on an inner identifier (seat, table_root, etc.)
    fails because that key is occupied or absent unexpectedly."""


# =============================================================================
# Tier 3 — Capacity
# =============================================================================


@dataclass
class InsufficientCapacity(PreconditionError):
    """Operation requested more than the aggregate can provide.

    ``available`` carries the upper limit relevant for the operation —
    available balance, remaining cards, players short of minimum, etc.
    Leaves keep diagnostic precision in their TEMPLATE wording.
    """

    requested: int
    available: int


@dataclass
class Exhausted(PreconditionError):
    """A bounded resource has been fully consumed.

    ``max_value`` (not ``max`` to avoid the Python builtin shadowing)
    is the declared upper limit; ``current`` is the current depleted
    state. e.g. ``BlindStructureExhausted(current=N, max_value=N)``.
    """

    current: int
    max_value: int


@dataclass
class ContainerFull(PreconditionError):
    """A capped container has reached capacity (no scalar payload)."""


# =============================================================================
# Tier 3 — Comparison violations
# =============================================================================


@dataclass
class BoundViolation(PreconditionError):
    """A scalar input violates a min/max bound. ``KIND`` distinguishes
    ``below_min`` (``got < bound``) from ``above_max`` (``got > bound``)."""

    got: int
    bound: int
    KIND: ClassVar[str] = ""  # "below_min" | "above_max"


@dataclass
class RelationViolation(PreconditionError):
    """Two related scalars violate the required relation between them.

    ``lhs`` and ``rhs`` are intentionally generic — leaves give them
    semantic names via the rendered TEMPLATE
    (e.g. ``"min_players ({lhs}) cannot exceed max_players ({rhs})"``).
    """

    lhs: int
    rhs: int


@dataclass
class IdentityMismatch(PreconditionError):
    """A submitted identifier or count does not match the expected one
    (e.g. ``Hand root mismatch``, ``Wrong card count for phase``)."""

    expected: int
    got: int


# =============================================================================
# Tier 3 — Variant
# =============================================================================


@dataclass
class VariantMismatch(PreconditionError):
    """Operation is not supported for the aggregate's game variant."""


# =============================================================================
# Tier 3 — Validation (input shape)
# =============================================================================


@dataclass
class FieldRequired(ValidationError):
    """A required input field was missing or empty. The field name is
    encoded in the leaf's CODE (``DISPLAY_NAME_REQUIRED``,
    ``EMAIL_REQUIRED``, etc.); no runtime data needed."""


@dataclass
class MustBePositive(ValidationError):
    """A scalar input must be > 0; ``value`` carries what was supplied."""

    value: int


@dataclass
class MustBeNonZero(ValidationError):
    """A scalar input must be != 0; ``value`` carries what was supplied
    (typically 0 — but kept for symmetry with ``MustBePositive``)."""

    value: int


@dataclass
class ValueOutOfRange(ValidationError):
    """A scalar input is outside an allowed range. Leaves describe the
    bounds in their TEMPLATE; ``got`` carries what was supplied."""

    got: int


__all__ = [
    "PreconditionError",
    "ValidationError",
    "AggregateNotFound",
    "AggregateAlreadyExists",
    "StateMismatch",
    "StateAlreadyEntered",
    "InvalidOperationInState",
    "EntityNotInContainer",
    "EntityKeyedConflict",
    "InsufficientCapacity",
    "Exhausted",
    "ContainerFull",
    "BoundViolation",
    "RelationViolation",
    "IdentityMismatch",
    "VariantMismatch",
    "FieldRequired",
    "MustBePositive",
    "MustBeNonZero",
    "ValueOutOfRange",
]
