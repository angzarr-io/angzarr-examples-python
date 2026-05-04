"""Step definitions for table aggregate tests."""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp
from table.agg.handlers import Table
from tests.helpers import uuid_for

from angzarr_client.errors import CommandRejectedError
from angzarr_client.helpers import type_name_from_url
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import table_pb2 as table

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, seq: int = 0) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")
    return types.EventPage(
        header=types.PageHeader(sequence=seq),
        event=event_any,
        created_at=make_timestamp(),
    )


def _make_event_book(pages):
    """Create an EventBook from a list of EventPages."""
    return types.EventBook(
        cover=types.Cover(
            root=types.UUID(value=b"table-123"),
            domain="table",
        ),
        pages=pages,
    )


# --- Given steps ---


@given(r"no prior events for the table aggregate")
def step_given_no_prior_events(context):
    """Initialize with empty event history."""
    context.events = []


@given(r'a TableCreated event for "(?P<name>[^"]+)"')
def step_given_table_created(context, name):
    """Add a TableCreated event to history."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.TableCreated(
        table_name=name,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=1000,
        max_players=9,
        action_timeout_seconds=30,
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a TableCreated event for "(?P<name>[^"]+)" with min_buy_in (?P<min_buy_in>\d+)'
)
def step_given_table_created_min_buy_in(context, name, min_buy_in):
    """Add a TableCreated event with specific min_buy_in."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.TableCreated(
        table_name=name,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=5,
        big_blind=10,
        min_buy_in=int(min_buy_in),
        max_buy_in=1000,
        max_players=9,
        action_timeout_seconds=30,
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a TableCreated event for "(?P<name>[^"]+)" with max_players (?P<max_players>\d+)'
)
def step_given_table_created_max_players(context, name, max_players):
    """Add a TableCreated event with specific max_players."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.TableCreated(
        table_name=name,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=1000,
        max_players=int(max_players),
        action_timeout_seconds=30,
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r'a PlayerJoined event for player "(?P<player_id>[^"]+)" at seat (?P<seat>\d+)')
def step_given_player_joined(context, player_id, seat):
    """Add a PlayerJoined event with default stack."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.PlayerJoined(
        player_root=uuid_for(player_id),
        seat_position=int(seat),
        buy_in_amount=500,
        stack=500,
        joined_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a PlayerJoined event for player "(?P<player_id>[^"]+)" at seat (?P<seat>\d+) with stack (?P<stack>\d+)'
)
def step_given_player_joined_with_stack(context, player_id, seat, stack):
    """Add a PlayerJoined event with specific stack."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.PlayerJoined(
        player_root=uuid_for(player_id),
        seat_position=int(seat),
        buy_in_amount=int(stack),
        stack=int(stack),
        joined_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r"a HandStarted event for hand (?P<hand_num>\d+)")
def step_given_hand_started(context, hand_num):
    """Add a HandStarted event."""
    if not hasattr(context, "events"):
        context.events = []

    # Get seated players from prior events to build hand root
    event_book = _make_event_book(context.events)
    agg = Table(event_book)

    active_players = []
    for pos, seat in agg.seats.items():
        active_players.append(
            table.SeatSnapshot(
                position=pos,
                player_root=seat.player_root,
                stack=seat.stack,
            )
        )

    event = table.HandStarted(
        hand_root=uuid_for(f"hand-{hand_num}"),
        hand_number=int(hand_num),
        dealer_position=0,
        small_blind_position=0,
        big_blind_position=1,
        game_variant=agg.game_variant if agg.exists else poker_types.TEXAS_HOLDEM,
        small_blind=agg.small_blind if agg.exists else 5,
        big_blind=agg.big_blind if agg.exists else 10,
        started_at=make_timestamp(),
    )
    event.active_players.extend(active_players)
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r"a HandStarted event for hand (?P<hand_num>\d+) with dealer at seat (?P<seat>\d+)"
)
def step_given_hand_started_with_dealer(context, hand_num, seat):
    """Add a HandStarted event with specific dealer position."""
    if not hasattr(context, "events"):
        context.events = []

    # Get seated players from prior events
    event_book = _make_event_book(context.events)
    agg = Table(event_book)

    active_players = []
    for pos, seat_state in agg.seats.items():
        active_players.append(
            table.SeatSnapshot(
                position=pos,
                player_root=seat_state.player_root,
                stack=seat_state.stack,
            )
        )

    # Derive SB/BB positions from the seated players so subsequent
    # dead-button advancement starts from a coherent prior state.
    active_positions = sorted(p.position for p in active_players)
    dealer_pos = int(seat)
    if dealer_pos in active_positions:
        d_idx = active_positions.index(dealer_pos)
    else:
        d_idx = 0
    if len(active_positions) == 2:
        sb_pos = active_positions[d_idx]
        bb_pos = active_positions[(d_idx + 1) % 2]
    else:
        sb_pos = active_positions[(d_idx + 1) % len(active_positions)]
        bb_pos = active_positions[(d_idx + 2) % len(active_positions)]

    event = table.HandStarted(
        hand_root=uuid_for(f"hand-{hand_num}"),
        hand_number=int(hand_num),
        dealer_position=dealer_pos,
        small_blind_position=sb_pos,
        big_blind_position=bb_pos,
        game_variant=agg.game_variant if agg.exists else poker_types.TEXAS_HOLDEM,
        small_blind=agg.small_blind if agg.exists else 5,
        big_blind=agg.big_blind if agg.exists else 10,
        started_at=make_timestamp(),
    )
    event.active_players.extend(active_players)
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r"a HandEnded event for hand (?P<hand_num>\d+)")
def step_given_hand_ended(context, hand_num):
    """Add a HandEnded event."""
    if not hasattr(context, "events"):
        context.events = []

    event = table.HandEnded(
        hand_root=uuid_for(f"hand-{hand_num}"),
        ended_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


# --- When steps ---


_HANDLER_MAP = {
    "create": "handle_create_table",
    "join": "handle_join_table",
    "leave": "handle_leave_table",
    "start_hand": "handle_start_hand",
    "end_hand": "handle_end_hand",
    "seat_player": "handle_seat_player",
    "add_rebuy_chips": "handle_add_rebuy_chips",
}


def _id_bytes(label: str) -> bytes:
    """Deterministic 16-byte id derived from a label."""
    return uuid_for(label)


def _execute_handler(context, method_name: str, cmd):
    """Execute a command handler method on the Table aggregate."""
    event_book = _make_event_book(context.events if hasattr(context, "events") else [])
    agg = Table(event_book)

    try:
        actual_name = _HANDLER_MAP.get(method_name, method_name)
        method = getattr(agg, actual_name)
        result_event = method(cmd)
        # Get the event book with new events (stateful path appends via _emit).
        result_book = agg.event_book()
        context.result = result_book
        context.error = None
        # Prefer the explicitly returned event (for handlers like seat_player
        # that return rejection events with raising).
        if result_event is not None:
            event_any = ProtoAny()
            event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
            context.result_event_any = event_any
            # Rebuild result book to contain only the new event for
            # single-event assertion steps.
            context.result = _make_event_book(
                [
                    make_event_page(
                        result_event,
                        seq=len(context.events) if hasattr(context, "events") else 0,
                    )
                ]
            )
        elif result_book.pages:
            context.result_event_any = result_book.pages[-1].event
        # Store aggregate for state access
        context.agg = agg
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


def _stamp_scenario_cover(context, err):
    """Mirror dispatch-boundary cover stamping for direct-call unit tests."""
    if err is None or getattr(err, "cover", None) is not None:
        return
    cover = getattr(context, "command_cover", None)
    if cover is not None:
        err.cover = cover


@when(
    r'I handle a CreateTable command with name "(?P<name>[^"]*)" and variant "(?P<variant>[^"]+)":'
)
def step_when_create_table(context, name, variant):
    """Handle CreateTable command with datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)

    cmd = table.CreateTable(
        table_name=name,
        game_variant=game_variant,
        small_blind=int(row.get("small_blind", 5)),
        big_blind=int(row.get("big_blind", 10)),
        min_buy_in=int(row.get("min_buy_in", 200)),
        max_buy_in=int(row.get("max_buy_in", 1000)),
        max_players=int(row.get("max_players", 9)),
        action_timeout_seconds=int(row.get("action_timeout_seconds", 30)),
    )
    _execute_handler(context, "create", cmd)


