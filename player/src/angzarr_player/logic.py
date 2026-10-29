"""The player's logic, in plain Python: what a seat does on its turn, and what
the player remembers of the moves it has made.

Nothing here imports angzarr_client or the generated code. The adapter
(:mod:`angzarr_player.adapter`) maps the framework's messages onto these
types and back, so a change of harness or scaffold leaves this module alone,
and so does a change of decision maker: :class:`Bot` asks a
:class:`~angzarr_player.strategy.Strategy` (rule-based tonight, a learned
model later).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .domain import Decision, Memory, Move, Turn
from .strategy import BasicStrategy, Strategy


class PlayerLogic(Protocol):
    """The player's logic, called by the adapter."""

    def decide(self, turn: Turn, memory: Memory) -> Move:
        """The move for ``turn``. Never DOUBLE_DOWN unless the turn says
        ``can_double``."""
        ...

    def remember(self, memory: Memory, decision: Decision) -> Memory:
        """``memory`` after ``decision``."""
        ...


@dataclass
class Bot:
    """The player's logic: its strategy decides, and it counts what it has
    done."""

    strategy: Strategy = field(default_factory=BasicStrategy)

    def decide(self, turn: Turn, memory: Memory) -> Move:
        move = self.strategy.choose(turn)
        if move is Move.DOUBLE_DOWN and not turn.can_double:
            return Move.HIT
        return move

    def remember(self, memory: Memory, decision: Decision) -> Memory:
        return Memory(
            decisions=memory.decisions + 1,
            hands_seen=memory.hands_seen + (1 if decision.cards == 2 else 0),
        )
