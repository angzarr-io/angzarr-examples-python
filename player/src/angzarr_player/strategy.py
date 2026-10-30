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
    dealer's up-card:

    - hard 10 or 11: double down when the turn may double, else hit;
    - hard 11 or less otherwise: hit;
    - hard 12: stand against a dealer 4 to 6, else hit;
    - hard 13 to 16: stand against a dealer 2 to 6, else hit;
    - hard 17 or more: stand;
    - soft 17 or less: hit; soft 18 or more: stand (no soft doubles).
    """

    def choose(self, turn: DecideMove) -> MoveAction:
        # Only a dealer 2 to 6 changes a move, so the rank is compared as it
        # is (an Ace, 1, and a face card, 11 to 13, both fall outside; so
        # does no up-card at all, 0).
        up = turn.dealer_up.rank if turn.dealer_up is not None else 0
        total = turn.total
        if turn.soft:
            return MoveAction.STAND if total >= 18 else MoveAction.HIT
        if total in (10, 11):
            return MoveAction.DOUBLE_DOWN if turn.can_double else MoveAction.HIT
        if total <= 11:
            return MoveAction.HIT
        if total == 12:
            return MoveAction.STAND if 4 <= up <= 6 else MoveAction.HIT
        if total <= 16:
            return MoveAction.STAND if 2 <= up <= 6 else MoveAction.HIT
        return MoveAction.STAND
