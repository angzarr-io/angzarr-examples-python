"""Table state rebuild helper for the reservation PM.

Minimal fold over Table-domain events. Used to pre-validate buy-in and
rebuy flows against live table state queried synchronously via
``QueryClient``.
"""

from dataclasses import dataclass, field

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
    seats: dict[int, bytes] = field(default_factory=dict)

    def find_seat_by_player(self, player_root: bytes) -> int | None:
        for pos, root in self.seats.items():
            if root == player_root:
                return pos
        return None


def apply_table_created(state: TableStateHelper, event: table.TableCreated) -> None:
    state.table_id = f"table_{event.table_name}"
    state.table_name = event.table_name
    state.min_buy_in = event.min_buy_in
    state.max_buy_in = event.max_buy_in
    state.max_players = event.max_players


def apply_player_joined(state: TableStateHelper, event: table.PlayerJoined) -> None:
    state.seats[event.seat_position] = event.player_root


def apply_player_seated(state: TableStateHelper, event: buy_in.PlayerSeated) -> None:
    state.seats[event.seat_position] = event.player_root


def apply_player_left(state: TableStateHelper, event: table.PlayerLeft) -> None:
    state.seats.pop(event.seat_position, None)


def table_state_rebuild(prior_state: TableStateHelper, event) -> TableStateHelper:
    if isinstance(event, table.TableCreated):
        apply_table_created(prior_state, event)
    elif isinstance(event, table.PlayerJoined):
        apply_player_joined(prior_state, event)
    elif isinstance(event, buy_in.PlayerSeated):
        apply_player_seated(prior_state, event)
    elif isinstance(event, table.PlayerLeft):
        apply_player_left(prior_state, event)
    return prior_state


def table_state_from_event_book(event_book) -> TableStateHelper:
    state = TableStateHelper()
    _type_map = {
        "angzarr_client.proto.examples.TableCreated": table.TableCreated,
        "angzarr_client.proto.examples.PlayerJoined": table.PlayerJoined,
        "angzarr_client.proto.examples.PlayerSeated": buy_in.PlayerSeated,
        "angzarr_client.proto.examples.PlayerLeft": table.PlayerLeft,
    }
    for page in event_book.pages:
        if not page.HasField("event"):
            continue
        type_name = page.event.type_url.split("/")[-1]
        proto_cls = _type_map.get(type_name)
        if proto_cls is None:
            continue
        evt = proto_cls()
        page.event.Unpack(evt)
        table_state_rebuild(state, evt)
    return state
