"""Step definitions for tournament aggregate tests.

Uses class-based handler pattern: Tournament(event_book) is instantiated
from replayed events, and handler methods are invoked as methods. Guard
failures raise CommandRejectedError; rejection-as-event failures return an
EnrollmentRejected / RebuyDenied event.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp
from tournament.agg.handlers import Tournament

from angzarr_client.errors import CommandRejectedError
from angzarr_client.helpers import try_unpack, type_name_from_url
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import tournament_pb2 as tournament

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
            root=types.UUID(value=b"tournament-123"),
            domain="tournament",
        ),
        pages=pages,
    )


def _id_bytes(label: str) -> bytes:
    """Deterministic 16-byte id derived from a label."""
    if not label:
        return b""
    raw = label.encode("utf-8")
    return (raw + b"\x00" * 16)[:16]


def _ensure_events(context):
    if not hasattr(context, "events"):
        context.events = []


def _append_created(
    context,
    name: str,
    buy_in: int,
    starting_stack: int,
    max_players: int,
    min_players: int,
) -> None:
    """Append a TournamentCreated event to context history."""
    _ensure_events(context)
    event = tournament.TournamentCreated(
        name=name,
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=buy_in,
        starting_stack=starting_stack,
        max_players=max_players,
        min_players=min_players,
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_registration_opened(context) -> None:
    _ensure_events(context)
    event = tournament.RegistrationOpened(opened_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_player_enrolled(context, player_label: str) -> None:
    """Append a TournamentPlayerEnrolled event for the given player label.

    Uses the current TournamentCreated values (if any) to set fee_paid /
    starting_stack on the event.
    """
    _ensure_events(context)
    # Replay to get current buy_in / starting_stack
    book = _make_event_book(context.events)
    agg = Tournament(book)
    event = tournament.TournamentPlayerEnrolled(
        player_root=player_label.encode("utf-8"),
        fee_paid=agg.buy_in,
        starting_stack=agg.starting_stack,
        registration_number=len(agg.registered_players) + 1,
        enrolled_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_tournament_started(context) -> None:
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    event = tournament.TournamentStarted(
        total_players=len(agg.registered_players),
        total_prize_pool=agg.total_prize_pool,
        started_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


# Handler lookup
_HANDLER_MAP = {
    "create": "handle_create_tournament",
    "open": "handle_open_registration",
    "close": "handle_close_registration",
    "enroll": "handle_enroll_player",
    "rebuy": "handle_process_rebuy",
    "eliminate": "handle_eliminate_player",
    "pause": "handle_pause_tournament",
    "resume": "handle_resume_tournament",
    "start": "handle_start_tournament",
}


def _execute_handler(context, method_name: str, cmd):
    """Execute a command handler method on the Tournament aggregate."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)

    actual_name = _HANDLER_MAP.get(method_name, method_name)
    method = getattr(agg, actual_name)

    try:
        result_event = method(cmd)
        event_any = ProtoAny()
        event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
        result_page = types.EventPage(
            header=types.PageHeader(sequence=len(context.events)),
            event=event_any,
            created_at=make_timestamp(),
        )
        context.result = _make_event_book([result_page])
        context.result_event_any = event_any
        context.error = None
        context.agg = agg
    except CommandRejectedError as e:
        context.result = None
        context.result_event_any = None
        context.error = e
        context.error_message = str(e)


# --- Given steps ---


@given(r"no prior events for the tournament aggregate")
def step_given_no_prior_events(context):
    """Initialize with empty event history."""
    context.events = []


@given(
    r'a TournamentCreated event with name "(?P<name>[^"]*)" '
    r"buy_in (?P<buy_in>-?\d+) starting_stack (?P<starting_stack>-?\d+) "
    r"max_players (?P<max_players>-?\d+) min_players (?P<min_players>-?\d+)"
)
def step_given_tournament_created(
    context, name, buy_in, starting_stack, max_players, min_players
):
    """Add a TournamentCreated event to history."""
    _append_created(
        context,
        name=name,
        buy_in=int(buy_in),
        starting_stack=int(starting_stack),
        max_players=int(max_players),
        min_players=int(min_players),
    )


