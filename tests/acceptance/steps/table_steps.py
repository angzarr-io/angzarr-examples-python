"""Step definitions for table aggregate acceptance tests.

Handles table creation, player seating, and table state assertions
by sending commands through the CommandClient abstraction.
"""

from behave import then, use_step_matcher, when

from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

from .common_steps import new_uuid_bytes, pack_command

use_step_matcher("re")


def _table_root(context, table_name: str) -> bytes:
    """Get or create a stable UUID for a named table."""
    if table_name not in context.tables:
        context.tables[table_name] = {
            "root": new_uuid_bytes(),
            "sequence": 0,
            "seated_players": 0,
        }
    return context.tables[table_name]["root"]


def _create_table(
    context,
    table_name: str,
    small_blind: int = 5,
    big_blind: int = 10,
    min_buy_in: int = 200,
    max_buy_in: int = 1000,
    max_players: int = 9,
):
    """Create a table and update tracked state."""
    root = _table_root(context, table_name)
    cmd = table.CreateTable(
        table_name=table_name,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=small_blind,
        big_blind=big_blind,
        min_buy_in=min_buy_in,
        max_buy_in=max_buy_in,
        max_players=max_players,
        action_timeout_seconds=30,
    )
    packed = pack_command(cmd, "examples.CreateTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", root, packed, sequence=seq)
    context.last_response = response
    context.tables[table_name]["sequence"] = seq + 1
    return response


def _join_table(context, player_name: str, table_name: str, seat: int, buy_in: int):
    """Join a player to a table and update tracked state."""
    from .player_steps import _player_root

    table_root = _table_root(context, table_name)
    player_root = _player_root(context, player_name)

    cmd = table.JoinTable(
        player_root=player_root,
        preferred_seat=seat,
        buy_in_amount=buy_in,
    )
    packed = pack_command(cmd, "examples.JoinTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", table_root, packed, sequence=seq)
    context.last_response = response
    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["seated_players"] += 1

    # Track reservation on the player side
    context.players[player_name]["reserved_funds"] += buy_in
    return response


# --- When steps ---


@when(
    r'I create a Texas Hold\'em table "(?P<table_name>[^"]+)" with blinds (?P<sb>\d+)/(?P<bb>\d+)'
)
def step_when_create_table(context, table_name, sb, bb):
    """Create a new poker table."""
    _create_table(context, table_name, small_blind=int(sb), big_blind=int(bb))


@when(
    r'player "(?P<name>[^"]+)" joins table "(?P<table_name>[^"]+)" at seat (?P<seat>\d+) with buy-in (?P<buy_in>\d+)'
)
def step_when_player_joins_table(context, name, table_name, seat, buy_in):
    """Seat a player at a table."""
    _join_table(context, name, table_name, int(seat), int(buy_in))


@when(r'player "(?P<name>[^"]+)" leaves table "(?P<table_name>[^"]+)"')
def step_when_player_leaves_table(context, name, table_name):
    """Remove a player from a table."""
    from .player_steps import _player_root

    table_root = _table_root(context, table_name)
    player_root = _player_root(context, name)

    cmd = table.LeaveTable(
        player_root=player_root,
    )
    packed = pack_command(cmd, "examples.LeaveTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", table_root, packed, sequence=seq)
    context.last_response = response
    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["seated_players"] -= 1

    # Release reservation on the player side
    context.players[name]["reserved_funds"] = 0


# --- Then steps ---


@then(r'table "(?P<table_name>[^"]+)" has (?P<count>\d+) seated players?')
def step_then_table_has_seated_players(context, table_name, count):
    """Assert number of seated players at a table."""
    expected = int(count)
    actual = context.tables[table_name]["seated_players"]
    assert actual == expected, f"Expected {expected} seated players, got {actual}"
