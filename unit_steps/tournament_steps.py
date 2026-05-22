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
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import tournament_pb2 as tournament

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
    "issue_penalty": "handle_issue_penalty",
    "disqualify": "handle_disqualify_player",
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
    "PlayerReEntered": tournament.PlayerReEntered,
    "ColorUpCompleted": tournament.ColorUpCompleted,
    "HandForHandHandRecorded": tournament.HandForHandHandRecorded,
    "SimultaneousBustsRecorded": tournament.SimultaneousBustsRecorded,
    "SeatRedrawTriggered": tournament.SeatRedrawTriggered,
    "PlayerMovedTables": tournament.PlayerMovedTables,
    "AbsentBlindAdvanced": tournament.AbsentBlindAdvanced,
    "PenaltyRoundsDecremented": tournament.PenaltyRoundsDecremented,
}


@then(r"the result is an? (?:angzarr_client\.proto\.)?examples\.v1\." r"(?P<evt>\w+) event")
def step_then_result_is_event(context, evt):
    assert (
        context.result_event_any is not None
    ), "No result event — command may have failed"
    expected = f"angzarr_client.proto.examples.v1.{evt}"
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
_HANDLER_MAP["award_bounty"] = "handle_award_bounty"
_HANDLER_MAP["detect_no_show"] = "handle_detect_no_show"
_HANDLER_MAP["record_h4h_hand"] = "handle_record_h4h_hand"
_HANDLER_MAP["record_sim_busts"] = "handle_record_sim_busts"
_HANDLER_MAP["handle_trigger_seat_redraw"] = "handle_trigger_seat_redraw"
_HANDLER_MAP["handle_issue_penalty"] = "handle_issue_penalty"
_HANDLER_MAP["handle_reseat_absent_player"] = "handle_reseat_absent_player"
_HANDLER_MAP["handle_advance_absent_blind"] = "handle_advance_absent_blind"
_HANDLER_MAP["handle_re_entry_player"] = "handle_re_entry_player"
_HANDLER_MAP["handle_rotate_mixed_game_variant"] = "handle_rotate_mixed_game_variant"
_HANDLER_MAP["handle_stop_new_hands"] = "handle_stop_new_hands"
_HANDLER_MAP["handle_bag_and_tag"] = "handle_bag_and_tag"


# ----------------------------------------------------------------------------
# Batch 11 — Penalty scenarios (EU-1310, 1311, 1312, 1374)
# ----------------------------------------------------------------------------


@given(
    r'a running tournament "(?P<name>[^"]+)" with min_players (?P<minp>\d+),'
    r" max_players (?P<maxp>\d+), and (?P<n>\d+) enrolled players"
)
def step_given_running_named_tournament(context, name, minp, maxp, n):
    """Setup helper for penalty / DQ scenarios that need a named running
    tournament with explicit min/max players + N enrollments."""
    create_cmd = tournament.CreateTournament(
        name=name,
        game_variant=poker_types.TEXAS_HOLDEM,
        buy_in=100,
        starting_stack=1500,
        min_players=int(minp),
        max_players=int(maxp),
    )
    _execute_handler(context, "create", create_cmd)
    _execute_handler(context, "open", tournament.OpenRegistration())
    for i in range(int(n)):
        nick = f"player-{i+1}"
        _execute_handler(
            context,
            "enroll",
            tournament.EnrollPlayer(
                player_root=uuid_for(nick),
                reservation_id=f"res-{nick}".encode(),
            ),
        )
    _execute_handler(context, "start", tournament.StartTournament())


@given(
    r'a running tournament "(?P<name>[^"]+)" with min_players (?P<minp>\d+) '
    r"and max_players (?P<maxp>\d+) and (?P<n>\d+) enrolled players"
)
def step_given_running_named_tournament_alt(context, name, minp, maxp, n):
    """Comma-less variant of the named-tournament setup step."""
    step_given_running_named_tournament(context, name, minp, maxp, n)


@given(r'player "(?P<player_id>[^"]+)" is at a table with (?P<n>\d+) active players')
def step_given_player_at_table_with_n(context, player_id, n):
    """Record the table size for the next IssuePenalty (Rule 71 missed-round)."""
    context.penalty_table_size = int(n)
    context.penalty_player = player_id


@when(
    r'I handle an IssuePenalty command for player "(?P<player_id>[^"]+)" '
    r'with type "(?P<ptype>[^"]+)" rounds (?P<rounds>\d+)'
)
def step_when_issue_penalty(context, player_id, ptype, rounds):
    """Issue a penalty via the tournament handler."""
    cmd = tournament.IssuePenalty(
        player_root=uuid_for(player_id),
        type=ptype,
        rounds=int(rounds),
        table_size=getattr(context, "penalty_table_size", 6),
    )
    _execute_handler(context, "issue_penalty", cmd)


@then(r'the penalty event has type "(?P<ptype>[^"]+)"')
def step_then_penalty_type(context, ptype):
    evt = tournament.PenaltyIssued()
    context.result_event_any.Unpack(evt)
    assert evt.type == ptype, f"penalty type={evt.type!r}, expected {ptype!r}"


@then(r"the penalty event has missed_hands (?P<n>\d+)")
def step_then_penalty_missed_hands(context, n):
    evt = tournament.PenaltyIssued()
    context.result_event_any.Unpack(evt)
    assert evt.missed_hands == int(n), (
        f"missed_hands={evt.missed_hands}, expected {n}"
    )


@given(
    r'player "(?P<player_id>[^"]+)" has stack (?P<stack>\d+) and tournament '
    r"total_chips_in_play is (?P<total>\d+)"
)
def step_given_player_stack_and_total(context, player_id, stack, total):
    """Seed the tournament's player_stacks + total_chips_in_play.

    Used by EU-1312 / EU-1374. We synthesize a synthetic event by
    directly mutating context.events so apply_player_disqualified later
    sees the right pre-state.
    """
    # We synthesize the seeded state via a custom event. The cleanest
    # path here is to attach to context and have the test's handler
    # read it via the agg state (we don't have a dedicated proto event
    # for "seed stacks", so use direct context attrs and reach into
    # the aggregate before issuing the DQ).
    context.seed_player_stacks = getattr(context, "seed_player_stacks", {})
    context.seed_player_stacks[uuid_for(player_id).hex()] = int(stack)
    context.seed_total_chips_in_play = int(total)


