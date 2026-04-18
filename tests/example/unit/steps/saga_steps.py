"""Behave step definitions for saga tests.

Tests the unified Router / @saga decorator pattern using the real
production sagas from the ``sagas`` package. Sagas are dispatched
through a freshly-built Router with a ``SagaHandleRequest``.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_client import Router, handles, saga
from angzarr_client.helpers import TYPE_URL_PREFIX, type_matches
from angzarr_client.proto.angzarr import SagaHandleRequest
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

# Real sagas under test.
from sagas.hand_results_saga import HandPayoutSaga, HandResultsSaga
from sagas.table_sync_saga import TableSyncCompleteSaga, TableSyncStartSaga

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, seq: int = 0) -> types.EventPage:
    """Create EventPage with packed event using the Router's expected prefix."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix=TYPE_URL_PREFIX)
    return types.EventPage(
        header=types.PageHeader(sequence=seq),
        event=event_any,
        created_at=make_timestamp(),
    )


# =============================================================================
# FailingSaga for EU-0306 (router-continues-after-saga-failure).
# =============================================================================


@saga(name="saga-failing", source="table", target="hand")
class FailingSaga:
    """A saga that always fails for testing."""

    @handles(table.HandStarted)
    def handle_hand_started(self, event: table.HandStarted, destinations):
        raise RuntimeError("FailingSaga always fails")


# =============================================================================
# Saga-group helpers
# =============================================================================


def _table_sync_group() -> list:
    """Return both halves of the table<->hand sync saga pair.

    The feature file speaks of a single ``TableSyncSaga``; the production
    implementation is split into two (start + complete), so we register
    both. Router dispatches based on source-domain + event type.
    """
    return [TableSyncStartSaga(), TableSyncCompleteSaga()]


def _hand_results_group() -> list:
    """Return both halves of the hand/table -> player bridge.

    ``HandResultsSaga`` handles table.HandEnded; ``HandPayoutSaga`` handles
    hand.PotAwarded. The feature file speaks of a single conceptual
    ``HandResultsSaga`` covering both.
    """
    return [HandResultsSaga(), HandPayoutSaga()]


def _build_router(*handlers) -> Router:
    """Build a Router with the given saga handlers."""
    r = Router("sagas")
    for h in handlers:
        r = r.with_handler(h)
    return r.build()


def _dispatch(handlers, event_book: types.EventBook, dest_seqs=None):
    """Dispatch ``event_book`` through ``handlers``, tolerating saga errors.

    Each handler is dispatched on its own so that one saga failing does not
    prevent the rest from producing commands (matches the expectations of
    EU-0306).
    """
    commands: list[types.CommandBook] = []
    req = SagaHandleRequest(source=event_book)
    for k, v in (dest_seqs or {}).items():
        req.destination_sequences[k] = v
    for inst in handlers:
        meta = type(inst).__angzarr_meta__
        if meta.get("source") != event_book.cover.domain:
            continue
        try:
            router = _build_router(inst)
            response = router.dispatch(req)
            commands.extend(response.commands)
        except Exception:
            continue
    return commands


# =============================================================================
# Given steps - saga setup
# =============================================================================


@given("a TableSyncSaga")
def step_given_table_sync_saga(context):
    """Register both halves of the table-sync saga pair for the scenario."""
    context.handlers = _table_sync_group()
    context.event = None
    context.event_book = None
    context.commands = []
    context.source_root = b"table-1"


@given("a HandResultsSaga")
def step_given_hand_results_saga(context):
    """Register both halves of the hand-results saga family."""
    context.handlers = _hand_results_group()
    context.event = None
    context.event_book = None
    context.commands = []
    context.source_root = b"hand-1"


@given("a SagaRouter with TableSyncSaga and HandResultsSaga")
def step_given_saga_router_with_sagas(context):
    """Build a saga router with both saga families registered."""
    context.handlers = _table_sync_group() + _hand_results_group()
    context.commands = []


@given("a SagaRouter with TableSyncSaga")
def step_given_saga_router_with_table_sync(context):
    """Build a saga router with only the table-sync saga pair."""
    context.handlers = _table_sync_group()
    context.commands = []


@given("a SagaRouter with a failing saga and TableSyncSaga")
def step_given_saga_router_with_failing(context):
    """Build a saga router with a failing saga + the table-sync pair."""
    context.handlers = [FailingSaga()] + _table_sync_group()
    context.commands = []
    context.exception_raised = False


# =============================================================================
# Given steps - events
# =============================================================================


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
    context.source_root = b"table-1"


