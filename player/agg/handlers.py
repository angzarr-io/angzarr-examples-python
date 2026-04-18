"""Player command handler helpers - guard/validate/compute functions.

Pure functions split into three phases per command:
    guard(state)        -> raises CommandRejectedError if state preconditions fail
    validate(cmd, ...)  -> raises CommandRejectedError if inputs invalid; may return
                          normalized values
    compute(cmd, ...)   -> builds and returns the resulting event

Top-level ``on_*`` wrappers compose the three phases and are invoked from
``PlayerAggregate`` methods in ``main.py``.
"""

import uuid

from .state import PlayerState

from angzarr_client import now
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration


# =============================================================================
# RegisterPlayer
# =============================================================================


def register_player_guard(state: PlayerState) -> None:
    """Check state preconditions before registering."""
    if state.exists:
        raise CommandRejectedError("Player already exists")


def register_player_validate(cmd: player.RegisterPlayer) -> None:
    """Validate registration command fields."""
    if not cmd.display_name:
        raise CommandRejectedError("display_name is required")
    if not cmd.email:
        raise CommandRejectedError("email is required")


def register_player_compute(
    cmd: player.RegisterPlayer, state: PlayerState
) -> player.PlayerRegistered:
    """Build PlayerRegistered event from validated inputs."""
    return player.PlayerRegistered(
        display_name=cmd.display_name,
        email=cmd.email,
        player_type=cmd.player_type,
        ai_model_id=cmd.ai_model_id,
        registered_at=now(),
    )


def handle_register_player(
    cmd: player.RegisterPlayer, state: PlayerState
) -> player.PlayerRegistered:
    """Register a new player."""
    register_player_guard(state)
    register_player_validate(cmd)
    return register_player_compute(cmd, state)


# =============================================================================
# DepositFunds
# =============================================================================


# docs:start:deposit_funds_guard
def deposit_funds_guard(state: PlayerState) -> None:
    """Check state preconditions before processing deposit."""
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


# docs:end:deposit_funds_guard


# docs:start:deposit_funds_validate
def deposit_funds_validate(cmd: player.DepositFunds) -> int:
    """Validate deposit command and extract amount."""
    amount = cmd.amount.amount if cmd.amount else 0
    if amount <= 0:
        raise CommandRejectedError.invalid_argument("amount must be positive")
    return amount


# docs:end:deposit_funds_validate


# docs:start:deposit_funds_compute
def deposit_funds_compute(
    cmd: player.DepositFunds, state: PlayerState, amount: int
) -> player.FundsDeposited:
    """Build FundsDeposited event from validated inputs."""
    new_balance = state.bankroll + amount
    return player.FundsDeposited(
        amount=cmd.amount,
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        deposited_at=now(),
    )


# docs:end:deposit_funds_compute


# docs:start:polyglot_handler
def handle_deposit_funds(
    cmd: player.DepositFunds, state: PlayerState
) -> player.FundsDeposited:
    """Deposit funds into player's bankroll."""
    deposit_funds_guard(state)
    amount = deposit_funds_validate(cmd)
    return deposit_funds_compute(cmd, state, amount)


# docs:end:polyglot_handler


# =============================================================================
# WithdrawFunds
# =============================================================================


def withdraw_funds_guard(state: PlayerState) -> None:
    """Check state preconditions before processing withdrawal."""
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


def withdraw_funds_validate(cmd: player.WithdrawFunds, state: PlayerState) -> int:
    """Validate withdrawal command and extract amount."""
    amount = cmd.amount.amount if cmd.amount else 0
    if amount <= 0:
        raise CommandRejectedError.invalid_argument("amount must be positive")
    if amount > state.available_balance:
        raise CommandRejectedError("insufficient available balance")
    return amount


def withdraw_funds_compute(
    cmd: player.WithdrawFunds, state: PlayerState, amount: int
) -> player.FundsWithdrawn:
    """Build FundsWithdrawn event from validated inputs."""
    new_balance = state.bankroll - amount
    return player.FundsWithdrawn(
        amount=cmd.amount,
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        withdrawn_at=now(),
    )


def handle_withdraw_funds(
    cmd: player.WithdrawFunds, state: PlayerState
) -> player.FundsWithdrawn:
    """Withdraw funds from player's bankroll."""
    withdraw_funds_guard(state)
    amount = withdraw_funds_validate(cmd, state)
    return withdraw_funds_compute(cmd, state, amount)


# =============================================================================
# ReserveFunds
# =============================================================================


def reserve_funds_guard(state: PlayerState) -> None:
    """Check state preconditions before reserving funds."""
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