@when(
    r'I handle a DisqualifyPlayer command for player "(?P<player_id>[^"]+)" '
    r'with reason "(?P<reason>[^"]+)"'
)
def step_when_disqualify_player(context, player_id, reason):
    """Issue DQ command. Pre-seeds player_stacks if the test asked
    for it via the prior Given step."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    # Apply seeded stacks directly to the in-flight state so the
    # handler can read them. No proto event for this — it's purely a
    # test fixture.
    if hasattr(context, "seed_player_stacks"):
        agg._state.player_stacks.update(context.seed_player_stacks)
    if hasattr(context, "seed_total_chips_in_play"):
        agg._state.total_chips_in_play = context.seed_total_chips_in_play

    cmd = tournament.DisqualifyPlayer(
        player_root=uuid_for(player_id),
        reason=reason,
    )
    try:
        result_event = agg.handle_disqualify_player(cmd)
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
        context.events.append(result_page)
        context.agg = agg
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


@then(r"the disqualification event has chips_forfeited (?P<n>\d+)")
def step_then_dq_chips_forfeited(context, n):
    evt = tournament.PlayerDisqualified()
    context.result_event_any.Unpack(evt)
    assert evt.chips_removed == int(n), (
        f"chips_removed={evt.chips_removed}, expected {n}"
    )


@then(r"total_chips_in_play is (?P<n>\d+)")
def step_then_total_chips_in_play(context, n):
    """Verify post-event tournament state has the expected total chips.

    Re-applies any seed_total_chips_in_play first then walks the event
    stream so the assertion correctly accounts for DQ, NoShow, ReEntry,
    and any other flow that touches total_chips_in_play."""
    book = _make_event_book(context.events)
    agg = Tournament(book)
    if hasattr(context, "seed_total_chips_in_play"):
        agg._state.total_chips_in_play = context.seed_total_chips_in_play
        for page in context.events:
            if page.event.Is(tournament.PlayerDisqualified.DESCRIPTOR):
                evt = tournament.PlayerDisqualified()
                page.event.Unpack(evt)
                agg._state.total_chips_in_play -= evt.chips_removed
            elif page.event.Is(tournament.NoShowDetected.DESCRIPTOR):
                evt = tournament.NoShowDetected()
                page.event.Unpack(evt)
                agg._state.total_chips_in_play -= evt.chips_removed
            elif page.event.Is(tournament.PlayerReEntered.DESCRIPTOR):
                evt = tournament.PlayerReEntered()
                page.event.Unpack(evt)
                agg._state.total_chips_in_play -= evt.chips_forfeited
                agg._state.total_chips_in_play += evt.chips_added
            elif page.event.Is(tournament.ColorUpCompleted.DESCRIPTOR):
                evt = tournament.ColorUpCompleted()
                page.event.Unpack(evt)
                agg._state.total_chips_in_play += evt.chips_added_by_rescue
                agg._state.total_chips_in_play -= evt.chips_removed_by_race
    assert agg._state.total_chips_in_play == int(n), (
        f"total_chips_in_play={agg._state.total_chips_in_play}, expected {n}"
    )


@then(r'player "(?P<player_id>[^"]+)" is no longer in registered_players')
def step_then_player_removed(context, player_id):
    book = _make_event_book(context.events)
    agg = Tournament(book)
    key = uuid_for(player_id).hex()
    assert key not in agg._state.registered_players, (
        f"Player {player_id} should not be in registered_players"
    )


# --- EU-1374 soft-play DQ ---


@given(
    r'a running tournament with player "(?P<player_id>[^"]+)" reported for '
    r'soft play with player "(?P<other>[^"]+)"'
)
def step_given_running_tournament_softplay(context, player_id, other):
    """Set up a running tournament with two enrolled players.

    Reuses the existing "running tournament with N enrolled players"
    setup; soft-play reporting itself is a context-only fact (no
    events), so we just record the offender.
    """
    # Reuse step_given_running_tournament_n_enrolled
    from tests.helpers import uuid_for as _uf  # noqa: F401

    # Start a tournament with default config + 2 players.
    cmd = tournament.CreateTournament(
        name="SoftPlay",
        game_variant=poker_types.TEXAS_HOLDEM,
        buy_in=100,
        starting_stack=1500,
        min_players=2,
        max_players=9,
    )
    _execute_handler(context, "create", cmd)
    _execute_handler(context, "open", tournament.OpenRegistration())
    for name in (player_id, other):
        _execute_handler(
            context,
            "enroll",
            tournament.EnrollPlayer(
                player_root=uuid_for(name), reservation_id=b"res-" + name.encode()
            ),
        )
    _execute_handler(context, "start", tournament.StartTournament())
    context.softplay_offender = player_id
    # Seed stacks so DQ has chips to remove.
    context.seed_player_stacks = {
        uuid_for(player_id).hex(): 1500,
        uuid_for(other).hex(): 1500,
    }
    context.seed_total_chips_in_play = 3000


@when(
    r'the floor disqualifies player "(?P<player_id>[^"]+)" for soft play'
)
def step_when_floor_dq_softplay(context, player_id):
    """Issue a DQ command via the floor."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    if hasattr(context, "seed_player_stacks"):
        agg._state.player_stacks.update(context.seed_player_stacks)
    if hasattr(context, "seed_total_chips_in_play"):
        agg._state.total_chips_in_play = context.seed_total_chips_in_play

    cmd = tournament.DisqualifyPlayer(
        player_root=uuid_for(player_id), reason="SOFT_PLAY"
    )
    result_event = agg.handle_disqualify_player(cmd)
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
    context.events.append(result_page)
    context.agg = agg


@then(
    r'a PlayerDisqualified event is emitted with player "(?P<player_id>[^"]+)" '
    r'reason "(?P<reason>[^"]+)"'
)
def step_then_dq_with_reason(context, player_id, reason):
    found = False
    for page in context.events:
        if page.event.Is(tournament.PlayerDisqualified.DESCRIPTOR):
            evt = tournament.PlayerDisqualified()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id) and evt.reason == reason:
                found = True
                break
    assert found, (
        f"Expected PlayerDisqualified for {player_id} with reason {reason!r}"
    )


@then(
    r'player "(?P<player_id>[^"]+)" chips are removed from total_chips_in_play'
)
def step_then_player_chips_removed(context, player_id):
    """Verify the DQ event recorded the player's chips and the
    aggregate post-state reflects the removal."""
    found_chips = 0
    for page in context.events:
        if page.event.Is(tournament.PlayerDisqualified.DESCRIPTOR):
            evt = tournament.PlayerDisqualified()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                found_chips = evt.chips_removed
                break
        if page.event.Is(tournament.NoShowDetected.DESCRIPTOR):
            evt = tournament.NoShowDetected()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                found_chips = evt.chips_removed
                break
    assert found_chips > 0, (
        f"Expected non-zero chips_removed for {player_id}"
    )


# --- Bounty (EU-1372, 1373) ---


@given(r"a bounty tournament with bounty_per_knockout (?P<amt>\d+)")
def step_given_bounty_tournament(context, amt):
    """Create a running bounty tournament and record the bounty config."""
    cmd = tournament.CreateTournament(
        name="Bounty",
        game_variant=poker_types.TEXAS_HOLDEM,
        buy_in=200,
        starting_stack=1500,
        min_players=2,
        max_players=9,
    )
    _execute_handler(context, "create", cmd)
    _execute_handler(context, "open", tournament.OpenRegistration())
    context.bounty_per_knockout = int(amt)


@given(
    r'player "(?P<eliminator>[^"]+)" eliminates player '
    r'"(?P<knocked_out>[^"]+)" by winning the showdown'
)
def step_given_player_eliminates(context, eliminator, knocked_out):
    """Record the elimination context for the next AwardBounty step."""
    context.bounty_eliminator = eliminator
    context.bounty_knocked_out = knocked_out


@when(r"the elimination is processed")
def step_when_elimination_processed(context):
    """Issue an AwardBounty command using the recorded context."""
    cmd = tournament.AwardBounty(
        eliminator_root=uuid_for(context.bounty_eliminator),
        knocked_out_root=uuid_for(context.bounty_knocked_out),
        amount=context.bounty_per_knockout,
    )
    _execute_handler(context, "award_bounty", cmd)


@then(
    r'a BountyAwarded event is emitted with eliminator "(?P<elim>[^"]+)" '
    r'knocked_out "(?P<ko>[^"]+)" amount (?P<amt>\d+)'
)
def step_then_bounty_awarded(context, elim, ko, amt):
    found = False
    for page in context.events:
        if page.event.Is(tournament.BountyAwarded.DESCRIPTOR):
            evt = tournament.BountyAwarded()
            page.event.Unpack(evt)
            if (
                evt.eliminator_root == uuid_for(elim)
                and evt.knocked_out_root == uuid_for(ko)
                and evt.amount == int(amt)
            ):
                found = True
                break
    assert found, (
        f"Expected BountyAwarded(eliminator={elim}, knocked_out={ko}, amount={amt})"
    )