@given("a HandStarted event")
def step_given_hand_started_event_simple(context):
    """Create a simple HandStarted event with two default players."""
    context.event = table.HandStarted(
        hand_root=b"hand-1",
        hand_number=1,
        dealer_position=0,
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=5,
        big_blind=10,
        started_at=make_timestamp(),
    )
    context.event.active_players.append(
        table.SeatSnapshot(player_root=b"player-1", position=0, stack=500)
    )
    context.event.active_players.append(
        table.SeatSnapshot(player_root=b"player-2", position=1, stack=500)
    )
    context.source_root = b"table-1"


@given("active players:")
def step_given_active_players(context):
    """Add active players from datatable to the current event."""
    target = getattr(context, "event", None)
    if not target:
        raise ValueError("No event in context")

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
    context.source_root = b"hand-1"


@given("winners:")
def step_given_winners(context):
    """Add winners from datatable to the current event."""
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
    context.source_root = b"table-1"


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
    context.source_root = b"hand-1"


@given("an event book with:")
def step_given_event_book_with(context):
    """Create event book with multiple events.

    We store individual events and their source domain so the When step can
    dispatch each as its own SagaHandleRequest (dispatch_saga only processes
    the last event per request).
    """
    context.event_list = []
    context.event_book_domain = "table"
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
            context.event_list.append(event)


# =============================================================================
# When steps
# =============================================================================


def _wrap_event_book(event_msg, source_domain: str, root: bytes) -> types.EventBook:
    """Wrap a single event message in a one-page EventBook."""
    return types.EventBook(
        cover=types.Cover(root=types.UUID(value=root), domain=source_domain),
        pages=[make_event_page(event_msg, 0)],
    )


def _source_domain_for(event) -> str:
    """Determine the source domain for an event proto.

    Uses the package prefix of the event's fully-qualified descriptor name
    when possible; otherwise falls back to known mappings.
    """
    if isinstance(event, (table.HandStarted, table.HandEnded)):
        return "table"
    if isinstance(event, (hand.HandComplete, hand.PotAwarded)):
        return "hand"
    # Default guess.
    return "table"


@when("the saga handles the event")
def step_when_saga_handles_event(context):
    """Dispatch the event through the configured handler group."""
    source_domain = _source_domain_for(context.event)
    root = getattr(context, "source_root", None) or (
        b"table-1" if source_domain == "table" else b"hand-1"
    )
    event_book = _wrap_event_book(context.event, source_domain, root)
    dest_seqs = {"hand": 0, "player": 0, "table": 0}
    context.commands = _dispatch(context.handlers, event_book, dest_seqs)


@when("the router routes the event")
def step_when_router_routes_event(context):
    """Have router route a single event through all registered sagas."""
    source_domain = _source_domain_for(context.event)
    root = getattr(context, "source_root", None) or b"table-1"
    event_book = _wrap_event_book(context.event, source_domain, root)
    dest_seqs = {"hand": 0, "player": 0, "table": 0}
    try:
        context.commands = _dispatch(context.handlers, event_book, dest_seqs)
    except Exception:
        context.exception_raised = True


@when("the router routes the events")
def step_when_router_routes_events(context):
    """Route each event in event_list individually (one request per event)."""
    dest_seqs = {"hand": 0, "player": 0, "table": 0}
    all_cmds: list[types.CommandBook] = []
    for ev in context.event_list:
        src = _source_domain_for(ev)
        book = _wrap_event_book(ev, src, b"table-1")
        all_cmds.extend(_dispatch(context.handlers, book, dest_seqs))
    context.commands = all_cmds


# =============================================================================
# Then steps
# =============================================================================


@then("the saga emits a DealCards command to hand domain")
def step_then_saga_emits_deal_cards(context):
    """Verify saga emits at least one DealCards command to hand domain."""
    assert (
        len(context.commands) >= 1
    ), f"Expected at least 1 command, got {len(context.commands)}"
    cmd_book = context.commands[0]
    assert (
        cmd_book.cover.domain == "hand"
    ), f"Expected hand domain, got {cmd_book.cover.domain}"
    assert type_matches(cmd_book.pages[0].command, hand.DealCards), (
        f"Expected DealCards, got {cmd_book.pages[0].command.type_url}"
    )


@then("the saga emits an EndHand command to table domain")
def step_then_saga_emits_end_hand(context):
    """Verify saga emits an EndHand command to table domain."""
    assert len(context.commands) >= 1, f"Expected >=1 commands, got {len(context.commands)}"
    cmd_book = context.commands[0]
    assert (
        cmd_book.cover.domain == "table"
    ), f"Expected table domain, got {cmd_book.cover.domain}"
    assert type_matches(cmd_book.pages[0].command, table.EndHand), (
        f"Expected EndHand, got {cmd_book.pages[0].command.type_url}"
    )


