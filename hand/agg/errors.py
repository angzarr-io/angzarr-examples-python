"""Hand-domain command error catalog.

One leaf per distinct rejection. Leaves now inherit from a shape parent
(see ``angzarr_examples.error_shapes``) for cross-cutting classification;
the shape parent supplies the canonical field schema (``got``/``bound``,
``requested``/``available``, etc.) and the right ``STATUS`` default.

Cucumber asserts on ``code`` and individual ``details`` fields; rendered
text is for human display only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from angzarr_examples.error_shapes import (
    BoundViolation,
    ContainerFull,
    EntityNotInContainer,
    FieldRequired,
    IdentityMismatch,
    InsufficientCapacity,
    InvalidOperationInState,
    MustBePositive,
    PreconditionError,
    StateAlreadyEntered,
    StateMismatch,
    ValueOutOfRange,
    VariantMismatch,
)


# --- DealCards ---


@dataclass
class HandAlreadyDealt(StateAlreadyEntered):
    CODE = "HAND_ALREADY_DEALT"
    TEMPLATE = "Hand already dealt"


@dataclass
class NoPlayersInHand(PreconditionError):
    """One-off: state-precondition with no shape-fitting structure."""

    CODE = "NO_PLAYERS_IN_HAND"
    TEMPLATE = "No players in hand"


@dataclass
class NeedAtLeast2Players(ValueOutOfRange):
    CODE = "NEED_AT_LEAST_2_PLAYERS"
    TEMPLATE = "Need at least 2 players, got {got}"


# --- Shared lifecycle / player gates ---


@dataclass
class HandNotDealt(StateMismatch):
    CODE = "HAND_NOT_DEALT"
    TEMPLATE = "Hand not dealt"


@dataclass
class HandAlreadyComplete(StateAlreadyEntered):
    CODE = "HAND_ALREADY_COMPLETE"
    TEMPLATE = "Hand already complete"


@dataclass
class PlayerRootRequired(FieldRequired):
    CODE = "PLAYER_ROOT_REQUIRED"
    TEMPLATE = "player_root is required"


@dataclass
class PlayerNotInHand(EntityNotInContainer):
    CODE = "PLAYER_NOT_IN_HAND"
    TEMPLATE = "Player not in hand"


@dataclass
class PlayerHasFolded(StateAlreadyEntered):
    CODE = "PLAYER_HAS_FOLDED"
    TEMPLATE = "Player has folded"


@dataclass
class PlayerIsAllIn(StateAlreadyEntered):
    CODE = "PLAYER_IS_ALL_IN"
    TEMPLATE = "Player is all-in"


# --- PostBlind ---


@dataclass
class BlindAmountMustBePositive(MustBePositive):
    CODE = "BLIND_AMOUNT_MUST_BE_POSITIVE"
    TEMPLATE = "Blind amount must be positive, got {value}"


# --- PlayerAction ---


@dataclass
class NotInBettingPhase(StateMismatch):
    CODE = "NOT_IN_BETTING_PHASE"
    TEMPLATE = "Not in betting phase"


@dataclass
class CannotCheckWithBet(InvalidOperationInState):
    CODE = "CANNOT_CHECK_WITH_BET"
    TEMPLATE = "Cannot check, there is a bet to call"


@dataclass
class NothingToCall(InvalidOperationInState):
    CODE = "NOTHING_TO_CALL"
    TEMPLATE = "Nothing to call"


@dataclass
class CannotBetOverExistingBet(InvalidOperationInState):
    CODE = "CANNOT_BET_OVER_EXISTING_BET"
    TEMPLATE = "Cannot bet, there is already a bet"


@dataclass
class BetBelowMinRaise(BoundViolation):
    CODE = "BET_BELOW_MIN_RAISE"
    TEMPLATE = "Bet must be at least {bound}, got {got}"
    KIND: ClassVar[str] = "below_min"


@dataclass
class BetExceedsStack(BoundViolation):
    CODE = "BET_EXCEEDS_STACK"
    TEMPLATE = "Bet {got} exceeds stack {bound}"
    KIND: ClassVar[str] = "above_max"


@dataclass
class CannotRaiseWithoutBet(InvalidOperationInState):
    CODE = "CANNOT_RAISE_WITHOUT_BET"
    TEMPLATE = "Cannot raise, there is no bet"


@dataclass
class RaiseBelowMin(BoundViolation):
    CODE = "RAISE_BELOW_MIN"
    TEMPLATE = "Raise must be at least {bound}, got {got}"
    KIND: ClassVar[str] = "below_min"


@dataclass
class RaiseExceedsStack(BoundViolation):
    CODE = "RAISE_EXCEEDS_STACK"
    TEMPLATE = "Raise {got} exceeds stack {bound}"
    KIND: ClassVar[str] = "above_max"


@dataclass
class InvalidAction(ValueOutOfRange):
    CODE = "INVALID_ACTION"
    TEMPLATE = "Invalid action: {got}"


# --- DealCommunityCards ---


@dataclass
class MustDealAtLeast1Card(BoundViolation):
    CODE = "MUST_DEAL_AT_LEAST_1_CARD"
    TEMPLATE = "Must deal at least {bound} card, got {got}"
    KIND: ClassVar[str] = "below_min"


@dataclass
class CommunityCardsNotUsedInVariant(VariantMismatch):
    CODE = "COMMUNITY_CARDS_NOT_USED_IN_VARIANT"
    TEMPLATE = "Community cards not used in this variant"


@dataclass
class NoMorePhases(ContainerFull):
    CODE = "NO_MORE_PHASES"
    TEMPLATE = "No more phases"


@dataclass
class CannotDealMoreCommunityCards(InvalidOperationInState):
    CODE = "CANNOT_DEAL_MORE_COMMUNITY_CARDS"
    TEMPLATE = "Cannot deal more community cards"


@dataclass
class WrongCardCountForPhase(IdentityMismatch):
    CODE = "WRONG_CARD_COUNT_FOR_PHASE"
    TEMPLATE = "Expected {expected} cards for phase {phase}, got {got}"
    phase: str = ""


@dataclass
class NotEnoughCardsInDeck(InsufficientCapacity):
    CODE = "NOT_ENOUGH_CARDS_IN_DECK"
    TEMPLATE = (
        "Not enough cards in deck: requested {requested}, available {available}"
    )


# --- RequestDraw ---


@dataclass
class DrawNotSupportedInVariant(VariantMismatch):
    CODE = "DRAW_NOT_SUPPORTED_IN_VARIANT"
    TEMPLATE = "Draw not supported in this game variant"


@dataclass
class NotInDrawPhase(StateMismatch):
    CODE = "NOT_IN_DRAW_PHASE"
    TEMPLATE = "Not in draw phase"


@dataclass
class TooManyDiscards(BoundViolation):
    CODE = "TOO_MANY_DISCARDS"
    TEMPLATE = "Cannot discard more than {bound} cards, got {got}"
    KIND: ClassVar[str] = "above_max"


@dataclass
class DuplicateCardIndices(PreconditionError):
    """One-off: list-content uniqueness violation, no scalar fits a shape."""

    CODE = "DUPLICATE_CARD_INDICES"
    TEMPLATE = "Duplicate card indices"


@dataclass
class InvalidCardIndex(ValueOutOfRange):
    CODE = "INVALID_CARD_INDEX"
    TEMPLATE = "Invalid card index {got}, must be 0-4"


# --- RevealCards ---


@dataclass
class NotInShowdownPhase(StateMismatch):
    CODE = "NOT_IN_SHOWDOWN_PHASE"
    TEMPLATE = "Not in showdown phase"


# --- AwardPot ---


@dataclass
class NoAwardsSpecified(PreconditionError):
    """One-off: missing-content precondition with no scalar fitting a shape."""

    CODE = "NO_AWARDS_SPECIFIED"
    TEMPLATE = "No awards specified"


@dataclass
class AwardPlayerNotInHand(EntityNotInContainer):
    CODE = "AWARD_PLAYER_NOT_IN_HAND"
    TEMPLATE = "Award to player not in hand"


@dataclass
class FoldedPlayerCannotWin(InvalidOperationInState):
    CODE = "FOLDED_PLAYER_CANNOT_WIN"
    TEMPLATE = "Folded player cannot win"


@dataclass
class AwardsExceedPot(BoundViolation):
    CODE = "AWARDS_EXCEED_POT"
    TEMPLATE = "Awards {got} exceed pot total {bound}"
    KIND: ClassVar[str] = "above_max"


@dataclass
class WinnerNotEligibleForPot(InvalidOperationInState):
    """Award assigns chips from a pot the player cannot legally win.

    Side pots (TDA Rule 42) are eligible only to players whose total
    investment reached that layer's level. A player who was all-in for
    less than a side pot's level cannot be awarded any of that side pot.
    """

    CODE = "WINNER_NOT_ELIGIBLE_FOR_POT"
    TEMPLATE = "Player {player_root} not eligible for pot {pot_type}"
    pot_type: str = ""
    player_root: str = ""


@dataclass
class BetBelowBigBlind(BoundViolation):
    """Reserved alias surface for clarity; behaviourally folded into
    BetBelowMinRaise once min_raise resets to BB on each new street.
    Kept here for cross-language naming parity if a port chooses to
    distinguish "min bet" from "min raise" externally.
    """

    CODE = "BET_BELOW_BIG_BLIND"
    TEMPLATE = "Bet {got} below big blind {bound}"
    KIND: ClassVar[str] = "below_min"


__all__ = [
    "HandAlreadyDealt",
    "NoPlayersInHand",
    "NeedAtLeast2Players",
    "HandNotDealt",
    "HandAlreadyComplete",
    "PlayerRootRequired",
    "PlayerNotInHand",
    "PlayerHasFolded",
    "PlayerIsAllIn",
    "BlindAmountMustBePositive",
    "NotInBettingPhase",
    "CannotCheckWithBet",
    "NothingToCall",
    "CannotBetOverExistingBet",
    "BetBelowMinRaise",
    "BetExceedsStack",
    "CannotRaiseWithoutBet",
    "RaiseBelowMin",
    "RaiseExceedsStack",
    "InvalidAction",
    "MustDealAtLeast1Card",
    "CommunityCardsNotUsedInVariant",
    "NoMorePhases",
    "CannotDealMoreCommunityCards",
    "WrongCardCountForPhase",
    "NotEnoughCardsInDeck",
    "DrawNotSupportedInVariant",
    "NotInDrawPhase",
    "TooManyDiscards",
    "DuplicateCardIndices",
    "InvalidCardIndex",
    "NotInShowdownPhase",
    "NoAwardsSpecified",
    "AwardPlayerNotInHand",
    "FoldedPlayerCannotWin",
    "AwardsExceedPot",
    "WinnerNotEligibleForPot",
    "BetBelowBigBlind",
]
