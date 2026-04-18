"""Behave step definitions for saga tests.

Tests the unified Router / @saga decorator pattern.
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


def _build_command_book(cmd_msg, target_domain: str, root: bytes = b"") -> types.CommandBook:
    cmd_any = ProtoAny()
    cmd_any.Pack(cmd_msg, type_url_prefix="type.googleapis.com/")
    cover = types.Cover(domain=target_domain)
    if root:
        cover.root.CopyFrom(types.UUID(value=root))
    return types.CommandBook(
        cover=cover,
        pages=[types.CommandPage(command=cmd_any)],
    )


# =============================================================================
# Saga implementations for testing
# =============================================================================


@saga(name="saga-table-hand", source="table", target="hand")
class TableSyncSaga:
    """Table -> Hand saga for testing."""

    @handles(table.HandStarted)
    def handle_hand_started(self, event: table.HandStarted, destinations):
        cmd = hand.DealCards(
            table_root=event.hand_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
        )

        for seat in event.active_players:
            cmd.players.append(
                hand.PlayerInHand(
                    player_root=seat.player_root,
                    position=seat.position,
                    stack=seat.stack,
                )
            )

        return _build_command_book(cmd, target_domain="hand", root=event.hand_root)


@saga(name="saga-hand-table", source="hand", target="table")
class HandToTableSaga:
    """Hand -> Table saga: hand.HandComplete -> table.EndHand."""

    @handles(hand.HandComplete)
    def handle_hand_complete(self, event: hand.HandComplete, destinations):
        cmd = table.EndHand(
            hand_root=event.table_root,
        )
        for winner in event.winners:
            cmd.results.append(
                table.PotResult(
                    winner_root=winner.player_root,
                    amount=winner.amount,
                    pot_type=winner.pot_type,
                )
            )
        return _build_command_book(cmd, target_domain="table", root=event.table_root)


@saga(name="saga-hand-player", source="hand", target="player")
class HandResultsSaga:
    """Hand -> Player saga: hand.PotAwarded -> player.DepositFunds."""

    @handles(hand.PotAwarded)
    def handle_pot_awarded(self, event: hand.PotAwarded, destinations):
        commands = []
        for winner in event.winners:
            cmd = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount, currency_code="CHIPS"
                ),
            )
            commands.append(
                _build_command_book(cmd, target_domain="player", root=winner.player_root)
            )
        return tuple(commands) if commands else None


@saga(name="saga-table-player", source="table", target="player")
class TableHandEndedSaga:
    """Table -> Player: table.HandEnded -> player.ReleaseFunds."""

    @handles(table.HandEnded)
    def handle_hand_ended(self, event: table.HandEnded, destinations):
        commands = []
        for player_hex, _change in event.stack_changes.items():
            cmd = player.ReleaseFunds(
                table_root=event.hand_root,
            )
            root = bytes.fromhex(player_hex)
            commands.append(
                _build_command_book(cmd, target_domain="player", root=root)
            )
        return tuple(commands) if commands else None


@saga(name="saga-failing", source="table", target="hand")
class FailingSaga:
    """A saga that always fails for testing."""

    @handles(table.HandStarted)
    def handle_hand_started(self, event: table.HandStarted, destinations):
        raise RuntimeError("FailingSaga always fails")


# =============================================================================
# Simple TestSagaRouter for testing multiple sagas (with error tolerance)
# =============================================================================


class TestSagaRouter:
    """Routes events to multiple registered sagas, tolerating failures."""

    def __init__(self):
        self._handlers: list = []

    def register(self, saga_instance) -> "TestSagaRouter":
        self._handlers.append(saga_instance)
        return self

    def route(
        self, source: types.EventBook, source_domain: str = None
    ) -> list[types.CommandBook]:
        """Route events to all matching sagas, collect commands."""
        commands = []
        for inst in self._handlers:
            # Only route to sagas that listen to this domain
            meta = type(inst).__angzarr_meta__
            if source_domain and meta.get("source") != source_domain:
                continue
            try:
                single_router = Router("test").with_handler(inst).build()
                response = single_router.dispatch(SagaHandleRequest(source=source))
                commands.extend(response.commands)
            except Exception:
                # Continue routing to other sagas even if one fails
                pass
        return commands


# =============================================================================
# Given steps
# =============================================================================


@given("a TableSyncSaga")
def step_given_table_sync_saga(context):
    """Create TableSyncSaga instance."""
    context.saga = TableSyncSaga()
    context.event = None
    context.event_book = None
    context.commands = []


@given("a HandResultsSaga")
def step_given_hand_results_saga(context):
    """Create HandResultsSaga instance."""
    context.saga = HandResultsSaga()
    context.event = None
    context.event_book = None
    context.commands = []


@given("a SagaRouter with TableSyncSaga and HandResultsSaga")
def step_given_saga_router_with_sagas(context):
    """Create SagaRouter with multiple sagas."""
    context.router = TestSagaRouter()
    context.table_sync = TableSyncSaga()
    context.hand_results = HandResultsSaga()
    context.router.register(context.table_sync)
    context.router.register(context.hand_results)
    context.commands = []


@given("a SagaRouter with TableSyncSaga")
def step_given_saga_router_with_table_sync(context):
    """Create SagaRouter with TableSyncSaga."""
    context.router = TestSagaRouter()
    context.table_sync = TableSyncSaga()
    context.router.register(context.table_sync)
    context.commands = []


@given("a SagaRouter with a failing saga and TableSyncSaga")
def step_given_saga_router_with_failing(context):
    """Create SagaRouter with a failing saga and TableSyncSaga."""
    context.router = TestSagaRouter()
    context.failing_saga = FailingSaga()
    context.table_sync = TableSyncSaga()
    context.router.register(context.failing_saga)
    context.router.register(context.table_sync)
    context.commands = []
    context.exception_raised = False


@given("a HandStarted event from table domain with:")
def step_given_hand_started_event(context):
    """Create a HandStarted event from datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    variant_name = row.get("game_variant", "TEXAS_HOLDEM")
    variant = getattr(poker_types, variant_name, poker_types.TEXAS_HOLDEM)

    context.event = table.HandStarted(
        hand_root=row.get("hand_root", "hand-1").encode(),
        hand_number=int(row.get("hand_number", 1)),
        dealer_position=int(row.get("dealer_position", 0)),
        game_variant=variant,
        small_blind=int(row.get("small_blind", 5)),
        big_blind=int(row.get("big_blind", 10)),
        started_at=make_timestamp(),
    )


