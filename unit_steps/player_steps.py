"""Player aggregate unit steps — bankroll primitives.

Drives the generated PlayerAggregate wiring through the FFI core. Given-steps
seed the player's history (PlayerRegistered, FundsDeposited, FundsReserved, ...)
which the core folds to rebuild PlayerState; When-steps dispatch a command; Then-
steps assert the emitted event, the coded rejection, or the resulting balances.

Pure-balance assertions ("Alice's total bankroll is N") read a parallel ledger
the seed/dispatch steps maintain on ``context`` — the FFI path exposes emitted
events, not rebuilt state, so the steps track bankroll / reserved / per-table
holds alongside the events they seed.

The buy-in / rebuy / tournament-registration lifecycle scenarios are NOT covered
here: after the reservation refactor those run on the reservation aggregate,
whose existence/funds checks need a cross-aggregate query the in-process FFI
harness does not yet expose.
"""

from __future__ import annotations

from behave import given, step, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "player"
P = "io.angzarr.examples.v1."


def _chips(amount: int) -> pt.Currency:
    return pt.Currency(amount=amount, currency_code="CHIPS")


def _ledger(context):
    """The per-scenario balance model the steps keep in lockstep with the
    seeded/emitted events, so pure-state assertions don't need FFI state."""
    if not hasattr(context, "bankroll"):
        context.bankroll = 0
        context.reserved = 0
        context.reservations = {}
        context.dispatched = False
    return context


# --- Given: seed prior history (and the parallel ledger) ---


@given('{who} has not yet registered')
def _given_unregistered(context, who):
    _ledger(context)


@given('{who} is registered')
def _given_registered(context, who):
    _ledger(context)
    context.world.seed_event(
        DOMAIN,
        P + "PlayerRegistered",
        player.PlayerRegistered(
            display_name=who,
            email=f"{who.lower()}@example.com",
            player_type=pt.HUMAN,
        ),
    )


@given('{who} has {n:d} chips')
def _given_has_chips(context, who, n):
    _ledger(context)
    context.bankroll += n
    context.world.seed_event(
        DOMAIN,
        P + "FundsDeposited",
        player.FundsDeposited(amount=_chips(n), new_balance=_chips(context.bankroll)),
    )


@given('{who} has withdrawn {n:d} chips')
def _given_has_withdrawn(context, who, n):
    _ledger(context)
    context.bankroll -= n
    context.world.seed_event(
        DOMAIN,
        P + "FundsWithdrawn",
        player.FundsWithdrawn(amount=_chips(n), new_balance=_chips(context.bankroll)),
    )


def _seed_reserved(context, n, table):
    context.reserved += n
    context.reservations[table] = n
    context.world.seed_event(
        DOMAIN,
        P + "FundsReserved",
        player.FundsReserved(
            amount=_chips(n),
            key=uuid_for(table),
            new_available_balance=_chips(context.bankroll - context.reserved),
            new_reserved_balance=_chips(context.reserved),
        ),
    )


@given('{who}\'s reservation for table "{table}" has been released in full')
def _given_released_in_full(context, who, table):
    _ledger(context)
    amount = context.reservations.pop(table, 0)
    context.reserved -= amount
    context.world.seed_event(
        DOMAIN,
        P + "FundsReleased",
        player.FundsReleased(
            amount=_chips(amount),
            key=uuid_for(table),
            new_available_balance=_chips(context.bankroll - context.reserved),
            new_reserved_balance=_chips(context.reserved),
        ),
    )


# --- When: dispatch a command ---


def _dispatch(context, cmd_name, cmd):
    _ledger(context)
    context.dispatched = True
    context.world.dispatch(DOMAIN, P + cmd_name, cmd)


@when('{who} registers with email "{email}"')
@when('{who} tries to register again with email "{email}"')
def _when_register(context, who, email):
    _dispatch(context, "RegisterPlayer", player.RegisterPlayer(display_name=who, email=email, player_type=pt.HUMAN))


@when('{who} registers as an AI with email "{email}" and model "{model}"')
def _when_register_ai(context, who, email, model):
    _dispatch(
        context,
        "RegisterPlayer",
        player.RegisterPlayer(display_name=who, email=email, player_type=pt.AI, ai_model_id=model),
    )


@when('{who} registers with an empty name and email "{email}"')
def _when_register_empty_name(context, who, email):
    _dispatch(context, "RegisterPlayer", player.RegisterPlayer(display_name="", email=email, player_type=pt.HUMAN))


