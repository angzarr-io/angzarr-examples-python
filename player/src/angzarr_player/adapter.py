# PLACEHOLDER: replace with `angzarr scaffold python` output (the regenerable
# adapter between the generated PlayerAggregateHandler seam and PlayerLogic).
"""The PlayerAggregate on the generated ``PlayerAggregateHandler`` seam: it
maps the framework's messages onto the plain types of :mod:`.domain`, calls
the :class:`~angzarr_player.logic.PlayerLogic` it is given, and maps the
answer back. It holds no logic of its own."""

from __future__ import annotations

import angzarr_client.router as _az

from ._gen.io.angzarr.examples.v1 import cards_pb2 as _cards
from ._gen.io.angzarr.examples.v1 import player_pb2 as _player
from .domain import Card, Decision, Memory, Move, Suit, Turn
from .logic import Bot, PlayerLogic

_SUITS = {
    _cards.CLUBS: Suit.CLUBS,
    _cards.DIAMONDS: Suit.DIAMONDS,
    _cards.HEARTS: Suit.HEARTS,
    _cards.SPADES: Suit.SPADES,
}
_ACTIONS = {
    Move.HIT: _player.MOVE_ACTION_HIT,
    Move.STAND: _player.MOVE_ACTION_STAND,
    Move.DOUBLE_DOWN: _player.MOVE_ACTION_DOUBLE_DOWN,
}
_MOVES = {action: move for move, action in _ACTIONS.items()}


def _card(card: _cards.Card) -> Card:
    return Card(rank=card.rank, suit=_SUITS[card.suit])


def turn_of(cmd: _player.DecideMove) -> Turn:
    return Turn(
        table_root=cmd.table_root,
        round=cmd.round,
        seat=cmd.seat,
        cards=tuple(_card(c) for c in cmd.cards),
        total=cmd.total,
        soft=cmd.soft,
        dealer_up=_card(cmd.dealer_up),
        can_double=cmd.can_double,
        stack=cmd.stack,
        wager=cmd.wager,
    )


def memory_of(state: _player.PlayerState) -> Memory:
    return Memory(decisions=state.decisions, hands_seen=state.hands_seen)


def decision_of(event: _player.MoveDecided) -> Decision:
    # SPEC GAP (a91b882): MoveDecided does not say how many cards the hand
    # held, which hands_seen needs (PlayerState: "decisions taken on a
    # two-card hand"). Until the spec records it, 0 is passed: no hand is
    # counted.
    return Decision(
        table_root=event.table_root,
        round=event.round,
        seat=event.seat,
        move=_MOVES[event.action],
        cards=0,
    )


class PlayerAggregate:
    """Implements ``PlayerAggregateHandler`` over a :class:`PlayerLogic`."""

    def __init__(self, logic: PlayerLogic | None = None) -> None:
        self.logic = logic if logic is not None else Bot()

    def decide_move(
        self,
        cmd: _player.DecideMove,
        state: _player.PlayerState,
        cctx: _az.CommandContext,
    ) -> list[_player.MoveDecided]:
        move = self.logic.decide(turn_of(cmd), memory_of(state))
        return [
            _player.MoveDecided(
                table_root=cmd.table_root,
                round=cmd.round,
                seat=cmd.seat,
                action=_ACTIONS[move],
            )
        ]

    def apply_move_decided(
        self,
        state: _player.PlayerState,
        event: _player.MoveDecided,
        ctx: _az.PageContext,
    ) -> None:
        memory = self.logic.remember(memory_of(state), decision_of(event))
        state.decisions = memory.decisions
        state.hands_seen = memory.hands_seen
