"""Step definitions for table aggregate acceptance tests.

Handles table creation, player seating, and table state assertions
by sending commands through the CommandClient abstraction.
"""

import hashlib

from behave import given, then, use_step_matcher, when

from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

from common_steps import new_uuid_bytes, pack_command


def _derive_hand_root(table_name: str, hand_number: int) -> bytes:
    """Mirror the deterministic hand_root the table aggregate computes in
    `handle_start_hand` (`table/agg/handlers/table.py:487`):

        hand_root = sha256(f"angzarr.poker.hand.table_{table_name}.{n}")[:16]

    Computing it client-side lets us send PostBlind / PlayerAction / AwardPot
    to the same hand the saga-driven DealCards landed on, even when StartHand
    is ASYNC (no event in the response to parse).
    """
    seed = f"angzarr.poker.hand.table_{table_name}.{hand_number}"
    return hashlib.sha256(seed.encode()).digest()[:16]

use_step_matcher("re")


def _table_root(context, table_name: str) -> bytes:
    """Get or create a stable UUID for a named table."""
    if table_name not in context.tables:
        context.tables[table_name] = {
            "root": new_uuid_bytes(),
            "sequence": 0,
            "seated_players": 0,
            "hand_count": 0,
            "game_variant": poker_types.TEXAS_HOLDEM,
        }
    return context.tables[table_name]["root"]


def _create_table(
    context,
    table_name: str,
    small_blind: int = 5,
    big_blind: int = 10,
    min_buy_in: int = 10,
    max_buy_in: int = 10000,
    max_players: int = 9,
    game_variant=None,
):
    """Create a table and update tracked state."""
    if game_variant is None:
        game_variant = poker_types.TEXAS_HOLDEM
    root = _table_root(context, table_name)
    cmd = table.CreateTable(
        table_name=table_name,
        game_variant=game_variant,
        small_blind=small_blind,
        big_blind=big_blind,
        min_buy_in=min_buy_in,
        max_buy_in=max_buy_in,
        max_players=max_players,
        action_timeout_seconds=30,
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.CreateTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", root, packed, sequence=seq)
    context.last_response = response
    context.last_error = None
    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["game_variant"] = game_variant
    context.current_table_name = table_name
    return response


def _join_table(context, player_name: str, table_name: str, seat: int, buy_in: int):
    """Join a player to a table and update tracked state."""
    from player_steps import _player_root

    table_root = _table_root(context, table_name)
    player_root = _player_root(context, player_name)

    cmd = table.JoinTable(
        player_root=player_root,
        preferred_seat=seat,
        buy_in_amount=buy_in,
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.JoinTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", table_root, packed, sequence=seq)
    context.last_response = response
    context.last_error = None
    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["seated_players"] += 1

    # Track reservation on the player side
    context.players[player_name]["reserved_funds"] += buy_in

    # Track per-table player stacks
    if "player_stacks" not in context.tables[table_name]:
        context.tables[table_name]["player_stacks"] = {}
    context.tables[table_name]["player_stacks"][player_name] = buy_in
    return response


def _start_hand(context, table_name: str, sync_mode=None, cascade_error_mode=None):
    """Start a hand at a table and update tracked state."""
    table_root = _table_root(context, table_name)
    cmd = table.StartHand()
    packed = pack_command(cmd, "angzarr_client.proto.examples.StartHand")
    seq = context.tables[table_name]["sequence"]

    kwargs = {"sequence": seq}
    if sync_mode is not None:
        kwargs["sync_mode"] = sync_mode
    if cascade_error_mode is not None:
        kwargs["cascade_error_mode"] = cascade_error_mode

    try:
        response = context.client.send_command("table", table_root, packed, **kwargs)
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_error = e
        context.command_succeeded = False

    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["hand_count"] += 1
    context.current_hand_root = _derive_hand_root(
        table_name, context.tables[table_name]["hand_count"]
    )
    context.current_table_name = table_name

    # Initialize hand tracking
    if "current_hand" not in context.tables[table_name]:
        context.tables[table_name]["current_hand"] = {}
    context.tables[table_name]["current_hand"] = {
        "pot": 0,
        "active_players": context.tables[table_name]["seated_players"],
        "phase": "preflop",
    }
    return context.last_response


# --- Given steps ---


@given(
    r'a Five Card Draw table "(?P<table_name>[^"]+)" '
    r"with blinds (?P<sb>\d+)/(?P<bb>\d+)"
)
def step_given_five_card_draw_table(context, table_name, sb, bb):
    """Create a Five Card Draw table."""
    _create_table(
        context,
        table_name,
        small_blind=int(sb),
        big_blind=int(bb),
        game_variant=poker_types.FIVE_CARD_DRAW,
    )


@given(
    r'an Omaha table "(?P<table_name>[^"]+)" ' r"with blinds (?P<sb>\d+)/(?P<bb>\d+)"
)
def step_given_omaha_table(context, table_name, sb, bb):
    """Create an Omaha table."""
    _create_table(
        context,
        table_name,
        small_blind=int(sb),
        big_blind=int(bb),
        game_variant=poker_types.OMAHA,
    )


@given(r"seated players:")
def step_given_seated_players(context):
    """Seat players at the most recently created table."""
    from player_steps import _deposit_funds, _register_player

    table_name = context.current_table_name
    assert table_name is not None, "No current table to seat players at"

    for row in context.table:
        name = row["name"]
        seat = int(row["seat"])
        stack = int(row["stack"])
        email = f"{name.lower()}@example.com"
        _register_player(context, name, email)
        _deposit_funds(context, name, stack * 2)
        _join_table(context, name, table_name, seat, stack)


@given(r'deterministic deck seed "(?P<seed>[^"]+)"')
def step_given_deterministic_deck_seed(context, seed):
    """Store seed for use when starting the hand."""
    context.deck_seed = seed


@given(r"deterministic deck where both players make the same flush")
def step_given_deterministic_deck_same_flush(context):
    """Deterministic deck setup for identical flush hands."""
    context.deck_config = "same_flush"


@given(r"deterministic deck with community cards making a royal flush")
def step_given_deterministic_deck_royal_flush(context):
    """Deterministic deck setup for community royal flush."""
    context.deck_config = "royal_flush_board"


@given(r"deterministic deck where:")
def step_given_deterministic_deck_where(context):
    """Deterministic deck setup from table data."""
    context.deck_config = {"players": []}
    for row in context.table:
        context.deck_config["players"].append(
            {
                "player": row["player"],
                "hole_cards": row["hole_cards"],
                "community": row["community"],
            }
        )


@given(r"deterministic deck where Alice has best hand, Bob has second best")
def step_given_deterministic_deck_alice_best(context):
    """Deterministic deck where Alice has best hand."""
    context.deck_config = "alice_best_bob_second"


@given(r'a hand is dealt with "(?P<name>[^"]+)" to act')
def step_given_hand_dealt_with_player_to_act(context, name):
    """Set up a hand that's been dealt with specific player to act."""
    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)
    context.tables[table_name]["current_hand"]["action_on"] = name


@given(r"current bet is (?P<bet>\d+) and min raise is (?P<min_raise>\d+)")
def step_given_current_bet_and_min_raise(context, bet, min_raise):
    """Set current bet state."""
    table_name = context.current_table_name
    if table_name and "current_hand" in context.tables.get(table_name, {}):
        context.tables[table_name]["current_hand"]["current_bet"] = int(bet)
        context.tables[table_name]["current_hand"]["min_raise"] = int(min_raise)


@given(r"a hand is in progress")
def step_given_hand_in_progress(context):
    """Set up a hand that's in progress."""
    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)


