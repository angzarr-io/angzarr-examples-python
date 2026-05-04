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
from tests.helpers import uuid_for

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
    return uuid_for(label)


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
        player_root=uuid_for(player_label),
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
        # Accumulate the emitted event so chained When steps see it.
        context.events.append(result_page)
        context.agg = agg
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.result_event_any = None
        context.error = e
        context.error_message = str(e)


def _stamp_scenario_cover(context, err):
    """Mirror dispatch-boundary cover stamping for direct-call unit tests."""
    if err is None or getattr(err, "cover", None) is not None:
        return
    cover = getattr(context, "command_cover", None)
    if cover is not None:
        err.cover = cover


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
def step_given_tournament_with_player_bounds_open(context, max_players, min_players):
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
def step_given_running_tournament_with_n_players(context, min_players, max_players, n):
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
        player_root=uuid_for(player_label) if player_label else b"",
        reservation_id=uuid_for(res_label) if res_label else b"",
    )
    _execute_handler(context, "enroll", cmd)


@when(r'I handle a ProcessRebuy command for player "(?P<player_label>[^"]*)"')
def step_when_process_rebuy(context, player_label):
    cmd = tournament.ProcessRebuy(
        player_root=uuid_for(player_label) if player_label else b"",
    )
    _execute_handler(context, "rebuy", cmd)


