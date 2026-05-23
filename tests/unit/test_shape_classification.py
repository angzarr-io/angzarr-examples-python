"""Cross-cutting shape classification — verify every leaf inherits from the
right shape parent.

This catches drift: if a future leaf is added without a shape, or the shape
assignment regresses, this test fails. It's the single source of truth for
"which leaves implement which shape" — far easier to audit than scanning
all four catalog files.
"""

from __future__ import annotations

import pytest

from poker.error_shapes import (
    AggregateAlreadyExists,
    AggregateNotFound,
    BoundViolation,
    ContainerFull,
    EntityKeyedConflict,
    EntityNotInContainer,
    Exhausted,
    FieldRequired,
    IdentityMismatch,
    InsufficientCapacity,
    InvalidOperationInState,
    MustBeNonZero,
    MustBePositive,
    PreconditionError,
    RelationViolation,
    StateAlreadyEntered,
    StateMismatch,
    ValidationError,
    ValueOutOfRange,
    VariantMismatch,
)
from poker.errors import StructuredCommandError

# Import all leaves from all four domains.
from hand.agg import errors as hand_errors
from player.agg import errors as player_errors
from table.agg import errors as table_errors
from tournament.agg import errors as tournament_errors

# Each entry is (leaf_class, expected_shape). One-off leaves that don't fit
# any shape are listed under StructuredCommandError as their immediate
# tier-2 parent (PreconditionError or ValidationError).

_LEAF_SHAPE_TABLE: list[tuple[type, type]] = [
    # --- player domain (13 leaves) ---
    (player_errors.PlayerAlreadyExists, AggregateAlreadyExists),
    (player_errors.PlayerNotFound, AggregateNotFound),
    (player_errors.DisplayNameRequired, FieldRequired),
    (player_errors.EmailRequired, FieldRequired),
    (player_errors.TableRootRequired, FieldRequired),
    (player_errors.KeyRequired, FieldRequired),
    (player_errors.AmountMustBePositive, MustBePositive),
    (player_errors.AmountMustBeNonZero, MustBeNonZero),
    (player_errors.InsufficientAvailableBalance, InsufficientCapacity),
    (player_errors.InsufficientFunds, InsufficientCapacity),
    (player_errors.AmountExceedsReservedFunds, InsufficientCapacity),
    (player_errors.FundsAlreadyReservedForTable, EntityKeyedConflict),
    (player_errors.NoFundsReservedForTable, EntityKeyedConflict),
    # --- tournament domain (20 leaves) ---
    (tournament_errors.TournamentAlreadyExists, AggregateAlreadyExists),
    (tournament_errors.TournamentNotFound, AggregateNotFound),
    (tournament_errors.NameRequired, FieldRequired),
    (tournament_errors.PlayerRootRequired, FieldRequired),
    (tournament_errors.BuyInMustBePositive, MustBePositive),
    (tournament_errors.StartingStackMustBePositive, MustBePositive),
    (tournament_errors.MaxPlayersTooFew, ValueOutOfRange),
    (tournament_errors.MinPlayersTooFew, ValueOutOfRange),
    (tournament_errors.MinPlayersExceedsMax, RelationViolation),
    (tournament_errors.CannotOpenRegistrationRunning, InvalidOperationInState),
    (tournament_errors.RegistrationAlreadyOpen, StateAlreadyEntered),
    (tournament_errors.RegistrationNotOpen, StateMismatch),
    (tournament_errors.TournamentNotRunning, StateMismatch),
    (tournament_errors.TournamentAlreadyPaused, StateAlreadyEntered),
    (tournament_errors.TournamentNotPaused, StateMismatch),
    (tournament_errors.NotEnoughPlayersToStart, InsufficientCapacity),
    (tournament_errors.TournamentAlreadyCompleted, StateAlreadyEntered),
    (tournament_errors.TournamentNotRunningOrPaused, StateMismatch),
    (tournament_errors.PlayerNotRegistered, EntityNotInContainer),
    (tournament_errors.BlindStructureExhausted, Exhausted),
    # --- table domain (22 leaves) ---
    (table_errors.TableAlreadyExists, AggregateAlreadyExists),
    (table_errors.TableNotFound, AggregateNotFound),
    (table_errors.TableNameRequired, FieldRequired),
    (table_errors.PlayerRootRequired, FieldRequired),
    (table_errors.SmallBlindMustBePositive, MustBePositive),
    (table_errors.MinBuyInMustBePositive, MustBePositive),
    (table_errors.AmountMustBePositive, MustBePositive),
    (table_errors.BigBlindMustExceedSmallBlind, RelationViolation),
    (table_errors.MaxBuyInMustExceedMinBuyIn, RelationViolation),
    (table_errors.MaxPlayersOutOfRange, ValueOutOfRange),
    (table_errors.TableIsFull, ContainerFull),
    (table_errors.BuyInBelowMin, BoundViolation),
    (table_errors.BuyInAboveMax, BoundViolation),
    (table_errors.SeatOccupied, EntityKeyedConflict),
    (table_errors.PlayerAlreadySeated, StateAlreadyEntered),
    (table_errors.PlayerNotSeated, EntityNotInContainer),
    (table_errors.CannotLeaveDuringHand, InvalidOperationInState),
    (table_errors.HandAlreadyInProgress, StateAlreadyEntered),
    (table_errors.NoHandInProgress, StateMismatch),
    (table_errors.NotEnoughPlayersToStartHand, InsufficientCapacity),
    (table_errors.HandRootMismatch, PreconditionError),  # one-off (bytes mismatch)
    (table_errors.SeatPositionMismatch, IdentityMismatch),
    # --- hand domain (36 leaves) ---
    (hand_errors.HandAlreadyDealt, StateAlreadyEntered),
    (hand_errors.HandNotDealt, StateMismatch),
    (hand_errors.HandAlreadyComplete, StateAlreadyEntered),
    (hand_errors.PlayerRootRequired, FieldRequired),
    (hand_errors.PlayerNotInHand, EntityNotInContainer),
    (hand_errors.PlayerHasFolded, StateAlreadyEntered),
    (hand_errors.PlayerIsAllIn, StateAlreadyEntered),
    (hand_errors.NoPlayersInHand, PreconditionError),  # one-off
    (hand_errors.NeedAtLeast2Players, ValueOutOfRange),
    (hand_errors.BlindAmountMustBePositive, MustBePositive),
    (hand_errors.NotInBettingPhase, StateMismatch),
    (hand_errors.CannotCheckWithBet, InvalidOperationInState),
    (hand_errors.NothingToCall, InvalidOperationInState),
    (hand_errors.CannotBetOverExistingBet, InvalidOperationInState),
    (hand_errors.BetBelowMinRaise, BoundViolation),
    (hand_errors.BetExceedsStack, BoundViolation),
    (hand_errors.CannotRaiseWithoutBet, InvalidOperationInState),
    (hand_errors.RaiseBelowMin, BoundViolation),
    (hand_errors.RaiseExceedsStack, BoundViolation),
    (hand_errors.InvalidAction, ValueOutOfRange),
    (hand_errors.MustDealAtLeast1Card, BoundViolation),
    (hand_errors.CommunityCardsNotUsedInVariant, VariantMismatch),
    (hand_errors.NoMorePhases, ContainerFull),
    (hand_errors.CannotDealMoreCommunityCards, InvalidOperationInState),
    (hand_errors.WrongCardCountForPhase, IdentityMismatch),
    (hand_errors.NotEnoughCardsInDeck, InsufficientCapacity),
    (hand_errors.DrawNotSupportedInVariant, VariantMismatch),
    (hand_errors.NotInDrawPhase, StateMismatch),
    (hand_errors.TooManyDiscards, BoundViolation),
    (hand_errors.DuplicateCardIndices, PreconditionError),  # one-off
    (hand_errors.InvalidCardIndex, ValueOutOfRange),
    (hand_errors.NotInShowdownPhase, StateMismatch),
    (hand_errors.NoAwardsSpecified, PreconditionError),  # one-off
    (hand_errors.AwardPlayerNotInHand, EntityNotInContainer),
    (hand_errors.FoldedPlayerCannotWin, InvalidOperationInState),
    (hand_errors.AwardsExceedPot, BoundViolation),
]


