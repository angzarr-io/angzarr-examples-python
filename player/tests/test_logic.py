"""PlayerLogicImpl: its strategy decides (and may never double unless the
turn allows it), its MoveDecided is built from the turn, and its fold counts
what it has done."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from angzarr_player.domain import CommandContext, MoveAction, MoveDecided, PlayerState
from angzarr_player.logic_impl import PlayerLogicImpl
from angzarr_player.strategy import BasicStrategy

from .test_strategy import turn

TABLE = b"\x01" * 16


@dataclass
class Always:
    """A strategy that always answers ``move``."""

    move: MoveAction

    def choose(self, _turn):
        return self.move


def decide(logic: PlayerLogicImpl, cmd) -> MoveDecided:
    return logic.decide_move(cmd, PlayerState(), CommandContext())


def test_the_player_plays_basic_strategy_by_default():
    assert isinstance(PlayerLogicImpl().strategy, BasicStrategy)
    cmd = turn((6, 5), 11, 6, can_double=True)
    assert decide(PlayerLogicImpl(), cmd).action == MoveAction.DOUBLE_DOWN


def test_the_decision_is_the_turn_with_its_strategys_move():
    cmd = turn((10, 7), 17, 10, can_double=True)
    for move in (MoveAction.HIT, MoveAction.STAND, MoveAction.DOUBLE_DOWN):
        decided = decide(PlayerLogicImpl(Always(move)), cmd)
        assert decided == MoveDecided.from_command(cmd, action=move)


def test_a_double_the_turn_does_not_allow_becomes_a_hit():
    logic = PlayerLogicImpl(Always(MoveAction.DOUBLE_DOWN))
    assert decide(logic, turn((6, 5), 11, 6, can_double=False)).action == MoveAction.HIT


def decided(cards: int, move: MoveAction = MoveAction.HIT) -> MoveDecided:
    cmd = turn(tuple(range(2, 2 + cards)), 9, 9)
    return MoveDecided.from_command(cmd, action=move)


def test_every_decision_is_counted_and_a_hand_once():
    logic = PlayerLogicImpl()
    state = PlayerState()
    # One hand: hit on two cards, hit on three, stand on four (EU-1606).
    for cards, move in (
        (2, MoveAction.HIT),
        (3, MoveAction.HIT),
        (4, MoveAction.STAND),
    ):
        state = logic.apply_move_decided(state, decided(cards, move))
    assert state == PlayerState(decisions=3, hands_seen=1)
    # The next hand: a double on two cards.
    state = logic.apply_move_decided(state, decided(2, MoveAction.DOUBLE_DOWN))
    assert state == PlayerState(decisions=4, hands_seen=2)


def test_the_fold_leaves_the_old_state_alone():
    before = PlayerState(decisions=5, hands_seen=2)
    after = PlayerLogicImpl().apply_move_decided(before, decided(2))
    assert before == PlayerState(decisions=5, hands_seen=2)
    assert after == dataclasses.replace(before, decisions=6, hands_seen=3)
