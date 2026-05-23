"""Tournament-domain command error catalog.

Note: enrollment- and rebuy-denial reasons are event-payload strings on
``TournamentEnrollmentRejected`` / ``RebuyDenied``, not structured command
rejections — they reach the saga as event-shape, not as gRPC errors. Only
*command* rejection sites are catalogued here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from poker.error_shapes import (
    AggregateAlreadyExists,
    AggregateNotFound,
    BoundViolation,
    EntityNotInContainer,
    Exhausted,
    FieldRequired,
    InsufficientCapacity,
    InvalidOperationInState,
    MustBePositive,
    RelationViolation,
    StateAlreadyEntered,
    StateMismatch,
    ValueOutOfRange,
)


@dataclass
class TournamentAlreadyExists(AggregateAlreadyExists):
    CODE = "TOURNAMENT_ALREADY_EXISTS"
    TEMPLATE = "Tournament already exists"


@dataclass
class NameRequired(FieldRequired):
    CODE = "NAME_REQUIRED"
    TEMPLATE = "name is required"


@dataclass
class BuyInMustBePositive(MustBePositive):
    CODE = "BUY_IN_MUST_BE_POSITIVE"
    TEMPLATE = "buy_in must be positive, got {value}"


@dataclass
class StartingStackMustBePositive(MustBePositive):
    CODE = "STARTING_STACK_MUST_BE_POSITIVE"
    TEMPLATE = "starting_stack must be positive, got {value}"


@dataclass
class MaxPlayersTooFew(ValueOutOfRange):
    CODE = "MAX_PLAYERS_TOO_FEW"
    TEMPLATE = "max_players must be at least 2, got {got}"


@dataclass
class MinPlayersTooFew(ValueOutOfRange):
    CODE = "MIN_PLAYERS_TOO_FEW"
    TEMPLATE = "min_players must be at least 2, got {got}"


@dataclass
class MinPlayersExceedsMax(RelationViolation):
    CODE = "MIN_PLAYERS_EXCEEDS_MAX"
    TEMPLATE = "min_players ({lhs}) cannot exceed max_players ({rhs})"


@dataclass
class TournamentNotFound(AggregateNotFound):
    CODE = "TOURNAMENT_NOT_FOUND"
    TEMPLATE = "Tournament does not exist"


@dataclass
class CannotOpenRegistrationRunning(InvalidOperationInState):
    CODE = "CANNOT_OPEN_REGISTRATION_RUNNING"
    TEMPLATE = "Cannot open registration on a running tournament"


@dataclass
class RegistrationAlreadyOpen(StateAlreadyEntered):
    CODE = "REGISTRATION_ALREADY_OPEN"
    TEMPLATE = "Registration is already open"


@dataclass
class RegistrationNotOpen(StateMismatch):
    CODE = "REGISTRATION_NOT_OPEN"
    TEMPLATE = "Registration is not open"


@dataclass
class TournamentNotRunning(StateMismatch):
    CODE = "TOURNAMENT_NOT_RUNNING"
    TEMPLATE = "Tournament is not running"


@dataclass
class PlayerRootRequired(FieldRequired):
    CODE = "PLAYER_ROOT_REQUIRED"
    TEMPLATE = "player_root is required"


@dataclass
class PlayerNotRegistered(EntityNotInContainer):
    CODE = "PLAYER_NOT_REGISTERED"
    TEMPLATE = "Player {player_root_hex} is not registered in this tournament"
    player_root_hex: str


@dataclass
class TournamentAlreadyPaused(StateAlreadyEntered):
    CODE = "TOURNAMENT_ALREADY_PAUSED"
    TEMPLATE = "Tournament is already paused"


@dataclass
class TournamentNotPaused(StateMismatch):
    CODE = "TOURNAMENT_NOT_PAUSED"
    TEMPLATE = "Tournament is not paused"


@dataclass
class NotEnoughPlayersToStart(InsufficientCapacity):
    CODE = "NOT_ENOUGH_PLAYERS_TO_START"
    TEMPLATE = (
        "Not enough players to start: requested {requested}, available {available}"
    )


@dataclass
class TournamentAlreadyCompleted(StateAlreadyEntered):
    CODE = "TOURNAMENT_ALREADY_COMPLETED"
    TEMPLATE = "Tournament is already completed"


@dataclass
class TournamentNotRunningOrPaused(StateMismatch):
    CODE = "TOURNAMENT_NOT_RUNNING_OR_PAUSED"
    TEMPLATE = "Tournament must be running or paused to complete"


@dataclass
class BlindStructureExhausted(Exhausted):
    CODE = "BLIND_STRUCTURE_EXHAUSTED"
    TEMPLATE = (
        "Blind structure exhausted at level {current}; max defined level is {max_value}"
    )


@dataclass
class FinishingOrderShorterThanPayoutPositions(BoundViolation):
    """CompleteTournament: finishing_order has fewer entries than the
    configured payout_structure requires."""

    CODE = "FINISHING_ORDER_SHORTER_THAN_PAYOUT_POSITIONS"
    TEMPLATE = "finishing_order length {got} is less than payout positions {bound}"
    KIND: ClassVar[str] = "below_min"


@dataclass
class PayoutsDoNotSumToPool(BoundViolation):
    """The configured percentages don't yield a whole-chip distribution
    that sums exactly to total_prize_pool."""

    CODE = "PAYOUTS_DO_NOT_SUM_TO_POOL"
    TEMPLATE = "payouts sum to {got} but prize pool is {bound}"
    KIND: ClassVar[str] = "mismatch"


__all__ = [
    "TournamentAlreadyExists",
    "NameRequired",
    "BuyInMustBePositive",
    "StartingStackMustBePositive",
    "MaxPlayersTooFew",
    "MinPlayersTooFew",
    "MinPlayersExceedsMax",
    "TournamentNotFound",
    "CannotOpenRegistrationRunning",
    "RegistrationAlreadyOpen",
    "RegistrationNotOpen",
    "TournamentNotRunning",
    "PlayerRootRequired",
    "PlayerNotRegistered",
    "TournamentAlreadyPaused",
    "TournamentNotPaused",
    "NotEnoughPlayersToStart",
    "TournamentAlreadyCompleted",
    "TournamentNotRunningOrPaused",
    "BlindStructureExhausted",
]