def test_leaf_shape_table_has_91_entries():
    """Pin the leaf count — catches accidental additions/removals."""
    assert len(_LEAF_SHAPE_TABLE) == 91, (
        f"Expected 91 leaves; the canonical catalog has changed. "
        f"Got {len(_LEAF_SHAPE_TABLE)}."
    )


@pytest.mark.parametrize(("leaf_cls", "expected_shape"), _LEAF_SHAPE_TABLE)
def test_leaf_inherits_from_assigned_shape(leaf_cls, expected_shape):
    """Every leaf class must subclass its assigned shape."""
    assert issubclass(leaf_cls, expected_shape), (
        f"{leaf_cls.__name__} is not a subclass of {expected_shape.__name__}"
    )


@pytest.mark.parametrize(("leaf_cls", "_expected_shape"), _LEAF_SHAPE_TABLE)
def test_every_leaf_inherits_from_structured_command_error(leaf_cls, _expected_shape):
    """Sanity: every leaf must also be a StructuredCommandError."""
    assert issubclass(leaf_cls, StructuredCommandError)


def test_validation_shapes_have_invalid_argument_status():
    """All ValidationError descendants default to INVALID_ARGUMENT."""
    for leaf_cls, expected_shape in _LEAF_SHAPE_TABLE:
        if not issubclass(expected_shape, ValidationError):
            continue
        assert issubclass(leaf_cls, ValidationError), leaf_cls.__name__
        # Sanity: the leaf's STATUS ClassVar matches.
        assert leaf_cls.STATUS == "INVALID_ARGUMENT", (
            f"{leaf_cls.__name__} is a ValidationError but STATUS={leaf_cls.STATUS}"
        )


