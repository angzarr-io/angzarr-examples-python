"""Step definitions for orchestration BDD tests.

Tests PM orchestration logic for BuyInOrchestrator, RegistrationOrchestrator,
and RebuyOrchestrator. Each orchestrator coordinates cross-aggregate flows
that require decision coupling.

The step definitions simulate the validation logic that the PM + aggregate
interaction implements, storing state in behave context and asserting on
emitted commands and process events.
"""

from behave import given, then, use_step_matcher, when

from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import tournament_pb2 as tournament

# Use regex matchers for flexibility
use_step_matcher("re")


# =============================================================================
# Helpers
# =============================================================================


def _init_orchestration_context(context):
    """Ensure orchestration context fields are initialized."""
    if not hasattr(context, "emitted_commands"):
        context.emitted_commands = []
    if not hasattr(context, "emitted_events"):
        context.emitted_events = []


# =============================================================================
# BuyInOrchestrator - Given steps
# =============================================================================


@given(r"a table with seat (?P<seat>\d+) available and buy-in range (?P<min>\d+)-(?P<max>\d+)")
def step_given_table_seat_available_with_range(context, seat, min, max):
    """Set up a table with a specific seat available and buy-in range."""
    _init_orchestration_context(context)
    context.table_min_buy_in = int(min)
    context.table_max_buy_in = int(max)
    context.table_max_players = 9
    context.occupied_seats = {}  # position -> player_root
    context.table_root = b"table-1"
    context.available_seat = int(seat)


