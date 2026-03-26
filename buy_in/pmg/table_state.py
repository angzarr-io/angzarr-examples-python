"""Table state router for BuyIn PM destination state rebuilding.

This module defines a StateRouter that automatically rebuilds TableStateHelper
from EventBooks, eliminating manual rebuild_table_state() boilerplate.

Usage in PM:
    class BuyInPM(ProcessManager[BuyInState]):
        _destination_routers = {
            "table": table_state_router,
        }

        @handles(BuyInRequested, input_domain="player")
        def handle_buy_in(self, event, destinations: dict[str, TableStateHelper], root):
            table_state = destinations["table"]  # Already rebuilt!
"""

from dataclasses import dataclass, field

from angzarr_client import StateRouter
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import table_pb2 as table


@dataclass
class TableStateHelper:
    """Minimal table state for PM validation."""

    table_id: str = ""
    table_name: str = ""
    min_buy_in: int = 0
    max_buy_in: int = 0
    max_players: int = 0
    seats: dict[int, bytes] = field(default_factory=dict)  # position -> player_root

    def find_seat_by_player(self, player_root: bytes) -> int | None:
        """Find seat position for a player."""
        for pos, root in self.seats.items():
            if root == player_root:
                return pos
        return None

    def next_available_seat(self) -> int | None:
        """Find next available seat."""
        for i in range(self.max_players):
            if i not in self.seats:
                return i
        return None


# --- State appliers (pure functions) ---


def apply_table_created(state: TableStateHelper, event: table.TableCreated) -> None:
    """Apply TableCreated event."""
    state.table_id = f"table_{event.table_name}"
    state.table_name = event.table_name
    state.min_buy_in = event.min_buy_in
    state.max_buy_in = event.max_buy_in
    state.max_players = event.max_players


def apply_player_joined(state: TableStateHelper, event: table.PlayerJoined) -> None:
    """Apply PlayerJoined event."""
    state.seats[event.seat_position] = event.player_root


def apply_player_seated(state: TableStateHelper, event: buy_in.PlayerSeated) -> None:
    """Apply PlayerSeated event (from buy-in flow)."""
    state.seats[event.seat_position] = event.player_root


def apply_player_left(state: TableStateHelper, event: table.PlayerLeft) -> None:
    """Apply PlayerLeft event."""
    state.seats.pop(event.seat_position, None)


# --- StateRouter configuration ---

table_state_router: StateRouter[TableStateHelper] = (
    StateRouter(TableStateHelper)
    .on(table.TableCreated, apply_table_created)
    .on(table.PlayerJoined, apply_player_joined)
    .on(buy_in.PlayerSeated, apply_player_seated)
    .on(table.PlayerLeft, apply_player_left)
)