def test_precondition_shapes_have_failed_precondition_status():
    """All PreconditionError descendants default to FAILED_PRECONDITION."""
    for leaf_cls, expected_shape in _LEAF_SHAPE_TABLE:
        if not issubclass(expected_shape, PreconditionError):
            continue
        assert issubclass(leaf_cls, PreconditionError), leaf_cls.__name__
        assert leaf_cls.STATUS == "FAILED_PRECONDITION", (
            f"{leaf_cls.__name__} is a PreconditionError but STATUS={leaf_cls.STATUS}"
        )


def test_no_leaf_is_misclassified_into_a_sibling_shape():
    """Each leaf belongs to exactly its assigned shape — not also a sibling
    shape it shouldn't belong to. Catches accidental multi-shape inheritance."""
    sibling_pairs = [
        (AggregateNotFound, AggregateAlreadyExists),
        (StateMismatch, StateAlreadyEntered),
        (FieldRequired, MustBePositive),
        (BoundViolation, RelationViolation),
        (InsufficientCapacity, Exhausted),
    ]
    for leaf_cls, expected_shape in _LEAF_SHAPE_TABLE:
        for shape_a, shape_b in sibling_pairs:
            if issubclass(leaf_cls, shape_a) and issubclass(leaf_cls, shape_b):
                pytest.fail(
                    f"{leaf_cls.__name__} subclasses both {shape_a.__name__} "
                    f"and {shape_b.__name__} — should be exactly one"
                )


def test_one_off_leaves_inherit_directly_from_precondition_error():
    """The 4 leaves that don't fit any shape — HandRootMismatch,
    NoPlayersInHand, DuplicateCardIndices, NoAwardsSpecified — should
    inherit directly from PreconditionError (no shape mid-level)."""
    one_offs = {
        table_errors.HandRootMismatch,
        hand_errors.NoPlayersInHand,
        hand_errors.DuplicateCardIndices,
        hand_errors.NoAwardsSpecified,
    }
    # Each one-off should NOT be in any of the field-bearing or marker shapes.
    all_shapes = (
        AggregateAlreadyExists,
        AggregateNotFound,
        StateMismatch,
        StateAlreadyEntered,
        InvalidOperationInState,
        EntityNotInContainer,
        EntityKeyedConflict,
        InsufficientCapacity,
        Exhausted,
        ContainerFull,
        BoundViolation,
        RelationViolation,
        IdentityMismatch,
        VariantMismatch,
        FieldRequired,
        MustBePositive,
        MustBeNonZero,
        ValueOutOfRange,
    )
    for leaf in one_offs:
        for shape in all_shapes:
            assert not issubclass(leaf, shape), (
                f"{leaf.__name__} is a one-off but unexpectedly inherits {shape.__name__}"
            )


def test_shape_name_returns_concrete_shape_class_name():
    """Cross-cutting observability: ``err.shape_name()`` returns the leaf's
    structural shape — used by metrics tags / log fields / cucumber."""
    assert player_errors.PlayerNotFound().shape_name() == "AggregateNotFound"
    assert (
        table_errors.BuyInBelowMin(got=100, bound=200).shape_name() == "BoundViolation"
    )
    assert (
        player_errors.InsufficientFunds(requested=500, available=100).shape_name()
        == "InsufficientCapacity"
    )
    assert (
        tournament_errors.MinPlayersExceedsMax(lhs=5, rhs=4).shape_name()
        == "RelationViolation"
    )
    assert player_errors.AmountMustBePositive(value=-1).shape_name() == "MustBePositive"


def test_shape_name_returns_empty_string_for_one_off_leaves():
    """The 4 leaves without a shape return ``""``."""
    assert table_errors.HandRootMismatch().shape_name() == ""
    assert hand_errors.NoPlayersInHand().shape_name() == ""
    assert hand_errors.DuplicateCardIndices().shape_name() == ""
    assert hand_errors.NoAwardsSpecified().shape_name() == ""


def test_classification_enables_cross_cutting_handling():
    """End-to-end demo: code can match by shape rather than by leaf code."""
    # Construct one leaf per cluster.
    not_found = player_errors.PlayerNotFound()
    bound_violation = table_errors.BuyInBelowMin(got=100, bound=200)
    capacity = player_errors.InsufficientFunds(requested=500, available=100)
    must_be_positive = player_errors.AmountMustBePositive(value=-5)

    # A generic logger that branches by shape, not code:
    def shape_label(err):
        if isinstance(err, AggregateNotFound):
            return "not_found"
        if isinstance(err, BoundViolation):
            return "bound_violation"
        if isinstance(err, InsufficientCapacity):
            return "capacity"
        if isinstance(err, MustBePositive):
            return "must_be_positive"
        return "other"

    assert shape_label(not_found) == "not_found"
    assert shape_label(bound_violation) == "bound_violation"
    assert shape_label(capacity) == "capacity"
    assert shape_label(must_be_positive) == "must_be_positive"
