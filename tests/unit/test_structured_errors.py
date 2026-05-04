"""Unit tests for StructuredCommandError base.

These exercise the base directly with a minimal subclass — domain catalogs
get their own tests in later phases.
"""

from dataclasses import dataclass

import pytest

from angzarr_client.errors import CommandRejectedError
from angzarr_examples.errors import StructuredCommandError


@dataclass
class _NeedAtLeast2Players(StructuredCommandError):
    CODE = "NEED_AT_LEAST_2_PLAYERS"
    TEMPLATE = "Need at least 2 players, got {got}"
    STATUS = "INVALID_ARGUMENT"
    got: int


@dataclass
class _BetBelowMinRaise(StructuredCommandError):
    CODE = "BET_BELOW_MIN_RAISE"
    TEMPLATE = "Bet must be at least {min_raise}, got {amount}"
    STATUS = "INVALID_ARGUMENT"
    min_raise: int
    amount: int


@dataclass
class _NoFields(StructuredCommandError):
    CODE = "GENERIC_FAILURE"
    TEMPLATE = "Generic failure with no runtime context"


def test_subclass_is_command_rejected_error():
    err = _NeedAtLeast2Players(got=1)
    assert isinstance(err, CommandRejectedError)


def test_code_is_published_to_framework_field():
    err = _NeedAtLeast2Players(got=1)
    assert err.code == "NEED_AT_LEAST_2_PLAYERS"


def test_template_is_the_static_wire_message():
    err = _NeedAtLeast2Players(got=1)
    assert err.message == "Need at least 2 players, got {got}"


def test_status_drives_framework_status_code():
    assert _NeedAtLeast2Players(got=1).status_code == "INVALID_ARGUMENT"
    assert _NoFields().status_code == "FAILED_PRECONDITION"


def test_fields_dict_contains_dataclass_fields():
    err = _BetBelowMinRaise(min_raise=200, amount=50)
    assert err.fields_dict() == {"min_raise": 200, "amount": 50}


def test_fields_dict_excludes_classvars():
    err = _NoFields()
    assert err.fields_dict() == {}


def test_details_carries_structured_runtime_context():
    # Framework stringifies details for cross-language wire parity (Audit #59).
    err = _BetBelowMinRaise(min_raise=200, amount=50)
    assert err.details == {"min_raise": "200", "amount": "50"}


def test_fields_dict_preserves_typed_values_for_in_process_consumers():
    err = _BetBelowMinRaise(min_raise=200, amount=50)
    assert err.fields_dict() == {"min_raise": 200, "amount": 50}


def test_render_substitutes_template_placeholders():
    err = _BetBelowMinRaise(min_raise=200, amount=50)
    assert err.render() == "Bet must be at least 200, got 50"


def test_render_returns_template_unchanged_when_no_fields():
    err = _NoFields()
    assert err.render() == "Generic failure with no runtime context"


def test_subclass_is_raisable_and_caught_as_command_rejected_error():
    with pytest.raises(CommandRejectedError) as exc_info:
        raise _NeedAtLeast2Players(got=0)
    assert exc_info.value.code == "NEED_AT_LEAST_2_PLAYERS"
    assert exc_info.value.details == {"got": "0"}


def test_predicate_methods_route_off_status_code():
    err = _NeedAtLeast2Players(got=1)
    assert err.is_invalid_argument()
    assert not err.is_precondition_failed()

    generic = _NoFields()
    assert generic.is_precondition_failed()
    assert not generic.is_invalid_argument()


def test_two_instances_have_identical_static_message_for_log_greppability():
    a = _NeedAtLeast2Players(got=1)
    b = _NeedAtLeast2Players(got=99)
    assert a.message == b.message
    # but their rendered output differs
    assert a.render() != b.render()