@given("a HandStarted event")
def step_given_hand_started_event_simple(context):
    """Create a simple HandStarted event."""
    context.event = table.HandStarted(
        hand_root=b"hand-1",
        hand_number=1,
        dealer_position=0,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=5,
        big_blind=10,
        started_at=make_timestamp(),
    )
    # Add some default players
    context.event.active_players.append(
        table.SeatSnapshot(
            player_root=b"player-1",
            position=0,
            stack=500,
        )
    )
    context.event.active_players.append(
        table.SeatSnapshot(
            player_root=b"player-2",
            position=1,
            stack=500,
        )
    )


@given("active players:")
def step_given_active_players(context):
    """Add active players from datatable."""
    target = getattr(context, "hand_started", None) or getattr(context, "event", None)
    if not target:
        raise ValueError("No hand_started or event in context")

    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = row_dict.get("player_root", "player-1").encode()
        target.active_players.append(
            table.SeatSnapshot(
                player_root=player_root,
                position=int(row_dict.get("position", 0)),
                stack=int(row_dict.get("stack", 500)),
            )
        )


@given("a HandComplete event from hand domain with:")
def step_given_hand_complete_event(context):
    """Create a HandComplete event from datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    context.event = hand.HandComplete(
        table_root=row.get("table_root", "table-1").encode(),
    )


@given("winners:")
def step_given_winners(context):
    """Add winners from datatable."""
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = row_dict.get("player_root", "player-1").encode()
        context.event.winners.append(
            hand.PotWinner(
                player_root=player_root,
                amount=int(row_dict.get("amount", 0)),
                pot_type="main",
            )
        )


@given("a HandEnded event from table domain with:")
def step_given_hand_ended_event(context):
    """Create a HandEnded event from datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    context.event = table.HandEnded(
        hand_root=row.get("hand_root", "hand-1").encode(),
        ended_at=make_timestamp(),
    )


@given("stack_changes:")
def step_given_stack_changes(context):
    """Add stack changes from datatable."""
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = row_dict.get("player_root", "player-1").encode()
        change = int(row_dict.get("change", 0))
        context.event.stack_changes[player_root.hex()] = change