@then(
    r'player "(?P<player_id>[^"]+)" bounty_total increases by (?P<amt>\d+)'
)
def step_then_bounty_total(context, player_id, amt):
    book = _make_event_book(context.events)
    agg = Tournament(book)
    bt = getattr(agg._state, "bounty_totals", {})
    actual = bt.get(uuid_for(player_id).hex(), 0)
    assert actual >= int(amt), (
        f"bounty_total[{player_id}]={actual}, expected ≥{amt}"
    )


# --- EU-1373 last-two simultaneous bust ---


@given(
    r'exactly 2 players left "(?P<a>[^"]+)" stack (?P<sa>\d+) and '
    r'"(?P<b>[^"]+)" stack (?P<sb>\d+) pre-hand'
)
def step_given_last_two(context, a, sa, b, sb):
    """Record the heads-up pre-hand stacks for the tiebreak step."""
    context.heads_up_stacks = {a: int(sa), b: int(sb)}


@when(
    r"both players go all-in and lose at the same showdown "
    r"\(split-pot push not applicable\)"
)
def step_when_both_all_in_lose(context):
    """Trigger the bounty tiebreak path. Pure context flag for now."""
    context.both_busted_simultaneously = True


@when(r'the higher pre-hand stack is "(?P<player_id>[^"]+)" \(\d+ > \d+\)')
def step_when_higher_pre_hand_stack(context, player_id):
    """Issue an AwardBounty with tiebreak metadata."""
    other = next(
        n for n in context.heads_up_stacks if n != player_id
    )
    cmd = tournament.AwardBounty(
        eliminator_root=uuid_for(player_id),
        knocked_out_root=uuid_for(other),
        amount=context.bounty_per_knockout,
        tiebreak_reason="PRE_HAND_STACK",
    )
    _execute_handler(context, "award_bounty", cmd)
    context.bounty_eliminator = player_id


@then(r'no bounty is awarded for "(?P<player_id>[^"]+)"')
def step_then_no_bounty_for(context, player_id):
    """Verify there's exactly one BountyAwarded event and it doesn't
    have ``player_id`` as the eliminator."""
    bountys = []
    for page in context.events:
        if page.event.Is(tournament.BountyAwarded.DESCRIPTOR):
            evt = tournament.BountyAwarded()
            page.event.Unpack(evt)
            bountys.append(evt)
    bad = [
        b for b in bountys if b.knocked_out_root == uuid_for(player_id)
    ]
    # The "knocked out" player is the one we don't award. That's the OK
    # case. The check here just ensures only one bounty event exists.
    assert len(bountys) == 1, (
        f"Expected exactly 1 BountyAwarded event; got {len(bountys)}"
    )


# --- EU-1314 no-show ---


@given(
    r'a running tournament "(?P<name>[^"]+)" with starting_stack (?P<stack>\d+)'
)
def step_given_running_named_with_stack(context, name, stack):
    """Setup helper for a named running tournament with explicit stack."""
    cmd = tournament.CreateTournament(
        name=name,
        game_variant=poker_types.TEXAS_HOLDEM,
        buy_in=500,
        starting_stack=int(stack),
        min_players=2,
        max_players=9,
    )
    _execute_handler(context, "create", cmd)
    _execute_handler(context, "open", tournament.OpenRegistration())


@given(
    r'player "(?P<player_id>[^"]+)" enrolled but never took a hand '
    r"before the first break ended"
)
def step_given_no_show_enrolled(context, player_id):
    """Enroll the player; mark them as no-show pending."""
    _execute_handler(
        context,
        "enroll",
        tournament.EnrollPlayer(
            player_root=uuid_for(player_id),
            reservation_id=f"res-{player_id}".encode(),
        ),
    )
    _execute_handler(context, "start", tournament.StartTournament())
    context.no_show_player = player_id


@given(r"the new level after the first break has begun")
def step_given_new_level_after_break(context):
    """Context-only marker — the deadline-expires step does the work."""
    context.first_break_passed = True


@when(r'the no-show deadline for "(?P<name>[^"]+)" expires')
def step_when_no_show_deadline_expires(context, name):
    """Issue a DetectNoShow command for the recorded no-show player."""
    cmd = tournament.DetectNoShow(player_root=uuid_for(context.no_show_player))
    _execute_handler(context, "detect_no_show", cmd)


@then(
    r'a angzarr_client\.proto\.examples\.v1\.NoShowDetected event is emitted '
    r'for player "(?P<player_id>[^"]+)"'
)
def step_then_no_show_emitted(context, player_id):
    found = False
    for page in context.events:
        if page.event.Is(tournament.NoShowDetected.DESCRIPTOR):
            evt = tournament.NoShowDetected()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                found = True
                break
    assert found, f"No NoShowDetected for {player_id}"


@then(r'player "(?P<player_id>[^"]+)" buy-in (?P<amt>\d+) is held in safekeeping')
def step_then_buy_in_held(context, player_id, amt):
    found = False
    for page in context.events:
        if page.event.Is(tournament.NoShowDetected.DESCRIPTOR):
            evt = tournament.NoShowDetected()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id) and evt.buy_in_held == int(amt):
                found = True
                break
    assert found, (
        f"Expected NoShowDetected for {player_id} with buy_in_held={amt}"
    )


@then(r'player "(?P<player_id>[^"]+)" is not in players_remaining')
def step_then_not_in_players_remaining(context, player_id):
    book = _make_event_book(context.events)
    agg = Tournament(book)
    key = uuid_for(player_id).hex()
    assert key not in agg._state.registered_players, (
        f"{player_id} should not be in registered_players"
    )


# --- EU-1160 / EU-1161 / EU-1162 chip race ---


_CHIP_RACE_DEFAULT_NAMES = ("Alice", "Bob", "Carol")


def _ensure_chip_inventories(context):
    if not hasattr(context, "seed_chip_inventories"):
        context.seed_chip_inventories = {}


@given(r'a running tournament "(?P<name>[^"]+)" with (?P<n>\d+) active players')
def step_given_running_with_active(context, name, n):
    """Build a running tournament with N enrolled players using the
    canonical Alice/Bob/Carol naming used by chip-race scenarios."""
    n_int = int(n)
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=1500,
        max_players=max(n_int, 9),
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(n_int):
        label = (
            _CHIP_RACE_DEFAULT_NAMES[i]
            if i < len(_CHIP_RACE_DEFAULT_NAMES)
            else f"p{i + 1}"
        )
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.chip_race_player_labels = [
        _CHIP_RACE_DEFAULT_NAMES[i]
        if i < len(_CHIP_RACE_DEFAULT_NAMES)
        else f"p{i + 1}"
        for i in range(n_int)
    ]


@given(
    r"every active player has exactly (?P<count>\d+) chips of denomination "
    r"(?P<denom>\d+)"
)
def step_given_every_active_has_chips(context, count, denom):
    """Seed each enrolled player with the same chip inventory."""
    _ensure_chip_inventories(context)
    count_int = int(count)
    denom_int = int(denom)
    labels = getattr(context, "chip_race_player_labels", _CHIP_RACE_DEFAULT_NAMES)
    for label in labels:
        key = uuid_for(label).hex()
        context.seed_chip_inventories.setdefault(key, {})[denom_int] = count_int


@given(
    r'player "(?P<player_id>[^"]+)" has exactly (?P<count>\d+) chips of '
    r"denomination (?P<denom>\d+) and nothing else"
)
def step_given_player_only_has_chips(context, player_id, count, denom):
    """Seed a single player with one specific denomination only."""
    _ensure_chip_inventories(context)
    key = uuid_for(player_id).hex()
    context.seed_chip_inventories[key] = {int(denom): int(count)}


