"""PlayerLogicImpl: the player's logic. Its strategy decides each turn's
move (never a double the turn does not allow), the decision is the turn it
answers with that move (a list of the one event: angzarr decision 14.75),
and the fold counts the decisions made and the hands they were on. A move
the table refused comes back as RecordMoveRefused (decision 14.76), which
the player records and which changes nothing it counts.
"""

from __future__ import annotations

import dataclasses

from angzarr_player.strategy import BasicStrategy, Strategy

from ._gen.domain import (
    CommandContext,
    DecideMove,
    DecideMoveRefused,
    MoveAction,
    MoveDecided,
    MoveRefused,
    PlayerState,
    RecordMoveRefused,
)
from ._gen.logic import PlayerLogic


class PlayerLogicImpl(PlayerLogic):
    def __init__(self, strategy: Strategy | None = None) -> None:
        self.strategy = strategy if strategy is not None else BasicStrategy()

    def decide_move(
        self, cmd: DecideMove, state: PlayerState, ctx: CommandContext
    ) -> list[MoveDecided] | DecideMoveRefused:
        move = self.strategy.choose(cmd)
        if move is MoveAction.DOUBLE_DOWN and not cmd.can_double:
            move = MoveAction.HIT
        return [MoveDecided.from_command(cmd, action=move)]

    def record_move_refused(
        self, fact: RecordMoveRefused, state: PlayerState, ctx: CommandContext
    ) -> list[MoveRefused]:
        return [MoveRefused(seat=fact.seat, action=fact.action, reason=fact.reason)]

    def apply_move_decided(self, state: PlayerState, event: MoveDecided) -> PlayerState:
        # A hand is seen once: on its first decision, taken on two cards.
        return dataclasses.replace(
            state,
            decisions=state.decisions + 1,
            hands_seen=state.hands_seen + (1 if len(event.cards) == 2 else 0),
        )

    def apply_move_refused(self, state: PlayerState, event: MoveRefused) -> PlayerState:
        return state