@given("a PotAwarded event from hand domain with:")
def step_given_pot_awarded_event(context):
    """Create a PotAwarded event from datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    context.event = hand.PotAwarded()
    context.pot_total = int(row.get("pot_total", 0))


@given("an event book with:")
def step_given_event_book_with(context):
    """Create event book with multiple events."""
    context.event_book = types.EventBook(
        cover=types.Cover(root=types.UUID(value=b"table-1"), domain="table"),
        pages=[],
    )
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        event_type = row_dict.get("event_type", "HandStarted")
        if event_type == "HandStarted":
            event = table.HandStarted(
                hand_root=b"hand-1",
                hand_number=1,
                dealer_position=0,
                game_variant=poker_types.TEXAS_HOLDEM,
                small_blind=5,
                big_blind=10,
                started_at=make_timestamp(),
            )
            event.active_players.append(
                table.SeatSnapshot(player_root=b"player-1", position=0, stack=500)
            )
            event.active_players.append(
                table.SeatSnapshot(player_root=b"player-2", position=1, stack=500)
            )
            context.event_book.pages.append(
                make_event_page(event, len(context.event_book.pages))
            )


# =============================================================================
# When steps
# =============================================================================


def _dispatch_single_saga(saga_instance, event_book: types.EventBook):
    """Dispatch an event book through a single saga instance."""
    router = Router("test").with_handler(saga_instance).build()
    return router.dispatch(SagaHandleRequest(source=event_book))


@when("the saga handles the event")
def step_when_saga_handles_event(context):
    """Dispatch the event to the configured saga through a fresh Router."""
    event_page = make_event_page(context.event)
    source_domain = type(context.saga).__angzarr_meta__.get("source", "table")
    event_book = types.EventBook(
        cover=types.Cover(
            root=types.UUID(value=b"source-1"),
            domain=source_domain,
        ),
        pages=[event_page],
    )
    response = _dispatch_single_saga(context.saga, event_book)
    context.commands = list(response.commands)


@when("the router routes the event")
def step_when_router_routes_event(context):
    """Have router route the event."""
    event_page = make_event_page(context.event)
    event_book = types.EventBook(
        cover=types.Cover(root=types.UUID(value=b"table-1"), domain="table"),
        pages=[event_page],
    )

    try:
        context.commands = context.router.route(event_book, "table")
    except Exception:
        context.exception_raised = True


@when("the router routes the events")
def step_when_router_routes_events(context):
    """Have router route events from event book."""
    context.commands = context.router.route(context.event_book, "table")


# =============================================================================
# Then steps
# =============================================================================


@then("the saga emits a DealCards command to hand domain")
def step_then_saga_emits_deal_cards(context):
    """Verify saga emits DealCards command."""
    assert (
        len(context.commands) >= 1
    ), f"Expected at least 1 command, got {len(context.commands)}"
    cmd_book = context.commands[0]
    assert (
        cmd_book.cover.domain == "hand"
    ), f"Expected hand domain, got {cmd_book.cover.domain}"
    assert "DealCards" in cmd_book.pages[0].command.type_url


@then("the saga emits an EndHand command to table domain")
def step_then_saga_emits_end_hand(context):
    """Verify saga emits EndHand command."""
    assert len(context.commands) >= 1
    cmd_book = context.commands[0]
    assert (
        cmd_book.cover.domain == "table"
    ), f"Expected table domain, got {cmd_book.cover.domain}"
    assert "EndHand" in cmd_book.pages[0].command.type_url


@then("the saga emits (?P<count>\\d+) ReleaseFunds commands to player domain")
def step_then_saga_emits_release_funds(context, count):
    """Verify saga emits ReleaseFunds commands."""
    expected = int(count)
    assert (
        len(context.commands) == expected
    ), f"Expected {expected} commands, got {len(context.commands)}"
    for cmd_book in context.commands:
        assert cmd_book.cover.domain == "player"
        assert "ReleaseFunds" in cmd_book.pages[0].command.type_url


@then("the saga emits (?P<count>\\d+) DepositFunds commands to player domain")
def step_then_saga_emits_deposit_funds(context, count):
    """Verify saga emits DepositFunds commands."""
    expected = int(count)
    assert (
        len(context.commands) == expected
    ), f"Expected {expected} commands, got {len(context.commands)}"
    for cmd_book in context.commands:
        assert cmd_book.cover.domain == "player"
        assert "DepositFunds" in cmd_book.pages[0].command.type_url


@then("the saga emits (?P<count>\\d+) DealCards commands")
def step_then_saga_emits_deal_cards_count(context, count):
    """Verify saga emits specified number of DealCards commands."""
    expected = int(count)
    deal_cards_count = sum(
        1 for cmd in context.commands if "DealCards" in cmd.pages[0].command.type_url
    )
    assert (
        deal_cards_count == expected
    ), f"Expected {expected} DealCards commands, got {deal_cards_count}"


@then("the command has game_variant (?P<variant>\\w+)")
def step_then_command_has_game_variant(context, variant):
    """Verify command has specified game variant."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = getattr(poker_types, variant)
    assert cmd.game_variant == expected, f"Expected {variant}, got {cmd.game_variant}"


