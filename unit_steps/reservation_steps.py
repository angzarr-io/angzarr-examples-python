"""Reservation aggregate unit steps — buy-in / rebuy / registration lifecycle.

Drives the generated ReservationAggregate wiring through the FFI core. Given-steps
seed a ``*Requested`` history (a pending record) the core folds into
ReservationState; When-steps dispatch an Initiate / Confirm / Release command;
Then-steps assert the emitted lifecycle event or the coded rejection.

The reservation aggregate records intent only — there is no player here, so no
funds/existence assertions. Those are orchestration outcomes (orchestration.feature).
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as registration
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected, decode_only_emitted

DOMAIN = "reservation"
P = "io.angzarr.examples.v1."
_PLAYER = uuid_for("Alice")


def _chips(n: int) -> pt.Currency:
    return pt.Currency(amount=n, currency_code="CHIPS")


# --- Given: seed a pending record ---


@given('a pending buy-in "{res}" for seat {seat:d} at table "{table}" for {n:d} chips')
def _given_pending_buy_in(context, res, seat, table, n):
    context.world.seed_event(
        DOMAIN,
        P + "BuyInRequested",
        buy_in.BuyInRequested(
            reservation_id=uuid_for(res),
            player_root=_PLAYER,
            table_root=uuid_for(table),
            seat=seat,
            amount=_chips(n),
        ),
    )


@given(
    'a pending tournament registration "{res}" for tournament "{trn}" with fee {fee:d}'
)
def _given_pending_registration(context, res, trn, fee):
    context.world.seed_event(
        DOMAIN,
        P + "RegistrationRequested",
        registration.RegistrationRequested(
            reservation_id=uuid_for(res),
            player_root=_PLAYER,
            tournament_root=uuid_for(trn),
            fee=_chips(fee),
        ),
    )


@given(
    'a pending rebuy "{res}" for tournament "{trn}" at table "{table}" seat {seat:d} with fee {fee:d}'
)
def _given_pending_rebuy(context, res, trn, table, seat, fee):
    context.world.seed_event(
        DOMAIN,
        P + "RebuyRequested",
        rebuy.RebuyRequested(
            reservation_id=uuid_for(res),
            player_root=_PLAYER,
            tournament_root=uuid_for(trn),
            table_root=uuid_for(table),
            seat=seat,
            fee=_chips(fee),
        ),
    )


# --- When: buy-in ---


@when('{who} initiates a buy-in for seat {seat:d} at table "{table}" for {n:d} chips')
@when('{who} initiates a buy-in for seat {seat:d} at table "{table}" for {n:d} chip')
def _when_initiate_buy_in(context, who, seat, table, n):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateBuyIn",
        buy_in.InitiateBuyIn(
            player_root=uuid_for(who),
            table_root=uuid_for(table),
            seat=seat,
            amount=_chips(n),
        ),
    )


@when(
    "{who} initiates a buy-in for seat {seat:d} at an empty table name for {n:d} chips"
)
def _when_initiate_buy_in_no_table(context, who, seat, n):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateBuyIn",
        buy_in.InitiateBuyIn(
            player_root=uuid_for(who), table_root=b"", seat=seat, amount=_chips(n)
        ),
    )


@when('{who}\'s buy-in "{res}" is confirmed')
def _when_confirm_buy_in(context, who, res):
    context.world.dispatch(
        DOMAIN, P + "ConfirmBuyIn", buy_in.ConfirmBuyIn(reservation_id=uuid_for(res))
    )


@when("{who}'s buy-in with an empty reservation identifier is confirmed")
def _when_confirm_buy_in_empty(context, who):
    context.world.dispatch(
        DOMAIN, P + "ConfirmBuyIn", buy_in.ConfirmBuyIn(reservation_id=b"")
    )


@when('{who}\'s buy-in "{res}" is released because of "{reason}"')
def _when_release_buy_in(context, who, res, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseBuyIn",
        buy_in.ReleaseBuyIn(reservation_id=uuid_for(res), reason=reason),
    )


@when(
    '{who}\'s buy-in with an empty reservation identifier is released because of "{reason}"'
)
def _when_release_buy_in_empty(context, who, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseBuyIn",
        buy_in.ReleaseBuyIn(reservation_id=b"", reason=reason),
    )


# --- When: registration ---


@when('{who} initiates registration for tournament "{trn}"')
def _when_initiate_registration(context, who, trn):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateTournamentRegistration",
        registration.InitiateTournamentRegistration(
            player_root=uuid_for(who), tournament_root=uuid_for(trn)
        ),
    )


@when("{who} initiates registration for an empty tournament name")
def _when_initiate_registration_no_trn(context, who):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateTournamentRegistration",
        registration.InitiateTournamentRegistration(
            player_root=uuid_for(who), tournament_root=b""
        ),
    )


@when('{who}\'s tournament registration "{res}" is confirmed')
def _when_confirm_registration(context, who, res):
    context.world.dispatch(
        DOMAIN,
        P + "ConfirmRegistrationFee",
        registration.ConfirmRegistrationFee(reservation_id=uuid_for(res)),
    )


@when(
    "{who}'s tournament registration with an empty reservation identifier is confirmed"
)
def _when_confirm_registration_empty(context, who):
    context.world.dispatch(
        DOMAIN,
        P + "ConfirmRegistrationFee",
        registration.ConfirmRegistrationFee(reservation_id=b""),
    )


@when('{who}\'s tournament registration "{res}" is released because of "{reason}"')
def _when_release_registration(context, who, res, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseRegistrationFee",
        registration.ReleaseRegistrationFee(
            reservation_id=uuid_for(res), reason=reason
        ),
    )


@when(
    '{who}\'s tournament registration with an empty reservation identifier is released because of "{reason}"'
)
def _when_release_registration_empty(context, who, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseRegistrationFee",
        registration.ReleaseRegistrationFee(reservation_id=b"", reason=reason),
    )


# --- When: rebuy ---


@when('{who} initiates a rebuy for tournament "{trn}" at table "{table}" seat {seat:d}')
def _when_initiate_rebuy(context, who, trn, table, seat):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateRebuy",
        rebuy.InitiateRebuy(
            player_root=uuid_for(who),
            tournament_root=uuid_for(trn),
            table_root=uuid_for(table),
            seat=seat,
        ),
    )


@when(
    '{who} initiates a rebuy for an empty tournament name at table "{table}" seat {seat:d}'
)
def _when_initiate_rebuy_no_trn(context, who, table, seat):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateRebuy",
        rebuy.InitiateRebuy(
            player_root=uuid_for(who),
            tournament_root=b"",
            table_root=uuid_for(table),
            seat=seat,
        ),
    )


@when(
    '{who} initiates a rebuy for tournament "{trn}" at an empty table name seat {seat:d}'
)
def _when_initiate_rebuy_no_table(context, who, trn, seat):
    context.world.dispatch(
        DOMAIN,
        P + "InitiateRebuy",
        rebuy.InitiateRebuy(
            player_root=uuid_for(who),
            tournament_root=uuid_for(trn),
            table_root=b"",
            seat=seat,
        ),
    )


@when('{who}\'s rebuy "{res}" is confirmed')
def _when_confirm_rebuy(context, who, res):
    context.world.dispatch(
        DOMAIN,
        P + "ConfirmRebuyFee",
        rebuy.ConfirmRebuyFee(reservation_id=uuid_for(res)),
    )


@when("{who}'s rebuy with an empty reservation identifier is confirmed")
def _when_confirm_rebuy_empty(context, who):
    context.world.dispatch(
        DOMAIN, P + "ConfirmRebuyFee", rebuy.ConfirmRebuyFee(reservation_id=b"")
    )


@when('{who}\'s rebuy "{res}" is released because of "{reason}"')
def _when_release_rebuy(context, who, res, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseRebuyFee",
        rebuy.ReleaseRebuyFee(reservation_id=uuid_for(res), reason=reason),
    )


@when(
    '{who}\'s rebuy with an empty reservation identifier is released because of "{reason}"'
)
def _when_release_rebuy_empty(context, who, reason):
    context.world.dispatch(
        DOMAIN,
        P + "ReleaseRebuyFee",
        rebuy.ReleaseRebuyFee(reservation_id=b"", reason=reason),
    )


# --- Then: records (initiate) ---


@then(
    'a pending buy-in is recorded for seat {seat:d} at table "{table}" for {n:d} chips'
)
@then(
    'a pending buy-in is recorded for seat {seat:d} at table "{table}" for {n:d} chip'
)
def _then_buy_in_recorded(context, seat, table, n):
    ev = context.world.emitted(P + "BuyInRequested", buy_in.BuyInRequested())
    assert ev.seat == seat, f"seat = {ev.seat}, want {seat}"
    assert ev.table_root == uuid_for(table), "table mismatch"
    assert ev.amount.amount == n, f"amount = {ev.amount.amount}, want {n}"


@then('a pending tournament registration is recorded for tournament "{trn}"')
def _then_registration_recorded(context, trn):
    ev = context.world.emitted(
        P + "RegistrationRequested", registration.RegistrationRequested()
    )
    assert ev.tournament_root == uuid_for(trn), "tournament mismatch"


@then(
    'a pending rebuy is recorded for tournament "{trn}" at table "{table}" seat {seat:d}'
)
def _then_rebuy_recorded(context, trn, table, seat):
    ev = context.world.emitted(P + "RebuyRequested", rebuy.RebuyRequested())
    assert ev.tournament_root == uuid_for(trn), "tournament mismatch"
    assert ev.table_root == uuid_for(table), "table mismatch"
    assert ev.seat == seat, f"seat = {ev.seat}, want {seat}"


# --- Then: confirm / release records ---


@then(
    'the buy-in "{res}" is confirmed for seat {seat:d} at table "{table}" for {n:d} chips'
)
def _then_buy_in_confirmed(context, res, seat, table, n):
    ev = context.world.emitted(P + "BuyInConfirmed", buy_in.BuyInConfirmed())
    assert ev.reservation_id == uuid_for(res), "reservation mismatch"
    assert ev.seat == seat and ev.table_root == uuid_for(table), "seat/table mismatch"
    assert ev.amount.amount == n, f"amount = {ev.amount.amount}, want {n}"


@then('the buy-in "{res}" is released with reason "{reason}"')
def _then_buy_in_released(context, res, reason):
    ev = context.world.emitted(
        P + "BuyInReservationReleased", buy_in.BuyInReservationReleased()
    )
    assert (
        ev.reservation_id == uuid_for(res) and ev.reason == reason
    ), "reservation/reason mismatch"


@then(
    'the tournament registration "{res}" is confirmed for tournament "{trn}" with fee {fee:d}'
)
def _then_registration_confirmed(context, res, trn, fee):
    ev = context.world.emitted(
        P + "RegistrationFeeConfirmed", registration.RegistrationFeeConfirmed()
    )
    assert ev.reservation_id == uuid_for(res) and ev.tournament_root == uuid_for(
        trn
    ), "reservation/tournament mismatch"
    assert ev.fee.amount == fee, f"fee = {ev.fee.amount}, want {fee}"


@then('the tournament registration "{res}" is released with reason "{reason}"')
def _then_registration_released(context, res, reason):
    ev = context.world.emitted(
        P + "RegistrationFeeReleased", registration.RegistrationFeeReleased()
    )
    assert (
        ev.reservation_id == uuid_for(res) and ev.reason == reason
    ), "reservation/reason mismatch"


@then('the rebuy "{res}" is confirmed for tournament "{trn}" with fee {fee:d}')
def _then_rebuy_confirmed(context, res, trn, fee):
    ev = context.world.emitted(P + "RebuyFeeConfirmed", rebuy.RebuyFeeConfirmed())
    assert ev.reservation_id == uuid_for(res) and ev.tournament_root == uuid_for(
        trn
    ), "reservation/tournament mismatch"
    assert ev.fee.amount == fee, f"fee = {ev.fee.amount}, want {fee}"


@then('the rebuy "{res}" is released with reason "{reason}"')
def _then_rebuy_released(context, res, reason):
    ev = context.world.emitted(P + "RebuyFeeReleased", rebuy.RebuyFeeReleased())
    assert (
        ev.reservation_id == uuid_for(res) and ev.reason == reason
    ), "reservation/reason mismatch"


# --- Then: generic id / timestamp over the single emitted event ---


@then("the {what} carries a generated reservation identifier")
def _then_carries_id(context, what):
    ev = decode_only_emitted(context)
    assert ev.reservation_id, "reservation_id was empty"


# --- Then: coded rejections ---


@then("the buy-in is refused because a table is required")
@then("the rebuy is refused because a table is required")
def _then_table_required(context):
    assert_rejected(context, "TABLE_ROOT_REQUIRED")


@then("the registration is refused because a tournament is required")
@then("the rebuy is refused because a tournament is required")
def _then_tournament_required(context):
    assert_rejected(context, "TOURNAMENT_ROOT_REQUIRED")


@then("the buy-in is refused because the amount must be positive")
def _then_amount_positive(context):
    assert_rejected(context, "AMOUNT_MUST_BE_POSITIVE")


@then("the confirmation is refused because a reservation identifier is required")
@then("the release is refused because a reservation identifier is required")
def _then_reservation_id_required(context):
    assert_rejected(context, "RESERVATION_ID_REQUIRED")


@then("the confirmation is refused because no buy-in with that reservation is pending")
@then("the release is refused because no buy-in with that reservation is pending")
def _then_no_pending_buy_in(context):
    assert_rejected(context, "NO_PENDING_BUY_IN")


@then(
    "the confirmation is refused because no registration with that reservation is pending"
)
@then("the release is refused because no registration with that reservation is pending")
def _then_no_pending_registration(context):
    assert_rejected(context, "NO_PENDING_REGISTRATION")


@then("the confirmation is refused because no rebuy with that reservation is pending")
@then("the release is refused because no rebuy with that reservation is pending")
def _then_no_pending_rebuy(context):
    assert_rejected(context, "NO_PENDING_REBUY")
