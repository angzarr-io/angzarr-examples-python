"""PlayerLogicImpl: the player's logic. Its strategy decides each turn's
move (never a double the turn does not allow), the decision is the turn it
answers with that move, and the fold counts the decisions made and the
hands they were on.
"""

from __future__ import annotations

import dataclasses

from angzarr_player.domain import (
    CommandContext,
    DecideMove,
    MoveAction,
    MoveDecided,
    PlayerState,
)
from angzarr_player.logic import PlayerLogic
from angzarr_player.strategy import BasicStrategy, Strategy


class PlayerLogicImpl(PlayerLogic):
    def __init__(self, strategy: Strategy | None = None) -> None:
        self.strategy = strategy if strategy is not None else BasicStrategy()

    def decide_move(
        self, cmd: DecideMove, state: PlayerState, ctx: CommandContext
    ) -> MoveDecided:
        move = self.strategy.choose(cmd)
        if move is MoveAction.DOUBLE_DOWN and not cmd.can_double:
            move = MoveAction.HIT
        return MoveDecided.from_command(cmd, action=move)

    def apply_move_decided(self, state: PlayerState, event: MoveDecided) -> PlayerState:
        # A hand is seen once: on its first decision, taken on two cards.
        return dataclasses.replace(
            state,
            decisions=state.decisions + 1,
            hands_seen=state.hands_seen + (1 if len(event.cards) == 2 else 0),
        )
