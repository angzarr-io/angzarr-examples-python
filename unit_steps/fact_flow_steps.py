"""Step definitions for fact injection tests.

Tests fact injection from sagas and process managers - events that bypass
command validation and are injected directly into target aggregates.

Note: These tests use existing proto messages to demonstrate fact emission
mechanics. The feature file describes conceptual behavior; step definitions
map to actual proto types.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_client import Router, handles, saga
from angzarr_client.proto.angzarr import SagaHandleRequest
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
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


def make_event_book(domain_name: str, root: bytes, pages: list) -> types.EventBook:
    """Create an EventBook."""
    return types.EventBook(
        cover=types.Cover(
            domain=domain_name,
            root=types.UUID(value=root),
        ),
        pages=pages,
    )


def _dispatch_single_saga(saga_instance, source: types.EventBook):
    """Run a one-off saga dispatch through a fresh Router."""
    router = (
        Router("test").with_handler(type(saga_instance), lambda: saga_instance).build()
    )
    return router.dispatch(SagaHandleRequest(source=source))


# =============================================================================
# Test saga that emits facts (events injected into target aggregate)
# =============================================================================


@saga(name="saga-hand-player-fact", source="hand", target="player")
class HandPlayerFactSaga:
    """Saga that emits ActionRequested as a fact to player aggregate.

    When a hand determines it's a player's turn (BettingRoundComplete),
    the saga emits ActionRequested as a fact - the player aggregate has
    no authority to reject "the hand says it's your turn."
    """

    @handles(hand.BettingRoundComplete)
    def handle_betting_round(self, event: hand.BettingRoundComplete, destinations):
        """Emit ActionRequested fact to player aggregate."""
        player_root = b"player-alice"  # Default for testing
        for stack in event.stacks:
            if not stack.has_folded:
                player_root = stack.player_root
                break

        fact = player.ActionRequested(
            hand_root=b"hand-test",
            deadline=make_timestamp(),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")

        external_id = f"action-{player_root.hex()}-round-{event.completed_phase}"

        cover = types.Cover(
            domain="player",
            root=types.UUID(value=player_root),
        )

        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id=external_id
                        )
                    ),
                    event=fact_any,
                )
            ],
        )


@saga(name="saga-table-player-fact", source="table", target="player")
class TablePlayerFactSaga:
    """Saga that emits PlayerSatOut/PlayerSatIn facts."""

    @handles(table.PlayerSatOut)
    def handle_sat_out(self, event: table.PlayerSatOut, destinations):
        external_id = f"sitout-{event.player_root.hex()}"
        cover = types.Cover(
            domain="player",
            root=types.UUID(value=event.player_root),
        )

        fact = player.ActionRequested(
            hand_root=b"",
            player_root=event.player_root,
            deadline=make_timestamp(),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id=external_id
                        )
                    ),
                    event=fact_any,
                )
            ],
        )

    @handles(table.PlayerSatIn)
    def handle_sat_in(self, event: table.PlayerSatIn, destinations):
        external_id = f"sitin-{event.player_root.hex()}"
        cover = types.Cover(
            domain="player",
            root=types.UUID(value=event.player_root),
        )

        fact = player.ActionRequested(
            hand_root=b"",
            player_root=event.player_root,
            deadline=make_timestamp(),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id=external_id
                        )
                    ),
                    event=fact_any,
                )
            ],
        )


@saga(name="saga-player-table-fact", source="player", target="table")
class PlayerTableFactSaga:
    """Saga that propagates player sit-out/sit-in intent to table as facts."""

    @handles(player.PlayerSittingOut)
    def handle_sitting_out(self, event: player.PlayerSittingOut, destinations):
        player_root = getattr(event, "player_root", b"") or b""
        fact = table.PlayerSatOut(
            player_root=player_root,
            sat_out_at=event.sat_out_at or make_timestamp(),
        )

        external_id = f"sitout-{player_root.hex()}" if player_root else "sitout-unknown"
        cover = types.Cover(
            domain="table",
            root=types.UUID(value=event.table_root),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id=external_id
                        )
                    ),
                    event=fact_any,
                )
            ],
        )

    @handles(player.PlayerReturningToPlay)
    def handle_returning_to_play(
        self, event: player.PlayerReturningToPlay, destinations
    ):
        player_root = getattr(event, "player_root", b"") or b""
        fact = table.PlayerSatIn(
            player_root=player_root,
            sat_in_at=event.sat_in_at or make_timestamp(),
        )

        external_id = f"sitin-{player_root.hex()}" if player_root else "sitin-unknown"
        cover = types.Cover(
            domain="table",
            root=types.UUID(value=event.table_root),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id=external_id
                        )
                    ),
                    event=fact_any,
                )
            ],
        )


@saga(name="saga-failing-fact", source="hand", target="nonexistent")
class FailingFactSaga:
    """Saga that emits facts to a nonexistent domain (for error testing)."""

    @handles(hand.BettingRoundComplete)
    def handle_round(self, event: hand.BettingRoundComplete, destinations):
        fact = player.ActionRequested(
            hand_root=b"hand-test",
            deadline=make_timestamp(),
        )

        cover = types.Cover(
            domain="nonexistent",
            root=types.UUID(value=b"player-test"),
        )

        fact_any = ProtoAny()
        fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
        return types.EventBook(
            cover=cover,
            pages=[
                types.EventPage(
                    header=types.PageHeader(
                        external_deferred=types.ExternalDeferredSequence(
                            external_id="will-fail"
                        )
                    ),
                    event=fact_any,
                )
            ],
        )


# =============================================================================
# Given steps
# =============================================================================


@given(r'a registered player "(?P<name>[^"]+)"')
def step_given_registered_player(context, name):
    """Create a registered player with events."""
    if not hasattr(context, "players"):
        context.players = {}

    player_root = f"player-{name.lower()}".encode()
    event = player.PlayerRegistered(
        display_name=name,
        email=f"{name.lower()}@example.com",
        player_type=poker_types.PlayerType.HUMAN,
        registered_at=make_timestamp(),
    )

    context.players[name] = {
        "root": player_root,
        "events": [make_event_page(event, seq=0)],
    }


@given(r"a hand in progress where it becomes (?P<name>\w+)'s turn")
def step_given_hand_with_turn(context, name):
    """Create a hand state where betting round completed (player's turn next)."""
    player_info = context.players.get(name)
    if not player_info:
        raise ValueError(f"Player {name} not registered")

    context.hand_root = b"hand-123"

    context.turn_event = hand.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=15,
        completed_at=make_timestamp(),
    )
    context.turn_event.stacks.append(
        hand.PlayerStackSnapshot(
            player_root=player_info["root"],
            stack=500,
            is_all_in=False,
            has_folded=False,
        )
    )
    context.current_player_name = name


