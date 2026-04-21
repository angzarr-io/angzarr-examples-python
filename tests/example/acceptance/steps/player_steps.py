"""Step definitions for player aggregate acceptance tests.

Handles player registration, deposits, and balance assertions by
sending commands through the CommandClient abstraction.
"""

from behave import given, then, use_step_matcher, when

from angzarr_client.proto.angzarr import SyncMode
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from common_steps import new_uuid_bytes, pack_command, send_with_retry

use_step_matcher("re")


def _player_root(context, name: str) -> bytes:
    """Get or create a stable UUID for a named player."""
    if name not in context.players:
        context.players[name] = {
            "root": new_uuid_bytes(),
            "sequence": 0,
            "bankroll": 0,
            "reserved_funds": 0,
        }
    return context.players[name]["root"]


def _register_player(context, name: str, email: str):
    """Register a player and update tracked state.

    Wrapped in send_with_retry so a transient UNAVAILABLE (player
    coordinator just rolled, channel still draining) doesn't fail the
    very-first scenario step.
    """
    root = _player_root(context, name)
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.HUMAN,
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.RegisterPlayer")
    seq = context.players[name]["sequence"]

    response = send_with_retry(context, "player", root, packed, seq)
    context.last_response = response
    context.last_error = None
    context.players[name]["sequence"] = seq + 1
    return response