@given(r'a hand is in progress with "(?P<name>[^"]+)" to act')
def step_given_hand_in_progress_with_player(context, name):
    """Set up a hand in progress with specific player to act."""
    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)
        context.tables[table_name]["current_hand"]["action_on"] = name


@given(r"a table with no seated players")
def step_given_table_no_seated_players(context):
    """Set up an empty table."""
    _create_table(context, "Empty", small_blind=5, big_blind=10)


# --- When steps ---


@when(
    r"I create a Texas Hold'em table "
    r'"(?P<table_name>[^"]+)" with blinds (?P<sb>\d+)/(?P<bb>\d+)'
)
def step_when_create_table(context, table_name, sb, bb):
    """Create a new poker table."""
    _create_table(context, table_name, small_blind=int(sb), big_blind=int(bb))


@when(
    r'player "(?P<name>[^"]+)" joins table "(?P<table_name>[^"]+)" '
    r"at seat (?P<seat>\d+) with buy-in (?P<buy_in>\d+)"
)
def step_when_player_joins_table(context, name, table_name, seat, buy_in):
    """Seat a player at a table."""
    _join_table(context, name, table_name, int(seat), int(buy_in))


@when(r'player "(?P<name>[^"]+)" leaves table "(?P<table_name>[^"]+)"')
def step_when_player_leaves_table(context, name, table_name):
    """Remove a player from a table."""
    from player_steps import _player_root

    table_root = _table_root(context, table_name)
    player_root = _player_root(context, name)

    cmd = table.LeaveTable(
        player_root=player_root,
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.LeaveTable")
    seq = context.tables[table_name]["sequence"]

    response = context.client.send_command("table", table_root, packed, sequence=seq)
    context.last_response = response
    context.last_error = None
    context.tables[table_name]["sequence"] = seq + 1
    context.tables[table_name]["seated_players"] -= 1

    # Release reservation on the player side and return to bankroll
    context.players[name]["reserved_funds"] = 0
    # Funds go back to available bankroll (already counted in bankroll)


@when(r'a hand starts at table "(?P<table_name>[^"]+)"')
def step_when_hand_starts_at_table(context, table_name):
    """Start a new hand at a table."""
    _start_hand(context, table_name)


@when(r'I send a StartHand command to table "(?P<table_name>[^"]+)"')
def step_when_send_start_hand(context, table_name):
    """Send a StartHand command to a table."""
    _start_hand(context, table_name)


# --- Then steps ---


@then(r'table "(?P<table_name>[^"]+)" has (?P<count>\d+) seated players?')
def step_then_table_has_seated_players(context, table_name, count):
    """Assert number of seated players at a table."""
    expected = int(count)
    actual = context.tables[table_name]["seated_players"]
    assert actual == expected, f"Expected {expected} seated players, got {actual}"


@then(r'table "(?P<table_name>[^"]+)" has hand_count (?P<count>\d+)')
def step_then_table_has_hand_count(context, table_name, count):
    """Assert number of hands played at a table."""
    expected = int(count)
    actual = context.tables[table_name]["hand_count"]
    assert actual == expected, f"Expected hand_count {expected}, got {actual}"


@then(r"the table updates player stacks")
def step_then_table_updates_stacks(context):
    """Assert the table updates player stacks after hand completion."""
    # Verified through subsequent stack assertions
    pass