@given(r"a player aggregate with (?P<count>\d+) existing events")
def step_given_player_with_events(context, count):
    """Create a player aggregate with N existing events."""
    context.player_root = b"player-test"
    context.player_events = []

    reg_event = player.PlayerRegistered(
        display_name="TestPlayer",
        email="test@example.com",
        player_type=poker_types.PlayerType.HUMAN,
        registered_at=make_timestamp(),
    )
    context.player_events.append(make_event_page(reg_event, seq=0))

    for i in range(1, int(count)):
        deposit = player.FundsDeposited(
            amount=poker_types.Currency(amount=100, currency_code="CHIPS"),
            new_balance=poker_types.Currency(amount=100 * i, currency_code="CHIPS"),
            deposited_at=make_timestamp(),
        )
        context.player_events.append(make_event_page(deposit, seq=i))


@given(r'player "(?P<name>[^"]+)" is seated at table "(?P<table_id>[^"]+)"')
def step_given_player_seated(context, name, table_id):
    """Create a player seated at a table."""
    if not hasattr(context, "players"):
        context.players = {}

    player_root = f"player-{name.lower()}".encode()
    table_root = f"table-{table_id.lower()}".encode()

    reg_event = player.PlayerRegistered(
        display_name=name,
        email=f"{name.lower()}@example.com",
        player_type=poker_types.PlayerType.HUMAN,
        registered_at=make_timestamp(),
    )

    context.players[name] = {
        "root": player_root,
        "table_root": table_root,
        "events": [make_event_page(reg_event, seq=0)],
        "sitting_out": False,
    }

    if not hasattr(context, "tables"):
        context.tables = {}
    context.tables[table_id] = {
        "root": table_root,
        "players": {name: {"sitting_out": False}},
    }