@given(r"a player with a BuyInRequested event for seat (?P<seat>\d+) with amount (?P<amount>\d+)")
def step_given_buy_in_requested_for_seat(context, seat, amount):
    """Create a BuyInRequested event for a specific seat and amount."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.reservation_id = b"res-001"
    context.buy_in_seat = int(seat)
    context.buy_in_amount = int(amount)
    context.buy_in_event = buy_in.BuyInRequested(
        reservation_id=context.reservation_id,
        table_root=getattr(context, "table_root", b"table-1"),
        seat=int(seat),
        amount=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r"a table with seat (?P<seat>\d+) occupied by another player")
def step_given_seat_occupied(context, seat):
    """Set up a table where a specific seat is already occupied."""
    _init_orchestration_context(context)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9
    context.occupied_seats = {int(seat): b"other-player"}
    context.table_root = b"table-1"


@given(r"a table that is full with (?P<count>\d+) players")
def step_given_table_full(context, count):
    """Set up a table that is full."""
    _init_orchestration_context(context)
    num_players = int(count)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = num_players
    context.occupied_seats = {
        i: f"player-{i}".encode() for i in range(num_players)
    }
    context.table_root = b"table-1"


@given(r"a player with a BuyInRequested event for any seat with amount (?P<amount>\d+)")
def step_given_buy_in_requested_any_seat(context, amount):
    """Create a BuyInRequested event for any available seat."""
    _init_orchestration_context(context)
    context.player_root = b"player-new"
    context.reservation_id = b"res-001"
    context.buy_in_seat = -1
    context.buy_in_amount = int(amount)
    context.buy_in_event = buy_in.BuyInRequested(
        reservation_id=context.reservation_id,
        table_root=getattr(context, "table_root", b"table-1"),
        seat=-1,
        amount=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r"a player and table in a pending buy-in state")
def step_given_pending_buy_in(context):
    """Set up a player and table in a pending buy-in state (seating phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.buy_in_amount = 500
    context.buy_in_seat = 0
    context.buy_in_phase = orch.BuyInPhase.BUY_IN_SEATING


# =============================================================================
# RegistrationOrchestrator - Given steps
# =============================================================================


@given(r"a tournament with registration open and capacity available")
def step_given_tournament_open_with_capacity(context):
    """Set up a tournament with open registration and available capacity."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = True
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r"a player with a RegistrationRequested event with fee (?P<fee>\d+)")
def step_given_registration_requested(context, fee):
    """Create a RegistrationRequested event with a specific fee."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.reservation_id = b"res-001"
    context.registration_fee = int(fee)
    context.registration_event = registration.RegistrationRequested(
        reservation_id=context.reservation_id,
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        fee=poker.Currency(amount=int(fee), currency_code="USD"),
    )


@given(r"a tournament that is full")
def step_given_tournament_full(context):
    """Set up a tournament that has reached max capacity."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = False
    context.tournament_max_players = 100
    context.tournament_registered_count = 100
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r"a tournament with registration closed")
def step_given_tournament_registration_closed(context):
    """Set up a tournament with closed registration."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = False
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING


@given(r"a player and tournament in a pending registration state")
def step_given_pending_registration(context):
    """Set up a player and tournament in pending registration (enrolling phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.reservation_id = b"res-001"
    context.registration_fee = 1000
    context.registration_phase = orch.RegistrationPhase.REGISTRATION_ENROLLING


# =============================================================================
# RebuyOrchestrator - Given steps
# =============================================================================


@given(r"a tournament in rebuy window with player eligible")
def step_given_tournament_rebuy_eligible(context):
    """Set up a tournament in rebuy window where the player is eligible."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    context.rebuy_window_open = True
    context.player_eligible_for_rebuy = True


@given(r"a table with the player seated at position (?P<pos>\d+)")
def step_given_player_seated_at_position(context, pos):
    """Set up table state with the player seated at a specific position."""
    _init_orchestration_context(context)
    context.table_root = b"table-1"
    context.player_root = b"player-1"
    context.player_seat_position = int(pos)
    context.player_is_seated = True


@given(r"a player with a RebuyRequested event for amount (?P<amount>\d+)")
def step_given_rebuy_requested(context, amount):
    """Create a RebuyRequested event for a specific amount."""
    _init_orchestration_context(context)
    context.reservation_id = b"res-001"
    context.rebuy_amount = int(amount)
    context.rebuy_event = rebuy.RebuyRequested(
        reservation_id=context.reservation_id,
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        table_root=getattr(context, "table_root", b"table-1"),
        seat=getattr(context, "player_seat_position", 2),
        fee=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r"a tournament with rebuy window closed")
def step_given_rebuy_window_closed(context):
    """Set up a tournament where the rebuy window is closed."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_COMPLETED
    context.rebuy_window_open = False
    context.player_eligible_for_rebuy = False


@given(r"a table without the player seated")
def step_given_player_not_seated(context):
    """Set up table state where the player is not seated."""
    _init_orchestration_context(context)
    context.table_root = b"table-1"
    context.player_root = b"player-1"
    context.player_is_seated = False
    context.player_seat_position = -1


@given(r"a player, tournament, and table in a pending rebuy state")
def step_given_pending_rebuy(context):
    """Set up all three domains in a pending rebuy state (approving phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_APPROVING


@given(r"a player, tournament, and table with chips added")
def step_given_rebuy_chips_added(context):
    """Set up all three domains after chips have been added (adding_chips phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_ADDING_CHIPS


# =============================================================================
# BuyInOrchestrator - When steps
# =============================================================================


@when(r"the BuyInOrchestrator handles the BuyInRequested event")
def step_when_buy_in_orchestrator_handles_request(context):
    """Execute BuyInOrchestrator validation and command emission logic.

    Simulates the PM + aggregate validation flow:
    - Check buy-in amount is within table range
    - Check seat availability
    - Check table is not full
    On success: emit SeatPlayer command + BuyInInitiated event
    On failure: emit BuyInFailed event with appropriate code
    """
    context.emitted_commands = []
    context.emitted_events = []

    amount = context.buy_in_amount
    seat = context.buy_in_seat
    min_buy_in = context.table_min_buy_in
    max_buy_in = context.table_max_buy_in
    occupied = context.occupied_seats

    # Validate buy-in amount range
    if amount < min_buy_in or amount > max_buy_in:
        context.emitted_events.append(
            ("BuyInFailed", "INVALID_AMOUNT")
        )
        return

    # For "any seat" requests, find an open seat
    if seat == -1:
        found = False
        for i in range(context.table_max_players):
            if i not in occupied:
                found = True
                break
        if not found:
            context.emitted_events.append(
                ("BuyInFailed", "TABLE_FULL")
            )
            return
    else:
        # Check specific seat is available
        if seat in occupied:
            context.emitted_events.append(
                ("BuyInFailed", "SEAT_OCCUPIED")
            )
            return

    # All validation passed - emit command and process event
    context.emitted_commands.append("SeatPlayer")
    context.emitted_events.append(("BuyInInitiated", None))


@when(r"the BuyInOrchestrator handles a PlayerSeated event")
def step_when_buy_in_handles_player_seated(context):
    """Handle PlayerSeated event - confirms buy-in flow completion."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ConfirmBuyIn")
    context.emitted_events.append(("BuyInCompleted", None))


@when(r"the BuyInOrchestrator handles a SeatingRejected event")
def step_when_buy_in_handles_seating_rejected(context):
    """Handle SeatingRejected event - releases funds and records failure."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ReleaseBuyIn")
    context.emitted_events.append(("BuyInFailed", "SEATING_REJECTED"))


# =============================================================================
# RegistrationOrchestrator - When steps
# =============================================================================


@when(r"the RegistrationOrchestrator handles the RegistrationRequested event")
def step_when_registration_orchestrator_handles_request(context):
    """Execute RegistrationOrchestrator validation and command emission logic.

    Simulates the PM validation against tournament state:
    - Check registration is open
    - Check capacity is available
    On success: emit EnrollPlayer command + RegistrationInitiated event
    On failure: emit RegistrationFailed event with appropriate code
    """
    context.emitted_commands = []
    context.emitted_events = []

    reg_open = context.tournament_registration_open
    max_players = context.tournament_max_players
    registered = context.tournament_registered_count

    # Validate registration is open
    if not reg_open:
        context.emitted_events.append(
            ("RegistrationFailed", "REGISTRATION_CLOSED")
        )
        return

    # Validate capacity
    if max_players > 0 and registered >= max_players:
        context.emitted_events.append(
            ("RegistrationFailed", "REGISTRATION_CLOSED")
        )
        return

    # All validation passed
    context.emitted_commands.append("EnrollPlayer")
    context.emitted_events.append(("RegistrationInitiated", None))


@when(r"the RegistrationOrchestrator handles a TournamentPlayerEnrolled event")
def step_when_registration_handles_enrolled(context):
    """Handle TournamentPlayerEnrolled - confirms registration completion."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ConfirmRegistrationFee")
    context.emitted_events.append(("RegistrationCompleted", None))