def reserve_funds_validate(
    cmd: player.ReserveFunds, state: PlayerState
) -> int:
    """Validate reserve command and extract amount."""
    amount = cmd.amount.amount if cmd.amount else 0
    if amount <= 0:
        raise CommandRejectedError.invalid_argument("amount must be positive")
    if amount > state.available_balance:
        raise CommandRejectedError("Insufficient funds")
    table_key = cmd.table_root.hex()
    if table_key in state.table_reservations:
        raise CommandRejectedError("Funds already reserved for this table")
    return amount


def reserve_funds_compute(
    cmd: player.ReserveFunds, state: PlayerState, amount: int
) -> player.FundsReserved:
    """Build FundsReserved event from validated inputs."""
    new_reserved = state.reserved_funds + amount
    new_available = state.bankroll - new_reserved
    return player.FundsReserved(
        amount=cmd.amount,
        table_root=cmd.table_root,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        reserved_at=now(),
    )


# docs:start:reserve_funds_imp
def handle_reserve_funds(
    cmd: player.ReserveFunds, state: PlayerState
) -> player.FundsReserved:
    """Reserve funds for a table buy-in."""
    reserve_funds_guard(state)
    amount = reserve_funds_validate(cmd, state)
    return reserve_funds_compute(cmd, state, amount)


# docs:end:reserve_funds_imp


# =============================================================================
# ReleaseFunds
# =============================================================================


def release_funds_guard(state: PlayerState) -> None:
    """Check state preconditions before releasing funds."""
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


def release_funds_validate(
    cmd: player.ReleaseFunds, state: PlayerState
) -> int:
    """Validate release command and return reserved amount."""
    if not cmd.table_root:
        raise CommandRejectedError("table_root is required")
    table_key = cmd.table_root.hex()
    reserved_for_table = state.table_reservations.get(table_key, 0)
    if reserved_for_table == 0:
        raise CommandRejectedError("No funds reserved for this table")
    return reserved_for_table


def release_funds_compute(
    cmd: player.ReleaseFunds, state: PlayerState, reserved_amount: int
) -> player.FundsReleased:
    """Build FundsReleased event from validated inputs."""
    new_reserved = state.reserved_funds - reserved_amount
    new_available = state.bankroll - new_reserved
    return player.FundsReleased(
        amount=poker_types.Currency(amount=reserved_amount, currency_code="CHIPS"),
        table_root=cmd.table_root,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        released_at=now(),
    )


def handle_release_funds(
    cmd: player.ReleaseFunds, state: PlayerState
) -> player.FundsReleased:
    """Release reserved funds when leaving a table."""
    release_funds_guard(state)
    reserved_amount = release_funds_validate(cmd, state)
    return release_funds_compute(cmd, state, reserved_amount)


# =============================================================================
# TransferFunds
# =============================================================================


def transfer_funds_guard(state: PlayerState) -> None:
    """Check state preconditions before transferring funds."""
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


def transfer_funds_validate(cmd: player.TransferFunds) -> int:
    """Validate transfer command and extract amount."""
    amount = cmd.amount.amount if cmd.amount else 0
    if amount == 0:
        raise CommandRejectedError.invalid_argument("amount must be non-zero")
    return amount


def transfer_funds_compute(
    cmd: player.TransferFunds, state: PlayerState, amount: int
) -> player.FundsTransferred:
    """Build FundsTransferred event from validated inputs."""
    new_balance = state.bankroll + amount
    return player.FundsTransferred(
        from_player_root=cmd.from_player_root,
        to_player_root=state.player_id.encode(),
        amount=cmd.amount,
        hand_root=cmd.hand_root,
        reason=cmd.reason,
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        transferred_at=now(),
    )


def handle_transfer_funds(
    cmd: player.TransferFunds, state: PlayerState
) -> player.FundsTransferred:
    """Transfer funds to player (from pot winnings, etc.)."""
    transfer_funds_guard(state)
    amount = transfer_funds_validate(cmd)
    return transfer_funds_compute(cmd, state, amount)


# =============================================================================
# Buy-in orchestration
# =============================================================================


def _require_exists(state: PlayerState) -> None:
    if not state.exists:
        raise CommandRejectedError("Player does not exist")


def _new_reservation_id() -> bytes:
    return uuid.uuid4().bytes


def handle_initiate_buy_in(
    cmd: buy_in.InitiateBuyIn, state: PlayerState
) -> buy_in.BuyInRequested:
    """Start a buy-in flow: reserve funds and announce the request."""
    _require_exists(state)
    if not cmd.table_root:
        raise CommandRejectedError("table_root is required")

    amount = cmd.amount.amount if cmd.HasField("amount") else 0
    if amount <= 0:
        raise CommandRejectedError.invalid_argument("amount must be positive")
    if amount > state.available_balance:
        raise CommandRejectedError("Insufficient funds")

    return buy_in.BuyInRequested(
        reservation_id=_new_reservation_id(),
        table_root=cmd.table_root,
        seat=cmd.seat,
        amount=cmd.amount,
        requested_at=now(),
    )