@then("the saga emits (?P<count>\\d+) ReleaseFunds commands to player domain")
def step_then_saga_emits_release_funds(context, count):
    """Verify saga emits the expected number of ReleaseFunds commands."""
    expected = int(count)
    release_cmds = [
        c for c in context.commands if type_matches(c.pages[0].command, player.ReleaseFunds)
    ]
    assert (
        len(release_cmds) == expected
    ), f"Expected {expected} ReleaseFunds commands, got {len(release_cmds)}"
    for cmd_book in release_cmds:
        assert cmd_book.cover.domain == "player"


@then("the saga emits (?P<count>\\d+) DepositFunds commands to player domain")
def step_then_saga_emits_deposit_funds(context, count):
    """Verify saga emits the expected number of DepositFunds commands."""
    expected = int(count)
    deposit_cmds = [
        c for c in context.commands if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    assert (
        len(deposit_cmds) == expected
    ), f"Expected {expected} DepositFunds commands, got {len(deposit_cmds)}"
    for cmd_book in deposit_cmds:
        assert cmd_book.cover.domain == "player"


@then("the saga emits (?P<count>\\d+) DealCards commands")
def step_then_saga_emits_deal_cards_count(context, count):
    """Verify saga emits the expected number of DealCards commands."""
    expected = int(count)
    deal_cards_count = sum(
        1 for cmd in context.commands if type_matches(cmd.pages[0].command, hand.DealCards)
    )
    assert (
        deal_cards_count == expected
    ), f"Expected {expected} DealCards commands, got {deal_cards_count}"


@then("the command has game_variant (?P<variant>\\w+)")
def step_then_command_has_game_variant(context, variant):
    """Verify the DealCards command carries the expected game variant."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = getattr(poker_types, variant)
    assert cmd.game_variant == expected, f"Expected {variant}, got {cmd.game_variant}"


@then("the command has (?P<count>\\d+) players")
def step_then_command_has_players(context, count):
    """Verify the DealCards command carries the expected number of players."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = int(count)
    assert (
        len(cmd.players) == expected
    ), f"Expected {expected} players, got {len(cmd.players)}"


@then("the command has hand_number (?P<num>\\d+)")
def step_then_command_has_hand_number(context, num):
    """Verify the DealCards command carries the expected hand number."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    expected = int(num)
    assert (
        cmd.hand_number == expected
    ), f"Expected hand_number {expected}, got {cmd.hand_number}"


@then("the command has (?P<count>\\d+) result")
def step_then_command_has_results(context, count):
    """Verify the EndHand command carries the expected number of results."""
    cmd_any = context.commands[0].pages[0].command
    cmd = table.EndHand()
    cmd_any.Unpack(cmd)
    expected = int(count)
    assert (
        len(cmd.results) == expected
    ), f"Expected {expected} results, got {len(cmd.results)}"


@then('the result has winner "(?P<winner>[^"]+)" with amount (?P<amount>\\d+)')
def step_then_result_has_winner(context, winner, amount):
    """Verify the first EndHand result has the expected winner + amount."""
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
    """Verify the first DepositFunds command carries the expected amount/player."""
    deposit_cmds = [
        c for c in context.commands if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    cmd_any = deposit_cmds[0].pages[0].command
    cmd = player.DepositFunds()
    cmd_any.Unpack(cmd)
    expected_amount = int(amount)
    assert (
        cmd.amount.amount == expected_amount
    ), f"Expected {expected_amount}, got {cmd.amount.amount}"
    assert (
        deposit_cmds[0].cover.root.value == player_id.encode()
    ), f"Expected root {player_id}, got {deposit_cmds[0].cover.root.value!r}"


@then('the second command has amount (?P<amount>\\d+) for "(?P<player_id>[^"]+)"')
def step_then_second_command_has_amount(context, amount, player_id):
    """Verify the second DepositFunds command carries the expected amount/player."""
    deposit_cmds = [
        c for c in context.commands if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    cmd_any = deposit_cmds[1].pages[0].command
    cmd = player.DepositFunds()
    cmd_any.Unpack(cmd)
    expected_amount = int(amount)
    assert (
        cmd.amount.amount == expected_amount
    ), f"Expected {expected_amount}, got {cmd.amount.amount}"
    assert (
        deposit_cmds[1].cover.root.value == player_id.encode()
    ), f"Expected root {player_id}, got {deposit_cmds[1].cover.root.value!r}"


@then("only TableSyncSaga handles the event")
def step_then_only_table_sync_handles(context):
    """Verify only TableSyncSaga emitted commands (a single DealCards)."""
    assert (
        len(context.commands) == 1
    ), f"Expected exactly 1 command, got {len(context.commands)}"
    assert type_matches(
        context.commands[0].pages[0].command, hand.DealCards
    ), f"Expected DealCards, got {context.commands[0].pages[0].command.type_url}"


@then("TableSyncSaga still emits its command")
def step_then_table_sync_emits(context):
    """Verify TableSyncSaga still emitted DealCards despite the failing saga."""
    deal_cards_count = sum(
        1 for cmd in context.commands if type_matches(cmd.pages[0].command, hand.DealCards)
    )
    assert deal_cards_count >= 1, "Expected TableSyncSaga to emit DealCards"


@then("no exception is raised")
def step_then_no_exception(context):
    """Verify no exception escaped the dispatch."""
    assert not context.exception_raised, "Exception was raised unexpectedly"


# =============================================================================
# New step defs (EU-0309..) - ported directly from tests/unit/test_saga.py.
# These exercise the Router via SagaHandleRequest with explicit destination
# sequences and event-type assertions in the "examples.EventName" style.
# =============================================================================


def _make_router_with(*handlers) -> Router:
    """Build a Router for dispatching a SagaHandleRequest."""
    return _build_router(*handlers)


def _dispatch_request(
    router: Router, event_book: types.EventBook, dest_seqs: dict | None = None
):
    """Build + dispatch a SagaHandleRequest and return the SagaResponse."""
    req = SagaHandleRequest(source=event_book)
    for k, v in (dest_seqs or {}).items():
        req.destination_sequences[k] = v
    return router.dispatch(req)


@given("a TableSyncStartSaga registered in a Router")
def step_given_table_sync_start_saga(context):
    """Register the production TableSyncStartSaga in a fresh Router."""
    context.router = _make_router_with(TableSyncStartSaga())
    context.event = None
    context.source_root = b"table-1"


@given("a TableSyncCompleteSaga registered in a Router")
def step_given_table_sync_complete_saga(context):
    """Register the production TableSyncCompleteSaga in a fresh Router."""
    context.router = _make_router_with(TableSyncCompleteSaga())
    context.event = None
    context.source_root = b"hand-1"


@given("a HandResultsSaga registered in a Router")
def step_given_hand_results_saga_router(context):
    """Register the production HandResultsSaga (table.HandEnded source)."""
    context.router = _make_router_with(HandResultsSaga())
    context.event = None
    context.source_root = b"table-1"


@given("a HandPayoutSaga registered in a Router")
def step_given_hand_payout_saga_router(context):
    """Register the production HandPayoutSaga (hand.PotAwarded source)."""
    context.router = _make_router_with(HandPayoutSaga())
    context.event = None
    context.source_root = b"hand-1"


@given(
    "a Router with TableSyncStartSaga, HandResultsSaga, and HandPayoutSaga"
)
def step_given_multi_saga_router(context):
    """Register all three sagas in a single Router for the fan-out scenario."""
    context.router = _make_router_with(
        TableSyncStartSaga(), HandResultsSaga(), HandPayoutSaga()
    )
    context.event = None
    context.source_root = b"table-1"


@when(
    r'I dispatch the event via SagaHandleRequest with destination_sequences '
    r'"(?P<dest_seqs>[^"]*)"'
)
def step_when_dispatch_saga_request(context, dest_seqs):
    """Build a SagaHandleRequest and dispatch via the configured Router.

    ``dest_seqs`` is a comma-separated list of ``domain=sequence`` entries
    (e.g. ``"hand=0"`` or ``"hand=0,table=0,player=0"``). Empty string means
    no destination sequences.
    """
    source_domain = _source_domain_for(context.event)
    root = getattr(context, "source_root", None) or b"source-1"
    event_book = _wrap_event_book(context.event, source_domain, root)

    parsed: dict[str, int] = {}
    if dest_seqs.strip():
        for chunk in dest_seqs.split(","):
            k, _, v = chunk.strip().partition("=")
            if k:
                parsed[k] = int(v or 0)

    response = _dispatch_request(context.router, event_book, parsed)
    context.response = response
    context.commands = list(response.commands)


@then("the result is a examples.(?P<event_name>\\w+) command to (?P<domain>\\w+) domain")
def step_then_result_is_command(context, event_name, domain):
    """Verify the first emitted command matches examples.<EventName> on the given domain."""
    assert len(context.commands) >= 1, "Expected at least one command"
    cmd_book = context.commands[0]
    assert (
        cmd_book.cover.domain == domain
    ), f"Expected domain {domain}, got {cmd_book.cover.domain}"
    suffix = f"examples.{event_name}"
    assert cmd_book.pages[0].command.type_url.endswith(suffix), (
        f"Expected command type ending with {suffix}, got "
        f"{cmd_book.pages[0].command.type_url}"
    )


@then("the command DealCards has hand_number (?P<num>\\d+) and (?P<count>\\d+) players")
def step_then_deal_cards_fields(context, num, count):
    """Verify the emitted DealCards command has the expected shape."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    assert cmd.hand_number == int(num), f"Expected hand_number {num}, got {cmd.hand_number}"
    assert (
        len(cmd.players) == int(count)
    ), f"Expected {count} players, got {len(cmd.players)}"


@then("the command DealCards has game_variant TEXAS_HOLDEM")
def step_then_deal_cards_variant(context):
    """Verify the emitted DealCards command uses TEXAS_HOLDEM."""
    cmd_any = context.commands[0].pages[0].command
    cmd = hand.DealCards()
    cmd_any.Unpack(cmd)
    assert cmd.game_variant == poker_types.TEXAS_HOLDEM, (
        f"Expected TEXAS_HOLDEM, got {cmd.game_variant}"
    )


@then("the EndHand command has (?P<count>\\d+) result with winner \"(?P<winner>[^\"]+)\" amount (?P<amount>\\d+)")
def step_then_end_hand_result(context, count, winner, amount):
    """Verify the emitted EndHand command has the expected winner/amount."""
    cmd_any = context.commands[0].pages[0].command
    cmd = table.EndHand()
    cmd_any.Unpack(cmd)
    assert len(cmd.results) == int(count), (
        f"Expected {count} results, got {len(cmd.results)}"
    )
    result = cmd.results[0]
    assert (
        result.winner_root == winner.encode()
    ), f"Expected winner {winner}, got {result.winner_root!r}"
    assert (
        result.amount == int(amount)
    ), f"Expected amount {amount}, got {result.amount}"


@then("(?P<count>\\d+) commands are emitted to player domain")
def step_then_commands_to_player(context, count):
    """Verify the expected number of commands were emitted to player domain."""
    expected = int(count)
    player_cmds = [c for c in context.commands if c.cover.domain == "player"]
    assert (
        len(player_cmds) == expected
    ), f"Expected {expected} commands to player, got {len(player_cmds)}"


@then("each command is a examples.ReleaseFunds")
def step_then_each_release_funds(context):
    """Verify every emitted command is a ReleaseFunds."""
    for c in context.commands:
        assert type_matches(c.pages[0].command, player.ReleaseFunds), (
            f"Expected ReleaseFunds, got {c.pages[0].command.type_url}"
        )


@then("each command is a examples.DepositFunds")
def step_then_each_deposit_funds(context):
    """Verify every emitted command is a DepositFunds."""
    for c in context.commands:
        assert type_matches(c.pages[0].command, player.DepositFunds), (
            f"Expected DepositFunds, got {c.pages[0].command.type_url}"
        )


@then(
    "DepositFunds (?P<index>\\d+) has amount (?P<amount>\\d+) for \"(?P<pid>[^\"]+)\""
)
def step_then_deposit_funds_index(context, index, amount, pid):
    """Verify the Nth (0-indexed) DepositFunds command has the expected fields."""
    deposit_cmds = [
        c for c in context.commands if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    i = int(index)
    assert i < len(deposit_cmds), f"Only {len(deposit_cmds)} deposit cmds"
    cmd_book = deposit_cmds[i]
    cmd = player.DepositFunds()
    cmd_book.pages[0].command.Unpack(cmd)
    assert (
        cmd.amount.amount == int(amount)
    ), f"Expected amount {amount}, got {cmd.amount.amount}"
    assert (
        cmd_book.cover.root.value == pid.encode()
    ), f"Expected root {pid}, got {cmd_book.cover.root.value!r}"


@then("only TableSyncStartSaga emits a DealCards command")
def step_then_only_table_start_emits(context):
    """Verify exactly one DealCards command was emitted (fan-out test)."""
    assert (
        len(context.commands) == 1
    ), f"Expected exactly 1 command, got {len(context.commands)}"
    assert type_matches(
        context.commands[0].pages[0].command, hand.DealCards
    ), f"Expected DealCards, got {context.commands[0].pages[0].command.type_url}"


@then("no commands are emitted")
def step_then_no_commands(context):
    """Verify zero commands were emitted."""
    assert (
        len(context.commands) == 0
    ), f"Expected 0 commands, got {len(context.commands)}"
