"""Player-domain error catalog: code/template/status/render assertions."""

import pytest

from player.agg.errors import (
    AmountExceedsReservedFunds,
    AmountMustBeNonZero,
    AmountMustBePositive,
    DisplayNameRequired,
    EmailRequired,
    FundsAlreadyReservedForTable,
    InsufficientAvailableBalance,
    InsufficientFunds,
    KeyRequired,
    NoFundsReservedForTable,
    PlayerAlreadyExists,
    PlayerNotFound,
    TableRootRequired,
)


@pytest.mark.parametrize(
    ("err", "expected_code", "expected_status", "expected_render"),
    [
        (
            PlayerAlreadyExists(),
            "PLAYER_ALREADY_EXISTS",
            "FAILED_PRECONDITION",
            "Player already exists",
        ),
        (
            DisplayNameRequired(),
            "DISPLAY_NAME_REQUIRED",
            "INVALID_ARGUMENT",
            "display_name is required",
        ),
        (EmailRequired(), "EMAIL_REQUIRED", "INVALID_ARGUMENT", "email is required"),
        (
            PlayerNotFound(),
            "PLAYER_NOT_FOUND",
            "FAILED_PRECONDITION",
            "Player does not exist",
        ),
        (
            AmountMustBePositive(value=-5),
            "AMOUNT_MUST_BE_POSITIVE",
            "INVALID_ARGUMENT",
            "Amount must be positive, got -5",
        ),
        (
            AmountMustBeNonZero(value=0),
            "AMOUNT_MUST_BE_NON_ZERO",
            "INVALID_ARGUMENT",
            "Amount must be non-zero",
        ),
        (
            InsufficientAvailableBalance(requested=500, available=100),
            "INSUFFICIENT_AVAILABLE_BALANCE",
            "FAILED_PRECONDITION",
            "Insufficient available balance: requested 500, available 100",
        ),
        (
            InsufficientFunds(requested=200, available=50),
            "INSUFFICIENT_FUNDS",
            "FAILED_PRECONDITION",
            "Insufficient funds: requested 200, available 50",
        ),
        (
            FundsAlreadyReservedForTable(table_root_hex="abc123"),
            "FUNDS_ALREADY_RESERVED_FOR_TABLE",
            "FAILED_PRECONDITION",
            "Funds already reserved for table abc123",
        ),
        (
            TableRootRequired(),
            "TABLE_ROOT_REQUIRED",
            "INVALID_ARGUMENT",
            "table_root is required",
        ),
        (
            NoFundsReservedForTable(table_root_hex="abc123"),
            "NO_FUNDS_RESERVED_FOR_TABLE",
            "FAILED_PRECONDITION",
            "No funds reserved for table abc123",
        ),
        (KeyRequired(), "KEY_REQUIRED", "INVALID_ARGUMENT", "key is required"),
        (
            AmountExceedsReservedFunds(requested=300, available=100),
            "AMOUNT_EXCEEDS_RESERVED_FUNDS",
            "FAILED_PRECONDITION",
            "Amount exceeds reserved funds: requested 300, available 100",
        ),
    ],
)
def test_each_error_publishes_code_status_and_renders(
    err, expected_code, expected_status, expected_render
):
    assert err.code == expected_code
    assert err.status_code == expected_status
    assert err.render() == expected_render


def test_amount_must_be_positive_carries_value_in_details():
    err = AmountMustBePositive(value=-7)
    assert err.details == {"value": "-7"}


def test_insufficient_funds_carries_both_fields_in_details():
    err = InsufficientFunds(requested=200, available=50)
    assert err.details == {"requested": "200", "available": "50"}


def test_amount_exceeds_reserved_carries_both_fields():
    err = AmountExceedsReservedFunds(requested=300, available=100)
    assert err.details == {"requested": "300", "available": "100"}


def test_template_is_static_wire_message():
    a = AmountMustBePositive(value=1)
    b = AmountMustBePositive(value=99)
    assert a.message == b.message == "Amount must be positive, got {value}"