@when(
    r'I handle a JoinTable command for player "(?P<player_id>[^"]*)" at seat (?P<seat>-?\d+) with buy-in (?P<buy_in_amt>\d+)'
)
def step_when_join_table(context, player_id, seat, buy_in_amt):
    """Handle JoinTable command."""
    cmd = table.JoinTable(
        player_root=uuid_for(player_id) if player_id else b"",
        preferred_seat=int(seat),
        buy_in_amount=int(buy_in_amt),
    )
    _execute_handler(context, "join", cmd)


@when(r'I handle a LeaveTable command for player "(?P<player_id>[^"]*)"')
def step_when_leave_table(context, player_id):
    """Handle LeaveTable command."""
    cmd = table.LeaveTable(
        player_root=uuid_for(player_id) if player_id else b"",
    )
    _execute_handler(context, "leave", cmd)


@when(r"I handle a StartHand command")
def step_when_start_hand(context):
    """Handle StartHand command."""
    cmd = table.StartHand()
    _execute_handler(context, "start_hand", cmd)


@when(
    r'I handle an EndHand command with winner "(?P<winner>[^"]+)" winning (?P<amount>\d+)'
)
def step_when_end_hand(context, winner, amount):
    """Handle EndHand command."""
    # Get current hand root from aggregate state
    event_book = _make_event_book(context.events if hasattr(context, "events") else [])
    agg = Table(event_book)

    cmd = table.EndHand(
        hand_root=agg.current_hand_root,
    )
    cmd.results.append(
        table.PotResult(
            winner_root=uuid_for(winner),
            amount=int(amount),
            pot_type="main",
        )
    )
    _execute_handler(context, "end_hand", cmd)


