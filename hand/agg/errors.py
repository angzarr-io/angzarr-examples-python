"""Hand-domain command error catalog.

One leaf per distinct rejection. Leaves now inherit from a shape parent
(see ``poker.error_shapes``) for cross-cutting classification;
the shape parent supplies the canonical field schema (``got``/``bound``,
``requested``/``available``, etc.) and the right ``STATUS`` default.

Cucumber asserts on ``code`` and individual ``details`` fields; rendered
text is for human display only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from poker.error_shapes import (
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
    TEMPLATE = "Not enough cards in deck: requested {requested}, available {available}"


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
class CannotPostAnteAfterBlinds(InvalidOperationInState):
    """Antes must be collected before SB/BB are posted (TDA Rule 7)."""

    CODE = "CANNOT_POST_ANTE_AFTER_BLINDS"
    TEMPLATE = "Cannot post ante after blinds are already posted"


@dataclass
class ActionClockNotOnThisPlayer(InvalidOperationInState):
    """TDA Rule 29: action clock can only run on the seat currently to act."""

    CODE = "ACTION_CLOCK_NOT_ON_THIS_PLAYER"
    TEMPLATE = "Action clock not on this player"


@dataclass
class RevealOutOfOrder(InvalidOperationInState):
    """Showdown reveal attempted out of order (TDA Rule 36).

    The last aggressive bettor on the river shows first; absent any
    river action, the first un-folded seat clockwise of the dealer
    shows first; remaining players follow clockwise.
    """

    CODE = "REVEAL_OUT_OF_ORDER"
    TEMPLATE = "Reveal out of order"


@dataclass
class IncompleteReveal(InvalidOperationInState):
    """TDA Rule 13A / Rule 19 — proper tabling shows ALL hole cards. A
    partial muck forfeits any claim to the pot (including playing the
    board); the player must table all hole cards or forfeit. The
    template explicitly mentions "play the board" so floor logs reflect
    the rule citation."""

    CODE = "INCOMPLETE_REVEAL"
    TEMPLATE = (
        "Incomplete reveal: {got} of {bound} hole cards tabled — "
        "must table all to play the board (Rule 19)"
    )
    got: int = 0
    bound: int = 0


@dataclass
class FaceUpRequired(InvalidOperationInState):
    """TDA Rule 16 — once a player is all-in and betting action is
    complete, every remaining hand must be tabled. Mucking is no longer
    permitted; pots in the main and side(s) are evaluated against live,
    visible hands."""

    CODE = "FACE_UP_REQUIRED"
    TEMPLATE = "All hands must be tabled face-up; mucking not permitted"


@dataclass
class PlayerAbsentAtDeal(InvalidOperationInState):
    """TDA Rule 30 — a player not at their seat when cards are dealt
    has their hand killed immediately. Returning later does not
    resurrect the hand; any action attempt is rejected."""

    CODE = "PLAYER_ABSENT_AT_DEAL"
    TEMPLATE = "Player was absent at deal; hand is dead"


@dataclass
class TabledWinnerCannotBeKilled(InvalidOperationInState):
    """TDA Rule 13C — a properly tabled winning hand cannot be killed
    by an erroneous award. The award winner must be the strongest tabled
    hand (or share a tie). ``tabled_winner`` carries the hex of the
    rightful winner's player_root for cross-language parity."""

    CODE = "TABLED_WINNER_CANNOT_BE_KILLED"
    TEMPLATE = "Tabled winner {tabled_winner} cannot be killed by award"
    tabled_winner: str = ""


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


@dataclass
class RaiseCapReached(PreconditionError):
    """TDA Rule 48 — limit raise cap reached for this betting round.

    The current_round has already seen the house-default count of
    raises (1 bet + 4 raises by default) while more than 2 players
    remain active. Subsequent raises are rejected with this code.
    """

    CODE = "RAISE_CAP_REACHED"
    TEMPLATE = "Raise cap of {max_raises_per_round} reached for this round"
    max_raises_per_round: int = 0


@dataclass
class BoundToCallOrRaise(PreconditionError):
    """TDA Rule 46B — pulling back a prior-bet chip while facing a raise
    binds the player to call or raise. Subsequent fold attempts within
    the same action are rejected with this code.
    """

    CODE = "BOUND_TO_CALL_OR_RAISE"
    TEMPLATE = "Player has pulled back a prior chip facing a raise; cannot fold"


@dataclass
class DoubledBetNotAllowed4thStreet(PreconditionError):
    """TDA RP-10F — Seven Card Stud (high) fixed-limit: an open pair on
    4th street does NOT permit doubling the bet to the upper limit. The
    bet must stay at the lower limit (small_bet). The rejection carries
    ``max_bet`` so callers can correct the action and resubmit. Not a
    plain BoundViolation because the cucumber assertion pins
    ``max_bet`` rather than the generic ``got``/``bound`` pair.
    """

    CODE = "DOUBLED_BET_NOT_ALLOWED_4TH_STREET"
    TEMPLATE = "Open pair on 4th street locks bet at {max_bet}"
    max_bet: int = 0


@dataclass
class OpenPairLocksLowerLimit(PreconditionError):
    """WSOP §Seven Card Stud Hi/Lo 8 or Better — an open pair on 4th
    street locks the bet to the lower limit. Different code from
    RP-10F's variant since WSOP cites the rule differently for Hi/Lo
    than TDA does for Stud Hi (Razz, by Robert's §RAZZ #3, does not
    lock at all — see EU-1341)."""

    CODE = "OPEN_PAIR_LOCKS_LOWER_LIMIT"
    TEMPLATE = "Open pair on 4th street locks bet at lower limit {max_bet}"
    max_bet: int = 0


@dataclass
class MuckedWithoutTabling(PreconditionError):
    """TDA Rule 18A — players who mucked face-down at showdown have no
    right to ask to see another player's hand. RequestShowHand from a
    mucked-without-tabling player is rejected with this code."""

    CODE = "MUCKED_WITHOUT_TABLING"
    TEMPLATE = "Player mucked face down without tabling; cannot ask to see hands"


@dataclass
class StudMuckByPickupForbidden(PreconditionError):
    """TDA Rule 66 — in stud, picking up the upcards while facing
    action kills the hand. The proper muck is turning down all up
    cards and pushing them forward face down. The aggregate rejects a
    FOLD that signals a pickup-style muck so the floor can apply the
    correct disciplinary procedure."""

    CODE = "STUD_MUCK_BY_PICKUP_FORBIDDEN"
    TEMPLATE = (
        "Stud players must muck by turning upcards down — picking them "
        "up kills the hand under Rule 66"
    )


@dataclass
class StudTooManyCards(PreconditionError):
    """Robert's §SC Stud #18 — at showdown a stud hand with more than
    7 cards is dead. Unlike the missing-card case (which goes to floor
    discretion via FloorDecisionRequired), too-many-cards is a hard
    rejection: the player demonstrably has more cards than the variant
    permits and cannot have a live hand under any ruling."""

    CODE = "STUD_TOO_MANY_CARDS"
    TEMPLATE = "Stud hand has {got} cards; maximum is 7"
    got: int = 0


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
    "RaiseCapReached",
    "BoundToCallOrRaise",
    "DoubledBetNotAllowed4thStreet",
    "OpenPairLocksLowerLimit",
    "MuckedWithoutTabling",
    "StudMuckByPickupForbidden",
    "StudTooManyCards",
    "CannotPostAnteAfterBlinds",
    "RevealOutOfOrder",
]
