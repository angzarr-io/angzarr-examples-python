"""OutputProjector — renders game events into a human-readable display.

A projector folds a domain's events into a read model. The rendered *display* is
presentation, not contract: it is accumulated in the projector's own sink
(``lines``), NOT in the projection proto. finish() returns the framework
Projection envelope; the read-model payload stays minimal. Observers (and these
tests) read the rendered lines from the projector instance.

Only the player-funds lines (register / deposit / withdraw) are rendered in this
slice; the remaining event handlers are no-ops (an unfamiliar event must not
crash the display).

Implements the generated ``OutputProjectorHandler`` seam.
"""

from __future__ import annotations

from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.output_projector_angzarr import (
    OutputProjectorHandler,
)


def _money(currency) -> str:
    return f"${currency.amount:,}"


def _chips(n: int) -> str:
    return f"${n:,}"


class OutputProjector:
    """Implements ``OutputProjectorHandler`` (player-funds display slice).

    ``lines`` is the rendered display sink — presentation, kept out of the
    contract proto.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.names: dict[str, str] = {}  # player_root_hex -> display name

    def _name(self, player_root: bytes) -> str:
        """A player's display name, or a short fallback for an unknown root."""
        return self.names.get(player_root.hex(), f"Player {player_root.hex()[:6]}")

    # --- rendered events (append to the display sink) ---

    def player_registered(self, projection, event) -> None:
        self.lines.append(f"{event.display_name} registered ({event.email})")

    def funds_deposited(self, projection, event) -> None:
        self.lines.append(
            f"Deposited {_money(event.amount)}, balance: {_money(event.new_balance)}"
        )

    def funds_withdrawn(self, projection, event) -> None:
        self.lines.append(
            f"Withdrew {_money(event.amount)}, balance: {_money(event.new_balance)}"
        )

    # --- finish: the read-model envelope (display lives in the sink, not here) ---

    def finish(self, projection, events: _t.EventBook) -> _t.Projection:
        return _t.Projection(projector="OutputProjector")

    # --- events not rendered in this slice (must not crash the display) ---

    def funds_reserved(self, projection, event) -> None:
        self.lines.append(f"Reserved {_money(event.amount)}")

    def table_created(self, projection, event) -> None:
        self.lines.append(
            f"{event.table_name} {_pt.GameVariant.Name(event.game_variant)} "
            f"{_chips(event.small_blind)}/{_chips(event.big_blind)} "
            f"{_chips(event.min_buy_in)} - {_chips(event.max_buy_in)}"
        )

    def player_joined(self, projection, event) -> None:
        self.lines.append(
            f"{self._name(event.player_root)} joined at seat {event.seat_position} "
            f"{_chips(event.buy_in_amount)}"
        )

    def player_left(self, projection, event) -> None:
        self.lines.append(
            f"{self._name(event.player_root)} left {_chips(event.chips_cashed_out)}"
        )

    def hand_started(self, projection, event) -> None:
        seated = " ".join(self._name(p.player_root) for p in event.active_players)
        self.lines.append(
            f"HAND #{event.hand_number} Dealer: Seat {event.dealer_position} {seated}"
        )

    def hand_complete(self, projection, event) -> None:
        for w in event.winners:
            self.lines.append(f"{self._name(w.player_root)} wins {_chips(w.amount)}")

    # --- events not rendered in this slice (must not crash the display) ---

    def cards_dealt(self, projection, event) -> None: ...
    def blind_posted(self, projection, event) -> None: ...
    def action_taken(self, projection, event) -> None: ...
    def community_cards_dealt(self, projection, event) -> None: ...
    def cards_revealed(self, projection, event) -> None: ...
    def cards_mucked(self, projection, event) -> None: ...
    def showdown_started(self, projection, event) -> None: ...
    def pot_awarded(self, projection, event) -> None: ...
    def player_timed_out(self, projection, event) -> None: ...
    def player_seated(self, projection, event) -> None: ...
    def hand_ended(self, projection, event) -> None: ...


_: OutputProjectorHandler = OutputProjector()
