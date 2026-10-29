"""How the player chooses a move: the seam a learned model replaces.

A :class:`Strategy` sees only the turn and answers a move. Tonight's is
:class:`BasicStrategy`, a fixed rule table; a PyTorch model is a Strategy
whose ``choose`` runs the model. Plain Python, as :mod:`.domain` is.
"""

from __future__ import annotations

from typing import Protocol

from .domain import Move, Turn


class Strategy(Protocol):
    def choose(self, turn: Turn) -> Move:
        """The move for ``turn``. May answer DOUBLE_DOWN only when the turn
        says ``can_double``."""
        ...


class BasicStrategy:
    """A simplified basic strategy, by the hand's total (AHR-2) and the
    dealer's up-card (Ace counts 11, a face card 10):

    - hard 10 or 11: double down when the turn may double, else hit;
    - hard 11 or less otherwise: hit;
    - hard 12: stand against a dealer 4 to 6, else hit;
    - hard 13 to 16: stand against a dealer 2 to 6, else hit;
    - hard 17 or more: stand;
    - soft 17 or less: hit; soft 18 or more: stand (no soft doubles).
    """

    def choose(self, turn: Turn) -> Move:
        raise NotImplementedError("red: BasicStrategy.choose")