@when(r"I handle an EndHand command with results:")
def step_when_end_hand_with_results(context):
    """Handle EndHand command with DataTable of results."""
    # Get current hand root from aggregate state
    event_book = _make_event_book(context.events if hasattr(context, "events") else [])
    agg = Table(event_book)

    cmd = table.EndHand(
        hand_root=agg.current_hand_root,
    )
    # Process DataTable rows - add all changes to results
    # Note: Using PotResult for all changes (even negative) to track stack_changes
    for row in context.table:
        player_id = row["player"]
        change = int(row["change"])
        cmd.results.append(
            table.PotResult(
                winner_root=uuid_for(player_id),
                amount=change,
                pot_type="main",
            )
        )
    _execute_handler(context, "end_hand", cmd)


@when(r"I rebuild the table state")
def step_when_rebuild_state(context):
    """Rebuild table state from events."""
    event_book = _make_event_book(context.events)
    context.agg = Table(event_book)


# --- Then steps ---


@then(r"the result is a (?P<event_type>\w+) event")
def step_then_result_is_event(context, event_type):
    """Verify the result event type."""
    assert (
        context.result is not None
    ), f"Expected {event_type} event but got error: {context.error}"
    assert context.result.pages, "No event pages in result"
    event_any = context.result.pages[0].event
    actual_type = type_name_from_url(event_any.type_url)
    assert actual_type == event_type, f"Expected {event_type} but got {actual_type}"


