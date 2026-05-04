"""Table-domain command error catalog.

Note: ``SeatPlayer`` denial reasons are *event-payload strings* on
``SeatingRejected`` events — not structured command rejections — so the PM
can compensate by releasing the buy-in reservation. Only *command*
rejection sites are catalogued here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from angzarr_examples.error_shapes import (
    AggregateAlreadyExists,
    AggregateNotFound,
    BoundViolation,
    ContainerFull,
    EntityKeyedConflict,
    EntityNotInContainer,
    FieldRequired,
    IdentityMismatch,
    InsufficientCapacity,
    InvalidOperationInState,
    MustBePositive,
    PreconditionError,
    RelationViolation,
    StateAlreadyEntered,
    StateMismatch,
    ValueOutOfRange,
)


@dataclass
class TableAlreadyExists(AggregateAlreadyExists):
    CODE = "TABLE_ALREADY_EXISTS"
    TEMPLATE = "Table already exists"


@dataclass
class TableNameRequired(FieldRequired):
    CODE = "TABLE_NAME_REQUIRED"
    TEMPLATE = "table_name is required"


@dataclass
class SmallBlindMustBePositive(MustBePositive):
    CODE = "SMALL_BLIND_MUST_BE_POSITIVE"
    TEMPLATE = "small_blind must be positive, got {value}"


@dataclass
class BigBlindMustExceedSmallBlind(RelationViolation):
    CODE = "BIG_BLIND_MUST_EXCEED_SMALL_BLIND"
    TEMPLATE = "big_blind {lhs} must be >= small_blind {rhs}"


@dataclass
class MinBuyInMustBePositive(MustBePositive):
    CODE = "MIN_BUY_IN_MUST_BE_POSITIVE"
    TEMPLATE = "min_buy_in must be positive, got {value}"


@dataclass
class MaxBuyInMustExceedMinBuyIn(RelationViolation):
    CODE = "MAX_BUY_IN_MUST_EXCEED_MIN_BUY_IN"
    TEMPLATE = "max_buy_in {lhs} must be >= min_buy_in {rhs}"


@dataclass
class MaxPlayersOutOfRange(ValueOutOfRange):
    CODE = "MAX_PLAYERS_OUT_OF_RANGE"
    TEMPLATE = "max_players must be 2-10, got {got}"


@dataclass
class TableNotFound(AggregateNotFound):
    CODE = "TABLE_NOT_FOUND"
    TEMPLATE = "Table does not exist"


@dataclass
class PlayerRootRequired(FieldRequired):
    CODE = "PLAYER_ROOT_REQUIRED"
    TEMPLATE = "player_root is required"


@dataclass
class PlayerAlreadySeated(StateAlreadyEntered):
    CODE = "PLAYER_ALREADY_SEATED"
    TEMPLATE = "Player already seated at table"


@dataclass
class TableIsFull(ContainerFull):
    CODE = "TABLE_IS_FULL"
    TEMPLATE = "Table is full"


@dataclass
class BuyInBelowMin(BoundViolation):
    CODE = "BUY_IN_BELOW_MIN"
    TEMPLATE = "Buy-in {got} is below table minimum {bound}"
    KIND: ClassVar[str] = "below_min"


@dataclass
class BuyInAboveMax(BoundViolation):
    CODE = "BUY_IN_ABOVE_MAX"
    TEMPLATE = "Buy-in {got} is above table maximum {bound}"
    KIND: ClassVar[str] = "above_max"


@dataclass
class SeatOccupied(EntityKeyedConflict):
    CODE = "SEAT_OCCUPIED"
    TEMPLATE = "Seat {seat} is occupied"
    seat: int


@dataclass
class PlayerNotSeated(EntityNotInContainer):
    CODE = "PLAYER_NOT_SEATED"
    TEMPLATE = "Player is not seated at table"


@dataclass
class CannotLeaveDuringHand(InvalidOperationInState):
    CODE = "CANNOT_LEAVE_DURING_HAND"
    TEMPLATE = "Cannot leave table during a hand"


@dataclass
class HandAlreadyInProgress(StateAlreadyEntered):
    CODE = "HAND_ALREADY_IN_PROGRESS"
    TEMPLATE = "Hand already in progress"


@dataclass
class NotEnoughPlayersToStartHand(InsufficientCapacity):
    CODE = "NOT_ENOUGH_PLAYERS_TO_START_HAND"
    TEMPLATE = "Not enough players to start hand: requested {requested}, available {available}"


@dataclass
class NoHandInProgress(StateMismatch):
    CODE = "NO_HAND_IN_PROGRESS"
    TEMPLATE = "No hand in progress"


@dataclass
class HandRootMismatch(PreconditionError):
    """One-off: hand_root is bytes, doesn't fit int IdentityMismatch."""

    CODE = "HAND_ROOT_MISMATCH"
    TEMPLATE = "Hand root mismatch"


@dataclass
class AmountMustBePositive(MustBePositive):
    CODE = "AMOUNT_MUST_BE_POSITIVE"
    TEMPLATE = "Amount must be positive, got {value}"


@dataclass
class SeatPositionMismatch(IdentityMismatch):
    CODE = "SEAT_POSITION_MISMATCH"
    TEMPLATE = "Seat position mismatch: expected {expected}, got {got}"


__all__ = [
    "TableAlreadyExists",
    "TableNameRequired",
    "SmallBlindMustBePositive",
    "BigBlindMustExceedSmallBlind",
    "MinBuyInMustBePositive",
    "MaxBuyInMustExceedMinBuyIn",
    "MaxPlayersOutOfRange",
    "TableNotFound",
    "PlayerRootRequired",
    "PlayerAlreadySeated",
    "TableIsFull",
    "BuyInBelowMin",
    "BuyInAboveMax",
    "SeatOccupied",
    "PlayerNotSeated",
    "CannotLeaveDuringHand",
    "HandAlreadyInProgress",
    "NotEnoughPlayersToStartHand",
    "NoHandInProgress",
    "HandRootMismatch",
    "AmountMustBePositive",
    "SeatPositionMismatch",
]