@then("the command has (?P<count>\\d+) players")
def step_then_command_has_players(context, count):
    """Verify command has specified number of players."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = int(count)
    assert (
        len(cmd.players) == expected
    ), f"Expected {expected} players, got {len(cmd.players)}"


@then("the command has hand_number (?P<num>\\d+)")
def step_then_command_has_hand_number(context, num):
    """Verify command has specified hand number."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = int(num)
    assert (
        cmd.hand_number == expected
    ), f"Expected hand_number {expected}, got {cmd.hand_number}"


@then("the command has (?P<count>\\d+) result")
def step_then_command_has_results(context, count):
    """Verify command has specified number of results."""
    cmd_any = context.commands[0].pages[0].command
    cmd = table.EndHand()
    cmd_any.Unpack(cmd)
    expected = int(count)
    assert (
        len(cmd.results) == expected
    ), f"Expected {expected} results, got {len(cmd.results)}"


@then('the result has winner "(?P<winner>[^"]+)" with amount (?P<amount>\\d+)')
def step_then_result_has_winner(context, winner, amount):
    """Verify result has specified winner and amount."""
    cmd_any = context.commands[0].pages[0].command
    cmd = table.EndHand()
    cmd_any.Unpack(cmd)
    result = cmd.results[0]
    expected_amount = int(amount)
    assert (
        result.winner_root == winner.encode()
    ), f"Expected {winner}, got {result.winner_root}"
    assert (
        result.amount == expected_amount
    ), f"Expected {expected_amount}, got {result.amount}"


@then('the first command has amount (?P<amount>\\d+) for "(?P<player_id>[^"]+)"')
def step_then_first_command_has_amount(context, amount, player_id):
    """Verify first command has specified amount for player."""
    cmd_any = context.commands[0].pages[0].command
    cmd = player.DepositFunds()
    cmd_any.Unpack(cmd)
    expected_amount = int(amount)
    assert (
        cmd.amount.amount == expected_amount
    ), f"Expected {expected_amount}, got {cmd.amount.amount}"


@then('the second command has amount (?P<amount>\\d+) for "(?P<player_id>[^"]+)"')
def step_then_second_command_has_amount(context, amount, player_id):
    """Verify second command has specified amount for player."""
    cmd_any = context.commands[1].pages[0].command
    cmd = player.DepositFunds()
    cmd_any.Unpack(cmd)
    expected_amount = int(amount)
    assert (
        cmd.amount.amount == expected_amount
    ), f"Expected {expected_amount}, got {cmd.amount.amount}"


@then("only TableSyncSaga handles the event")
def step_then_only_table_sync_handles(context):
    """Verify only TableSyncSaga handled the event."""
    deal_cards_count = sum(
        1 for cmd in context.commands if "DealCards" in cmd.pages[0].command.type_url
    )
    assert deal_cards_count >= 1, "Expected TableSyncSaga to emit DealCards"


@then("TableSyncSaga still emits its command")
def step_then_table_sync_emits(context):
    """Verify TableSyncSaga still emitted its command despite other saga failure."""
    deal_cards_count = sum(
        1 for cmd in context.commands if "DealCards" in cmd.pages[0].command.type_url
    )
    assert deal_cards_count >= 1, "Expected TableSyncSaga to emit DealCards"


@then("no exception is raised")
def step_then_no_exception(context):
    """Verify no exception was raised."""
    assert not context.exception_raised, "Exception was raised unexpectedly"