@when('{who} registers with an empty email')
def _when_register_empty_email(context, who):
    _dispatch(context, "RegisterPlayer", player.RegisterPlayer(display_name=who, email="", player_type=pt.HUMAN))


@when('{who} deposits {n:d} chips')
@when('{who} deposits {n:d} chip')
def _when_deposit(context, who, n):
    _dispatch(context, "DepositFunds", player.DepositFunds(amount=_chips(n)))
    _fold_balance(context)


@when('{who} withdraws {n:d} chips')
@when('{who} withdraws {n:d} chip')
def _when_withdraw(context, who, n):
    _dispatch(context, "WithdrawFunds", player.WithdrawFunds(amount=_chips(n)))
    _fold_balance(context)


@when('{who} reserves {n:d} chips for table "{table}"')
@when('{who} reserves {n:d} chip for table "{table}"')
def _when_reserve(context, who, n, table):
    _dispatch(context, "ReserveFunds", player.ReserveFunds(amount=_chips(n), key=uuid_for(table)))
    if context.world.resp is not None:
        ev = context.world.emitted(P + "FundsReserved", player.FundsReserved())
        context.reserved = ev.new_reserved_balance.amount
        context.reservations[table] = ev.amount.amount


@when('{who}\'s funds for table "{table}" are released')
@when('{who}\'s join attempt at table "{table}" is rejected')
def _when_release(context, who, table):
    # A rejected table join compensates by releasing that table's reservation;
    # observably identical to an explicit release of the same hold.
    _dispatch(context, "ReleaseFunds", player.ReleaseFunds(key=uuid_for(table)))
    if context.world.resp is not None:
        ev = context.world.emitted(P + "FundsReleased", player.FundsReleased())
        context.reserved = ev.new_reserved_balance.amount
        context.reservations.pop(table, None)


@when('{who}\'s funds for an empty table name are released')
def _when_release_empty(context, who):
    _dispatch(context, "ReleaseFunds", player.ReleaseFunds(key=b""))


@when('{n:d} chips are transferred to {who} from "{src}" for hand "{hand}" with reason "{reason}"')
def _when_transfer(context, n, who, src, hand, reason):
    _dispatch(
        context,
        "TransferFunds",
        player.TransferFunds(
            from_player_root=uuid_for(src), amount=_chips(n), hand_root=uuid_for(hand), reason=reason
        ),
    )
    _fold_balance(context)


def _fold_balance(context):
    """After a successful balance-changing command, carry the new bankroll into
    the ledger so a following ``balance is N`` assertion reflects it."""
    if context.world.resp is None:
        return
    emitted = set(context.world.emitted_fqs())
    for name, cls in (
        ("FundsDeposited", player.FundsDeposited),
        ("FundsWithdrawn", player.FundsWithdrawn),
        ("FundsTransferred", player.FundsTransferred),
    ):
        if (P + name) in emitted:
            ev = context.world.emitted(P + name, cls())
            context.bankroll = ev.new_balance.amount
            return


# --- Then: emitted-event assertions ---


@then('{who} is registered as a human player')
def _then_human(context, who):
    ev = context.world.emitted(P + "PlayerRegistered", player.PlayerRegistered())
    assert ev.player_type == pt.HUMAN, f"player_type = {ev.player_type}, want HUMAN"


@then('{who} is registered as an AI player using the "{model}" model')
def _then_ai(context, who, model):
    ev = context.world.emitted(P + "PlayerRegistered", player.PlayerRegistered())
    assert ev.player_type == pt.AI, f"player_type = {ev.player_type}, want AI"
    assert ev.ai_model_id == model, f"ai_model_id = {ev.ai_model_id!r}, want {model!r}"


@then("{who}'s registration is timestamped")
def _then_registration_ts(context, who):
    ev = context.world.emitted(P + "PlayerRegistered", player.PlayerRegistered())
    assert ev.registered_at.seconds > 0, "registered_at not set"


@then('the transfer is recorded as coming from "{src}" for hand "{hand}" with reason "{reason}"')
def _then_transfer_recorded(context, src, hand, reason):
    ev = context.world.emitted(P + "FundsTransferred", player.FundsTransferred())
    assert ev.from_player_root == uuid_for(src), "from_player_root mismatch"
    assert ev.hand_root == uuid_for(hand), "hand_root mismatch"
    assert ev.reason == reason, f"reason = {ev.reason!r}, want {reason!r}"


