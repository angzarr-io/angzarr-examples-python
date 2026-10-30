"""PlayerLogicImpl: the implementation of ``PlayerLogic``, written once by
``angzarr scaffold python`` and yours from then on: ``--missing`` adds the
methods it lacks, each a TODO.
"""

from __future__ import annotations

from angzarr_player.domain import (
    CommandContext,
    DecideMove,
    MoveDecided,
    PlayerState,
)
from angzarr_player.logic import PlayerLogic


class PlayerLogicImpl(PlayerLogic):
    def decide_move(
        self, cmd: DecideMove, state: PlayerState, ctx: CommandContext
    ) -> MoveDecided:
        raise NotImplementedError  # TODO: decide DecideMove

    def apply_move_decided(self, state: PlayerState, event: MoveDecided) -> PlayerState:
        raise NotImplementedError  # TODO: fold MoveDecided into the state
