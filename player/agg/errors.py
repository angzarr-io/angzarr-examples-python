"""Player-domain command error catalog.

One leaf per distinct rejection. Leaves now inherit from a shape parent
(see ``angzarr_examples.error_shapes``) for cross-cutting classification;
the shape parent supplies the canonical field schema (``got``/``bound``,
``requested``/``available``, etc.) and the right ``STATUS`` default.

Cucumber asserts on ``code`` and individual ``details`` fields; rendered
text is for human display only.
"""

from __future__ import annotations

from dataclasses import dataclass

from angzarr_examples.error_shapes import (
    AggregateAlreadyExists,
    AggregateNotFound,
    EntityKeyedConflict,
    FieldRequired,
    InsufficientCapacity,
    MustBeNonZero,
    MustBePositive,
)


@dataclass
class PlayerAlreadyExists(AggregateAlreadyExists):
    CODE = "PLAYER_ALREADY_EXISTS"
    TEMPLATE = "Player already exists"


@dataclass
class DisplayNameRequired(FieldRequired):
    CODE = "DISPLAY_NAME_REQUIRED"
    TEMPLATE = "display_name is required"


@dataclass
class EmailRequired(FieldRequired):
    CODE = "EMAIL_REQUIRED"
    TEMPLATE = "email is required"


@dataclass
class PlayerNotFound(AggregateNotFound):
    CODE = "PLAYER_NOT_FOUND"
    TEMPLATE = "Player does not exist"


@dataclass
class AmountMustBePositive(MustBePositive):
    CODE = "AMOUNT_MUST_BE_POSITIVE"
    TEMPLATE = "Amount must be positive, got {value}"


@dataclass
class AmountMustBeNonZero(MustBeNonZero):
    CODE = "AMOUNT_MUST_BE_NON_ZERO"
    TEMPLATE = "Amount must be non-zero"


@dataclass
class InsufficientAvailableBalance(InsufficientCapacity):
    CODE = "INSUFFICIENT_AVAILABLE_BALANCE"
    TEMPLATE = "Insufficient available balance: requested {requested}, available {available}"


@dataclass
class InsufficientFunds(InsufficientCapacity):
    CODE = "INSUFFICIENT_FUNDS"
    TEMPLATE = "Insufficient funds: requested {requested}, available {available}"


@dataclass
class FundsAlreadyReservedForTable(EntityKeyedConflict):
    CODE = "FUNDS_ALREADY_RESERVED_FOR_TABLE"
    TEMPLATE = "Funds already reserved for table {table_root_hex}"
    table_root_hex: str


@dataclass
class TableRootRequired(FieldRequired):
    CODE = "TABLE_ROOT_REQUIRED"
    TEMPLATE = "table_root is required"


@dataclass
class NoFundsReservedForTable(EntityKeyedConflict):
    CODE = "NO_FUNDS_RESERVED_FOR_TABLE"
    TEMPLATE = "No funds reserved for table {table_root_hex}"
    table_root_hex: str


@dataclass
class KeyRequired(FieldRequired):
    CODE = "KEY_REQUIRED"
    TEMPLATE = "key is required"


@dataclass
class AmountExceedsReservedFunds(InsufficientCapacity):
    CODE = "AMOUNT_EXCEEDS_RESERVED_FUNDS"
    TEMPLATE = "Amount exceeds reserved funds: requested {requested}, available {available}"


__all__ = [
    "PlayerAlreadyExists",
    "DisplayNameRequired",
    "EmailRequired",
    "PlayerNotFound",
    "AmountMustBePositive",
    "AmountMustBeNonZero",
    "InsufficientAvailableBalance",
    "InsufficientFunds",
    "FundsAlreadyReservedForTable",
    "TableRootRequired",
    "NoFundsReservedForTable",
    "KeyRequired",
    "AmountExceedsReservedFunds",
]
