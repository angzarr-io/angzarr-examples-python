"""Player command handler helpers - guard/validate/compute functions.

Pure functions split into three phases per command:
    guard(state)        -> raises CommandRejectedError if state preconditions fail
    validate(cmd, ...)  -> raises CommandRejectedError if inputs invalid; may return
                          normalized values
    compute(cmd, ...)   -> builds and returns the resulting event

Top-level ``on_*`` wrappers compose the three phases and are invoked from
``PlayerAggregate`` methods in ``main.py``.
"""

from .state import PlayerState

from angzarr_client import now
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types


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