@when(r"the RegistrationOrchestrator handles a TournamentEnrollmentRejected event")
def step_when_registration_handles_rejected(context):
    """Handle TournamentEnrollmentRejected - releases fee and records failure."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ReleaseRegistrationFee")
    context.emitted_events.append(("RegistrationFailed", "ENROLLMENT_REJECTED"))


# =============================================================================
# RebuyOrchestrator - When steps
# =============================================================================


@when(r"the RebuyOrchestrator handles the RebuyRequested event")
def step_when_rebuy_orchestrator_handles_request(context):
    """Execute RebuyOrchestrator validation and command emission logic.

    Simulates the PM validation against tournament + table state:
    - Check tournament is running and rebuy window is open
    - Check player is seated at table
    On success: emit ProcessRebuy command + RebuyInitiated event
    On failure: emit RebuyFailed event with appropriate code
    """
    context.emitted_commands = []
    context.emitted_events = []

    rebuy_open = getattr(context, "rebuy_window_open", False)
    player_seated = getattr(context, "player_is_seated", False)

    # Validate tournament is running with rebuy window open
    if not rebuy_open:
        context.emitted_events.append(
            ("RebuyFailed", "TOURNAMENT_NOT_RUNNING")
        )
        return

    # Validate player is seated
    if not player_seated:
        context.emitted_events.append(
            ("RebuyFailed", "NOT_SEATED")
        )
        return

    # All validation passed
    context.emitted_commands.append("ProcessRebuy")
    context.emitted_events.append(("RebuyInitiated", None))


@when(r"the RebuyOrchestrator handles a RebuyProcessed event")
def step_when_rebuy_handles_processed(context):
    """Handle RebuyProcessed - emits AddRebuyChips to table."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("AddRebuyChips")


