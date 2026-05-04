"""Direct unit tests for the shape hierarchy.

Verifies each shape parent constructs correctly, exposes the canonical
field names, renders templates from a subclass that uses them, and
preserves ``isinstance`` classification through the inheritance chain.
"""

from dataclasses import dataclass

from angzarr_client.errors import CommandRejectedError
from angzarr_examples.error_shapes import (
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
from angzarr_examples.errors import StructuredCommandError


# --- Sample leaves used to exercise each shape ---


@dataclass
class _SampleAggregateNotFound(AggregateNotFound):
    CODE = "X_NOT_FOUND"
    TEMPLATE = "X does not exist"


@dataclass
class _SampleBoundViolation(BoundViolation):
    CODE = "SAMPLE_BELOW_MIN"
    TEMPLATE = "Sample {got} below limit {bound}"
    KIND = "below_min"
    STATUS = "INVALID_ARGUMENT"


@dataclass
class _SampleRelationViolation(RelationViolation):
    CODE = "SAMPLE_RELATION"
    TEMPLATE = "left ({lhs}) must be <= right ({rhs})"


@dataclass
class _SampleIdentityMismatch(IdentityMismatch):
    CODE = "SAMPLE_IDENTITY"
    TEMPLATE = "expected {expected}, got {got}"


@dataclass
class _SampleInsufficient(InsufficientCapacity):
    CODE = "SAMPLE_INSUFFICIENT"
    TEMPLATE = "requested {requested}, available {available}"


@dataclass
class _SampleExhausted(Exhausted):
    CODE = "SAMPLE_EXHAUSTED"
    TEMPLATE = "exhausted at {current}, max {max_value}"


@dataclass
class _SampleMustBePositive(MustBePositive):
    CODE = "SAMPLE_POSITIVE"
    TEMPLATE = "must be positive, got {value}"


@dataclass
class _SampleValueOutOfRange(ValueOutOfRange):
    CODE = "SAMPLE_OUT_OF_RANGE"
    TEMPLATE = "out of range, got {got}"


@dataclass
class _SampleFieldRequired(FieldRequired):
    CODE = "X_REQUIRED"
    TEMPLATE = "x is required"


@dataclass
class _SampleStateMismatch(StateMismatch):
    CODE = "SAMPLE_STATE"
    TEMPLATE = "wrong state"


# --- Tests ---


def test_every_shape_inherits_from_structured_command_error():
    err = _SampleAggregateNotFound()
    assert isinstance(err, StructuredCommandError)
    assert isinstance(err, CommandRejectedError)
    assert isinstance(err, PreconditionError)
    assert isinstance(err, AggregateNotFound)


def test_validation_shapes_default_to_invalid_argument_status():
    assert _SampleMustBePositive(value=0).status_code == "INVALID_ARGUMENT"
    assert _SampleValueOutOfRange(got=99).status_code == "INVALID_ARGUMENT"
    assert _SampleFieldRequired().status_code == "INVALID_ARGUMENT"


def test_precondition_shapes_default_to_failed_precondition_status():
    assert _SampleAggregateNotFound().status_code == "FAILED_PRECONDITION"
    assert _SampleStateMismatch().status_code == "FAILED_PRECONDITION"
    assert _SampleRelationViolation(lhs=5, rhs=4).status_code == "FAILED_PRECONDITION"


def test_bound_violation_carries_canonical_fields_and_kind():
    err = _SampleBoundViolation(got=50, bound=200)
    assert err.got == 50
    assert err.bound == 200
    assert err.KIND == "below_min"
    assert err.render() == "Sample 50 below limit 200"
    assert err.details == {"got": "50", "bound": "200"}


def test_relation_violation_uses_lhs_rhs_canonical():
    err = _SampleRelationViolation(lhs=5, rhs=4)
    assert err.lhs == 5
    assert err.rhs == 4
    assert err.render() == "left (5) must be <= right (4)"


def test_identity_mismatch_renders_expected_and_got():
    err = _SampleIdentityMismatch(expected=3, got=7)
    assert err.render() == "expected 3, got 7"


def test_insufficient_capacity_renders_requested_and_available():
    err = _SampleInsufficient(requested=500, available=100)
    assert err.render() == "requested 500, available 100"


def test_exhausted_uses_current_and_max_value():
    err = _SampleExhausted(current=3, max_value=3)
    assert err.render() == "exhausted at 3, max 3"
    assert err.details == {"current": "3", "max_value": "3"}


def test_must_be_positive_uses_value():
    err = _SampleMustBePositive(value=-5)
    assert err.render() == "must be positive, got -5"


def test_value_out_of_range_uses_got():
    err = _SampleValueOutOfRange(got=99)
    assert err.render() == "out of range, got 99"


def test_marker_shapes_have_no_field_args():
    # Constructible with no args.
    _SampleStateMismatch()
    _SampleFieldRequired()
    _SampleAggregateNotFound()


def test_isinstance_classification_matches_tree():
    """Cross-cutting code can match either the leaf, its shape, or the
    mid-level Precondition/Validation parent."""
    bv = _SampleBoundViolation(got=1, bound=2)
    assert isinstance(bv, BoundViolation)
    assert isinstance(bv, PreconditionError)
    # But not in a sibling shape.
    assert not isinstance(bv, ValidationError)
    assert not isinstance(bv, AggregateNotFound)


def test_marker_shapes_are_distinct_under_isinstance():
    not_found = _SampleAggregateNotFound()
    state = _SampleStateMismatch()
    assert isinstance(not_found, AggregateNotFound)
    assert not isinstance(not_found, StateMismatch)
    assert isinstance(state, StateMismatch)
    assert not isinstance(state, AggregateNotFound)


def test_all_shapes_are_importable_and_distinct():
    """Smoke test the export list — each shape is its own class."""
    shapes = [
        AggregateNotFound,
        AggregateAlreadyExists,
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
    ]
    assert len(set(shapes)) == len(shapes)
    for shape in shapes:
        assert issubclass(shape, StructuredCommandError)
