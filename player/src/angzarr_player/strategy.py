"""How the player chooses a move: the seam a learned model replaces.

A :class:`Strategy` sees only the turn (the ``DecideMove`` the table sent)
and answers a move. Tonight's is :class:`BasicStrategy`, a fixed rule
table; a PyTorch model is a Strategy whose ``choose`` runs the model. Plain
Python over :mod:`.domain`'s types.
"""

from __future__ import annotations

from typing import Protocol

from .domain import DecideMove, MoveAction


class Strategy(Protocol):
    def choose(self, turn: DecideMove) -> MoveAction:
        """The move for ``turn``. May answer DOUBLE_DOWN only when the turn
        says ``can_double``."""
        ...


class BasicStrategy:
    """A simplified basic strategy, by the hand's total (AHR-2) and the
    dealer's up-card."""

    def choose(self, turn: DecideMove) -> MoveAction:
        raise NotImplementedError