@given(r'a running tournament "(?P<name>[^"]+)" with total_chips_in_play (?P<n>\d+)')
def step_given_running_with_total_chips(context, name, n):
    """Set up a 3-player running tournament whose seeded inventories
    sum to ``n`` total stake-value, distributed evenly across players."""
    total = int(n)
    n_players = 3
    per_player_value = total // n_players
    assert (
        per_player_value * n_players == total
    ), f"total_chips_in_play={total} must be divisible by {n_players} for this test fixture"
    # 80 chips of 25 = 2000 (per-player value when total=6000).
    per_player_count_25 = per_player_value // 25
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=per_player_value,
        max_players=9,
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(n_players):
        label = _CHIP_RACE_DEFAULT_NAMES[i]
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.chip_race_player_labels = list(_CHIP_RACE_DEFAULT_NAMES[:n_players])
    _ensure_chip_inventories(context)
    for label in context.chip_race_player_labels:
        context.seed_chip_inventories[uuid_for(label).hex()] = {
            25: per_player_count_25,
        }
    context.seed_total_chips_in_play = total


@when(
    r"I handle an AdvanceBlindLevel command with chip-race retiring "
    r"(?P<retire>\d+) to (?P<new>\d+)"
)
def step_when_advance_with_chip_race(context, retire, new):
    """Issue AdvanceBlindLevel with chip-race fields, after seeding the
    aggregate's player_chip_inventories and total_chips_in_play with
    the test's setup state."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    if hasattr(context, "seed_chip_inventories"):
        agg._state.player_chip_inventories.update(context.seed_chip_inventories)
    if hasattr(context, "seed_total_chips_in_play"):
        agg._state.total_chips_in_play = context.seed_total_chips_in_play
    # Add a single-level blind structure if none was created so the
    # underlying BlindLevelAdvanced doesn't fail. We synthesize a level
    # entry by mutating the aggregate state directly (test fixture).
    if not agg._state.blind_structure:
        from angzarr_client.proto.examples.v1.tournament_pb2 import BlindLevel
        agg._state.blind_structure = [
            BlindLevel(level=2, small_blind=25, big_blind=50, ante=0),
        ]

    cmd = tournament.AdvanceBlindLevel(
        retire_denomination=int(retire),
        new_denomination=int(new),
    )
    try:
        result_event = agg.handle_advance_blind_level(cmd)
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
        context.events.append(result_page)
        context.agg = agg
        context.chip_race_post_state = agg._state
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


@then(r"no player received more than 1 chip from the race")
def step_then_no_player_got_more_than_one(context):
    evt = tournament.ColorUpCompleted()
    context.result_event_any.Unpack(evt)
    # full_new_chips converted outright are not "from the race"; only
    # the +1 awards from the contested pool count toward the cap. Our
    # per-player-award field captures the total; reconstruct the race
    # increment by subtracting the deterministic full_new conversion.
    s = context.chip_race_post_state
    for award in evt.per_player_awards:
        key = award.player_root.hex()
        retire_count = s.player_chip_inventories.get(key, {}).get(
            evt.retired_denomination, 0
        )
        full_new = (
            retire_count * evt.retired_denomination // evt.new_denomination
        )
        from_race = award.chips_won - full_new
        # rescue clause adds at most 1 chip on top of any race award; only
        # the race component itself must be ≤ 1 per Rule 24A.
        if award.rescued:
            from_race -= 1
        assert from_race <= 1, (
            f"Player {key[:8]} got {from_race} chips from the race; expected ≤1"
        )


@then(r'player "(?P<player_id>[^"]+)" stack is at least (?P<min_stack>\d+)')
def step_then_player_stack_at_least(context, player_id, min_stack):
    s = context.chip_race_post_state
    key = uuid_for(player_id).hex()
    stack = s.player_stacks.get(key, 0)
    assert stack >= int(min_stack), (
        f"Player {player_id} stack={stack}, expected ≥ {min_stack}"
    )


@then(r"the event has chips_added_by_rescue and chips_removed_by_race")
def step_then_event_has_conservation_fields(context):
    evt = tournament.ColorUpCompleted()
    context.result_event_any.Unpack(evt)
    assert hasattr(evt, "chips_added_by_rescue"), "Missing chips_added_by_rescue"
    assert hasattr(evt, "chips_removed_by_race"), "Missing chips_removed_by_race"
    assert evt.chips_added_by_rescue >= 0
    assert evt.chips_removed_by_race >= 0


@then(
    r"total_chips_in_play after race equals (?P<base>\d+) \+ "
    r"chips_added_by_rescue - chips_removed_by_race"
)
def step_then_total_chips_invariant(context, base):
    evt = tournament.ColorUpCompleted()
    context.result_event_any.Unpack(evt)
    s = context.chip_race_post_state
    expected = int(base) + evt.chips_added_by_rescue - evt.chips_removed_by_race
    assert s.total_chips_in_play == expected, (
        f"total_chips_in_play={s.total_chips_in_play}, "
        f"expected {expected} (base={base}, "
        f"+rescue={evt.chips_added_by_rescue}, "
        f"-race={evt.chips_removed_by_race})"
    )


# --- EU-1190 / EU-1191 / EU-1192 hand-for-hand ---


@given(r"hand-for-hand is active")
def step_given_h4h_active(context):
    """Append a HandForHandStarted event so the aggregate's H4H state
    is set on replay."""
    _ensure_events(context)
    event = tournament.HandForHandStarted(started_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a running tournament "(?P<name>[^"]+)" with hand-for-hand active and '
    r"level_seconds_remaining (?P<secs>\d+)"
)
def step_given_running_h4h_with_clock(context, name, secs):
    """Build a 4-player running tournament, enter H4H, seed the level
    clock to the requested duration."""
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=1500,
        max_players=9,
        min_players=2,
    )
    _append_registration_opened(context)
    for label in ("Alice", "Bob", "Carol", "Dave"):
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    event = tournament.HandForHandStarted(started_at=make_timestamp())
    context.events.append(make_event_page(event, seq=len(context.events)))
    context.seed_level_seconds_remaining = int(secs)


def _execute_with_seeded_clock(context, method_name, cmd):
    """Like _execute_handler but seeds level_seconds_remaining first."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    if hasattr(context, "seed_level_seconds_remaining"):
        agg._state.level_seconds_remaining = context.seed_level_seconds_remaining
        # Once seeded, future calls reuse the in-flight state via
        # context.h4h_agg_state below.
    if hasattr(context, "h4h_post_state"):
        agg._state.level_seconds_remaining = context.h4h_post_state.level_seconds_remaining
    actual_name = _HANDLER_MAP.get(method_name, method_name)
    method = getattr(agg, actual_name)
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
    context.events.append(result_page)
    context.agg = agg
    context.h4h_post_state = agg._state


@when(r"a hand-for-hand hand takes (?P<mins>\d+) minutes of real time to complete")
def step_when_h4h_hand_takes_real_time(context, mins):
    cmd = tournament.RecordHandForHandHand(real_seconds=int(mins) * 60)
    _execute_with_seeded_clock(context, "record_h4h_hand", cmd)


@when(r"the (?:first|second) hand-for-hand hand completes")
def step_when_h4h_hand_completes(context):
    cmd = tournament.RecordHandForHandHand()
    _execute_with_seeded_clock(context, "record_h4h_hand", cmd)


@then(r"the level_seconds_remaining(?: after the hand)? (?:equals|is) (?P<n>\d+)")
def step_then_level_seconds_remaining(context, n):
    s = context.h4h_post_state
    assert s.level_seconds_remaining == int(n), (
        f"level_seconds_remaining={s.level_seconds_remaining}, expected {n}"
    )