@given(r"a tournament with registration open")
def step_given_tournament_registration_open(context):
    """Seed a tournament with default config and registration opened."""
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=100,
        min_players=10,
    )
    _append_registration_opened(context)


@given(
    r"a tournament with max_players (?P<max_players>-?\d+) and "
    r"min_players (?P<min_players>-?\d+) and registration open"
)
def step_given_tournament_with_player_bounds_open(
    context, max_players, min_players
):
    """Seed a tournament with specific max/min player bounds and open registration."""
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=int(max_players),
        min_players=int(min_players),
    )
    _append_registration_opened(context)


@given(
    r"a tournament with min_players (?P<min_players>-?\d+) and "
    r"max_players (?P<max_players>-?\d+) and registration open"
)
def step_given_tournament_with_min_max_open(context, min_players, max_players):
    """Seed a tournament with specific min/max player bounds and open registration."""
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=int(max_players),
        min_players=int(min_players),
    )
    _append_registration_opened(context)


@given(r'a player "(?P<player_label>[^"]+)" enrolled')
def step_given_player_enrolled(context, player_label):
    """Append a TournamentPlayerEnrolled event for this player label."""
    _append_player_enrolled(context, player_label)


@given(
    r"a running tournament with min_players (?P<min_players>-?\d+) and "
    r"max_players (?P<max_players>-?\d+) and (?P<n>\d+) enrolled players"
)
def step_given_running_tournament_with_n_players(
    context, min_players, max_players, n
):
    """Seed a created+open+N-enrolled+started tournament."""
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=int(max_players),
        min_players=int(min_players),
    )
    _append_registration_opened(context)
    for i in range(int(n)):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)


# --- When steps ---


@when(
    r'I handle a CreateTournament command with name "(?P<name>[^"]*)" '
    r"buy_in (?P<buy_in>-?\d+) starting_stack (?P<starting_stack>-?\d+) "
    r"max_players (?P<max_players>-?\d+) min_players (?P<min_players>-?\d+)"
)
def step_when_create_tournament(
    context, name, buy_in, starting_stack, max_players, min_players
):
    cmd = tournament.CreateTournament(
        name=name,
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=int(buy_in),
        starting_stack=int(starting_stack),
        max_players=int(max_players),
        min_players=int(min_players),
    )
    _execute_handler(context, "create", cmd)


@when(r"I handle an OpenRegistration command")
def step_when_open_registration(context):
    cmd = tournament.OpenRegistration()
    _execute_handler(context, "open", cmd)


@when(r"I handle a CloseRegistration command")
def step_when_close_registration(context):
    cmd = tournament.CloseRegistration()
    _execute_handler(context, "close", cmd)


@when(
    r'I handle an EnrollPlayer command for player "(?P<player_label>[^"]*)" '
    r'reservation "(?P<res_label>[^"]*)"'
)
def step_when_enroll_player(context, player_label, res_label):
    cmd = tournament.EnrollPlayer(
        player_root=player_label.encode("utf-8") if player_label else b"",
        reservation_id=res_label.encode("utf-8") if res_label else b"",
    )
    _execute_handler(context, "enroll", cmd)


@when(r'I handle a ProcessRebuy command for player "(?P<player_label>[^"]*)"')
def step_when_process_rebuy(context, player_label):
    cmd = tournament.ProcessRebuy(
        player_root=player_label.encode("utf-8") if player_label else b"",
    )
    _execute_handler(context, "rebuy", cmd)


@when(r'I handle an EliminatePlayer command for player "(?P<player_label>[^"]*)"')
def step_when_eliminate_player(context, player_label):
    cmd = tournament.EliminatePlayer(
        player_root=player_label.encode("utf-8") if player_label else b"",
    )
    _execute_handler(context, "eliminate", cmd)


@when(r'I handle a PauseTournament command with reason "(?P<reason>[^"]*)"')
def step_when_pause_tournament(context, reason):
    cmd = tournament.PauseTournament(reason=reason)
    _execute_handler(context, "pause", cmd)


@when(r"I handle a ResumeTournament command")
def step_when_resume_tournament(context):
    cmd = tournament.ResumeTournament()
    _execute_handler(context, "resume", cmd)


