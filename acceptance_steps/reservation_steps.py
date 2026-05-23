"""Step definitions for the reservation domain + player-financial primitives.

Two layers exercised here:

1. Reservation aggregate ``Initiate*`` commands — these emit ``*Requested``
   events that the deployed ``pmg-reservation-pm`` consumes from the
   ``reservation`` topic and fans out to player + table/tournament. Steps
   here send the Initiate* and assert that the reservation aggregate
   accepted (the Requested event is in the response). Downstream PM
   activity is observed indirectly via the next scenario step.

2. Direct player financial primitives — ``ReserveFunds``,
   ``ReleaseFunds``, ``DeductReservedFunds``, ``WithdrawFunds``,
   ``TransferFunds``. Useful for exercising those handler paths
   without needing the full PM chain to complete. All financial
   commands use ``SYNC_MODE_SIMPLE`` per the testing policy in
   ``CLUSTER_TOURNAMENT_E2E.md``.
"""

from behave import then, use_step_matcher, when

from angzarr_client.proto.angzarr.v1.types_pb2 import SyncMode
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in
from angzarr_client.proto.examples.v1 import player_pb2 as player
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import rebuy_pb2 as rebuy
from angzarr_client.proto.examples.v1 import registration_pb2 as registration

from common_steps import new_uuid_bytes, pack_command

use_step_matcher("re")


# ---------------------------------------------------------------------------
# Reservation root tracking
#
# The reservation aggregate is keyed by the cover.root the client picks. We
# allocate one fresh root per (player, flow_kind) pair so the test can issue
# multiple reservations without collisions, and so subsequent assertions can
# look up the response/event book by the same root.
# ---------------------------------------------------------------------------


def _reservation_root(context, player_name: str, kind: str) -> bytes:
    if not hasattr(context, "reservations"):
        context.reservations = {}
    key = f"{player_name}:{kind}"
    if key not in context.reservations:
        context.reservations[key] = {
            "root": new_uuid_bytes(),
            "sequence": 0,
        }
    return context.reservations[key]["root"]


