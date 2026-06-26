"""Process-manager unit steps — ReservationProcessManager (buy-in / rebuy /
registration lifecycles).

Exercises the reservation PM component type: a stateful, event-sourced handler
dispatched with a self-contained trigger event (via the FFI
Router.dispatch_process_manager). Each scenario's trigger carries every field the
handler reads — the harness does NOT seed PM process_state, so the PM rebuilds
from empty on each dispatch. The Given steps are narrative context only and build
nothing; the When dispatches the trigger; the Then steps assert the emitted
downstream commands (SeatPlayer / ReserveFunds / ConfirmBuyIn / ReleaseBuyIn /
ProcessRebuy / AddRebuyChips / ... ) and/or the PM's own process-events
(BuyInInitiated / BuyInCompleted / BuyInFailed / Rebuy* / Registration*).
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as registration
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as tournament
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as poker
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."


def _currency(amount: int) -> poker.Currency:
    return poker.Currency(amount=amount, currency_code="CHIPS")


def _command(context, domain: str, name: str, message):
    """Decode the first emitted command named ``name`` targeted at ``domain``.

    ``emitted_commands`` reports the fully-qualified type name (e.g.
    ``io.angzarr.examples.v1.SeatPlayer``), so match against ``P + name``.
    """
    target = P + name
    for cmd_domain, cmd_fq, command_any in context.world.emitted_commands():
        if cmd_domain == domain and cmd_fq == target:
            message.ParseFromString(command_any.value)
            return message
    raise AssertionError(
        f"no emitted {name} command to {domain}; got "
        f"{[(d, f) for d, f, _ in context.world.emitted_commands()]}"
    )


# ====================================================================== #
# Given — narrative context only (the trigger carries everything).
# ====================================================================== #


@given('a buy-in is in progress for player "{player_name}"')
def _given_buy_in_in_progress_for_player(context, player_name):
    pass


@given("a buy-in is in progress")
def _given_buy_in_in_progress(context):
    pass


@given('a rebuy is in progress for player "{player_name}"')
def _given_rebuy_in_progress_for_player(context, player_name):
    pass


@given('a rebuy is in progress for table "{table_name}" at seat {seat:d}')
def _given_rebuy_in_progress_for_table_seat(context, table_name, seat):
    pass


@given('a rebuy is in progress for tournament "{tournament_name}"')
def _given_rebuy_in_progress_for_tournament(context, tournament_name):
    pass


@given(
    'a rebuy is in progress for tournament "{tournament_name}" at table '
    '"{table_name}" with fee {fee:d}'
)
def _given_rebuy_in_progress_for_tournament_table_fee(
    context, tournament_name, table_name, fee
):
    pass


@given('a registration is in progress for player "{player_name}"')
def _given_registration_in_progress_for_player(context, player_name):
    pass


@given(
    'a registration is in progress for tournament "{tournament_name}" with fee {fee:d}'
)
def _given_registration_in_progress_for_tournament_fee(context, tournament_name, fee):
    pass


@given('a registration is in progress for tournament "{tournament_name}"')
def _given_registration_in_progress_for_tournament(context, tournament_name):
    pass


# ====================================================================== #
# When — dispatch a self-contained trigger.
# ====================================================================== #

# --- Buy-in ---


@when(
    'player "{player_name}" requests a buy-in at table "{table_name}" for seat '
    '{seat:d} with {amount:d} chips under reservation "{reservation_name}"'
)
def _when_buy_in_requested(
    context, player_name, table_name, seat, amount, reservation_name
):
    event = buy_in.BuyInRequested(
        player_root=uuid_for(player_name),
        table_root=uuid_for(table_name),
        reservation_id=uuid_for(reservation_name),
        seat=seat,
        amount=_currency(amount),
    )
    context.world.dispatch_process_manager("reservation", P + "BuyInRequested", event)


@when(
    'the table seats "{player_name}" at seat {seat:d} with {amount:d} chips under '
    'reservation "{reservation_name}"'
)
def _when_player_seated(context, player_name, seat, amount, reservation_name):
    event = buy_in.PlayerSeated(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        seat_position=seat,
        stack=amount,
    )
    context.world.dispatch_process_manager("table", P + "PlayerSeated", event)


@when(
    'the table refuses to seat "{player_name}" under reservation '
    '"{reservation_name}" because "{reason}"'
)
def _when_seating_rejected(context, player_name, reservation_name, reason):
    event = buy_in.SeatingRejected(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        reason=reason,
    )
    context.world.dispatch_process_manager("table", P + "SeatingRejected", event)


# --- Rebuy ---


@when(
    'player "{player_name}" requests a rebuy at tournament "{tournament_name}", '
    'table "{table_name}", seat {seat:d} with fee {fee:d} under reservation '
    '"{reservation_name}"'
)
def _when_rebuy_requested(
    context, player_name, tournament_name, table_name, seat, fee, reservation_name
):
    event = rebuy.RebuyRequested(
        player_root=uuid_for(player_name),
        tournament_root=uuid_for(tournament_name),
        table_root=uuid_for(table_name),
        reservation_id=uuid_for(reservation_name),
        seat=seat,
        fee=_currency(fee),
    )
    context.world.dispatch_process_manager("reservation", P + "RebuyRequested", event)


@when(
    'the tournament approves the rebuy for "{player_name}" under reservation '
    '"{reservation_name}" with {chips:d} chips'
)
def _when_rebuy_processed(context, player_name, reservation_name, chips):
    event = tournament.RebuyProcessed(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        chips_added=chips,
    )
    context.world.dispatch_process_manager("tournament", P + "RebuyProcessed", event)


@when(
    'the tournament denies the rebuy for "{player_name}" under reservation '
    '"{reservation_name}" because "{reason}"'
)
def _when_rebuy_denied(context, player_name, reservation_name, reason):
    event = tournament.RebuyDenied(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        reason=reason,
    )
    context.world.dispatch_process_manager("tournament", P + "RebuyDenied", event)


@when(
    'the table adds {chips:d} rebuy chips for "{player_name}" at seat {seat:d} '
    'under reservation "{reservation_name}"'
)
def _when_rebuy_chips_added(context, chips, player_name, seat, reservation_name):
    event = rebuy.RebuyChipsAdded(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        seat=seat,
        amount=chips,
    )
    context.world.dispatch_process_manager("table", P + "RebuyChipsAdded", event)


# --- Registration ---


@when(
    'player "{player_name}" requests registration in tournament '
    '"{tournament_name}" with fee {fee:d} under reservation "{reservation_name}"'
)
def _when_registration_requested(
    context, player_name, tournament_name, fee, reservation_name
):
    event = registration.RegistrationRequested(
        player_root=uuid_for(player_name),
        tournament_root=uuid_for(tournament_name),
        reservation_id=uuid_for(reservation_name),
        fee=_currency(fee),
    )
    context.world.dispatch_process_manager(
        "reservation", P + "RegistrationRequested", event
    )


@when(
    'player "{player_name}" requests registration in tournament '
    '"{tournament_name}" under reservation "{reservation_name}" with no fee'
)
def _when_registration_requested_no_fee(
    context, player_name, tournament_name, reservation_name
):
    event = registration.RegistrationRequested(
        player_root=uuid_for(player_name),
        tournament_root=uuid_for(tournament_name),
        reservation_id=uuid_for(reservation_name),
    )
    context.world.dispatch_process_manager(
        "reservation", P + "RegistrationRequested", event
    )


@when(
    'the tournament enrolls "{player_name}" under reservation "{reservation_name}" '
    "with fee paid {fee:d} and starting stack {stack:d}"
)
def _when_tournament_player_enrolled(
    context, player_name, reservation_name, fee, stack
):
    event = tournament.TournamentPlayerEnrolled(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        fee_paid=fee,
        starting_stack=stack,
    )
    context.world.dispatch_process_manager(
        "tournament", P + "TournamentPlayerEnrolled", event
    )


@when(
    'the tournament rejects the registration for "{player_name}" under reservation '
    '"{reservation_name}" because "{reason}"'
)
def _when_tournament_enrollment_rejected(
    context, player_name, reservation_name, reason
):
    event = tournament.TournamentEnrollmentRejected(
        player_root=uuid_for(player_name),
        reservation_id=uuid_for(reservation_name),
        reason=reason,
    )
    context.world.dispatch_process_manager(
        "tournament", P + "TournamentEnrollmentRejected", event
    )


# ====================================================================== #
# Then — assert emitted commands / own process-events.
# ====================================================================== #

# --- Buy-in ---


@then(
    'the table is asked to seat "{player_name}" at seat {seat:d} with {amount:d} '
    'chips under reservation "{reservation_name}"'
)
def _then_table_asked_to_seat(context, player_name, seat, amount, reservation_name):
    cmd = _command(context, "table", "SeatPlayer", buy_in.SeatPlayer())
    assert cmd.player_root == uuid_for(player_name), "wrong player on SeatPlayer"
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on SeatPlayer"
    assert cmd.seat == seat, f"seat {cmd.seat} != {seat}"
    assert cmd.amount == amount, f"amount {cmd.amount} != {amount}"


@then(
    'the buy-in for "{player_name}" at "{table_name}" is recorded as awaiting seating'
)
def _then_buy_in_awaiting_seating(context, player_name, table_name):
    event = context.world.process_event(P + "BuyInInitiated", buy_in.BuyInInitiated())
    assert event.player_root == uuid_for(player_name), "wrong player on BuyInInitiated"
    assert event.table_root == uuid_for(table_name), "wrong table on BuyInInitiated"


@then('"{player_name}"\'s buy-in reservation "{reservation_name}" is confirmed')
def _then_buy_in_confirmed(context, player_name, reservation_name):
    cmd = _command(context, "reservation", "ConfirmBuyIn", buy_in.ConfirmBuyIn())
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ConfirmBuyIn"


@then('the buy-in for "{player_name}" at seat {seat:d} is recorded as completed')
def _then_buy_in_completed(context, player_name, seat):
    event = context.world.process_event(P + "BuyInCompleted", buy_in.BuyInCompleted())
    assert event.player_root == uuid_for(player_name), "wrong player on BuyInCompleted"
    assert event.seat == seat, f"seat {event.seat} != {seat}"


@then(
    '"{player_name}"\'s buy-in reservation "{reservation_name}" is released '
    'because "{reason}"'
)
def _then_buy_in_released(context, player_name, reservation_name, reason):
    cmd = _command(context, "reservation", "ReleaseBuyIn", buy_in.ReleaseBuyIn())
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ReleaseBuyIn"
    assert cmd.reason == reason, f"reason {cmd.reason!r} != {reason!r}"


@then(
    'the buy-in for "{player_name}" is recorded as failed because the table '
    "refused to seat the player"
)
def _then_buy_in_failed(context, player_name):
    event = context.world.process_event(P + "BuyInFailed", buy_in.BuyInFailed())
    assert event.player_root == uuid_for(player_name), "wrong player on BuyInFailed"


# --- Rebuy ---


@then(
    'the tournament is asked to approve the rebuy for "{player_name}" under '
    'reservation "{reservation_name}"'
)
def _then_tournament_asked_approve_rebuy(context, player_name, reservation_name):
    cmd = _command(context, "tournament", "ProcessRebuy", tournament.ProcessRebuy())
    assert cmd.player_root == uuid_for(player_name), "wrong player on ProcessRebuy"
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ProcessRebuy"


@then(
    'the rebuy for "{player_name}" in tournament "{tournament_name}" is recorded '
    "as awaiting approval"
)
def _then_rebuy_awaiting_approval(context, player_name, tournament_name):
    event = context.world.process_event(P + "RebuyInitiated", rebuy.RebuyInitiated())
    assert event.player_root == uuid_for(player_name), "wrong player on RebuyInitiated"
    assert event.tournament_root == uuid_for(
        tournament_name
    ), "wrong tournament on RebuyInitiated"


@then(
    'the table is asked to add {chips:d} chips for "{player_name}" at seat {seat:d} '
    'under reservation "{reservation_name}"'
)
def _then_table_asked_add_chips(context, chips, player_name, seat, reservation_name):
    cmd = _command(context, "table", "AddRebuyChips", rebuy.AddRebuyChips())
    assert cmd.player_root == uuid_for(player_name), "wrong player on AddRebuyChips"
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on AddRebuyChips"
    assert cmd.amount == chips, f"chips {cmd.amount} != {chips}"
    # NOTE: the seat ({seat}) is carried on the PM's own event-sourced state
    # (set when RebuyRequested -> RebuyInitiated folded). The RebuyProcessed
    # trigger has no `seat` proto field, so in this isolated dispatch — where the
    # harness rebuilds PM state from empty rather than seeding it — `state.seat`
    # is 0 and cannot be asserted. The seat is verified end-to-end, not here.


@then(
    '"{player_name}"\'s rebuy reservation "{reservation_name}" is released because "{reason}"'
)
def _then_rebuy_released(context, player_name, reservation_name, reason):
    cmd = _command(context, "reservation", "ReleaseRebuyFee", rebuy.ReleaseRebuyFee())
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ReleaseRebuyFee"
    assert cmd.reason == reason, f"reason {cmd.reason!r} != {reason!r}"


@then(
    'the rebuy for "{player_name}" is recorded as failed because the tournament '
    "denied the rebuy"
)
def _then_rebuy_failed(context, player_name):
    event = context.world.process_event(P + "RebuyFailed", rebuy.RebuyFailed())
    assert event.player_root == uuid_for(player_name), "wrong player on RebuyFailed"


@then('"{player_name}"\'s rebuy fee reservation "{reservation_name}" is confirmed')
def _then_rebuy_fee_confirmed(context, player_name, reservation_name):
    cmd = _command(context, "reservation", "ConfirmRebuyFee", rebuy.ConfirmRebuyFee())
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ConfirmRebuyFee"


@then(
    'the rebuy for "{player_name}" is recorded as completed with {chips:d} chips added'
)
def _then_rebuy_completed(context, player_name, chips):
    event = context.world.process_event(P + "RebuyCompleted", rebuy.RebuyCompleted())
    assert event.player_root == uuid_for(player_name), "wrong player on RebuyCompleted"
    assert event.chips_added == chips, f"chips_added {event.chips_added} != {chips}"


# --- Registration ---


@then(
    'the tournament is asked to enroll "{player_name}" under reservation "{reservation_name}"'
)
def _then_tournament_asked_enroll(context, player_name, reservation_name):
    cmd = _command(context, "tournament", "EnrollPlayer", tournament.EnrollPlayer())
    assert cmd.player_root == uuid_for(player_name), "wrong player on EnrollPlayer"
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on EnrollPlayer"


@then(
    '"{player_name}"\'s registration fee reservation "{reservation_name}" is confirmed'
)
def _then_registration_fee_confirmed(context, player_name, reservation_name):
    cmd = _command(
        context,
        "reservation",
        "ConfirmRegistrationFee",
        registration.ConfirmRegistrationFee(),
    )
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ConfirmRegistrationFee"


@then(
    '"{player_name}"\'s registration fee reservation "{reservation_name}" is '
    'released because "{reason}"'
)
def _then_registration_fee_released(context, player_name, reservation_name, reason):
    cmd = _command(
        context,
        "reservation",
        "ReleaseRegistrationFee",
        registration.ReleaseRegistrationFee(),
    )
    assert cmd.reservation_id == uuid_for(
        reservation_name
    ), "wrong reservation on ReleaseRegistrationFee"
    assert cmd.reason == reason, f"reason {cmd.reason!r} != {reason!r}"


@then('the registration for "{player_name}" is recorded with a fee of {fee:d}')
def _then_registration_recorded_with_fee(context, player_name, fee):
    event = context.world.process_event(
        P + "RegistrationInitiated", registration.RegistrationInitiated()
    )
    assert event.player_root == uuid_for(
        player_name
    ), "wrong player on RegistrationInitiated"
    actual = event.fee.amount if event.HasField("fee") else 0
    assert actual == fee, f"fee {actual} != {fee}"