@then(r'the table event has table_name "(?P<name>[^"]+)"')
def step_then_event_has_table_name(context, name):
    """Verify the event table_name field."""
    event = table.TableCreated()
    context.result_event_any.Unpack(event)
    assert (
        event.table_name == name
    ), f"Expected table_name={name}, got {event.table_name}"


@then(r'the table event has game_variant "(?P<variant>[^"]+)"')
def step_then_event_has_game_variant(context, variant):
    """Verify the event game_variant field."""
    event = table.TableCreated()
    context.result_event_any.Unpack(event)
    expected = getattr(poker_types, variant)
    assert (
        event.game_variant == expected
    ), f"Expected game_variant={variant}, got {event.game_variant}"


@then(r"the table event has small_blind (?P<amount>\d+)")
def step_then_event_has_small_blind(context, amount):
    """Verify the event small_blind field."""
    event = table.TableCreated()
    context.result_event_any.Unpack(event)
    assert event.small_blind == int(
        amount
    ), f"Expected small_blind={amount}, got {event.small_blind}"


@then(r"the table event has big_blind (?P<amount>\d+)")
def step_then_event_has_big_blind(context, amount):
    """Verify the event big_blind field."""
    event = table.TableCreated()
    context.result_event_any.Unpack(event)
    assert event.big_blind == int(
        amount
    ), f"Expected big_blind={amount}, got {event.big_blind}"


@then(r"the table event has seat_position (?P<pos>\d+)")
def step_then_event_has_seat_position(context, pos):
    """Verify the event seat_position field."""
    event = table.PlayerJoined()
    context.result_event_any.Unpack(event)
    assert event.seat_position == int(
        pos
    ), f"Expected seat_position={pos}, got {event.seat_position}"


@then(r"the table event has buy_in_amount (?P<amount>\d+)")
def step_then_event_has_buy_in_amount(context, amount):
    """Verify the event buy_in_amount field."""
    event = table.PlayerJoined()
    context.result_event_any.Unpack(event)
    assert event.buy_in_amount == int(
        amount
    ), f"Expected buy_in_amount={amount}, got {event.buy_in_amount}"


@then(r"the table event has chips_cashed_out (?P<amount>\d+)")
def step_then_event_has_chips_cashed_out(context, amount):
    """Verify the event chips_cashed_out field."""
    event = table.PlayerLeft()
    context.result_event_any.Unpack(event)
    assert event.chips_cashed_out == int(
        amount
    ), f"Expected chips_cashed_out={amount}, got {event.chips_cashed_out}"


@then(r"the table event has hand_number (?P<num>\d+)")
def step_then_event_has_hand_number(context, num):
    """Verify the event hand_number field."""
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.hand_number == int(
        num
    ), f"Expected hand_number={num}, got {event.hand_number}"


@then(r"the table event has (?P<count>\d+) active_players")
def step_then_event_has_active_players(context, count):
    """Verify the event active_players count."""
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert len(event.active_players) == int(
        count
    ), f"Expected {count} active_players, got {len(event.active_players)}"


@then(r"the table event has dealer_position (?P<pos>\d+)")
def step_then_event_has_dealer_position(context, pos):
    """Verify the event dealer_position field."""
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.dealer_position == int(
        pos
    ), f"Expected dealer_position={pos}, got {event.dealer_position}"


@then(r'player "(?P<player_id>[^"]+)" stack change is (?P<amount>-?\d+)')
def step_then_player_stack_change(context, player_id, amount):
    """Verify the player's stack change in HandEnded event."""
    event = table.HandEnded()
    context.result_event_any.Unpack(event)
    player_hex = uuid_for(player_id).hex()
    assert player_hex in event.stack_changes, f"No stack change for {player_id}"
    assert event.stack_changes[player_hex] == int(
        amount
    ), f"Expected stack change {amount}, got {event.stack_changes[player_hex]}"