@when(r"I handle a StartTournament command")
def step_when_start_tournament(context):
    cmd = tournament.StartTournament()
    _execute_handler(context, "start", cmd)


# --- Then steps ---


@then(r'the tournament event has name "(?P<name>[^"]*)"')
def step_then_event_has_name(context, name):
    event = try_unpack(context.result_event_any, tournament.TournamentCreated)
    assert event is not None, (
        f"Not a TournamentCreated event: {context.result_event_any.type_url}"
    )
    assert event.name == name, f"Expected name={name!r}, got {event.name!r}"


@then(r"the tournament event has buy_in (?P<buy_in>-?\d+)")
def step_then_event_has_buy_in(context, buy_in):
    event = try_unpack(context.result_event_any, tournament.TournamentCreated)
    assert event is not None
    assert event.buy_in == int(buy_in), (
        f"Expected buy_in={buy_in}, got {event.buy_in}"
    )


@then(r"the tournament event has starting_stack (?P<stack>-?\d+)")
def step_then_event_has_starting_stack(context, stack):
    event = try_unpack(context.result_event_any, tournament.TournamentCreated)
    assert event is not None
    assert event.starting_stack == int(stack), (
        f"Expected starting_stack={stack}, got {event.starting_stack}"
    )


@then(r'the tournament event has player_root "(?P<label>[^"]*)"')
def step_then_event_has_player_root(context, label):
    event_any = context.result_event_any
    event = (
        try_unpack(event_any, tournament.TournamentPlayerEnrolled)
        or try_unpack(event_any, tournament.TournamentEnrollmentRejected)
        or try_unpack(event_any, tournament.RebuyProcessed)
        or try_unpack(event_any, tournament.RebuyDenied)
        or try_unpack(event_any, tournament.PlayerEliminated)
    )
    assert event is not None, f"No player_root field on event: {event_any.type_url}"
    assert event.player_root == label.encode("utf-8"), (
        f"Expected player_root={label.encode('utf-8')!r}, got {event.player_root!r}"
    )


@then(r"the tournament event has fee_paid (?P<fee>-?\d+)")
def step_then_event_has_fee_paid(context, fee):
    event = try_unpack(
        context.result_event_any, tournament.TournamentPlayerEnrolled
    )
    assert event is not None, (
        f"Not a TournamentPlayerEnrolled event: {context.result_event_any.type_url}"
    )
    assert event.fee_paid == int(fee), (
        f"Expected fee_paid={fee}, got {event.fee_paid}"
    )


@then(r'the tournament event has reason containing "(?P<text>[^"]*)"')
def step_then_event_reason_contains(context, text):
    event_any = context.result_event_any
    event = try_unpack(
        event_any, tournament.TournamentEnrollmentRejected
    ) or try_unpack(event_any, tournament.RebuyDenied)
    assert event is not None, f"No reason field on event: {event_any.type_url}"
    assert text.lower() in event.reason.lower(), (
        f"Expected reason to contain {text!r}, got {event.reason!r}"
    )


@then(r"the tournament event has total_players (?P<n>-?\d+)")
def step_then_event_has_total_players(context, n):
    event = try_unpack(context.result_event_any, tournament.TournamentStarted)
    assert event is not None, (
        f"Not a TournamentStarted event: {context.result_event_any.type_url}"
    )
    assert event.total_players == int(n), (
        f"Expected total_players={n}, got {event.total_players}"
    )


@then(r'the command fails with status "(?P<status>[^"]+)"')
def step_then_command_fails_with_status(context, status):
    assert context.error is not None, "Expected command to fail but it succeeded"
    assert hasattr(
        context.error, "status_code"
    ), f"Error {type(context.error).__name__} has no status_code attribute"
    assert context.error.status_code == status, (
        f"Expected status {status}, got {context.error.status_code}"
    )


@then(r'the error message contains "(?P<text>[^"]+)"')
def step_then_error_contains(context, text):
    assert context.error is not None, "Expected an error but got success"
    assert text.lower() in context.error_message.lower(), (
        f"Expected error to contain {text!r}, got {context.error_message!r}"
    )