def _deposit_funds(context, name: str, amount: int, sync_mode=None):
    """Deposit funds for a player and update tracked state.

    DepositFunds is a financial command — default to SYNC_MODE_SIMPLE so the
    aggregate write is durable before the test moves on. Game-state commands
    use the GrpcClient default (ASYNC).
    """
    root = _player_root(context, name)
    cmd = player.DepositFunds(
        amount=poker_types.Currency(amount=amount, currency_code="USD"),
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.DepositFunds")
    seq = context.players[name]["sequence"]

    effective_sync = sync_mode if sync_mode is not None else SyncMode.SYNC_MODE_SIMPLE
    response = send_with_retry(
        context, "player", root, packed, seq, sync_mode=effective_sync
    )
    context.last_response = response
    context.last_error = None
    context.players[name]["sequence"] = seq + 1
    context.players[name]["bankroll"] += amount
    return response


# --- Given steps ---


@given(r"registered players with bankroll:")
def step_given_registered_players_with_bankroll(context):
    """Register multiple players and deposit funds from a data table."""
    for row in context.table:
        name = row["name"]
        bankroll = int(row["bankroll"])
        email = f"{name.lower()}@example.com"
        _register_player(context, name, email)
        if bankroll > 0:
            _deposit_funds(context, name, bankroll)


@given(r'a table "(?P<table_name>[^"]+)" with seated players:')
def step_given_table_with_seated_players(context, table_name):
    """Set up a table with pre-seated players.

    Creates the table and joins all players listed in the data table.
    """
    from table_steps import _create_table, _join_table

    # First register and fund all players
    for row in context.table:
        name = row["name"]
        stack = int(row["stack"])
        email = f"{name.lower()}@example.com"
        _register_player(context, name, email)
        _deposit_funds(context, name, stack * 2)

    # Create the table
    _create_table(context, table_name, small_blind=5, big_blind=10)

    # Track current table name for later use
    context.current_table_name = table_name

    # Seat each player
    for row in context.table:
        name = row["name"]
        seat = int(row["seat"])
        stack = int(row["stack"])
        _join_table(context, name, table_name, seat, stack)


@given(r'a table "(?P<table_name>[^"]+)" with (?P<count>\d+) seated players?')
def step_given_table_with_n_seated_players(context, table_name, count):
    """Set up a table with N default players."""
    from table_steps import _create_table, _join_table

    count = int(count)
    _create_table(context, table_name, small_blind=5, big_blind=10)
    context.current_table_name = table_name

    for i in range(count):
        name = f"Player{i + 1}"
        email = f"{name.lower()}@example.com"
        _register_player(context, name, email)
        _deposit_funds(context, name, 1000)
        _join_table(context, name, table_name, i, 500)


@given(r'a table "(?P<table_name>[^"]+)" with an active hand')
def step_given_table_with_active_hand(context, table_name):
    """Set up a table with an active hand."""
    step_given_table_with_n_seated_players(context, table_name, "2")


@given(
    r'player "(?P<name>[^"]+)" has bankroll '
    r"(?P<bankroll>\d+) with (?P<reserved>\d+) reserved"
)
def step_given_player_has_bankroll_with_reserved(context, name, bankroll, reserved):
    """Pre-condition: player has given financial state."""
    _player_root(context, name)
    context.players[name]["bankroll"] = int(bankroll)
    context.players[name]["reserved_funds"] = int(reserved)


@given(r"(?P<count>\d+) registered players")
def step_given_n_registered_players(context, count):
    """Register N players for performance testing."""
    context.test_players = []
    for i in range(int(count)):
        name = f"Player{i + 1}"
        email = f"{name.lower()}@example.com"
        _register_player(context, name, email)
        context.test_players.append(name)


# --- When steps ---


@when(r'I register player "(?P<name>[^"]+)" with email "(?P<email>[^"]+)"')
def step_when_register_player(context, name, email):
    """Register a new player."""
    _register_player(context, name, email)


@when(r'I deposit (?P<amount>\d+) chips to player "(?P<name>[^"]+)"')
def step_when_deposit_funds(context, amount, name):
    """Deposit chips into a player's bankroll."""
    _deposit_funds(context, name, int(amount))


@when(
    r'I deposit (?P<amount>\d+) chips to player "(?P<name>[^"]+)" '
    r"with sync_mode (?P<mode>\w+)"
)
def step_when_deposit_with_sync_mode(context, amount, name, mode):
    """Deposit chips with specified sync mode."""
    from sync_steps import parse_sync_mode

    import time

    sync_mode = parse_sync_mode(mode)
    context.last_sync_mode = sync_mode
    context.command_start_time = time.time()
    _deposit_funds(context, name, int(amount), sync_mode=sync_mode)
    context.command_end_time = time.time()
    context.command_succeeded = context.last_error is None


@when(r"I deposit chips to all players with sync_mode (?P<mode>\w+)")
def step_when_deposit_to_all_players(context, mode):
    """Deposit chips to all test players for performance testing."""
    import time

    from sync_steps import parse_sync_mode

    sync_mode = parse_sync_mode(mode)
    context.last_sync_mode = sync_mode
    context.deposit_times = []

    for player_name in getattr(context, "test_players", []):
        start = time.time()
        _deposit_funds(context, player_name, 100, sync_mode=sync_mode)
        end = time.time()
        context.deposit_times.append((end - start) * 1000)


# --- Then steps ---


@then(r'player "(?P<name>[^"]+)" has bankroll (?P<amount>\d+)')
def step_then_player_has_bankroll(context, name, amount):
    """Assert player's tracked bankroll."""
    expected = int(amount)
    actual = context.players[name]["bankroll"]
    assert actual == expected, f"Expected bankroll {expected}, got {actual}"


@then(r'player "(?P<name>[^"]+)" has available balance (?P<amount>\d+)')
def step_then_player_has_available_balance(context, name, amount):
    """Assert player's available balance (bankroll - reserved)."""
    expected = int(amount)
    info = context.players[name]
    actual = info["bankroll"] - info["reserved_funds"]
    assert actual == expected, f"Expected available balance {expected}, got {actual}"


@then(r'player "(?P<name>[^"]+)" has reserved funds (?P<amount>\d+)')
def step_then_player_has_reserved_funds(context, name, amount):
    """Assert player's reserved funds."""
    expected = int(amount)
    actual = context.players[name]["reserved_funds"]
    assert actual == expected, f"Expected reserved funds {expected}, got {actual}"