@then(r'the command fails with status "(?P<status>[^"]+)"')
def step_then_command_fails(context, status):
    """Verify the command failed with expected status."""
    assert context.error is not None, "Expected command to fail but it succeeded"
    assert hasattr(
        context.error, "status_code"
    ), f"Error {type(context.error).__name__} has no status_code attribute"
    assert (
        context.error.status_code == status
    ), f"Expected status {status}, got {context.error.status_code}"


@then(r'the error message contains "(?P<text>[^"]+)"')
def step_then_error_contains(context, text):
    """Verify the error message contains expected text."""
    assert context.error is not None, "Expected an error but got success"
    assert (
        text.lower() in context.error_message.lower()
    ), f"Expected error to contain '{text}', got '{context.error_message}'"


@then(r"the table state has (?P<count>\d+) players")
def step_then_state_has_players(context, count):
    """Verify the table state player count."""
    assert context.agg is not None, "No table aggregate"
    assert context.agg.player_count == int(
        count
    ), f"Expected {count} players, got {context.agg.player_count}"


@then(r'the table state has seat (?P<seat>\d+) occupied by "(?P<player_id>[^"]+)"')
def step_then_state_seat_occupied(context, seat, player_id):
    """Verify the table state seat occupancy."""
    assert context.agg is not None, "No table aggregate"
    seat_state = context.agg.get_seat(int(seat))
    assert seat_state is not None, f"Seat {seat} not occupied"
    expected_player = uuid_for(player_id)
    assert (
        seat_state.player_root == expected_player
    ), f"Expected {player_id} at seat {seat}, got {seat_state.player_root}"


@then(r'the table state has status "(?P<status>[^"]+)"')
def step_then_state_has_status(context, status):
    """Verify the table state status."""
    assert context.agg is not None, "No table aggregate"
    assert (
        context.agg.status == status
    ), f"Expected status={status}, got {context.agg.status}"


@then(r"the table state has hand_count (?P<count>\d+)")
def step_then_state_has_hand_count(context, count):
    """Verify the table state hand_count."""
    assert context.agg is not None, "No table aggregate"
    assert context.agg.hand_count == int(
        count
    ), f"Expected hand_count={count}, got {context.agg.hand_count}"


# =============================================================================
# Phase 2 additions: richer Table coverage + SeatPlayer / AddRebuyChips
# =============================================================================


# --- Additional Given steps ---