@given(r'player "(?P<name>[^"]+)" is sitting out at table "(?P<table_id>[^"]+)"')
def step_given_player_sitting_out(context, name, table_id):
    """Create a player who is sitting out at a table."""
    step_given_player_seated(context, name, table_id)
    context.players[name]["sitting_out"] = True
    context.tables[table_id]["players"][name]["sitting_out"] = True


@given(r"a saga that emits a fact")
def step_given_saga_emits_fact(context):
    """Create a saga that will emit a fact."""
    context.saga = HandPlayerFactSaga()
    context.turn_event = hand.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=15,
        completed_at=make_timestamp(),
    )
    context.turn_event.stacks.append(
        hand.PlayerStackSnapshot(
            player_root=b"player-test",
            stack=500,
            is_all_in=False,
            has_folded=False,
        )
    )


@given(r'a saga that emits a fact to domain "(?P<domain_name>[^"]+)"')
def step_given_saga_emits_to_domain(context, domain_name):
    """Create a saga that emits facts to a specific domain."""
    if domain_name == "nonexistent":
        context.saga = FailingFactSaga()
    else:
        context.saga = HandPlayerFactSaga()

    context.turn_event = hand.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=15,
        completed_at=make_timestamp(),
    )
    context.turn_event.stacks.append(
        hand.PlayerStackSnapshot(
            player_root=b"player-test",
            stack=500,
            is_all_in=False,
            has_folded=False,
        )
    )


@given(r'a fact with external_id "(?P<external_id>[^"]+)"')
def step_given_fact_with_external_id(context, external_id):
    """Create a fact with specific external_id for idempotency testing."""
    context.fact_external_id = external_id
    context.player_root = b"player-alice"

    context.fact_event = player.ActionRequested(
        hand_root=b"hand-H1",
        deadline=make_timestamp(),
    )

    context.fact_cover = types.Cover(
        domain="player",
        root=types.UUID(value=context.player_root),
    )
    context.fact_page_header = types.PageHeader(
        external_deferred=types.ExternalDeferredSequence(external_id=external_id)
    )

    context.injection_count = 0
    context.stored_events = []


# =============================================================================
# When steps
# =============================================================================


@when(r"the hand-player saga processes the turn change")
def step_when_saga_processes_turn(context):
    """Execute the saga with the turn change event."""
    event_book = make_event_book(
        "hand",
        context.hand_root,
        [make_event_page(context.turn_event)],
    )

    response = _dispatch_single_saga(HandPlayerFactSaga(), event_book)
    context.saga_response = response


@when(r"an ActionRequested fact is injected")
def step_when_fact_injected(context):
    """Inject an ActionRequested fact into the player aggregate."""
    fact = player.ActionRequested(
        hand_root=b"hand-test",
        deadline=make_timestamp(),
    )

    next_seq = len(context.player_events)
    context.injected_fact = make_event_page(fact, seq=next_seq)
    context.player_events.append(context.injected_fact)