@then('{n:d} chips are returned to {who}\'s available balance')
def _then_chips_returned(context, n, who):
    ev = context.world.emitted(P + "FundsReleased", player.FundsReleased())
    assert ev.amount.amount == n, f"released {ev.amount.amount}, want {n}"


@then('no chips are returned to {who}\'s available balance')
def _then_no_chips_returned(context, who):
    assert context.world.resp is None or (P + "FundsReleased") not in context.world.emitted_fqs(), (
        "expected no funds released"
    )


@then('{who} no longer has a reservation for table "{table}"')
def _then_no_reservation(context, who, table):
    assert table not in context.reservations, f"{table} still reserved"


# --- Then: balance ledger assertions ---


@then("{who}'s balance is {n:d}")
def _then_balance(context, who, n):
    assert context.bankroll == n, f"balance = {context.bankroll}, want {n}"


@then("{who}'s total bankroll is {n:d}")
def _then_total_bankroll(context, who, n):
    assert context.bankroll == n, f"bankroll = {context.bankroll}, want {n}"


@then("{who}'s reserved funds are {n:d}")
def _then_reserved(context, who, n):
    assert context.reserved == n, f"reserved = {context.reserved}, want {n}"


@then("{who}'s available balance is {n:d}")
def _then_available(context, who, n):
    available = context.bankroll - context.reserved
    assert available == n, f"available = {available}, want {n}"


# --- dual-use: seed when no command has run yet, else assert the emitted event ---


@step('{who} has reserved {n:d} chips for table "{table}"')
@step('{who} has reserved {n:d} chip for table "{table}"')
def _reserved_for_table(context, who, n, table):
    _ledger(context)
    if context.dispatched:
        ev = context.world.emitted(P + "FundsReserved", player.FundsReserved())
        assert ev.amount.amount == n, f"reserved {ev.amount.amount}, want {n}"
        assert ev.key == uuid_for(table), "reservation key mismatch"
    else:
        _seed_reserved(context, n, table)


# --- Then: coded rejections ---


@then('registration is refused because {who} already exists')
def _then_already_exists(context, who):
    assert_rejected(context, "PLAYER_ALREADY_EXISTS")


@then('registration is refused because a name is required')
def _then_name_required(context):
    assert_rejected(context, "DISPLAY_NAME_REQUIRED")


@then('registration is refused because an email is required')
def _then_email_required(context):
    assert_rejected(context, "EMAIL_REQUIRED")


@then('the deposit is refused because {who} does not exist')
@then('the withdrawal is refused because {who} does not exist')
@then('the reservation is refused because {who} does not exist')
@then('the release is refused because {who} does not exist')
@then('the transfer is refused because {who} does not exist')
def _then_not_found(context, who):
    assert_rejected(context, "PLAYER_NOT_FOUND")


@then('the deposit is refused because the amount must be positive')
@then('the withdrawal is refused because the amount must be positive')
@then('the reservation is refused because the amount must be positive')
def _then_must_be_positive(context):
    assert_rejected(context, "AMOUNT_MUST_BE_POSITIVE")


@then('the transfer is refused because the amount must be non-zero')
def _then_must_be_non_zero(context):
    assert_rejected(context, "AMOUNT_MUST_BE_NON_ZERO")


@then('the withdrawal is refused because {who} has {available:d} available but requested {requested:d}')
def _then_withdraw_insufficient(context, who, available, requested):
    assert_rejected(context, "INSUFFICIENT_AVAILABLE_BALANCE")


@then('the reservation is refused because {who} has {available:d} available but requested {requested:d}')
def _then_reserve_insufficient(context, who, available, requested):
    assert_rejected(context, "INSUFFICIENT_FUNDS")


@then('the reservation is refused because {who} already has funds reserved for table "{table}"')
def _then_already_reserved(context, who, table):
    assert_rejected(context, "FUNDS_ALREADY_RESERVED_FOR_TABLE")


@then('the release is refused because a table is required')
def _then_table_required(context):
    assert_rejected(context, "TABLE_ROOT_REQUIRED")


@then('the release is refused because {who} has no funds reserved for table "{table}"')
def _then_no_reservation_refused(context, who, table):
    assert_rejected(context, "NO_FUNDS_RESERVED_FOR_TABLE")