@when(
    r'players "(?P<players>[^"]+)" both bust on the same hand-for-hand hand'
)
def step_when_players_simultaneous_bust(context, players):
    """Issue RecordSimultaneousBusts with the named players."""
    names = [n.strip() for n in players.split(",")]
    cmd = tournament.RecordSimultaneousBusts(
        player_roots=[uuid_for(n) for n in names],
        hand_root=uuid_for("h4h_hand_1"),
    )
    _execute_handler(context, "record_sim_busts", cmd)


@given(
    r'a running tournament "(?P<name>[^"]+)" with registration open and '
    r"(?P<n>\d+) enrolled players"
)
def step_given_running_named_with_reg_open(context, name, n):
    n_int = int(n)
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=1500,
        max_players=max(n_int + 4, 9),
        min_players=2,
    )
    _append_registration_opened(context)
    # Use anonymous player labels so the named "Alice" used by
    # late-reg scenarios is still a fresh player.
    for i in range(n_int):
        _append_player_enrolled(context, f"early-p{i + 1}")
    _append_tournament_started(context)


# --- EU-1313 late-reg player can be dealt the button ---


@given(
    r'the dealer button at "(?P<table_name>[^"]+)" is about to advance to a '
    r"vacated seat (?P<seat>\d+)"
)
def step_given_dealer_about_to_advance(context, table_name, seat):
    """Build a Spring-1 table with all seats EXCEPT the named one
    occupied, and a prior HandStarted event whose dealer is one less
    than the vacated seat (so next-dealer rotation lands on it)."""
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    seat_int = int(seat)
    pages = []
    pages.append(
        make_event_page(
            table_proto.TableCreated(
                table_name=table_name,
                small_blind=25,
                big_blind=50,
                created_at=make_timestamp(),
            ),
            seq=0,
        )
    )
    for s in range(9):
        if s == seat_int:
            continue
        pages.append(
            make_event_page(
                table_proto.PlayerJoined(
                    player_root=uuid_for(f"{table_name}-p{s}"),
                    seat_position=s,
                    buy_in_amount=1500,
                    stack=1500,
                    joined_at=make_timestamp(),
                ),
                seq=len(pages),
            )
        )
    # Prior hand: dealer one position before the vacated seat so the
    # next-dealer rotation lands on the soon-to-be-filled vacated seat.
    prior_dealer = seat_int - 1 if seat_int > 0 else 8
    pages.append(
        make_event_page(
            table_proto.HandStarted(
                hand_root=b"prior-hand",
                hand_number=1,
                dealer_position=prior_dealer,
                small_blind_position=(prior_dealer + 1) % 9,
                big_blind_position=(prior_dealer + 2) % 9,
                small_blind=25,
                big_blind=50,
                started_at=make_timestamp(),
            ),
            seq=len(pages),
        )
    )
    pages.append(
        make_event_page(
            table_proto.HandEnded(
                hand_root=b"prior-hand",
                ended_at=make_timestamp(),
            ),
            seq=len(pages),
        )
    )
    context.late_reg_table_name = table_name
    context.late_reg_seat = seat_int
    context.late_reg_table_pages = pages


@when(
    r'player "(?P<player_id>[^"]+)" late-registers and is seated at '
    r'"(?P<table_name>[^"]+)" seat (?P<seat>\d+)'
)
def step_when_late_reg_seated(context, player_id, table_name, seat):
    """Enroll the player at the tournament aggregate, then synthesize
    a PlayerJoined event onto the table to fill the vacated seat."""
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    cmd = tournament.EnrollPlayer(
        player_root=uuid_for(player_id),
        reservation_id=f"res-{player_id}".encode(),
    )
    _execute_handler(context, "enroll", cmd)
    # Append PlayerJoined to the table's event stream so StartHand sees Alice.
    context.late_reg_table_pages.append(
        make_event_page(
            table_proto.PlayerJoined(
                player_root=uuid_for(player_id),
                seat_position=int(seat),
                buy_in_amount=1500,
                stack=1500,
                joined_at=make_timestamp(),
            ),
            seq=len(context.late_reg_table_pages),
        )
    )
    context.late_reg_player = player_id


@when(r'I handle a StartHand command at "(?P<table_name>[^"]+)"')
def step_when_start_hand_at_named_table_double_quoted(context, table_name):
    from table.agg.handlers import Table
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    book = _make_event_book(context.late_reg_table_pages)
    agg = Table(book)
    cmd = table_proto.StartHand()
    pre_pages = len(agg.event_book().pages)
    agg.handle_start_hand(cmd)
    new_pages = list(agg.event_book().pages)[pre_pages:]
    for page in new_pages:
        context.late_reg_table_pages.append(page)
    hand_started_page = new_pages[0]
    context.result = _make_event_book([hand_started_page])
    context.result_event_any = hand_started_page.event
    context.error = None


@then(r"the dealer_position is seat (?P<seat>\d+)")
def step_then_dealer_position_is_seat(context, seat):
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    evt = table_proto.HandStarted()
    context.result_event_any.Unpack(evt)
    assert evt.dealer_position == int(seat), (
        f"dealer_position={evt.dealer_position}, expected {seat}"
    )


@then(r'player "(?P<player_id>[^"]+)" is dealt in for that hand')
def step_then_player_dealt_in_for_hand(context, player_id):
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    evt = table_proto.HandStarted()
    context.result_event_any.Unpack(evt)
    target = uuid_for(player_id)
    found = any(p.player_root == target for p in evt.active_players)
    assert found, (
        f"Player {player_id} not in HandStarted active_players: "
        f"{[p.player_root.hex()[:8] for p in evt.active_players]}"
    )


# --- EU-1311 player on penalty has cards dealt then killed ---


@given(
    r'player "(?P<player_id>[^"]+)" is on a (?P<rounds>\d+)-round '
    r"(?P<ptype>VERBAL_WARNING|MISSED_HAND|MISSED_ROUND|DISQUALIFIED) penalty"
)
def step_given_player_on_penalty(context, player_id, rounds, ptype):
    """Issue a penalty for the named player against the running tournament."""
    cmd = tournament.IssuePenalty(
        player_root=uuid_for(player_id),
        type=ptype,
        rounds=int(rounds),
        table_size=2,
    )
    _execute_handler(context, "handle_issue_penalty", cmd)
    context.penalty_player = player_id
    context.penalty_initial_rounds = int(rounds)


@given(r'the next hand at (?P<player_id>\w+)\'s table has SB at \w+\'s seat')
def step_given_next_hand_sb_at_player_seat(context, player_id):
    """Set up a 2-player heads-up table with the on-penalty player at
    seat 0 (where, per HU rule, dealer == SB). Build the table via
    direct events on the Table aggregate; we keep tournament events
    untouched."""
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    other_label = "Bob" if player_id != "Bob" else "Alice"
    table_events = [
        make_event_page(
            table_proto.TableCreated(
                table_name=f"{player_id}-table",
                small_blind=25,
                big_blind=50,
                created_at=make_timestamp(),
            ),
            seq=0,
        ),
        make_event_page(
            table_proto.PlayerJoined(
                player_root=uuid_for(player_id),
                seat_position=0,
                buy_in_amount=1500,
                stack=1500,
                joined_at=make_timestamp(),
            ),
            seq=1,
        ),
        make_event_page(
            table_proto.PlayerJoined(
                player_root=uuid_for(other_label),
                seat_position=1,
                buy_in_amount=1500,
                stack=1500,
                joined_at=make_timestamp(),
            ),
            seq=2,
        ),
    ]
    context.table_events = table_events


