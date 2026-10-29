"""The Bot: its strategy decides (and may never double unless the turn
allows it), and it counts what it has done."""

from __future__ import annotations

from dataclasses import dataclass

from angzarr_player.domain import Decision, Memory, Move
from angzarr_player.logic import Bot
from angzarr_player.strategy import BasicStrategy

from .test_strategy import turn

TABLE = b"\x01" * 16


@dataclass
class Always:
    """A strategy that always answers ``move``."""

    move: Move

    def choose(self, _turn):
        return self.move


def test_the_bot_plays_basic_strategy_by_default():
    assert isinstance(Bot().strategy, BasicStrategy)
    assert Bot().decide(turn((6, 5), 11, 6, can_double=True), Memory()) == (
        Move.DOUBLE_DOWN
    )


def test_the_bot_answers_its_strategys_move():
    hand = turn((10, 7), 17, 10, can_double=True)
    for move in Move:
        assert Bot(Always(move)).decide(hand, Memory()) == move


def test_a_double_the_turn_does_not_allow_becomes_a_hit():
    bot = Bot(Always(Move.DOUBLE_DOWN))
    assert bot.decide(turn((6, 5), 11, 6, can_double=False), Memory()) == Move.HIT


def decision(cards: int, move: Move = Move.HIT, round: int = 1) -> Decision:
    return Decision(table_root=TABLE, round=round, seat=0, move=move, cards=cards)


def test_every_decision_is_counted_and_a_hand_once():
    bot = Bot()
    memory = Memory()
    # One hand: hit on two cards, hit on three, stand on four (EU-1606).
    for cards, move in ((2, Move.HIT), (3, Move.HIT), (4, Move.STAND)):
        memory = bot.remember(memory, decision(cards, move))
    assert memory == Memory(decisions=3, hands_seen=1)
    # The next hand: a double on two cards.
    memory = bot.remember(memory, decision(2, Move.DOUBLE_DOWN, round=2))
    assert memory == Memory(decisions=4, hands_seen=2)


def test_remembering_leaves_the_old_memory_alone():
    before = Memory(decisions=5, hands_seen=2)
    after = Bot().remember(before, decision(2))
    assert before == Memory(decisions=5, hands_seen=2)
    assert after == Memory(decisions=6, hands_seen=3)