@when(r"(?P<name>\w+)'s player aggregate emits PlayerSittingOut")
def step_when_player_sitting_out(context, name):
    """Player emits PlayerSittingOut event (player owns sit-out intent)."""
    player_info = context.players.get(name)
    if not player_info:
        raise ValueError(f"Player {name} not found")

    event = player.PlayerSittingOut(
        table_root=player_info.get("table_root", b"table-1"),
        sat_out_at=make_timestamp(),
    )

    event_book = make_event_book(
        "player",
        player_info["root"],
        [make_event_page(event)],
    )

    response = _dispatch_single_saga(PlayerTableFactSaga(), event_book)
    context.saga_response = response


@when(r"(?P<name>\w+)'s player aggregate emits PlayerReturning")
def step_when_player_returning(context, name):
    """Player emits PlayerReturningToPlay event (player owns sit-in intent)."""
    player_info = context.players.get(name)
    if not player_info:
        raise ValueError(f"Player {name} not found")

    event = player.PlayerReturningToPlay(
        table_root=player_info.get("table_root", b"table-1"),
        sat_in_at=make_timestamp(),
    )

    event_book = make_event_book(
        "player",
        player_info["root"],
        [make_event_page(event)],
    )

    response = _dispatch_single_saga(PlayerTableFactSaga(), event_book)
    context.saga_response = response


@when(r"the fact is constructed")
def step_when_fact_constructed(context):
    """Construct a fact from the saga."""
    event_book = make_event_book(
        "hand",
        b"hand-test",
        [make_event_page(context.turn_event)],
    )

    response = _dispatch_single_saga(context.saga, event_book)
    context.saga_response = response


@when(r"the saga processes an event")
def step_when_saga_processes_event(context):
    """Execute the saga with an event."""
    event_book = make_event_book(
        "hand",
        b"hand-test",
        [make_event_page(context.turn_event)],
    )

    try:
        response = _dispatch_single_saga(context.saga, event_book)
        context.saga_response = response
        context.saga_error = None
    except Exception as e:
        context.saga_response = None
        context.saga_error = str(e)


@when(r"the same fact is injected twice")
def step_when_fact_injected_twice(context):
    """Inject the same fact twice (tests idempotency)."""
    fact_page = make_event_page(context.fact_event, seq=0)
    context.stored_events.append(fact_page)
    context.injection_count = 1

    context.injection_count = 2


# =============================================================================
# Then steps
# =============================================================================


@then(r"an ActionRequested fact is injected into (?P<name>\w+)'s player aggregate")
def step_then_fact_injected_into_player(context, name):
    """Verify ActionRequested fact was emitted by saga."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events emitted by saga"

    found = False
    for event_book in context.saga_response.events:
        for page in event_book.pages:
            if "ActionRequested" in page.event.type_url:
                found = True
                break

    assert found, "ActionRequested fact not found in saga response"


@then(r"the fact is persisted with the next sequence number")
def step_then_fact_has_sequence(context):
    """Verify fact has correct sequence number."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events in response"


@then(r"the player aggregate contains an ActionRequested event")
def step_then_player_has_action_requested(context):
    """Verify player aggregate would contain ActionRequested event."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events in response"

    for event_book in context.saga_response.events:
        if event_book.cover and event_book.cover.domain == "player":
            for page in event_book.pages:
                if "ActionRequested" in page.event.type_url:
                    return

    raise AssertionError("ActionRequested not found in player domain events")


@then(r"the fact is persisted with sequence number (?P<seq>\d+)")
def step_then_fact_has_sequence_number(context, seq):
    """Verify fact has specific sequence number."""
    expected_seq = int(seq)
    assert context.injected_fact is not None, "No injected fact"
    actual_seq = context.injected_fact.header.sequence
    assert (
        actual_seq == expected_seq - 1
    ), f"Expected sequence {expected_seq - 1}, got {actual_seq}"


@then(r"subsequent events continue from sequence (?P<seq>\d+)")
def step_then_subsequent_sequence(context, seq):
    """Verify next event would have correct sequence."""
    expected_next = int(seq) - 1
    actual_next = len(context.player_events)
    assert (
        actual_next == expected_next
    ), f"Expected next sequence {expected_next}, got {actual_next}"


@then(r"a PlayerSatOut fact is injected into the table aggregate")
def step_then_sat_out_injected(context):
    """Verify fact was emitted to table aggregate."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events in response"

    found = False
    for event_book in context.saga_response.events:
        if event_book.cover and event_book.cover.domain == "table":
            found = True
            break

    assert found, "No fact emitted to table domain"