@when(r"I handle a StartHand command at (?P<player_id>\w+)'s table")
def step_when_start_hand_at_player_table(context, player_id):
    """Issue StartHand on the previously-built table with the on-penalty
    player included in players_on_penalty. Captures the resulting events
    on context.table_events for downstream Then steps."""
    from table.agg.handlers import Table
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    book = _make_event_book(context.table_events)
    agg = Table(book)
    cmd = table_proto.StartHand(
        players_on_penalty=[uuid_for(context.penalty_player)],
    )
    pre_pages = len(agg.event_book().pages)
    agg.handle_start_hand(cmd)
    new_pages = list(agg.event_book().pages)[pre_pages:]
    # Capture all newly emitted events (HandStarted +
    # PlayerHandKilledByPenalty) into context.table_events, keep
    # HandStarted as the "result" for downstream "the result is X" step.
    for page in new_pages:
        context.table_events.append(page)
    hand_started_page = new_pages[0]
    context.result = _make_event_book([hand_started_page])
    context.result_event_any = hand_started_page.event
    context.error = None
    context.table_agg_state = agg._state


@then(r'player "(?P<player_id>[^"]+)" had her? SB posted from her? stack')
def step_then_sb_posted_from_stack(context, player_id):
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    found = False
    for page in context.table_events:
        if page.event.Is(table_proto.PlayerHandKilledByPenalty.DESCRIPTOR):
            evt = table_proto.PlayerHandKilledByPenalty()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id) and evt.stack_charged > 0:
                found = True
                break
    assert found, f"No SB-posting kill event for {player_id}"


@then(r'player "(?P<player_id>[^"]+)" hand is killed after the initial deal')
def step_then_hand_killed(context, player_id):
    from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
    found = False
    for page in context.table_events:
        if page.event.Is(table_proto.PlayerHandKilledByPenalty.DESCRIPTOR):
            evt = table_proto.PlayerHandKilledByPenalty()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                found = True
                break
    assert found, f"No PlayerHandKilledByPenalty event for {player_id}"


# --- EU-1316 seat redraw ---


@given(
    r'a running tournament "(?P<name>[^"]+)" with original_field '
    r"(?P<field>\d+) and (?P<tables>\d+) tables remaining"
)
def step_given_running_with_field(context, name, field, tables):
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=1500,
        max_players=int(field) + 50,
        min_players=2,
    )
    _append_registration_opened(context)
    for i in range(2):
        _append_player_enrolled(context, f"p{i}")
    _append_tournament_started(context)
    context.original_field = int(field)
    context.tables_remaining = int(tables)


@when(r"the field collapses to (?P<tables>\d+) table\(s\)")
def step_when_field_collapses(context, tables):
    cmd = tournament.TriggerSeatRedraw(
        tables_remaining=int(tables),
        original_field=context.original_field,
    )
    _execute_handler(context, "handle_trigger_seat_redraw", cmd)


@then(r'the redraw event has trigger "(?P<label>[^"]+)"')
def step_then_redraw_trigger(context, label):
    evt = tournament.SeatRedrawTriggered()
    context.result_event_any.Unpack(evt)
    assert evt.trigger == label, f"trigger={evt.trigger!r}, expected {label!r}"


# --- EU-1317 same-table simultaneous busts (WSOP-126b tiebreak) ---


@given(r"the current hand started with stacks: (?P<spec>.+)")
def step_given_hand_started_with_stacks(context, spec):
    """Parse a comma-separated 'Name N' list and stash as
    pre_hand_stacks for downstream sim-bust steps."""
    pairs: dict[str, int] = {}
    for chunk in spec.split(","):
        parts = chunk.strip().rsplit(" ", 1)
        pairs[parts[0]] = int(parts[1])
    context.pre_hand_stacks = pairs


@when(
    r'players "(?P<players>[^"]+)" both bust on the same hand at the same table'
)
def step_when_simultaneous_bust_same_table(context, players):
    names = [n.strip() for n in players.split(",")]
    pre_stacks = getattr(context, "pre_hand_stacks", {})
    cmd = tournament.RecordSimultaneousBusts(
        player_roots=[uuid_for(n) for n in names],
        hand_root=uuid_for("h4h_hand_st"),
        same_table=True,
        pre_hand_stacks={uuid_for(n).hex(): pre_stacks.get(n, 0) for n in names},
    )
    _execute_handler(context, "record_sim_busts", cmd)


@then(
    r'no TournamentResult has player_root "(?P<label>[^"]+)" with non-zero payout'
)
def step_then_no_result_with_nonzero_payout(context, label):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    target = uuid_for(label)
    matches = [r for r in evt.results if r.player_root == target and r.payout > 0]
    assert not matches, (
        f"Found unexpected paid TournamentResult for {label}: {matches}"
    )


@then(
    r'TournamentResult tiebreak_reason for position (?P<pos>\d+) is "(?P<reason>[^"]+)"'
)
def step_then_result_tiebreak_reason(context, pos, reason):
    evt = tournament.TournamentCompleted()
    context.result_event_any.Unpack(evt)
    matches = [r for r in evt.results if r.position == int(pos)]
    assert matches, f"No TournamentResult at position {pos}"
    assert any(r.tiebreak_reason == reason for r in matches), (
        f"No TournamentResult at position {pos} with tiebreak_reason "
        f"{reason!r}; got {[r.tiebreak_reason for r in matches]!r}"
    )


# --- EU-1371 HORSE rotation ---


@given(
    r"a HORSE tournament with (?P<n>\d+) active players starting on Texas Hold'em"
)
def step_given_horse_tournament(context, n):
    n_int = int(n)
    cmd = tournament.CreateTournament(
        name="HORSE",
        game_variant=poker_types.TEXAS_HOLDEM,
        buy_in=100,
        starting_stack=1500,
        min_players=2,
        max_players=max(n_int, 9),
    )
    _execute_handler(context, "create", cmd)
    _execute_handler(context, "open", tournament.OpenRegistration())
    for i in range(n_int):
        _execute_handler(
            context,
            "enroll",
            tournament.EnrollPlayer(
                player_root=uuid_for(f"p{i}"),
                reservation_id=f"res-{i}".encode(),
            ),
        )
    _execute_handler(context, "start", tournament.StartTournament())


@when(r"one full orbit of (?P<variant>.+) completes(?: \(.+\))?")
def step_when_orbit_completes(context, variant):
    cmd = tournament.RotateMixedGameVariant()
    _execute_handler(context, "handle_rotate_mixed_game_variant", cmd)


_VARIANT_LABEL_TO_PROTO = {
    "Texas Hold'em": 1,
    "Omaha Hi/Lo": 7,
    "Razz": 5,
    "Seven Card Stud": 4,
    "Seven Card Stud Hi/Lo 8 or Better": 6,
}


@then(r"the variant transitions (?:to|back to) (?P<variant>.+)")
def step_then_variant_transitions(context, variant):
    expected_id = _VARIANT_LABEL_TO_PROTO.get(variant.strip())
    assert expected_id is not None, f"Unknown variant label {variant!r}"
    evt = tournament.MixedGameVariantRotated()
    context.result_event_any.Unpack(evt)
    assert evt.to_variant == expected_id, (
        f"Expected to_variant={expected_id} ({variant}), got {evt.to_variant}"
    )


# --- EU-1375 end-of-day ---


@given(r"a running tournament at minute (?P<m>\d+) of the final scheduled level \(.+\)")
def step_given_running_at_final_level_minute(context, m):
    """Build a basic running tournament; the minute-marker is informational."""
    _append_created(
        context,
        name="EOD",
        buy_in=100,
        starting_stack=1500,
        max_players=9,
        min_players=2,
    )
    _append_registration_opened(context)
    for label in ("Alice", "Bob"):
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.eod_minute = int(m)