def _send_reservation_command(context, player_name, kind, cmd, type_name):
    root = _reservation_root(context, player_name, kind)
    packed = pack_command(cmd, type_name)
    seq = context.reservations[f"{player_name}:{kind}"]["sequence"]
    try:
        # Initiate* on reservation IS a financial-flow gate — use SIMPLE so
        # the test sees the rejection (e.g. player does not exist) before
        # moving on.
        response = context.client.send_command(
            "reservation",
            root,
            packed,
            sequence=seq,
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False
    context.reservations[f"{player_name}:{kind}"]["sequence"] = seq + 1


# ---------------------------------------------------------------------------
# Reservation — initiation commands (drive the PM chain)
# ---------------------------------------------------------------------------


@when(
    r'player "(?P<player>[^"]+)" initiates tournament registration '
    r'for "(?P<tournament>[^"]+)"'
)
def step_when_initiate_tournament_registration(context, player, tournament):
    """Send InitiateTournamentRegistration → reservation aggregate.

    Triggers RegistrationRequested → pmg-reservation-pm picks it up and
    fans out player.ReserveFunds + tournament.EnrollPlayer.
    """
    from player_steps import _player_root
    from tournament_steps import _tournament_root

    player_root = _player_root(context, player)
    tournament_root = _tournament_root(context, tournament)

    cmd = registration.InitiateTournamentRegistration(
        tournament_root=tournament_root,
        player_root=player_root,
    )
    _send_reservation_command(
        context,
        player,
        "registration",
        cmd,
        "angzarr_client.proto.examples.v1.InitiateTournamentRegistration",
    )


@when(
    r'player "(?P<player>[^"]+)" initiates buy-in to table '
    r'"(?P<table>[^"]+)" at seat (?P<seat>\d+) for (?P<amount>\d+)'
)
def step_when_initiate_buy_in(context, player, table, seat, amount):
    """Send InitiateBuyIn → reservation aggregate.

    Triggers BuyInRequested → PM fans out player.ReserveFunds +
    table.SeatPlayer.
    """
    from player_steps import _player_root
    from table_steps import _table_root

    player_root = _player_root(context, player)
    table_root = _table_root(context, table)
    cmd = buy_in.InitiateBuyIn(
        table_root=table_root,
        seat=int(seat),
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        player_root=player_root,
    )
    _send_reservation_command(
        context,
        player,
        "buy_in",
        cmd,
        "angzarr_client.proto.examples.v1.InitiateBuyIn",
    )


@when(
    r'player "(?P<player>[^"]+)" initiates rebuy on tournament '
    r'"(?P<tournament>[^"]+)" at table "(?P<table>[^"]+)" seat (?P<seat>\d+)'
)
def step_when_initiate_rebuy(context, player, tournament, table, seat):
    """Send InitiateRebuy → reservation aggregate.

    Triggers RebuyRequested → PM fans out player.ReserveFunds +
    tournament.ProcessRebuy. On success PM dispatches table.AddRebuyChips.
    """
    from player_steps import _player_root
    from table_steps import _table_root
    from tournament_steps import _tournament_root

    player_root = _player_root(context, player)
    tournament_root = _tournament_root(context, tournament)
    table_root = _table_root(context, table)
    cmd = rebuy.InitiateRebuy(
        tournament_root=tournament_root,
        table_root=table_root,
        seat=int(seat),
        player_root=player_root,
    )
    _send_reservation_command(
        context,
        player,
        "rebuy",
        cmd,
        "angzarr_client.proto.examples.v1.InitiateRebuy",
    )


def _assert_request_accepted(context):
    """Assert the reservation aggregate accepted the Initiate* — the
    Requested event was emitted (success path). PM behavior beyond this
    is observed by the next scenario step.
    """
    assert context.command_succeeded, (
        f"Reservation Initiate* failed: {context.last_error}"
    )


@then(r"the registration request was accepted")
def step_then_registration_request_accepted(context):
    _assert_request_accepted(context)


@then(r"the buy-in request was accepted")
def step_then_buy_in_request_accepted(context):
    _assert_request_accepted(context)


@then(r"the rebuy request was accepted")
def step_then_rebuy_request_accepted(context):
    _assert_request_accepted(context)


@then(r"the reservation request was rejected")
def step_then_reservation_request_rejected(context):
    """Assert the reservation aggregate rejected the Initiate*."""
    assert not context.command_succeeded, (
        "Expected reservation request to be rejected, but it succeeded"
    )


# ---------------------------------------------------------------------------
# Direct player financial primitives — exercise the handler paths the PM
# chain would normally drive (ReserveFunds, ReleaseFunds, DeductReservedFunds)
# plus standalone Withdraw / Transfer.
# ---------------------------------------------------------------------------


def _send_player_command(context, player_name, cmd, type_name):
    """Send a financial command directly to the player aggregate (SIMPLE)."""
    from player_steps import _player_root

    root = _player_root(context, player_name)
    packed = pack_command(cmd, type_name)
    seq = context.players[player_name]["sequence"]
    try:
        response = context.client.send_command(
            "player",
            root,
            packed,
            sequence=seq,
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False
    context.players[player_name]["sequence"] = seq + 1


def _bet_reservation_key(name: str, amount: int) -> bytes:
    """Derive a stable per-(player, amount) reservation key for the
    business-vocab steps that don't carry an explicit key. Tracks the
    most-recent reserve so a follow-up confirm/release can target it.
    """
    return f"bet:{name}:{amount}".encode()


@when(
    r'player "(?P<name>[^"]+)" reserves (?P<amount>\d+) chips for an '
    r"upcoming bet"
)
def step_when_reserve_funds_for_bet(context, name, amount):
    """Direct ReserveFunds — bypasses the PM, exercises the handler."""
    amt = int(amount)
    key = _bet_reservation_key(name, amt)
    cmd = player.ReserveFunds(
        amount=poker_types.Currency(amount=amt, currency_code="CHIPS"),
        key=key,
    )
    _send_player_command(
        context, name, cmd, "angzarr_client.proto.examples.v1.ReserveFunds"
    )
    if context.command_succeeded:
        context.players[name]["reserved_funds"] += amt
        context.players[name]["last_reservation_key"] = key
        context.players[name]["last_reservation_amount"] = amt


@when(r'player "(?P<name>[^"]+)" releases the reserved (?P<amount>\d+) chips')
def step_when_release_reserved_chips(context, name, amount):
    """Direct ReleaseFunds — returns the reserved bucket to available."""
    amt = int(amount)
    key = context.players[name].get(
        "last_reservation_key", _bet_reservation_key(name, amt)
    )
    cmd = player.ReleaseFunds(key=key)
    _send_player_command(
        context, name, cmd, "angzarr_client.proto.examples.v1.ReleaseFunds"
    )
    if context.command_succeeded:
        context.players[name]["reserved_funds"] -= amt


@when(r'player "(?P<name>[^"]+)" confirms the (?P<amount>\d+)-chip deduction')
def step_when_confirm_chip_deduction(context, name, amount):
    """Direct DeductReservedFunds — settles a reserved amount (bankroll - amt)."""
    amt = int(amount)
    key = context.players[name].get(
        "last_reservation_key", _bet_reservation_key(name, amt)
    )
    cmd = player.DeductReservedFunds(
        amount=poker_types.Currency(amount=amt, currency_code="CHIPS"),
        key=key,
        reservation_id=new_uuid_bytes(),
    )
    _send_player_command(
        context, name, cmd, "angzarr_client.proto.examples.v1.DeductReservedFunds"
    )
    if context.command_succeeded:
        context.players[name]["bankroll"] -= amt
        context.players[name]["reserved_funds"] -= amt


@when(r'player "(?P<name>[^"]+)" withdraws (?P<amount>\d+) chips')
def step_when_withdraw_funds(context, name, amount):
    """Direct WithdrawFunds — debits the available balance."""
    cmd = player.WithdrawFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="USD"),
    )
    _send_player_command(
        context, name, cmd, "angzarr_client.proto.examples.v1.WithdrawFunds"
    )
    if context.command_succeeded:
        context.players[name]["bankroll"] -= int(amount)


@when(
    r'(?P<amount>\d+) chips transfer from player "(?P<src>[^"]+)" to '
    r'player "(?P<dst>[^"]+)" for hand "(?P<hand>[^"]+)"'
)
def step_when_transfer_funds(context, amount, src, dst, hand):
    """Direct TransferFunds — pot-award equivalent (no actual deposit on dst)."""
    from player_steps import _player_root

    cmd = player.TransferFunds(
        from_player_root=_player_root(context, src),
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        hand_root=hand.encode(),
        reason="test_transfer",
    )
    _send_player_command(
        context, dst, cmd, "angzarr_client.proto.examples.v1.TransferFunds"
    )