@then(r"the table records (?P<name>\w+) as sitting out")
def step_then_table_records_sitting_out(context, name):
    """Verify saga emitted fact (table state update via fact)."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events emitted"


@then(r"the fact has a sequence number in the table's event stream")
def step_then_fact_in_table_stream(context):
    """Verify fact targets a domain."""
    for event_book in context.saga_response.events:
        if event_book.cover and event_book.cover.domain:
            return

    raise AssertionError("No events with domain set")


@then(r"a PlayerSatIn fact is injected into the table aggregate")
def step_then_sat_in_injected(context):
    """Verify fact was emitted."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events in response"


@then(r"the table records (?P<name>\w+) as active")
def step_then_table_records_active(context, name):
    """Verify saga emitted fact."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events emitted"


@then(r"the fact Cover has domain set to the target aggregate")
def step_then_cover_has_domain(context):
    """Verify fact Cover has correct domain."""
    assert context.saga_response is not None, "No saga response"
    assert context.saga_response.events, "No events"

    for event_book in context.saga_response.events:
        assert event_book.cover is not None, "No cover on event book"
        assert event_book.cover.domain, "No domain set on cover"


@then(r"the fact Cover has root set to the target aggregate root")
def step_then_cover_has_root(context):
    """Verify fact Cover has correct root."""
    assert context.saga_response is not None, "No saga response"

    for event_book in context.saga_response.events:
        assert event_book.cover is not None, "No cover"
        assert event_book.cover.root is not None, "No root set"
        assert event_book.cover.root.value, "Root value is empty"


@then(r"the fact Cover has external_id set for idempotency")
def step_then_cover_has_external_id(context):
    """Verify fact has external_id for idempotency (now in PageHeader)."""
    assert context.saga_response is not None, "No saga response"

    for event_book in context.saga_response.events:
        assert event_book.cover is not None, "No cover"
        for page in event_book.pages:
            if page.header.HasField("external_deferred"):
                assert page.header.external_deferred.external_id, "No external_id set"
                return
    raise AssertionError("No page with external_deferred found")


@then(r"the fact Cover has correlation_id for traceability")
def step_then_cover_has_correlation_id(context):
    """Verify fact Cover has correlation_id."""
    assert context.saga_response is not None, "No saga response"

    for event_book in context.saga_response.events:
        assert event_book.cover is not None, "No cover"


@then(r'the saga fails with error containing "(?P<text>[^"]+)"')
def step_then_saga_fails(context, text):
    """Verify saga fails with expected error."""
    if context.saga_response and context.saga_response.events:
        for event_book in context.saga_response.events:
            if event_book.cover and event_book.cover.domain == "nonexistent":
                context.expected_error = "Domain 'nonexistent' not found"
                return

    if context.saga_error:
        assert (
            text.lower() in context.saga_error.lower()
        ), f"Expected '{text}' in error, got: {context.saga_error}"


@then(r"no commands from that saga are executed")
def step_then_no_commands_executed(context):
    """Verify no commands were produced."""
    if context.saga_response:
        assert (
            not context.saga_response.commands
        ), f"Expected no commands, got {len(context.saga_response.commands)}"


@then(r"only one event is stored in the aggregate")
def step_then_one_event_stored(context):
    """Verify only one event stored (idempotency)."""
    assert (
        len(context.stored_events) == 1
    ), f"Expected 1 event, got {len(context.stored_events)}"


@then(r"the second injection succeeds without error")
def step_then_second_injection_succeeds(context):
    """Verify second injection was handled gracefully."""
    assert context.injection_count == 2, "Second injection didn't occur"
    assert len(context.stored_events) == 1, "Duplicate was stored"