def handle_confirm_buy_in(
    cmd: buy_in.ConfirmBuyIn, state: PlayerState
) -> buy_in.BuyInConfirmed:
    """Finalize a buy-in: deduct reserved funds and settle to the table."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    pending = state.pending_buy_ins.get(reservation_hex)
    if pending is None:
        raise CommandRejectedError("No pending buy-in with this reservation_id")

    return buy_in.BuyInConfirmed(
        reservation_id=cmd.reservation_id,
        table_root=pending.table_root,
        seat=pending.seat,
        amount=poker_types.Currency(amount=pending.amount, currency_code="CHIPS"),
        confirmed_at=now(),
    )


def handle_release_buy_in(
    cmd: buy_in.ReleaseBuyIn, state: PlayerState
) -> buy_in.BuyInReservationReleased:
    """Abandon a pending buy-in and release the reserved funds."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    if reservation_hex not in state.pending_buy_ins:
        raise CommandRejectedError("No pending buy-in with this reservation_id")

    return buy_in.BuyInReservationReleased(
        reservation_id=cmd.reservation_id,
        reason=cmd.reason,
        released_at=now(),
    )


# =============================================================================
# Tournament registration orchestration
# =============================================================================


def handle_initiate_tournament_registration(
    cmd: registration.InitiateTournamentRegistration, state: PlayerState
) -> registration.RegistrationRequested:
    """Start a tournament-registration flow. Fee is supplied by the PM later
    from Tournament state; this aggregate just emits the request."""
    _require_exists(state)
    if not cmd.tournament_root:
        raise CommandRejectedError("tournament_root is required")

    return registration.RegistrationRequested(
        reservation_id=_new_reservation_id(),
        tournament_root=cmd.tournament_root,
        requested_at=now(),
    )


def handle_confirm_registration_fee(
    cmd: registration.ConfirmRegistrationFee, state: PlayerState
) -> registration.RegistrationFeeConfirmed:
    """Finalize a pending registration by deducting the fee."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    pending = state.pending_registrations.get(reservation_hex)
    if pending is None:
        raise CommandRejectedError("No pending registration with this reservation_id")

    return registration.RegistrationFeeConfirmed(
        reservation_id=cmd.reservation_id,
        tournament_root=pending.tournament_root,
        fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
        confirmed_at=now(),
    )


def handle_release_registration_fee(
    cmd: registration.ReleaseRegistrationFee, state: PlayerState
) -> registration.RegistrationFeeReleased:
    """Cancel a pending registration and release the reserved fee."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    if reservation_hex not in state.pending_registrations:
        raise CommandRejectedError("No pending registration with this reservation_id")

    return registration.RegistrationFeeReleased(
        reservation_id=cmd.reservation_id,
        reason=cmd.reason,
        released_at=now(),
    )


# =============================================================================
# Rebuy orchestration
# =============================================================================


def handle_initiate_rebuy(
    cmd: rebuy.InitiateRebuy, state: PlayerState
) -> rebuy.RebuyRequested:
    """Start a rebuy flow. Fee comes from Tournament state via the PM."""
    _require_exists(state)
    if not cmd.tournament_root:
        raise CommandRejectedError("tournament_root is required")
    if not cmd.table_root:
        raise CommandRejectedError("table_root is required")

    return rebuy.RebuyRequested(
        reservation_id=_new_reservation_id(),
        tournament_root=cmd.tournament_root,
        table_root=cmd.table_root,
        seat=cmd.seat,
        requested_at=now(),
    )


def handle_confirm_rebuy_fee(
    cmd: rebuy.ConfirmRebuyFee, state: PlayerState
) -> rebuy.RebuyFeeConfirmed:
    """Finalize a pending rebuy and deduct the fee."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    pending = state.pending_rebuys.get(reservation_hex)
    if pending is None:
        raise CommandRejectedError("No pending rebuy with this reservation_id")

    return rebuy.RebuyFeeConfirmed(
        reservation_id=cmd.reservation_id,
        tournament_root=pending.tournament_root,
        fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
        chips_added=pending.chips_to_add,
        confirmed_at=now(),
    )


def handle_release_rebuy_fee(
    cmd: rebuy.ReleaseRebuyFee, state: PlayerState
) -> rebuy.RebuyFeeReleased:
    """Cancel a pending rebuy and release the reserved fee."""
    _require_exists(state)
    if not cmd.reservation_id:
        raise CommandRejectedError("reservation_id is required")

    reservation_hex = cmd.reservation_id.hex()
    if reservation_hex not in state.pending_rebuys:
        raise CommandRejectedError("No pending rebuy with this reservation_id")

    return rebuy.RebuyFeeReleased(
        reservation_id=cmd.reservation_id,
        reason=cmd.reason,
        released_at=now(),
    )