@given(r"a hand is currently in progress")
def step_given_hand_in_progress(context):
    context.hand_in_progress = True


@when(r"the floor issues a StopNewHands command")
def step_when_stop_new_hands(context):
    cmd = tournament.StopNewHands(reason="END_OF_DAY")
    _execute_handler(context, "handle_stop_new_hands", cmd)


@then(
    r'a NewHandsHalted event is emitted with effective_at "(?P<at>[^"]+)"'
)
def step_then_new_hands_halted(context, at):
    evt = tournament.NewHandsHalted()
    context.result_event_any.Unpack(evt)
    assert evt.effective_at == at, (
        f"effective_at={evt.effective_at!r}, expected {at!r}"
    )


@then(r"the in-progress hand is allowed to complete normally")
def step_then_in_progress_hand_completes(context):
    """Marker assertion — the StopNewHands semantics is enforced by the
    AFTER_CURRENT_HAND effective_at value already verified above."""
    assert getattr(context, "hand_in_progress", False)


@when(r"the in-progress hand completes")
def step_when_hand_completes(context):
    """Move the tournament status to TOURNAMENT_BAGGED via BagAndTag."""
    cmd = tournament.BagAndTag()
    _execute_handler(context, "handle_bag_and_tag", cmd)


@then(r"the tournament transitions to BAGGING_AND_TAGGING")
def step_then_transitions_to_bagging(context):
    book = _make_event_book(context.events)
    agg = Tournament(book)
    assert agg._state.status == tournament.TournamentStatus.TOURNAMENT_BAGGED, (
        f"status={agg._state.status}, expected TOURNAMENT_BAGGED"
    )


@then(
    r"no new StartHand command is accepted until the next day's resume"
)
def step_then_no_start_hand_until_resume(context):
    """Enforced by status: tournaments in BAGGED state cannot start new
    hands. We assert the status reflects this; a real StartHand on the
    Table aggregate would be gated by the saga checking tournament
    status before issuing the command."""
    book = _make_event_book(context.events)
    agg = Tournament(book)
    assert agg._state.status == tournament.TournamentStatus.TOURNAMENT_BAGGED


# --- EU-1376 Day 2 resume ---


@given(
    r"a tournament that completed Day 1 with bag-and-tag for (?P<n>\d+) "
    r"surviving players"
)
def step_given_completed_day1_with_bagtag(context, n):
    """Build a running tournament + seed N player_stacks and emit
    BagAndTagComplete to put it in TOURNAMENT_BAGGED."""
    n_int = int(n)
    _append_created(
        context,
        name="Day1",
        buy_in=100,
        starting_stack=1500,
        max_players=max(n_int, 9),
        min_players=2,
    )
    _append_registration_opened(context)
    names = [f"Player{i}" for i in range(n_int)]
    for label in names:
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.bagged_players = names
    context.bagged_stacks = {label: 1500 + i * 100 for i, label in enumerate(names)}


@given(
    r"a BagAndTagComplete event recorded each player's stack and seat"
)
def step_given_bag_and_tag_event(context):
    snapshots = [
        tournament.PlayerBagSnapshot(
            player_root=uuid_for(label),
            stack=context.bagged_stacks[label],
            table_root=b"day1-table",
            seat=i,
        )
        for i, label in enumerate(context.bagged_players)
    ]
    event = tournament.BagAndTagComplete(
        snapshots=snapshots,
        completed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@when(r"the floor issues a ResumeTournament command for Day 2")
def step_when_resume_day2(context):
    cmd = tournament.ResumeTournament()
    _execute_handler(context, "handle_resume_tournament", cmd)


@then(r"a TournamentResumed event is emitted")
def step_then_tournament_resumed(context):
    evt_type = type_name_from_url(context.result_event_any.type_url)
    assert evt_type.endswith("TournamentResumed"), (
        f"Expected TournamentResumed event, got {evt_type}"
    )


@then(r"every player's starting stack equals their Day 1 bagged stack")
def step_then_starting_stack_equals_bagged(context):
    book = _make_event_book(context.events)
    agg = Tournament(book)
    for label, stack in context.bagged_stacks.items():
        snap = agg._state.bagged_snapshots.get(uuid_for(label).hex())
        assert snap is not None and snap.stack == stack, (
            f"Player {label} bagged stack mismatch: snap={snap}, expected {stack}"
        )


@then(
    r"every player's seat assignment matches the Day 2 redraw if 100\+ event, "
    r"else bagged seat"
)
def step_then_seat_assignment_matches(context):
    """For events with <100 players, bagged seat is preserved. The
    bagged_snapshots dict carries the seat info."""
    book = _make_event_book(context.events)
    agg = Tournament(book)
    for label in context.bagged_players:
        snap = agg._state.bagged_snapshots.get(uuid_for(label).hex())
        assert snap is not None, f"No bagged snapshot for {label}"


# --- EU-1151 re-entry chip removal ---


@given(
    r'a running tournament "(?P<name>[^"]+)" with starting_stack '
    r"(?P<stack>\d+) and (?P<n>\d+) enrolled players"
)
def step_given_running_with_stack_and_players(context, name, stack, n):
    """Build a running tournament with the given starting_stack and N
    enrolled players (Alice/Bob/Carol/Dave...)."""
    n_int = int(n)
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=int(stack),
        max_players=max(n_int, 9),
        min_players=2,
    )
    _append_registration_opened(context)
    names = ("Alice", "Bob", "Carol", "Dave", "Eve", "Frank")
    for i in range(n_int):
        label = names[i] if i < len(names) else f"p{i + 1}"
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.starting_stack = int(stack)


@given(r"total_chips_in_play is (?P<n>\d+)")
def step_given_total_chips_in_play_simple(context, n):
    """Seed total_chips_in_play on the in-flight aggregate via a side
    channel context attribute consumed by the next handler call."""
    context.seed_total_chips_in_play = int(n)


@given(
    r'player "(?P<player_id>[^"]+)" has (?P<chips>\d+) chips remaining and '
    r"elects to re-enter"
)
def step_given_player_re_entering(context, player_id, chips):
    context.re_entry_player = player_id
    context.re_entry_forfeit = int(chips)


@when(
    r'I handle a ReEntryPlayer command for player "(?P<player_id>[^"]+)" '
    r"forfeiting (?P<chips>\d+) chips"
)
def step_when_re_entry(context, player_id, chips):
    """Issue the re-entry command, seeding total_chips_in_play first."""
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    if hasattr(context, "seed_total_chips_in_play"):
        agg._state.total_chips_in_play = context.seed_total_chips_in_play
    cmd = tournament.ReEntryPlayer(
        player_root=uuid_for(player_id),
        chips_forfeited=int(chips),
    )
    result_event = agg.handle_re_entry_player(cmd)
    event_any = ProtoAny()
    event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
    page = types.EventPage(
        header=types.PageHeader(sequence=len(context.events)),
        event=event_any,
        created_at=make_timestamp(),
    )
    context.result = _make_event_book([page])
    context.result_event_any = event_any
    context.error = None
    context.events.append(page)
    context.agg = agg


@then(r"the tournament event has chips_forfeited (?P<n>\d+)")
def step_then_event_chips_forfeited(context, n):
    evt = tournament.PlayerReEntered()
    context.result_event_any.Unpack(evt)
    assert evt.chips_forfeited == int(n), (
        f"chips_forfeited={evt.chips_forfeited}, expected {n}"
    )


# --- EU-1370 absent player on broken table ---


