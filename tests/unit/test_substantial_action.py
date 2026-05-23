"""Unit tests for ``hand.agg.substantial_action``.

Mirrors the Rust unit tests in
``examples-rust/main/hand/agg/src/substantial_action.rs``.
"""

import pytest

from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from hand.agg.substantial_action import is_substantial_action

CHECK = poker_types.CHECK
FOLD = poker_types.FOLD
CALL = poker_types.CALL
BET = poker_types.BET
RAISE = poker_types.RAISE
ALL_IN = poker_types.ALL_IN


def test_no_actions_is_not_sa():
    assert is_substantial_action([]) is False


def test_one_action_is_not_sa():
    assert is_substantial_action([FOLD]) is False
    assert is_substantial_action([CHECK]) is False
    assert is_substantial_action([RAISE]) is False
    assert is_substantial_action([CALL]) is False


def test_two_folds_is_not_sa():
    """EU-1232 example row: FOLD,FOLD → false."""
    assert is_substantial_action([FOLD, FOLD]) is False


def test_two_checks_is_not_sa():
    """EU-1232 example row: CHECK,CHECK → false."""
    assert is_substantial_action([CHECK, CHECK]) is False


def test_check_then_fold_is_not_sa():
    """Rule 36: 2 actions with no chips in pot is NOT SA."""
    assert is_substantial_action([CHECK, FOLD]) is False


def test_fold_then_check_is_not_sa():
    assert is_substantial_action([FOLD, CHECK]) is False


def test_call_then_fold_is_sa():
    """EU-1232 example row: CALL,FOLD → true (CALL puts chips in)."""
    assert is_substantial_action([CALL, FOLD]) is True


def test_raise_then_fold_is_sa():
    """EU-1232 example row: RAISE,FOLD → true."""
    assert is_substantial_action([RAISE, FOLD]) is True


def test_bet_then_call_is_sa():
    assert is_substantial_action([BET, CALL]) is True


def test_call_then_check_is_sa():
    """A CALL on the round counts as a chip action even followed by a
    CHECK from a player not facing a bet."""
    assert is_substantial_action([CALL, CHECK]) is True


def test_all_in_then_fold_is_sa():
    assert is_substantial_action([ALL_IN, FOLD]) is True


def test_three_folds_is_sa():
    """EU-1232 example row: FOLD,FOLD,FOLD → true. 3 actions of any
    kind constitute SA per Rule 36 case B."""
    assert is_substantial_action([FOLD, FOLD, FOLD]) is True


def test_three_checks_is_sa():
    """A check-around (3 checks in turn) is SA per Rule 36 case B."""
    assert is_substantial_action([CHECK, CHECK, CHECK]) is True


def test_check_check_fold_is_sa():
    assert is_substantial_action([CHECK, CHECK, FOLD]) is True


def test_four_actions_is_sa_regardless_of_mix():
    """4+ actions is SA. Pin a few combinations."""
    assert is_substantial_action([CHECK, CHECK, CHECK, FOLD]) is True
    assert is_substantial_action([FOLD, FOLD, FOLD, FOLD]) is True
    assert is_substantial_action([CALL, CHECK, FOLD, RAISE]) is True


def test_single_raise_is_not_sa():
    """EU-1232 example row: RAISE → false. A single chip action without
    a follow-up is not yet SA — RP-8/Rule 35 wait for the SECOND action."""
    assert is_substantial_action([RAISE]) is False


def test_chip_action_alone_in_first_position_not_sa():
    """A solo BET / CALL / ALL_IN — same as the RAISE case. Not yet SA."""
    assert is_substantial_action([BET]) is False
    assert is_substantial_action([CALL]) is False
    assert is_substantial_action([ALL_IN]) is False


@pytest.mark.parametrize(
    "actions,expected",
    [
        # EU-1232 outline cases:
        ([FOLD, FOLD], False),
        ([CHECK, CHECK], False),
        ([FOLD, FOLD, FOLD], True),
        ([CALL, FOLD], True),
        ([RAISE], False),
        ([RAISE, FOLD], True),
    ],
    ids=[
        "FOLD,FOLD",
        "CHECK,CHECK",
        "FOLD,FOLD,FOLD",
        "CALL,FOLD",
        "RAISE",
        "RAISE,FOLD",
    ],
)
def test_eu_1232_outline_table(actions, expected):
    """EU-1232 — TDA Rule 36 — exhaustive outline cases."""
    assert is_substantial_action(actions) is expected