@given(r'a PlayerSatOut event for player "(?P<player_id>[^"]+)"')
def step_given_player_sat_out(context, player_id):
    """Add a PlayerSatOut event to the history."""
    if not hasattr(context, "events"):
        context.events = []
    event = table.PlayerSatOut(player_root=uuid_for(player_id))
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r'a PlayerSatIn event for player "(?P<player_id>[^"]+)"')
def step_given_player_sat_in(context, player_id):
    """Add a PlayerSatIn event to the history."""
    if not hasattr(context, "events"):
        context.events = []
    event = table.PlayerSatIn(player_root=uuid_for(player_id))
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a ChipsAdded event for player "(?P<player_id>[^"]+)" with new_stack (?P<new_stack>\d+)'
)
def step_given_chips_added(context, player_id, new_stack):
    """Add a ChipsAdded event to the history."""
    if not hasattr(context, "events"):
        context.events = []
    event = table.ChipsAdded(
        player_root=uuid_for(player_id),
        new_stack=int(new_stack),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


# --- Additional When steps ---


@when(r"I handle an EndHand command with mismatched hand_root")
def step_when_end_hand_mismatch(context):
    """Handle EndHand with a deliberately wrong hand_root to trigger
    the "Hand root mismatch" rejection."""
    cmd = table.EndHand(hand_root=b"\x99\x99\x99")
    _execute_handler(context, "end_hand", cmd)


@when(
    r'I start a hand and end it with winner "(?P<winner>[^"]+)" winning (?P<amount>\d+)'
)
def step_when_start_and_end_hand(context, winner, amount):
    """Run StartHand then EndHand in sequence, re-using the emitted hand_root.

    Exercises the full end-to-end lifecycle within a single scenario.
    """
    events = context.events if hasattr(context, "events") else []
    agg = Table(_make_event_book(events))

    start_event = agg.handle_start_hand(table.StartHand())
    end_cmd = table.EndHand(hand_root=start_event.hand_root)
    end_cmd.results.append(
        table.PotResult(
            winner_root=uuid_for(winner),
            amount=int(amount),
            pot_type="main",
        )
    )
    try:
        end_event = agg.handle_end_hand(end_cmd)
        event_any = ProtoAny()
        event_any.Pack(end_event, type_url_prefix="type.googleapis.com/")
        context.result_event_any = event_any
        context.result = _make_event_book(
            [make_event_page(end_event, seq=len(events) + 1)]
        )
        context.error = None
        context.agg = agg
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


@when(
    r'I handle a SeatPlayer command for player "(?P<player_id>[^"]*)" '
    r'reservation "(?P<res>[^"]+)" seat (?P<seat>-?\d+) amount (?P<amount>\d+)'
)
def step_when_seat_player(context, player_id, res, seat, amount):
    """Handle SeatPlayer orchestration command."""
    cmd = buy_in.SeatPlayer(
        player_root=uuid_for(player_id) if player_id else b"",
        reservation_id=_id_bytes(res),
        seat=int(seat),
        amount=int(amount),
    )
    _execute_handler(context, "seat_player", cmd)


@when(
    r'I handle an AddRebuyChips command for player "(?P<player_id>[^"]*)" '
    r'reservation "(?P<res>[^"]+)" seat (?P<seat>-?\d+) amount (?P<amount>-?\d+)'
)
def step_when_add_rebuy_chips(context, player_id, res, seat, amount):
    """Handle AddRebuyChips orchestration command."""
    cmd = rebuy.AddRebuyChips(
        player_root=uuid_for(player_id) if player_id else b"",
        reservation_id=_id_bytes(res),
        seat=int(seat),
        amount=int(amount),
    )
    _execute_handler(context, "add_rebuy_chips", cmd)


# --- Additional Then steps ---


@then(r"the small_blind_position equals the dealer_position")
def step_then_sb_equals_dealer(context):
    """Heads-up: dealer posts SB."""
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.small_blind_position == event.dealer_position, (
        f"Expected SB==dealer, got SB={event.small_blind_position} "
        f"dealer={event.dealer_position}"
    )


@then(r"the small_blind_position differs from the dealer_position")
def step_then_sb_differs_from_dealer(context):
    """3+ players: SB is left of dealer, so must differ."""
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert (
        event.small_blind_position != event.dealer_position
    ), f"Expected SB!=dealer, both are {event.small_blind_position}"


@then(r'the table state has table_id "(?P<table_id>[^"]+)"')
def step_then_state_table_id(context, table_id):
    assert context.agg is not None, "No table aggregate"
    assert (
        context.agg.table_id == table_id
    ), f"Expected table_id={table_id!r}, got {context.agg.table_id!r}"


@then(r"the table state is full")
def step_then_state_is_full(context):
    assert context.agg is not None, "No table aggregate"
    assert context.agg.is_full, "Expected table to be full"


@then(r"the table state has (?P<count>\d+) active_players")
def step_then_state_active_players(context, count):
    assert context.agg is not None, "No table aggregate"
    assert context.agg.active_player_count == int(
        count
    ), f"Expected {count} active_players, got {context.agg.active_player_count}"


@then(r"the table state has current_hand_root empty")
def step_then_state_current_hand_root_empty(context):
    assert context.agg is not None, "No table aggregate"
    assert (
        context.agg.current_hand_root == b""
    ), f"Expected empty current_hand_root, got {context.agg.current_hand_root!r}"


@then(r"the table state seat (?P<seat>\d+) has stack (?P<stack>\d+)")
def step_then_state_seat_stack(context, seat, stack):
    assert context.agg is not None, "No table aggregate"
    s = context.agg.get_seat(int(seat))
    assert s is not None, f"Seat {seat} is empty"
    assert s.stack == int(stack), f"Expected stack={stack}, got {s.stack}"


# --- Seating event (PlayerSeated / SeatingRejected) assertions ---


@then(r"the seating event has seat_position (?P<pos>\d+)")
def step_then_seating_seat_position(context, pos):
    event = buy_in.PlayerSeated()
    context.result_event_any.Unpack(event)
    assert event.seat_position == int(
        pos
    ), f"Expected seat_position={pos}, got {event.seat_position}"


@then(r"the seating event has stack (?P<stack>\d+)")
def step_then_seating_stack(context, stack):
    event = buy_in.PlayerSeated()
    context.result_event_any.Unpack(event)
    assert event.stack == int(stack), f"Expected stack={stack}, got {event.stack}"


@then(r'the seating rejection reason contains "(?P<text>[^"]+)"')
def step_then_seating_rejection_reason(context, text):
    event = buy_in.SeatingRejected()
    context.result_event_any.Unpack(event)
    assert (
        text.lower() in event.reason.lower()
    ), f"Expected reason to contain {text!r}, got {event.reason!r}"


# --- Rebuy event assertions ---


@then(r"the rebuy event has amount (?P<amount>\d+)")
def step_then_rebuy_amount(context, amount):
    event = rebuy.RebuyChipsAdded()
    context.result_event_any.Unpack(event)
    assert event.amount == int(amount), f"Expected amount={amount}, got {event.amount}"


@then(r"the rebuy event has new_stack (?P<stack>\d+)")
def step_then_rebuy_new_stack(context, stack):
    event = rebuy.RebuyChipsAdded()
    context.result_event_any.Unpack(event)
    assert event.new_stack == int(
        stack
    ), f"Expected new_stack={stack}, got {event.new_stack}"


@then(r"the rebuy event has seat (?P<seat>\d+)")
def step_then_rebuy_seat(context, seat):
    event = rebuy.RebuyChipsAdded()
    context.result_event_any.Unpack(event)
    assert event.seat == int(seat), f"Expected seat={seat}, got {event.seat}"


# --- Dead button rule (TDA Rule 6) ----------------------------------------


@given(
    r'player "(?P<player_id>[^"]+)" busted at seat (?P<seat>\d+) during '
    r"hand (?P<hand_num>\d+)"
)
def step_given_player_busted(context, player_id, seat, hand_num):
    """A player who busted during hand N was a participant in hand N's
    blind structure; their seat is freed before the next StartHand.

    To reflect this in the event stream we splice a PlayerJoined event
    immediately before the HandStarted event for hand N (so the blind
    positions of that prior hand can be re-derived to include the
    busted player) and emit a PlayerLeft after the existing HandEnded.
    """
    if not hasattr(context, "events"):
        context.events = []

    seat_pos = int(seat)
    target_hand = int(hand_num)
    # Inject PlayerJoined retroactively before the matching HandStarted.
    new_pages = []
    inserted = False
    for page in context.events:
        if not inserted and page.event.Is(table.HandStarted.DESCRIPTOR):
            hs = table.HandStarted()
            page.event.Unpack(hs)
            if hs.hand_number == target_hand:
                join = table.PlayerJoined(
                    player_root=uuid_for(player_id),
                    seat_position=seat_pos,
                    buy_in_amount=500,
                    joined_at=make_timestamp(),
                )
                new_pages.append(make_event_page(join, seq=len(new_pages)))
                # Re-derive the blind positions of this HandStarted
                # accounting for the inserted player.
                positions = sorted([seat_pos] + [p.position for p in hs.active_players])
                d_pos = hs.dealer_position
                d_idx = positions.index(d_pos) if d_pos in positions else 0
                if len(positions) == 2:
                    sb_pos = positions[d_idx]
                    bb_pos = positions[(d_idx + 1) % 2]
                else:
                    sb_pos = positions[(d_idx + 1) % len(positions)]
                    bb_pos = positions[(d_idx + 2) % len(positions)]
                hs.small_blind_position = sb_pos
                hs.big_blind_position = bb_pos
                # Add the busted player to active_players for replay
                # symmetry.
                hs.active_players.append(
                    table.SeatSnapshot(
                        position=seat_pos,
                        player_root=uuid_for(player_id),
                        stack=500,
                    )
                )
                # Repack
                new_page = make_event_page(hs, seq=len(new_pages))
                new_pages.append(new_page)
                inserted = True
                continue
        # Re-sequence pages we keep so PageHeader.sequence stays dense.
        if page.event.Is(table.HandStarted.DESCRIPTOR):
            hs = table.HandStarted()
            page.event.Unpack(hs)
            new_pages.append(make_event_page(hs, seq=len(new_pages)))
        elif page.event.Is(table.HandEnded.DESCRIPTOR):
            he = table.HandEnded()
            page.event.Unpack(he)
            new_pages.append(make_event_page(he, seq=len(new_pages)))
        elif page.event.Is(table.TableCreated.DESCRIPTOR):
            tc = table.TableCreated()
            page.event.Unpack(tc)
            new_pages.append(make_event_page(tc, seq=len(new_pages)))
        elif page.event.Is(table.PlayerJoined.DESCRIPTOR):
            pj = table.PlayerJoined()
            page.event.Unpack(pj)
            new_pages.append(make_event_page(pj, seq=len(new_pages)))
        elif page.event.Is(table.PlayerLeft.DESCRIPTOR):
            pl = table.PlayerLeft()
            page.event.Unpack(pl)
            new_pages.append(make_event_page(pl, seq=len(new_pages)))
        else:
            new_pages.append(page)

    # Append PlayerLeft for the busted player.
    left = table.PlayerLeft(
        player_root=uuid_for(player_id),
        seat_position=seat_pos,
        chips_cashed_out=0,
        left_at=make_timestamp(),
    )
    new_pages.append(make_event_page(left, seq=len(new_pages)))
    context.events = new_pages


@given(
    r'big_blind_position on hand (?P<hand_num>\d+) was player "(?P<player_id>[^"]+)"'
)
def step_given_prev_bb_was(context, hand_num, player_id):
    """Annotate the previous BB occupant for assertions in EU-0578."""
    context.prev_bb_player = player_id


@then(r"the small_blind_position is seat (?P<seat>\d+)")
def step_then_sb_position(context, seat):
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.small_blind_position == int(
        seat
    ), f"Expected SB at seat {seat}, got {event.small_blind_position}"


@then(r"the big_blind_position is seat (?P<seat>\d+)")
def step_then_bb_position(context, seat):
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.big_blind_position == int(
        seat
    ), f"Expected BB at seat {seat}, got {event.big_blind_position}"


@then(r"the dealer_position is seat (?P<seat>\d+)")
def step_then_dealer_seat(context, seat):
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    assert event.dealer_position == int(
        seat
    ), f"Expected dealer at seat {seat}, got {event.dealer_position}"


@then(r'the player at the big_blind_position is not "(?P<player_id>[^"]+)"')
def step_then_bb_is_not(context, player_id):
    """Assert the player at the new BB position is NOT the same player
    who held BB on the prior hand. Look up who's seated at the new BB
    in the active_players snapshot of the new HandStarted event.
    """
    event = table.HandStarted()
    context.result_event_any.Unpack(event)
    excluded_root = uuid_for(player_id)
    bb_pos = event.big_blind_position
    bb_player = next(
        (p.player_root for p in event.active_players if p.position == bb_pos),
        None,
    )
    assert bb_player is not None, f"No active player found at BB position {bb_pos}"
    assert bb_player != excluded_root, (
        f"BB position {bb_pos} is occupied by {player_id}, but the test "
        f"requires it to be a DIFFERENT player from the prior hand"
    )