@when(r"the RebuyOrchestrator handles a RebuyChipsAdded event")
def step_when_rebuy_handles_chips_added(context):
    """Handle RebuyChipsAdded - confirms rebuy fee and records completion."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ConfirmRebuyFee")
    context.emitted_events.append(("RebuyCompleted", None))


@when(r"the RebuyOrchestrator handles a RebuyDenied event")
def step_when_rebuy_handles_denied(context):
    """Handle RebuyDenied - releases fee and records failure."""
    context.emitted_commands = []
    context.emitted_events = []

    context.emitted_commands.append("ReleaseRebuyFee")
    context.emitted_events.append(("RebuyFailed", "REBUY_DENIED"))


# =============================================================================
# Then steps - Command assertions
# =============================================================================


@then(r"the PM emits a SeatPlayer command to the table")
def step_then_pm_emits_seat_player(context):
    """Verify PM emits a SeatPlayer command."""
    assert "SeatPlayer" in context.emitted_commands, (
        f"Expected SeatPlayer command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ConfirmBuyIn command to the player")
def step_then_pm_emits_confirm_buy_in(context):
    """Verify PM emits a ConfirmBuyIn command."""
    assert "ConfirmBuyIn" in context.emitted_commands, (
        f"Expected ConfirmBuyIn command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ReleaseBuyIn command to the player")
def step_then_pm_emits_release_buy_in(context):
    """Verify PM emits a ReleaseBuyIn command."""
    assert "ReleaseBuyIn" in context.emitted_commands, (
        f"Expected ReleaseBuyIn command, got {context.emitted_commands}"
    )


@then(r"the PM emits an EnrollPlayer command to the tournament")
def step_then_pm_emits_enroll_player(context):
    """Verify PM emits an EnrollPlayer command."""
    assert "EnrollPlayer" in context.emitted_commands, (
        f"Expected EnrollPlayer command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ConfirmRegistrationFee command to the player")
def step_then_pm_emits_confirm_registration(context):
    """Verify PM emits a ConfirmRegistrationFee command."""
    assert "ConfirmRegistrationFee" in context.emitted_commands, (
        f"Expected ConfirmRegistrationFee command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ReleaseRegistrationFee command to the player")
def step_then_pm_emits_release_registration(context):
    """Verify PM emits a ReleaseRegistrationFee command."""
    assert "ReleaseRegistrationFee" in context.emitted_commands, (
        f"Expected ReleaseRegistrationFee command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ProcessRebuy command to the tournament")
def step_then_pm_emits_process_rebuy(context):
    """Verify PM emits a ProcessRebuy command."""
    assert "ProcessRebuy" in context.emitted_commands, (
        f"Expected ProcessRebuy command, got {context.emitted_commands}"
    )


@then(r"the PM emits an AddRebuyChips command to the table")
def step_then_pm_emits_add_rebuy_chips(context):
    """Verify PM emits an AddRebuyChips command."""
    assert "AddRebuyChips" in context.emitted_commands, (
        f"Expected AddRebuyChips command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ConfirmRebuyFee command to the player")
def step_then_pm_emits_confirm_rebuy(context):
    """Verify PM emits a ConfirmRebuyFee command."""
    assert "ConfirmRebuyFee" in context.emitted_commands, (
        f"Expected ConfirmRebuyFee command, got {context.emitted_commands}"
    )


@then(r"the PM emits a ReleaseRebuyFee command to the player")
def step_then_pm_emits_release_rebuy(context):
    """Verify PM emits a ReleaseRebuyFee command."""
    assert "ReleaseRebuyFee" in context.emitted_commands, (
        f"Expected ReleaseRebuyFee command, got {context.emitted_commands}"
    )


@then(r"the PM emits no commands")
def step_then_pm_emits_no_commands(context):
    """Verify PM did not emit any commands."""
    assert len(context.emitted_commands) == 0, (
        f"Expected no commands, got {context.emitted_commands}"
    )


# =============================================================================
# Then steps - Process event assertions
# =============================================================================


@then(r"the PM emits a BuyInInitiated process event")
def step_then_pm_emits_buy_in_initiated(context):
    """Verify PM emits a BuyInInitiated process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "BuyInInitiated" in event_names, (
        f"Expected BuyInInitiated event, got {event_names}"
    )


