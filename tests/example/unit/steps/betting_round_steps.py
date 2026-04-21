"""Step definitions for the betting-round iteration scenarios.

These scenarios exercise the ``BettingRoundTester`` fixture from
``tests/test_betting_round.py`` — a standalone harness that mirrors the
``betting_round()`` driver in ``run_game.py``. No aggregate handlers are
involved here; we're only checking the iteration logic.
"""

import importlib.util
import sys
from pathlib import Path

from behave import given, then, use_step_matcher, when

use_step_matcher("re")


# Load the sibling support module by path. We can't use a relative import here
# because behave loads step modules via exec() — they have no __package__.
_SUPPORT_PATH = Path(__file__).resolve().parent / "_betting_round_support.py"
_MODULE_NAME = "_betting_round_support"
if _MODULE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SUPPORT_PATH)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _mod
    _spec.loader.exec_module(_mod)
else:
    _mod = sys.modules[_MODULE_NAME]

BettingRoundTester = _mod.BettingRoundTester
MockPlayer = _mod.MockPlayer
FOLD = _mod.FOLD
CHECK = _mod.CHECK
CALL = _mod.CALL
BET = _mod.BET
RAISE = _mod.RAISE

_ACTION_LOOKUP = {
    "FOLD": FOLD,
    "CHECK": CHECK,
    "CALL": CALL,
    "BET": BET,
    "RAISE": RAISE,
}


# --- Given steps ---


@given(r"a (?P<count>\d+)-player table with big_blind (?P<bb>\d+)")
def step_given_n_player_table(context, count, bb):
    """Create a standard N-player table with default 1000-chip stacks."""
    names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Henry"]
    n = int(count)
    players = {
        i: MockPlayer(name=names[i % len(names)], seat=i, stack=1000) for i in range(n)
    }
    context.br_game = BettingRoundTester(players, big_blind=int(bb))


@given(r"a table with players:")
def step_given_table_with_players(context):
    """Create a table from a datatable of players."""
    players = {}
    for row in context.table:
        d = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        seat = int(d["seat"])
        players[seat] = MockPlayer(name=d["name"], seat=seat, stack=int(d["stack"]))
    # Default big_blind; will be overridden by the next step
    context.br_game = BettingRoundTester(players, big_blind=10)


@given(r"big_blind (?P<bb>\d+)")
def step_given_big_blind(context, bb):
    """Set the big_blind on the existing tester."""
    context.br_game.big_blind = int(bb)


@given(
    r'blinds posted: "(?P<sb_name>[^"]+)" seat (?P<sb_seat>\d+) amount (?P<sb_amt>\d+) '
    r'and "(?P<bb_name>[^"]+)" seat (?P<bb_seat>\d+) amount (?P<bb_amt>\d+)'
)
def step_given_blinds_posted(
    context, sb_name, sb_seat, sb_amt, bb_name, bb_seat, bb_amt
):
    """Seed SB and BB bets on the tester's state (matches preflop entry)."""
    game = context.br_game
    game.players[int(sb_seat)].bet = int(sb_amt)
    game.players[int(bb_seat)].bet = int(bb_amt)
    game.current_bet = int(bb_amt)
    game.pot = int(sb_amt) + int(bb_amt)


@given(r"scripted actions:")
def step_given_scripted_actions(context):
    """Populate the tester's predetermined action sequence."""
    actions = []
    for row in context.table:
        d = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        actions.append((_ACTION_LOOKUP[d["action"].upper()], int(d["amount"])))
    context.br_game.set_actions(actions)


# --- When steps ---


@when(r"I run a preflop betting round starting at seat (?P<seat>\d+)")
def step_when_run_preflop(context, seat):
    """Run the preflop betting round from the given first-to-act seat."""
    context.br_game.betting_round(first_to_act_seat=int(seat), preflop=True)


# --- Then steps ---


@then(r"the seats asked to act are \[(?P<seats>[^\]]*)\]")
def step_then_seats_order(context, seats):
    """Verify the exact order of seats asked to act."""
    expected = [int(s.strip()) for s in seats.split(",") if s.strip()]
    actual = context.br_game.seats_asked_to_act
    assert actual == expected, f"Expected {expected}, got {actual}"


@then(r"seat (?P<after>\d+) is asked to act after seat (?P<before>\d+)")
def step_then_seat_after(context, after, before):
    """Verify that seat ``after`` appears after seat ``before`` in the order."""
    order = context.br_game.seats_asked_to_act
    before_i = int(before)
    after_i = int(after)
    assert before_i in order, f"seat {before_i} was never asked to act: {order}"
    slice_after = order[order.index(before_i) + 1 :]
    assert after_i in slice_after, (
        f"seat {after_i} did not appear after seat {before_i}; " f"full order: {order}"
    )


@then(r"seat (?P<seat>\d+) is asked to act exactly (?P<n>\d+) times?")
def step_then_seat_asked_count(context, seat, n):
    """Verify a given seat was asked to act an exact number of times."""
    count = context.br_game.seats_asked_to_act.count(int(seat))
    assert count == int(n), (
        f"seat {seat} asked {count} times, expected {n}. "
        f"full order: {context.br_game.seats_asked_to_act}"
    )


@then(r"seat (?P<seat>\d+) is all-in")
def step_then_seat_all_in(context, seat):
    """Verify a seat is all-in."""
    player = context.br_game.players[int(seat)]
    assert player.all_in, f"seat {seat} is not all-in"


@then(r"seat (?P<seat>\d+) has stack (?P<stack>\d+)")
def step_then_seat_stack(context, seat, stack):
    """Verify a seat's remaining stack."""
    player = context.br_game.players[int(seat)]
    assert player.stack == int(
        stack
    ), f"seat {seat} has stack {player.stack}, expected {stack}"