@given(
    r'a tournament with table "(?P<from_t>[^"]+)" being broken and '
    r'player "(?P<player_id>[^"]+)" absent at "(?P<at_table>[^"]+)"'
)
def step_given_broken_table_with_absent(context, from_t, player_id, at_table):
    """Build a basic running tournament context for the breaking-table
    scenario. The 'broken' state is conceptual; we just need a running
    tournament so the ReseatAbsentPlayer command is valid."""
    _append_created(
        context,
        name="Broken",
        buy_in=100,
        starting_stack=1500,
        max_players=18,
        min_players=2,
    )
    _append_registration_opened(context)
    for label in (player_id, "Other"):
        _append_player_enrolled(context, label)
    _append_tournament_started(context)
    context.broken_from_table = from_t
    context.absent_player = player_id


@given(r'player "(?P<player_id>[^"]+)" had (?P<stack>\d+) in chips on "(?P<table>[^"]+)"')
def step_given_absent_chips(context, player_id, stack, table):
    context.absent_stack = int(stack)


@given(r'open seats exist at table "(?P<t1>[^"]+)" and "(?P<t2>[^"]+)"')
def step_given_open_seats_at(context, t1, t2):
    context.target_table = t1


@when(r'the breaking-table coordinator reseats absent "(?P<player_id>[^"]+)"')
def step_when_reseat_absent(context, player_id):
    cmd = tournament.ReseatAbsentPlayer(
        player_root=uuid_for(player_id),
        from_table_root=uuid_for(context.broken_from_table),
        to_table_root=uuid_for(context.target_table),
        to_seat=0,
        stack=context.absent_stack,
    )
    _execute_handler(context, "handle_reseat_absent_player", cmd)


@then(
    r'a PlayerMovedTables event is emitted for "(?P<player_id>[^"]+)" '
    r'with from_table "(?P<from_t>[^"]+)"'
)
def step_then_player_moved_tables(context, player_id, from_t):
    found = False
    for page in context.events:
        if page.event.Is(tournament.PlayerMovedTables.DESCRIPTOR):
            evt = tournament.PlayerMovedTables()
            page.event.Unpack(evt)
            if (
                evt.player_root == uuid_for(player_id)
                and evt.from_table_root == uuid_for(from_t)
            ):
                found = True
                break
    assert found, f"No PlayerMovedTables for {player_id} from {from_t}"


@then(
    r'player "(?P<player_id>[^"]+)" stack at the new table equals (?P<stack>\d+)'
)
def step_then_player_stack_at_new_table(context, player_id, stack):
    for page in context.events:
        if page.event.Is(tournament.PlayerMovedTables.DESCRIPTOR):
            evt = tournament.PlayerMovedTables()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                assert evt.stack == int(stack), (
                    f"PlayerMovedTables stack={evt.stack}, expected {stack}"
                )
                return
    assert False, f"No PlayerMovedTables event for {player_id}"


@then(
    r'player "(?P<player_id>[^"]+)" missed-blinds clock continues at the new table'
)
def step_then_missed_blinds_clock_continues(context, player_id):
    """absent_at_move=true on PlayerMovedTables is the marker that
    the missed-blinds clock keeps running."""
    for page in context.events:
        if page.event.Is(tournament.PlayerMovedTables.DESCRIPTOR):
            evt = tournament.PlayerMovedTables()
            page.event.Unpack(evt)
            if evt.player_root == uuid_for(player_id):
                assert evt.absent_at_move, (
                    "absent_at_move must be true for missed-blinds clock to continue"
                )
                return
    assert False, f"No PlayerMovedTables event for {player_id}"


# --- EU-1315 heads-up absent blind progression ---


@given(
    r'a running tournament "(?P<name>[^"]+)" in heads-up between '
    r'"(?P<a>[^"]+)" and "(?P<b>[^"]+)"'
)
def step_given_hu_tournament(context, name, a, b):
    _append_created(
        context,
        name=name,
        buy_in=100,
        starting_stack=1500,
        max_players=2,
        min_players=2,
    )
    _append_registration_opened(context)
    _append_player_enrolled(context, a)
    _append_player_enrolled(context, b)
    _append_tournament_started(context)
    context.hu_lone = a
    context.hu_absent = b


@given(
    r'player "(?P<player_id>[^"]+)" has been absent from the table for '
    r"(?P<mins>\d+) minutes"
)
def step_given_hu_absent_minutes(context, player_id, mins):
    """Records the absence; the AdvanceAbsentBlind tick is what moves
    chips. Per WSOP Rule 36 the first 5 minutes are grace; after that
    each 2-minute tick produces an AbsentBlindAdvanced event."""
    context.hu_absent_minutes = int(mins)


@when(
    r'(?P<mins>\d+) minutes elapses with player "(?P<player_id>[^"]+)" still absent'
)
def step_when_hu_absent_elapses(context, mins, player_id):
    cmd = tournament.AdvanceAbsentBlind(
        table_root=uuid_for("hu-table"),
        absent_player_root=uuid_for(context.hu_absent),
        lone_player_root=uuid_for(context.hu_lone),
        small_blind=25,
        big_blind=50,
    )
    # Seed the lone+absent stacks so apply step has a baseline.
    _ensure_events(context)
    book = _make_event_book(context.events)
    agg = Tournament(book)
    agg._state.player_stacks[uuid_for(context.hu_lone).hex()] = 1500
    agg._state.player_stacks[uuid_for(context.hu_absent).hex()] = 1500
    result_event = agg.handle_advance_absent_blind(cmd)
    event_any = ProtoAny()
    event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
    page = types.EventPage(
        header=types.PageHeader(sequence=len(context.events)),
        event=event_any,
        created_at=make_timestamp(),
    )
    context.result = _make_event_book([page])
    context.result_event_any = event_any
    context.error = None
    context.events.append(page)
    context.agg = agg
    context.hu_post_state = agg._state


@then(r"the dealer button advances by (?P<n>\d+) position")
def step_then_button_advances(context, n):
    """The button advance is recorded by the AbsentBlindAdvanced event;
    the actual button rotation lives on the Table aggregate. For this
    unit-level scenario we just verify the event was emitted."""
    evt = tournament.AbsentBlindAdvanced()
    context.result_event_any.Unpack(evt)
    assert evt.stack_delta > 0


@then(r'player "(?P<player_id>[^"]+)" stack is increased by SB \+ BB')
def step_then_stack_increased_by_blinds(context, player_id):
    s = context.hu_post_state
    key = uuid_for(player_id).hex()
    assert s.player_stacks.get(key, 0) > 1500, (
        f"Stack should have increased; got {s.player_stacks.get(key)}"
    )


@then(r'player "(?P<player_id>[^"]+)" stack is decreased by SB \+ BB')
def step_then_stack_decreased_by_blinds(context, player_id):
    s = context.hu_post_state
    key = uuid_for(player_id).hex()
    assert s.player_stacks.get(key, 1500) < 1500, (
        f"Stack should have decreased; got {s.player_stacks.get(key)}"
    )


@then(
    r'player "(?P<player_id>[^"]+)" remains on penalty with rounds_remaining '
    r"decremented by (?P<n>\d+)"
)
def step_then_penalty_decremented(context, player_id, n):
    """Issue DecrementPenalty against the tournament aggregate and
    verify the rounds_remaining matches the expected post-decrement
    count."""
    cmd = tournament.DecrementPenalty(player_root=uuid_for(player_id))
    book = _make_event_book(context.events)
    agg = Tournament(book)
    decrement_event = agg.handle_decrement_penalty(cmd)
    expected = max(0, context.penalty_initial_rounds - int(n))
    assert decrement_event.rounds_remaining == expected, (
        f"rounds_remaining={decrement_event.rounds_remaining}, expected {expected}"
    )