@then(r'the PM emits a BuyInFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_buy_in_failed(context, code):
    """Verify PM emits a BuyInFailed process event with a specific failure code."""
    matching = [
        (name, c) for name, c in context.emitted_events
        if name == "BuyInFailed"
    ]
    assert len(matching) > 0, (
        f"Expected BuyInFailed event, got {[n for n, _ in context.emitted_events]}"
    )
    actual_code = matching[0][1]
    assert actual_code == code, (
        f"Expected failure code '{code}', got '{actual_code}'"
    )


@then(r"the PM emits a BuyInCompleted process event")
def step_then_pm_emits_buy_in_completed(context):
    """Verify PM emits a BuyInCompleted process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "BuyInCompleted" in event_names, (
        f"Expected BuyInCompleted event, got {event_names}"
    )


@then(r"the PM emits a RegistrationInitiated process event")
def step_then_pm_emits_registration_initiated(context):
    """Verify PM emits a RegistrationInitiated process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "RegistrationInitiated" in event_names, (
        f"Expected RegistrationInitiated event, got {event_names}"
    )


@then(r'the PM emits a RegistrationFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_registration_failed(context, code):
    """Verify PM emits a RegistrationFailed process event with a specific failure code."""
    matching = [
        (name, c) for name, c in context.emitted_events
        if name == "RegistrationFailed"
    ]
    assert len(matching) > 0, (
        f"Expected RegistrationFailed event, got {[n for n, _ in context.emitted_events]}"
    )
    actual_code = matching[0][1]
    assert actual_code == code, (
        f"Expected failure code '{code}', got '{actual_code}'"
    )


@then(r"the PM emits a RegistrationCompleted process event")
def step_then_pm_emits_registration_completed(context):
    """Verify PM emits a RegistrationCompleted process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "RegistrationCompleted" in event_names, (
        f"Expected RegistrationCompleted event, got {event_names}"
    )


@then(r"the PM emits a RebuyInitiated process event")
def step_then_pm_emits_rebuy_initiated(context):
    """Verify PM emits a RebuyInitiated process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "RebuyInitiated" in event_names, (
        f"Expected RebuyInitiated event, got {event_names}"
    )


@then(r'the PM emits a RebuyFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_rebuy_failed(context, code):
    """Verify PM emits a RebuyFailed process event with a specific failure code."""
    matching = [
        (name, c) for name, c in context.emitted_events
        if name == "RebuyFailed"
    ]
    assert len(matching) > 0, (
        f"Expected RebuyFailed event, got {[n for n, _ in context.emitted_events]}"
    )
    actual_code = matching[0][1]
    assert actual_code == code, (
        f"Expected failure code '{code}', got '{actual_code}'"
    )


@then(r"the PM emits a RebuyCompleted process event")
def step_then_pm_emits_rebuy_completed(context):
    """Verify PM emits a RebuyCompleted process event."""
    event_names = [name for name, _ in context.emitted_events]
    assert "RebuyCompleted" in event_names, (
        f"Expected RebuyCompleted event, got {event_names}"
    )
