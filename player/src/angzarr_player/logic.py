"""PlayerLogic: the player domain's logic, for
``io.angzarr.examples.v1.PlayerState``. Written once by ``angzarr scaffold
python`` and yours from then on: ``--missing`` adds the methods it lacks. It
takes and returns the domain's plain types (:mod:`.domain`), each decision its
``CommandContext`` too, raising ``Rejection`` to refuse its command (or ``Bug``
for a defect), and imports nothing of angzarr directly; the generated dispatch
(``_gen/.../player_aggregate_angzarr.py``) calls it.
"""

from __future__ import annotations

from typing import Protocol

from angzarr_player.domain import (
    CommandContext,
    DecideMove,
    MoveDecided,
    PlayerState,
)


class PlayerLogic(Protocol):
    def decide_move(
        self, cmd: DecideMove, state: PlayerState, ctx: CommandContext
    ) -> MoveDecided: ...

    def apply_move_decided(
        self, state: PlayerState, event: MoveDecided
    ) -> PlayerState: ...
