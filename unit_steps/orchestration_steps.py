"""Cross-domain orchestration steps — the reservation PM deciding a buy-in /
registration / rebuy against its FOLDED cross-domain read model (look-before-leap
without a synchronous read).

The Given seeds the orchestrator's read model by folding the other domain's state
event (e.g. table.TableCreated carrying the buy-in range + capacity,
table.PlayerSeated marking occupied seats, tournament.RegistrationOpened /
TournamentStarted carrying registration/rebuy windows) into the PM's
process_state via ``prior_events``; the When dispatches the request trigger; the
Then asserts the orchestrator either offered the command (accept) or refused up
front with a failure event and NO command (refuse).
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as poker
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import registration_pb2 as registration
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as tournament
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."


def _reservation_id(player: str) -> bytes:
    return uuid_for(f"{player}-buy-in")


def _emitted_command_fqs(context):
    return [fq for (_domain, fq, _cmd) in context.world.emitted_commands()]


# ============================================================================
# Buy-in coordination (Player + Table) — EU-0600..0606
# ============================================================================


@given(
    'table "{table_name}" has seat {seat:d} available with a buy-in range of '
    "{low:d} to {high:d}"
)
def _given_table_range(context, table_name, seat, low, high):
    context.orch_table = table_name
    # Folded into the PM's read model so the buy-in decision can see the range.
    context.orch_prior = [
        (
            P + "TableCreated",
            table.TableCreated(min_buy_in=low, max_buy_in=high, max_players=9),
        )
    ]


@given('table "{table_name}" has seat {seat:d} occupied by another player')
def _given_seat_occupied(context, table_name, seat):
    context.orch_table = table_name
    # TableCreated sets capacity; a PlayerSeated for the other player folds the
    # seat into the orchestrator's occupied-seats read model.
    context.orch_prior = [
        (P + "TableCreated", table.TableCreated(max_players=9)),
        (
            P + "PlayerSeated",
            buy_in.PlayerSeated(
                player_root=uuid_for("other-player"), seat_position=seat, stack=500
            ),
        ),
    ]


@given('table "{table_name}" is full with {count:d} players')
def _given_table_full(context, table_name, count):
    context.orch_table = table_name
    prior = [(P + "TableCreated", table.TableCreated(max_players=count))]
    for seat in range(count):
        prior.append(
            (
                P + "PlayerSeated",
                buy_in.PlayerSeated(
                    player_root=uuid_for(f"other-{seat}"),
                    seat_position=seat,
                    stack=500,
                ),
            )
        )
    context.orch_prior = prior


@given("{player} has requested a buy-in for seat {seat:d} with amount {amount:d}")
def _given_buy_in_request(context, player, seat, amount):
    context.orch_player = player
    context.orch_buy_in = buy_in.BuyInRequested(
        player_root=uuid_for(player),
        table_root=uuid_for(context.orch_table),
        reservation_id=_reservation_id(player),
        seat=seat,
        amount=poker.Currency(amount=amount, currency_code="CHIPS"),
    )


@given("{player} has requested a buy-in for any seat with amount {amount:d}")
def _given_buy_in_request_any(context, player, amount):
    context.orch_player = player
    context.orch_buy_in = buy_in.BuyInRequested(
        player_root=uuid_for(player),
        table_root=uuid_for(context.orch_table),
        reservation_id=_reservation_id(player),
        seat=-1,
        amount=poker.Currency(amount=amount, currency_code="CHIPS"),
    )


@given('{player} has a pending buy-in at table "{table_name}"')
def _given_pending_buy_in(context, player, table_name):
    context.orch_player = player
    context.orch_table = table_name
    context.orch_reservation_id = _reservation_id(player)
    # Seed the PM's own in-flight state via BuyInInitiated.
    context.orch_prior = [
        (
            P + "BuyInInitiated",
            buy_in.BuyInInitiated(
                player_root=uuid_for(player),
                table_root=uuid_for(table_name),
                reservation_id=_reservation_id(player),
                seat=0,
                amount=poker.Currency(amount=500, currency_code="CHIPS"),
            ),
        )
    ]


@when("{player}'s buy-in is processed")
def _when_buy_in_processed(context, player):
    context.world.dispatch_process_manager(
        "reservation",
        P + "BuyInRequested",
        context.orch_buy_in,
        prior_events=getattr(context, "orch_prior", None),
    )


@when("{player:w} is seated at the table")
def _when_seated(context, player):
    context.world.dispatch_process_manager(
        "table",
        P + "PlayerSeated",
        buy_in.PlayerSeated(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            seat_position=0,
            stack=500,
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@when("the table refuses to seat {player:w}")
def _when_seating_refused(context, player):
    context.world.dispatch_process_manager(
        "table",
        P + "SeatingRejected",
        buy_in.SeatingRejected(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            requested_seat=0,
            reason="seat_occupied",
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@then('{player} is offered seat {seat:d} at table "{table_name}"')
def _then_offered_seat(context, player, seat, table_name):
    for _domain, fq, cmd_any in context.world.emitted_commands():
        if fq == P + "SeatPlayer":
            cmd = buy_in.SeatPlayer()
            cmd.ParseFromString(cmd_any.value)
            assert cmd.seat == seat, f"offered seat {cmd.seat}, expected {seat}"
            return
    raise AssertionError(
        f"no SeatPlayer offered; commands={_emitted_command_fqs(context)}"
    )


@then("the buy-in is recorded as initiated")
def _then_recorded_initiated(context):
    context.world.process_event(P + "BuyInInitiated", buy_in.BuyInInitiated())


@then("{player} is not offered a seat")
def _then_not_offered(context, player):
    fqs = _emitted_command_fqs(context)
    assert (
        P + "SeatPlayer" not in fqs
    ), f"a seat was offered (SeatPlayer); commands={fqs}"


@then("the buy-in is refused because the amount is outside the allowed range")
def _then_refused_out_of_range(context):
    failed = buy_in.BuyInFailed()
    context.world.process_event(P + "BuyInFailed", failed)
    assert failed.failure.code == "AMOUNT_OUT_OF_RANGE", failed.failure.code


@then("the buy-in is refused because the seat is already taken")
def _then_refused_seat_taken(context):
    failed = buy_in.BuyInFailed()
    context.world.process_event(P + "BuyInFailed", failed)
    assert failed.failure.code == "SEAT_TAKEN", failed.failure.code


@then("the buy-in is refused because the table is full")
def _then_refused_table_full(context):
    failed = buy_in.BuyInFailed()
    context.world.process_event(P + "BuyInFailed", failed)
    assert failed.failure.code == "TABLE_FULL", failed.failure.code


@then("{player}'s buy-in is confirmed")
def _then_buy_in_confirmed(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "ConfirmBuyIn" in fqs, f"buy-in not confirmed; commands={fqs}"


@then("the buy-in is recorded as completed")
def _then_buy_in_completed(context):
    context.world.process_event(P + "BuyInCompleted", buy_in.BuyInCompleted())


@then("{player}'s reserved buy-in funds are released")
def _then_buy_in_released(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "ReleaseBuyIn" in fqs, f"buy-in funds not released; commands={fqs}"


@then("the buy-in is refused because seating was rejected")
def _then_buy_in_seating_rejected(context):
    failed = buy_in.BuyInFailed()
    context.world.process_event(P + "BuyInFailed", failed)
    assert failed.failure.code == "SEATING_REJECTED", failed.failure.code


# ============================================================================
# Tournament registration coordination (Player + Tournament) — EU-0607..0611
# ============================================================================


@given('tournament "{trn}" is open for registration with capacity available')
def _given_trn_open(context, trn):
    context.orch_tournament = trn
    context.orch_prior = [
        (P + "TournamentCreated", tournament.TournamentCreated(max_players=9)),
        (P + "RegistrationOpened", tournament.RegistrationOpened()),
    ]


@given('tournament "{trn}" is full')
def _given_trn_full(context, trn):
    context.orch_tournament = trn
    prior = [
        (P + "TournamentCreated", tournament.TournamentCreated(max_players=2)),
        (P + "RegistrationOpened", tournament.RegistrationOpened()),
    ]
    for i in range(2):
        prior.append(
            (
                P + "TournamentPlayerEnrolled",
                tournament.TournamentPlayerEnrolled(
                    player_root=uuid_for(f"enrolled-{i}")
                ),
            )
        )
    context.orch_prior = prior


@given('tournament "{trn}" has registration closed')
def _given_trn_closed(context, trn):
    context.orch_tournament = trn
    context.orch_prior = [
        (P + "TournamentCreated", tournament.TournamentCreated(max_players=9)),
        (P + "RegistrationOpened", tournament.RegistrationOpened()),
        (
            P + "RegistrationClosed",
            tournament.RegistrationClosed(total_registrations=0),
        ),
    ]


@given("{player} has requested registration with fee {fee:d}")
def _given_registration_request(context, player, fee):
    context.orch_player = player
    context.orch_registration = registration.RegistrationRequested(
        player_root=uuid_for(player),
        tournament_root=uuid_for(context.orch_tournament),
        reservation_id=_reservation_id(player),
        fee=poker.Currency(amount=fee, currency_code="CHIPS"),
    )


@given('{player} has a pending registration for tournament "{trn}"')
def _given_pending_registration(context, player, trn):
    context.orch_player = player
    context.orch_tournament = trn
    context.orch_reservation_id = _reservation_id(player)
    context.orch_prior = [
        (
            P + "RegistrationInitiated",
            registration.RegistrationInitiated(
                player_root=uuid_for(player),
                tournament_root=uuid_for(trn),
                reservation_id=_reservation_id(player),
                fee=poker.Currency(amount=1000, currency_code="CHIPS"),
            ),
        )
    ]


@when("{player}'s registration is processed")
def _when_registration_processed(context, player):
    context.world.dispatch_process_manager(
        "reservation",
        P + "RegistrationRequested",
        context.orch_registration,
        prior_events=getattr(context, "orch_prior", None),
    )


@when("{player} is enrolled in the tournament")
def _when_enrolled(context, player):
    context.world.dispatch_process_manager(
        "tournament",
        P + "TournamentPlayerEnrolled",
        tournament.TournamentPlayerEnrolled(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            starting_stack=10000,
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@when("the tournament refuses to enroll {player:w}")
def _when_enroll_refused(context, player):
    context.world.dispatch_process_manager(
        "tournament",
        P + "TournamentEnrollmentRejected",
        tournament.TournamentEnrollmentRejected(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            reason="full",
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@then('{player} is enrolled in tournament "{trn}"')
def _then_enrolled(context, player, trn):
    fqs = _emitted_command_fqs(context)
    assert P + "EnrollPlayer" in fqs, f"not asked to enroll; commands={fqs}"


@then("the registration is recorded as initiated")
def _then_registration_initiated(context):
    context.world.process_event(
        P + "RegistrationInitiated", registration.RegistrationInitiated()
    )


@then("{player} is not enrolled")
def _then_not_enrolled(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "EnrollPlayer" not in fqs, f"player was enrolled; commands={fqs}"


@then("the registration is refused because registration is closed")
def _then_registration_refused_closed(context):
    failed = registration.RegistrationFailed()
    context.world.process_event(P + "RegistrationFailed", failed)
    assert failed.failure.code == "REGISTRATION_CLOSED", failed.failure.code


@then("{player}'s registration fee is confirmed")
def _then_registration_fee_confirmed(context, player):
    fqs = _emitted_command_fqs(context)
    assert (
        P + "ConfirmRegistrationFee" in fqs
    ), f"registration fee not confirmed; commands={fqs}"


@then("the registration is recorded as completed")
def _then_registration_completed(context):
    context.world.process_event(
        P + "RegistrationCompleted", registration.RegistrationCompleted()
    )


@then("{player}'s reserved registration fee is released")
def _then_registration_fee_released(context, player):
    fqs = _emitted_command_fqs(context)
    assert (
        P + "ReleaseRegistrationFee" in fqs
    ), f"registration fee not released; commands={fqs}"


@then("the registration is refused because enrollment was rejected")
def _then_registration_refused_rejected(context):
    failed = registration.RegistrationFailed()
    context.world.process_event(P + "RegistrationFailed", failed)
    assert failed.failure.code == "ENROLLMENT_REJECTED", failed.failure.code


# ============================================================================
# Rebuy coordination (Player + Tournament + Table) — EU-0612..0617
# ============================================================================


@given('tournament "{trn}" is in its rebuy window and {player} is eligible')
def _given_rebuy_window_open(context, trn, player):
    context.orch_tournament = trn
    # RUNNING tournament => rebuy window open.
    context.orch_prior = [
        (P + "TournamentStarted", tournament.TournamentStarted(total_players=2)),
    ]


@given('tournament "{trn}" has its rebuy window closed')
def _given_rebuy_window_closed(context, trn):
    context.orch_tournament = trn
    # PAUSED tournament => rebuy window closed (not RUNNING).
    context.orch_prior = [
        (P + "TournamentStarted", tournament.TournamentStarted(total_players=2)),
        (P + "TournamentPaused", tournament.TournamentPaused(reason="break")),
    ]


@given('{player} is seated at table "{table_name}" in seat {seat:d}')
def _given_seated_at(context, player, table_name, seat):
    context.orch_table = table_name
    context.orch_seat = seat
    context.orch_prior = list(getattr(context, "orch_prior", [])) + [
        (
            P + "PlayerSeated",
            buy_in.PlayerSeated(
                player_root=uuid_for(player), seat_position=seat, stack=500
            ),
        )
    ]


@given("{player} is not seated at any table in the tournament")
def _given_not_seated(context, player):
    # No PlayerSeated folded => player_seated stays false.
    context.orch_table = "table-1"
    context.orch_seat = 0


@given("{player} has requested a rebuy for amount {amount:d}")
def _given_rebuy_request(context, player, amount):
    context.orch_player = player
    context.orch_rebuy = rebuy.RebuyRequested(
        player_root=uuid_for(player),
        tournament_root=uuid_for(context.orch_tournament),
        table_root=uuid_for(getattr(context, "orch_table", "table-1")),
        reservation_id=_reservation_id(player),
        seat=getattr(context, "orch_seat", 0),
        fee=poker.Currency(amount=amount, currency_code="CHIPS"),
    )


@given('{player} has a pending rebuy at table "{table_name}" in tournament "{trn}"')
def _given_pending_rebuy(context, player, table_name, trn):
    context.orch_player = player
    context.orch_table = table_name
    context.orch_tournament = trn
    context.orch_reservation_id = _reservation_id(player)
    context.orch_prior = [
        (
            P + "RebuyInitiated",
            rebuy.RebuyInitiated(
                player_root=uuid_for(player),
                tournament_root=uuid_for(trn),
                table_root=uuid_for(table_name),
                reservation_id=_reservation_id(player),
                seat=2,
                fee=poker.Currency(amount=1000, currency_code="CHIPS"),
            ),
        )
    ]


@given(
    '{player}\'s rebuy chips have been added at table "{table_name}" in tournament "{trn}"'
)
def _given_rebuy_chips_added(context, player, table_name, trn):
    context.orch_player = player
    context.orch_table = table_name
    context.orch_tournament = trn
    context.orch_reservation_id = _reservation_id(player)
    context.orch_prior = [
        (
            P + "RebuyInitiated",
            rebuy.RebuyInitiated(
                player_root=uuid_for(player),
                tournament_root=uuid_for(trn),
                table_root=uuid_for(table_name),
                reservation_id=_reservation_id(player),
                seat=2,
                fee=poker.Currency(amount=1000, currency_code="CHIPS"),
            ),
        )
    ]


@when("{player}'s rebuy is processed")
def _when_rebuy_processed(context, player):
    context.world.dispatch_process_manager(
        "reservation",
        P + "RebuyRequested",
        context.orch_rebuy,
        prior_events=getattr(context, "orch_prior", None),
    )


@when("the tournament approves {player:w}'s rebuy")
def _when_rebuy_approved(context, player):
    context.world.dispatch_process_manager(
        "tournament",
        P + "RebuyProcessed",
        tournament.RebuyProcessed(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            chips_added=1000,
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@when("the chips are settled at the table")
def _when_chips_settled(context):
    context.world.dispatch_process_manager(
        "table",
        P + "RebuyChipsAdded",
        rebuy.RebuyChipsAdded(
            player_root=uuid_for(context.orch_player),
            reservation_id=context.orch_reservation_id,
            seat=2,
            amount=1000,
            new_stack=1500,
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@when("the tournament denies {player:w}'s rebuy")
def _when_rebuy_denied(context, player):
    context.world.dispatch_process_manager(
        "tournament",
        P + "RebuyDenied",
        tournament.RebuyDenied(
            player_root=uuid_for(player),
            reservation_id=context.orch_reservation_id,
            reason="window_closed",
        ),
        prior_events=getattr(context, "orch_prior", None),
    )


@then('{player}\'s rebuy is submitted to tournament "{trn}"')
def _then_rebuy_submitted(context, player, trn):
    fqs = _emitted_command_fqs(context)
    assert P + "ProcessRebuy" in fqs, f"rebuy not submitted; commands={fqs}"


@then("the rebuy is recorded as initiated")
def _then_rebuy_initiated(context):
    context.world.process_event(P + "RebuyInitiated", rebuy.RebuyInitiated())


@then("{player}'s rebuy is not submitted")
def _then_rebuy_not_submitted(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "ProcessRebuy" not in fqs, f"rebuy was submitted; commands={fqs}"


@then("the rebuy is refused because the tournament is not currently running")
def _then_rebuy_refused_window(context):
    failed = rebuy.RebuyFailed()
    context.world.process_event(P + "RebuyFailed", failed)
    assert failed.failure.code == "REBUY_WINDOW_CLOSED", failed.failure.code


@then("the rebuy is refused because {player} is not seated")
def _then_rebuy_refused_not_seated(context, player):
    failed = rebuy.RebuyFailed()
    context.world.process_event(P + "RebuyFailed", failed)
    assert failed.failure.code == "PLAYER_NOT_SEATED", failed.failure.code


@then("{player}'s rebuy chips are added at the table")
def _then_rebuy_chips_added(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "AddRebuyChips" in fqs, f"chips not added; commands={fqs}"


@then("{player}'s rebuy fee is confirmed")
def _then_rebuy_fee_confirmed(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "ConfirmRebuyFee" in fqs, f"rebuy fee not confirmed; commands={fqs}"


@then("the rebuy is recorded as completed")
def _then_rebuy_completed(context):
    context.world.process_event(P + "RebuyCompleted", rebuy.RebuyCompleted())


@then("{player}'s reserved rebuy fee is released")
def _then_rebuy_fee_released(context, player):
    fqs = _emitted_command_fqs(context)
    assert P + "ReleaseRebuyFee" in fqs, f"rebuy fee not released; commands={fqs}"


@then("the rebuy is refused because the rebuy was denied")
def _then_rebuy_refused_denied(context):
    failed = rebuy.RebuyFailed()
    context.world.process_event(P + "RebuyFailed", failed)
    assert failed.failure.code == "REBUY_DENIED", failed.failure.code