@when(r'I handle an EliminatePlayer command for player "(?P<player_label>[^"]*)"')
def step_when_eliminate_player(context, player_label):
    cmd = tournament.EliminatePlayer(
        player_root=uuid_for(player_label) if player_label else b"",
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
    assert (
        event is not None
    ), f"Not a TournamentCreated event: {context.result_event_any.type_url}"
    assert event.name == name, f"Expected name={name!r}, got {event.name!r}"


@then(r"the tournament event has buy_in (?P<buy_in>-?\d+)")
def step_then_event_has_buy_in(context, buy_in):
    event = try_unpack(context.result_event_any, tournament.TournamentCreated)
    assert event is not None
    assert event.buy_in == int(buy_in), f"Expected buy_in={buy_in}, got {event.buy_in}"


@then(r"the tournament event has starting_stack (?P<stack>-?\d+)")
def step_then_event_has_starting_stack(context, stack):
    """starting_stack is on TournamentCreated and TournamentPlayerEnrolled
    — try both event types so this step works for either context."""
    for cls in (tournament.TournamentCreated, tournament.TournamentPlayerEnrolled):
        event = try_unpack(context.result_event_any, cls)
        if event is not None:
            assert event.starting_stack == int(
                stack
            ), f"Expected starting_stack={stack}, got {event.starting_stack}"
            return
    raise AssertionError("event has no starting_stack field")


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
    assert event.player_root == uuid_for(
        label
    ), f"Expected player_root={uuid_for(label)!r}, got {event.player_root!r}"


@then(r"the tournament event has fee_paid (?P<fee>-?\d+)")
def step_then_event_has_fee_paid(context, fee):
    event = try_unpack(context.result_event_any, tournament.TournamentPlayerEnrolled)
    assert (
        event is not None
    ), f"Not a TournamentPlayerEnrolled event: {context.result_event_any.type_url}"
    assert event.fee_paid == int(fee), f"Expected fee_paid={fee}, got {event.fee_paid}"


@then(r'the tournament event has reason containing "(?P<text>[^"]*)"')
def step_then_event_reason_contains(context, text):
    event_any = context.result_event_any
    event = try_unpack(
        event_any, tournament.TournamentEnrollmentRejected
    ) or try_unpack(event_any, tournament.RebuyDenied)
    assert event is not None, f"No reason field on event: {event_any.type_url}"
    assert (
        text.lower() in event.reason.lower()
    ), f"Expected reason to contain {text!r}, got {event.reason!r}"


@then(r"the tournament event has total_players (?P<n>-?\d+)")
def step_then_event_has_total_players(context, n):
    event = try_unpack(context.result_event_any, tournament.TournamentStarted)
    assert (
        event is not None
    ), f"Not a TournamentStarted event: {context.result_event_any.type_url}"
    assert event.total_players == int(
        n
    ), f"Expected total_players={n}, got {event.total_players}"


@then(r'the command fails with status "(?P<status>[^"]+)"')
def step_then_command_fails_with_status(context, status):
    assert context.error is not None, "Expected command to fail but it succeeded"
    assert hasattr(
        context.error, "status_code"
    ), f"Error {type(context.error).__name__} has no status_code attribute"
    assert (
        context.error.status_code == status
    ), f"Expected status {status}, got {context.error.status_code}"


@then(r'the error message contains "(?P<text>[^"]+)"')
def step_then_error_contains(context, text):
    assert context.error is not None, "Expected an error but got success"
    assert (
        text.lower() in context.error_message.lower()
    ), f"Expected error to contain {text!r}, got {context.error_message!r}"


# =============================================================================
# Given: richer tournament seeds
# =============================================================================


def _append_tournament_completed(context) -> None:
    _ensure_events(context)
    event = tournament.TournamentCompleted(completed_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_tournament_paused(context, reason: str = "pause") -> None:
    _ensure_events(context)
    event = tournament.TournamentPaused(reason=reason, paused_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_tournament_resumed(context) -> None:
    _ensure_events(context)
    event = tournament.TournamentResumed(resumed_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_registration_closed(context, total_registrations: int = 0) -> None:
    _ensure_events(context)
    event = tournament.RegistrationClosed(
        total_registrations=total_registrations,
        closed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_blind_level_advanced(
    context, level: int, small_blind: int = 0, big_blind: int = 0, ante: int = 0
) -> None:
    _ensure_events(context)
    event = tournament.BlindLevelAdvanced(
        level=level,
        small_blind=small_blind,
        big_blind=big_blind,
        ante=ante,
        advanced_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_player_eliminated(context, player_label: str) -> None:
    _ensure_events(context)
    event = tournament.PlayerEliminated(
        player_root=uuid_for(player_label),
        eliminated_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_enrollment_rejected(context, player_label: str, reason: str) -> None:
    _ensure_events(context)
    event = tournament.TournamentEnrollmentRejected(
        player_root=uuid_for(player_label),
        reason=reason,
        rejected_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_rebuy_processed(
    context, player_label: str, rebuy_cost: int, rebuy_count: int
) -> None:
    _ensure_events(context)
    event = tournament.RebuyProcessed(
        player_root=uuid_for(player_label),
        rebuy_cost=rebuy_cost,
        rebuy_count=rebuy_count,
        processed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_rebuy_denied(context, player_label: str, reason: str) -> None:
    _ensure_events(context)
    event = tournament.RebuyDenied(
        player_root=uuid_for(player_label),
        reason=reason,
        denied_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_created_with_rebuy_config(
    context,
    name: str,
    buy_in: int = 100,
    starting_stack: int = 1000,
    rebuy_config: tournament.RebuyConfig | None = None,
    blind_structure: list | None = None,
) -> None:
    _ensure_events(context)
    event = tournament.TournamentCreated(
        name=name,
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=buy_in,
        starting_stack=starting_stack,
        max_players=9,
        min_players=2,
        rebuy_config=rebuy_config,
        blind_structure=blind_structure or [],
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a TournamentCreated event for "(?P<name>[^"]+)" with '
    r"buy_in (?P<buy_in>-?\d+) starting_stack (?P<stack>-?\d+) "
    r"max_players (?P<max_p>-?\d+) min_players (?P<min_p>-?\d+)"
)
def step_given_tc_for_name(context, name, buy_in, stack, max_p, min_p):
    _append_created(
        context,
        name=name,
        buy_in=int(buy_in),
        starting_stack=int(stack),
        max_players=int(max_p),
        min_players=int(min_p),
    )


@given(r"a RegistrationOpened event")
def step_given_registration_opened(context):
    _append_registration_opened(context)


@given(r"a RegistrationClosed event")
def step_given_registration_closed(context):
    _append_registration_closed(context)


@given(r"a TournamentPaused event")
def step_given_tournament_paused(context):
    _append_tournament_paused(context)


@given(r"a TournamentResumed event")
def step_given_tournament_resumed(context):
    _append_tournament_resumed(context)


@given(r"a TournamentCompleted event")
def step_given_tournament_completed(context):
    _append_tournament_completed(context)


@given(
    r'a TournamentPlayerEnrolled event for player "(?P<label>[^"]+)" '
    r"with fee_paid (?P<fee>-?\d+)"
)
def step_given_enrolled_with_fee(context, label, fee):
    _ensure_events(context)
    event = tournament.TournamentPlayerEnrolled(
        player_root=uuid_for(label),
        fee_paid=int(fee),
        enrolled_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a TournamentEnrollmentRejected event for player "(?P<label>[^"]+)" '
    r'with reason "(?P<reason>[^"]*)"'
)
def step_given_enrollment_rejected(context, label, reason):
    _append_enrollment_rejected(context, label, reason)


@given(
    r'a RebuyProcessed event for player "(?P<label>[^"]+)" '
    r"with rebuy_cost (?P<cost>-?\d+) rebuy_count (?P<cnt>-?\d+)"
)
def step_given_rebuy_processed(context, label, cost, cnt):
    _append_rebuy_processed(context, label, int(cost), int(cnt))


@given(
    r'a RebuyDenied event for player "(?P<label>[^"]+)" '
    r'with reason "(?P<reason>[^"]*)"'
)
def step_given_rebuy_denied(context, label, reason):
    _append_rebuy_denied(context, label, reason)


@given(r"a BlindLevelAdvanced event to level (?P<lvl>-?\d+)")
def step_given_blind_advanced(context, lvl):
    _append_blind_level_advanced(context, int(lvl))


@given(r'a PlayerEliminated event for player "(?P<label>[^"]+)"')
def step_given_player_eliminated(context, label):
    _append_player_eliminated(context, label)


@given(r"a paused tournament")
def step_given_paused_tournament(context):
    _append_created(
        context,
        name="Paused Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=10,
        min_players=2,
    )
    _append_registration_opened(context)
    _append_player_enrolled(context, "p0")
    _append_player_enrolled(context, "p1")
    _append_tournament_started(context)
    _append_tournament_paused(context)


@given(r"a running tournament with a two-level blind structure")
def step_given_running_two_level_blinds(context):
    rebuy_config = None
    blind_structure = [
        tournament.BlindLevel(level=1, small_blind=25, big_blind=50, ante=0),
        tournament.BlindLevel(level=2, small_blind=50, big_blind=100, ante=10),
    ]
    _append_created_with_rebuy_config(
        context,
        name="Blinds Test",
        blind_structure=blind_structure,
        rebuy_config=rebuy_config,
    )
    _append_registration_opened(context)
    _append_player_enrolled(context, "p0")
    _append_player_enrolled(context, "p1")
    _append_tournament_started(context)


@given(r"a running tournament at the final defined blind level")
def step_given_running_at_final_blind_level(context):
    """Two-level structure with current_level already advanced to 2 (final).

    Used by EU-0830 to verify that the next AdvanceBlindLevel rejects with
    BLIND_STRUCTURE_EXHAUSTED instead of silently emitting an event past
    the declared structure.
    """
    rebuy_config = None
    blind_structure = [
        tournament.BlindLevel(level=1, small_blind=25, big_blind=50, ante=0),
        tournament.BlindLevel(level=2, small_blind=50, big_blind=100, ante=10),
    ]
    _append_created_with_rebuy_config(
        context,
        name="Final Level Test",
        blind_structure=blind_structure,
        rebuy_config=rebuy_config,
    )
    _append_registration_opened(context)
    _append_player_enrolled(context, "p0")
    _append_player_enrolled(context, "p1")
    _append_tournament_started(context)
    # Advance from default level 1 to level 2 — the final defined level.
    _append_blind_level_advanced(
        context, level=2, small_blind=50, big_blind=100, ante=10
    )


@given(r"a running tournament with no blind structure")
def step_given_running_no_blind_structure(context):
    """Tournament running with an empty blind_structure.

    Used by EU-0831 to verify that AdvanceBlindLevel rejects with
    BLIND_STRUCTURE_EXHAUSTED (max_defined_level=0) when no structure is
    declared.
    """
    _append_created_with_rebuy_config(
        context,
        name="No Blinds Test",
        blind_structure=[],
        rebuy_config=None,
    )
    _append_registration_opened(context)
    _append_player_enrolled(context, "p0")
    _append_player_enrolled(context, "p1")
    _append_tournament_started(context)


def _running_with_rebuy_config(
    context,
    enabled: bool,
    *,
    max_rebuys: int = 0,
    rebuy_level_cutoff: int = 0,
    rebuy_cost: int = 100,
    rebuy_chips: int = 1000,
    players: int = 1,
    current_level: int = 1,
    rebuys_used_for_p0: int = 0,
) -> None:
    rebuy_config = tournament.RebuyConfig(
        enabled=enabled,
        max_rebuys=max_rebuys,
        rebuy_level_cutoff=rebuy_level_cutoff,
        rebuy_cost=rebuy_cost,
        rebuy_chips=rebuy_chips,
    )
    _append_created_with_rebuy_config(
        context,
        name="Rebuy Test",
        rebuy_config=rebuy_config,
    )
    _append_registration_opened(context)
    for i in range(players):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)
    if current_level > 1:
        _append_blind_level_advanced(context, current_level)
    for _ in range(rebuys_used_for_p0):
        _append_rebuy_processed(context, "p0", rebuy_cost, _ + 1)


@given(r"a running tournament with rebuys enabled and " r"(?P<n>-?\d+) enrolled player")
def step_given_running_with_rebuys_enabled(context, n):
    _running_with_rebuy_config(context, enabled=True, players=int(n))


@given(
    r"a running tournament with rebuys disabled and " r"(?P<n>-?\d+) enrolled player"
)
def step_given_running_with_rebuys_disabled(context, n):
    _running_with_rebuy_config(context, enabled=False, players=int(n))


@given(
    r"a running tournament with rebuy cutoff (?P<cut>-?\d+) and "
    r"(?P<n>-?\d+) enrolled player at level (?P<lvl>-?\d+)"
)
def step_given_running_with_rebuy_cutoff(context, cut, n, lvl):
    _running_with_rebuy_config(
        context,
        enabled=True,
        rebuy_level_cutoff=int(cut),
        players=int(n),
        current_level=int(lvl),
    )


@given(
    r"a running tournament with max_rebuys (?P<mx>-?\d+) and "
    r'player "(?P<label>[^"]+)" who has used (?P<used>-?\d+) rebuys'
)
def step_given_running_with_max_rebuys(context, mx, label, used):
    _running_with_rebuy_config(
        context,
        enabled=True,
        max_rebuys=int(mx),
        players=1,
        rebuys_used_for_p0=int(used),
    )


# =============================================================================
# When: remaining commands
# =============================================================================


@when(r"I handle an AdvanceBlindLevel command")
def step_when_advance_blind_level(context):
    cmd = tournament.AdvanceBlindLevel()
    _execute_handler(context, "handle_advance_blind_level", cmd)


@when(
    r'I handle an EliminatePlayer command for player "(?P<label>[^"]*)" '
    r'with hand_root "(?P<hand>[^"]+)"'
)
def step_when_eliminate_player_with_hand(context, label, hand):
    cmd = tournament.EliminatePlayer(
        player_root=uuid_for(label) if label else b"",
        hand_root=uuid_for(hand),
    )
    _execute_handler(context, "eliminate", cmd)


@when(r"I rebuild the tournament state")
def step_when_rebuild_tournament_state(context):
    _ensure_events(context)
    book = _make_event_book(context.events)
    context.agg = Tournament(book)


# =============================================================================
# Then: result-event type + field assertions
# =============================================================================


_EVENT_TYPES = {
    "BlindLevelAdvanced": tournament.BlindLevelAdvanced,
    "PlayerEliminated": tournament.PlayerEliminated,
    "TournamentPaused": tournament.TournamentPaused,
    "TournamentResumed": tournament.TournamentResumed,
    "RegistrationClosed": tournament.RegistrationClosed,
    "RebuyProcessed": tournament.RebuyProcessed,
    "RebuyDenied": tournament.RebuyDenied,
    "TournamentCreated": tournament.TournamentCreated,
    "TournamentPlayerEnrolled": tournament.TournamentPlayerEnrolled,
    "TournamentEnrollmentRejected": tournament.TournamentEnrollmentRejected,
    "TournamentStarted": tournament.TournamentStarted,
    "RegistrationOpened": tournament.RegistrationOpened,
}


@then(r"the result is an? (?:angzarr_client\.proto\.)?examples\." r"(?P<evt>\w+) event")
def step_then_result_is_event(context, evt):
    assert (
        context.result_event_any is not None
    ), "No result event — command may have failed"
    expected = f"angzarr_client.proto.examples.{evt}"
    actual = type_name_from_url(context.result_event_any.type_url)
    assert actual == expected, f"Expected {expected}, got {actual}"


def _unpack_result(context):
    """Decode the result event using the _EVENT_TYPES lookup."""
    actual = type_name_from_url(context.result_event_any.type_url)
    short = actual.rsplit(".", 1)[-1]
    cls = _EVENT_TYPES.get(short)
    assert cls is not None, f"Unknown result event type {actual}"
    evt = cls()
    context.result_event_any.Unpack(evt)
    return evt


@then(r"the tournament event has blind level (?P<lvl>-?\d+)")
def step_then_event_blind_level(context, lvl):
    evt = _unpack_result(context)
    assert evt.level == int(lvl), f"Expected level={lvl}, got {evt.level}"


@then(r"the tournament event has small_blind (?P<v>-?\d+)")
def step_then_event_small_blind(context, v):
    evt = _unpack_result(context)
    assert evt.small_blind == int(v), f"Expected small_blind={v}, got {evt.small_blind}"


@then(r"the tournament event has ante (?P<v>-?\d+)")
def step_then_event_ante(context, v):
    evt = _unpack_result(context)
    assert evt.ante == int(v), f"Expected ante={v}, got {evt.ante}"


@then(r'the tournament event has hand_root "(?P<hand>[^"]+)"')
def step_then_event_hand_root(context, hand):
    evt = _unpack_result(context)
    assert evt.hand_root == uuid_for(
        hand
    ), f"Expected hand_root={hand!r}, got {evt.hand_root!r}"


@then(r'the tournament event has reason "(?P<text>[^"]*)"')
def step_then_event_reason_exact(context, text):
    evt = _unpack_result(context)
    assert evt.reason == text, f"Expected reason={text!r}, got {evt.reason!r}"


@then(r"the tournament event has total_registrations (?P<n>-?\d+)")
def step_then_event_total_registrations(context, n):
    evt = _unpack_result(context)
    assert evt.total_registrations == int(
        n
    ), f"Expected total_registrations={n}, got {evt.total_registrations}"


@then(r"the tournament event has rebuy_cost (?P<v>-?\d+)")
def step_then_event_rebuy_cost(context, v):
    evt = _unpack_result(context)
    assert evt.rebuy_cost == int(v), f"Expected rebuy_cost={v}, got {evt.rebuy_cost}"


@then(r"the tournament event has chips_added (?P<v>-?\d+)")
def step_then_event_chips_added(context, v):
    evt = _unpack_result(context)
    assert evt.chips_added == int(v), f"Expected chips_added={v}, got {evt.chips_added}"


@then(r"the tournament event has rebuy_count (?P<v>-?\d+)")
def step_then_event_rebuy_count(context, v):
    evt = _unpack_result(context)
    assert evt.rebuy_count == int(v), f"Expected rebuy_count={v}, got {evt.rebuy_count}"


# =============================================================================
# Then: tournament state assertions
# =============================================================================


_STATUS_NAME_TO_ENUM = {
    "Created": tournament.TournamentStatus.TOURNAMENT_CREATED,
    "RegistrationOpen": tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
    "Running": tournament.TournamentStatus.TOURNAMENT_RUNNING,
    "Paused": tournament.TournamentStatus.TOURNAMENT_PAUSED,
    "Completed": tournament.TournamentStatus.TOURNAMENT_COMPLETED,
    "Cancelled": tournament.TournamentStatus.TOURNAMENT_CANCELLED,
}


@then(r'the tournament state has tournament_id "(?P<tid>[^"]+)"')
def step_then_state_tournament_id(context, tid):
    assert (
        context.agg._state.tournament_id == tid
    ), f"Expected tournament_id={tid!r}, got {context.agg._state.tournament_id!r}"


@then(r'the tournament state has name "(?P<name>[^"]+)"')
def step_then_state_name(context, name):
    assert (
        context.agg._state.name == name
    ), f"Expected name={name!r}, got {context.agg._state.name!r}"


@then(r'the tournament state has status "(?P<status>[^"]+)"')
def step_then_state_status(context, status):
    expected = _STATUS_NAME_TO_ENUM[status]
    assert (
        context.agg.status == expected
    ), f"Expected status={status} ({expected}), got {context.agg.status}"


@then(r"the tournament state has buy_in (?P<v>-?\d+)")
def step_then_state_buy_in(context, v):
    assert context.agg.buy_in == int(
        v
    ), f"Expected buy_in={v}, got {context.agg.buy_in}"


@then(r"the tournament state has starting_stack (?P<v>-?\d+)")
def step_then_state_starting_stack(context, v):
    assert context.agg.starting_stack == int(
        v
    ), f"Expected starting_stack={v}, got {context.agg.starting_stack}"


@then(r"the tournament state has max_players (?P<v>-?\d+)")
def step_then_state_max_players(context, v):
    assert context.agg.max_players == int(
        v
    ), f"Expected max_players={v}, got {context.agg.max_players}"


@then(r"the tournament state has min_players (?P<v>-?\d+)")
def step_then_state_min_players(context, v):
    assert context.agg.min_players == int(
        v
    ), f"Expected min_players={v}, got {context.agg.min_players}"


@then(r"the tournament state has current_level (?P<v>-?\d+)")
def step_then_state_current_level(context, v):
    assert context.agg.current_level == int(
        v
    ), f"Expected current_level={v}, got {context.agg.current_level}"


@then(r"the tournament state has blind_structure count (?P<v>-?\d+)")
def step_then_state_blind_structure_count(context, v):
    assert len(context.agg.blind_structure) == int(
        v
    ), f"Expected blind_structure count={v}, got {len(context.agg.blind_structure)}"


@then(r"the tournament state has total_prize_pool (?P<v>-?\d+)")
def step_then_state_total_prize_pool(context, v):
    assert context.agg.total_prize_pool == int(
        v
    ), f"Expected total_prize_pool={v}, got {context.agg.total_prize_pool}"


@then(r"the tournament state has registered_players count (?P<v>-?\d+)")
def step_then_state_registered_count(context, v):
    assert len(context.agg.registered_players) == int(
        v
    ), f"Expected registered count={v}, got {len(context.agg.registered_players)}"


@then(r"the tournament state has players_remaining (?P<v>-?\d+)")
def step_then_state_players_remaining(context, v):
    assert context.agg.players_remaining == int(
        v
    ), f"Expected players_remaining={v}, got {context.agg.players_remaining}"


@then(
    r"the tournament state has rebuys_used (?P<v>-?\d+) "
    r'for player "(?P<label>[^"]+)"'
)
def step_then_state_rebuys_used(context, v, label):
    player_hex = uuid_for(label).hex()
    reg = context.agg.registered_players.get(player_hex)
    assert reg is not None, f"Player {label!r} not registered"
    assert reg.rebuys_used == int(v), f"Expected rebuys_used={v}, got {reg.rebuys_used}"


@then(r'the tournament state has no registered player "(?P<label>[^"]+)"')
def step_then_state_no_player(context, label):
    player_hex = uuid_for(label).hex()
    assert (
        player_hex not in context.agg.registered_players
    ), f"Expected {label!r} absent, but it is registered"


# --- Late registration / multi-place payout ---------------------------------


@given(r"a running tournament with registration open and (?P<n>\d+) enrolled players")
def step_given_running_with_open_reg(context, n):
    """Tournament that is running but registration is still open
    (TDA Rule 30 — late registration)."""
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=100,
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(int(n)):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)


@given(
    r"a running tournament with starting_stack (?P<stack>\d+), registration "
    r"open, and (?P<n>\d+) enrolled players"
)
def step_given_running_with_stack_and_open_reg(context, stack, n):
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=int(stack),
        max_players=100,
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(int(n)):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)


@given(
    r"a running tournament with registration_cutoff_level (?P<cut>\d+) at "
    r"level (?P<level>\d+) and (?P<n>\d+) enrolled players"
)
def step_given_running_with_cutoff(context, cut, level, n):
    _ensure_events(context)
    event = tournament.TournamentCreated(
        name="Test Tournament",
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=100,
        starting_stack=1000,
        max_players=100,
        min_players=2,
        registration_cutoff_level=int(cut),
        created_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    _append_registration_opened(context)
    for i in range(int(n)):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)
    # Advance to the configured level via BlindLevelAdvanced events.
    for lvl in range(2, int(level) + 1):
        adv = tournament.BlindLevelAdvanced(level=lvl, advanced_at=make_timestamp())
        context.events.append(make_event_page(adv, seq=len(context.events)))


@given(r"a running tournament with (?P<n>\d+) enrolled players")
def step_given_running_with_n_simple(context, n):
    _append_created(
        context,
        name="Test Tournament",
        buy_in=100,
        starting_stack=1000,
        max_players=100,
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(int(n)):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)


@given(
    r'a running tournament "(?P<name>[^"]+)" with total_prize_pool '
    r"(?P<pool>\d+) and (?P<n>\d+) enrolled players"
)
def step_given_running_with_pool(context, name, pool, n):
    """Set up a running tournament whose accumulated prize pool matches
    the requested amount. We pick buy_in = pool / n so N enrollments
    produce the total pool exactly.
    """
    n_int = int(n)
    pool_int = int(pool)
    buy_in = pool_int // max(n_int, 1)
    _append_created(
        context,
        name=name,
        buy_in=buy_in,
        starting_stack=1500,
        max_players=max(n_int, 9),
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(n_int):
        _append_player_enrolled(context, f"p{i + 1}")
    _append_tournament_started(context)


@given(
    r"a payout_structure paying positions (?P<positions>[\d, ]+) at "
    r"percentages (?P<percentages>[\d, ]+)"
)
def step_given_payout_structure(context, positions, percentages):
    """Re-emit the TournamentCreated with payout_structure populated.

    The simplest approach: rebuild context.events by replacing the
    initial TournamentCreated with one carrying the payout_structure.
    """
    pos_list = [int(p.strip()) for p in positions.split(",")]
    pct_list = [int(p.strip()) for p in percentages.split(",")]
    new_events = []
    for page in context.events:
        if page.event.Is(tournament.TournamentCreated.DESCRIPTOR):
            tc = tournament.TournamentCreated()
            page.event.Unpack(tc)
            for pos, pct in zip(pos_list, pct_list):
                tc.payout_structure.append(
                    tournament.PayoutPosition(position=pos, percentage=pct)
                )
            new_events.append(make_event_page(tc, seq=len(new_events)))
        else:
            # Re-emit untouched events with fresh sequence numbers.
            cls_map = {
                tournament.RegistrationOpened: tournament.RegistrationOpened,
                tournament.RegistrationClosed: tournament.RegistrationClosed,
                tournament.TournamentPlayerEnrolled: tournament.TournamentPlayerEnrolled,
                tournament.TournamentStarted: tournament.TournamentStarted,
                tournament.TournamentPaused: tournament.TournamentPaused,
                tournament.TournamentResumed: tournament.TournamentResumed,
                tournament.BlindLevelAdvanced: tournament.BlindLevelAdvanced,
                tournament.RebuyProcessed: tournament.RebuyProcessed,
                tournament.PlayerEliminated: tournament.PlayerEliminated,
                tournament.TournamentCompleted: tournament.TournamentCompleted,
            }
            unpacked = None
            for cls in cls_map:
                if page.event.Is(cls.DESCRIPTOR):
                    inst = cls()
                    page.event.Unpack(inst)
                    unpacked = inst
                    break
            if unpacked is not None:
                new_events.append(make_event_page(unpacked, seq=len(new_events)))
            else:
                new_events.append(page)
    context.events = new_events


@given(r'finishing order "(?P<order>[^"]+)"')
def step_given_finishing_order(context, order):
    context.finishing_order = [name.strip() for name in order.split(",")]


@when(r'I handle a CompleteTournament command with winner "(?P<winner>[^"]+)"')
def step_when_complete_tournament_simple(context, winner):
    cmd = tournament.CompleteTournament(winner_root=uuid_for(winner))
    finishing = getattr(context, "finishing_order", [])
    for name in finishing:
        cmd.finishing_order.append(uuid_for(name))
    _execute_handler(context, "complete", cmd)


@when(
    r'I handle a CompleteTournament command with winner "(?P<winner>[^"]+)" '
    r'and finishing order "(?P<order>[^"]+)"'
)
def step_when_complete_tournament_with_order(context, winner, order):
    cmd = tournament.CompleteTournament(winner_root=uuid_for(winner))
    for name in order.split(","):
        cmd.finishing_order.append(uuid_for(name.strip()))
    _execute_handler(context, "complete", cmd)


@then(r'the tournament event has winner_root "(?P<label>[^"]+)"')
def step_then_event_winner_root(context, label):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    assert evt.winner_root == uuid_for(
        label
    ), f"winner_root: expected {label}, got {evt.winner_root.hex()[:8]}"


@then(r"the tournament event has (?P<n>\d+) results?")
def step_then_event_n_results(context, n):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    assert len(evt.results) == int(n), f"Expected {n} results, got {len(evt.results)}"


@then(
    r"TournamentResult (?P<idx>\d+) has position (?P<pos>\d+) "
    r'player_root "(?P<label>[^"]+)" payout (?P<payout>\d+)'
)
def step_then_result_at(context, idx, pos, label, payout):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    i = int(idx)
    assert i < len(evt.results), f"Only {len(evt.results)} results"
    r = evt.results[i]
    assert r.position == int(pos), f"position: expected {pos}, got {r.position}"
    assert r.player_root == uuid_for(
        label
    ), f"player_root: expected {label}, got {r.player_root.hex()[:8]}"
    assert r.payout == int(payout), f"payout: expected {payout}, got {r.payout}"


@then(r'no TournamentResult has player_root "(?P<label>[^"]+)"')
def step_then_no_result_with_player(context, label):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    target = uuid_for(label)
    matches = [r for r in evt.results if r.player_root == target]
    assert not matches, f"Expected no result for {label}, but found {len(matches)}"


# Update the existing rejection-field-equals step to translate player labels.
# (The common_steps version already handles the basic case; this is local
# augmentation if needed.)


_HANDLER_MAP["complete"] = "handle_complete_tournament"
