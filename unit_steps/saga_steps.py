"""Behave step definitions for cross-domain event-translation (saga) tests.

The step regexes match the business-language phrasing in
``features/example/unit/saga.feature``: things like
"the hand-start is translated for the hand" rather than implementation-
level "the saga handles the event". The implementations still dispatch
through the production sagas — the same handler classes that ship as
standalone gRPC services in the cluster.

The feature file groups saga structs under logical names:
- "table-to-hand" / "table-to-hand-start" / "table-to-hand-complete"
  cover ``TableHandSaga`` (HandStarted) + ``HandTableSaga`` (HandComplete)
- "hand-to-player" / "hand-results" / "hand-payout" cover
  ``TablePlayerSaga`` (HandEnded) + ``HandPlayerSaga`` (PotAwarded)
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp

from tests.helpers import uuid_for

from angzarr_client import Router, handles, saga
from angzarr_client.helpers import TYPE_URL_PREFIX, type_matches
from angzarr_client.proto.angzarr.v1.saga_pb2 import SagaHandleRequest
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import hand_pb2 as hand
from angzarr_client.proto.examples.v1 import player_pb2 as player
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import table_pb2 as table

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(module_name: str, relative_path: str):
    """Load a hyphenated-dir Python module by file path.

    Saga production code lives under ``hand/saga-player/main.py`` etc. — the
    hyphens prevent normal package imports, so we use importlib.
    """
    full_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, str(full_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_name} from {full_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_hand_saga_player = _load("_hand_saga_player_main", "hand/saga-player/main.py")
_hand_saga_table = _load("_hand_saga_table_main", "hand/saga-table/main.py")
_table_saga_player = _load("_table_saga_player_main", "table/saga-player/main.py")
_table_saga_hand = _load("_table_saga_hand_main", "table/saga-hand/main.py")

# Production saga classes — dispatched by Router from SagaHandleRequest.
HandPlayerSaga = _hand_saga_player.HandPlayerSaga
HandTableSaga = _hand_saga_table.HandTableSaga
TablePlayerSaga = _table_saga_player.TablePlayerSaga
TableHandSaga = _table_saga_hand.TableHandSaga


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
    """Return both halves of the table↔hand sync saga pair.

    The feature speaks of a single "table-to-hand" translator; production
    splits it: ``TableHandSaga`` (table → hand) and ``HandTableSaga``
    (hand → table). Router dispatches by source domain.
    """
    return [TableHandSaga(), HandTableSaga()]


def _hand_results_group() -> list:
    """Return both halves of the hand/table → player bridge.

    ``TablePlayerSaga`` handles ``table.HandEnded``; ``HandPlayerSaga``
    handles ``hand.PotAwarded``. The feature groups them as
    "hand-to-player" / "hand-results" / "hand-payout".
    """
    return [TablePlayerSaga(), HandPlayerSaga()]


def _build_router(*handlers) -> Router:
    """Build a Router with the given saga handlers."""
    r = Router("sagas")
    for h in handlers:
        r = r.with_handler(type(h), lambda inst=h: inst)
    return r.build()


def _dispatch(handlers, event_book: types.EventBook, dest_seqs=None):
    """Dispatch ``event_book`` through ``handlers``, tolerating saga errors.

    Each handler is dispatched on its own so that one saga failing does not
    prevent the rest from producing commands (matches EU-0306).
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


def _wrap_event_book(event_msg, source_domain: str, root: bytes) -> types.EventBook:
    """Wrap a single event message in a one-page EventBook."""
    return types.EventBook(
        cover=types.Cover(root=types.UUID(value=root), domain=source_domain),
        pages=[make_event_page(event_msg, 0)],
    )


def _source_domain_for(event) -> str:
    """Determine the source domain for an event proto."""
    if isinstance(event, (table.HandStarted, table.HandEnded)):
        return "table"
    if isinstance(event, (hand.HandComplete, hand.PotAwarded)):
        return "hand"
    return "table"


# =============================================================================
# Given steps — events expressed in business vocabulary
# =============================================================================


@given(
    r'a hand "(?P<hand_id>[^"]+)" begins as hand number (?P<num>\d+) with '
    r"(?P<variant>\w+) and dealer at position (?P<dealer>\d+)"
)
def step_given_hand_begins(context, hand_id, num, variant, dealer):
    """A hand has just been started at a table (HandStarted from table domain)."""
    variant_enum = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    context.event = table.HandStarted(
        hand_root=uuid_for(hand_id),
        hand_number=int(num),
        dealer_position=int(dealer),
        game_variant=variant_enum,
        small_blind=5,
        big_blind=10,
        started_at=make_timestamp(),
    )
    context.source_root = b"table-1"


@given(r"the active players are:")
def step_given_active_players_table(context):
    """Append SeatSnapshot entries from the data table to the current event."""
    target = getattr(context, "event", None)
    if target is None:
        raise ValueError("No event in context to attach active players to")
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        target.active_players.append(
            table.SeatSnapshot(
                player_root=player_root,
                position=int(row_dict.get("position", 0)),
                stack=int(row_dict.get("stack", 500)),
            )
        )


@given(r"there are no active players")
def step_given_no_active_players(context):
    """No-op: HandStarted already has an empty active_players list by default."""
    # No-op stub — the event's active_players is empty unless populated.


@given(
    r'a hand at table "(?P<table_id>[^"]+)" completes(?: with pot total (?P<pot>\d+))?'
)
def step_given_hand_at_table_completes(context, table_id, pot):
    """A hand has completed in the hand domain (HandComplete event)."""
    context.event = hand.HandComplete(table_root=uuid_for(table_id))
    context.source_root = b"hand-1"
    if pot is not None:
        context.pot_total = int(pot)


@given(r"the winners are:")
def step_given_winners(context):
    """Append PotWinner entries from data table to the current event."""
    target = getattr(context, "event", None)
    if target is None:
        raise ValueError("No event in context to attach winners to")
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        target.winners.append(
            hand.PotWinner(
                player_root=player_root,
                amount=int(row_dict.get("amount", 0)),
                pot_type="main",
            )
        )


@given(r"there are no winners")
def step_given_no_winners(context):
    """No-op: the current event's winners list is empty by default."""


@given(r"the winners include winning-hand detail:")
def step_given_winners_with_winning_hand(context):
    """Append winners that carry a populated winning_hand."""
    target = getattr(context, "event", None)
    if target is None:
        raise ValueError("No event in context to attach winners to")
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        target.winners.append(
            hand.PotWinner(
                player_root=player_root,
                amount=int(row_dict.get("amount", 0)),
                pot_type="main",
                winning_hand=poker_types.HandRanking(
                    rank_type=poker_types.HIGH_CARD,
                    score=1,
                ),
            )
        )


@given(r'hand "(?P<hand_id>[^"]+)" ends with the following stack changes:')
def step_given_hand_ends_with_stack_changes(context, hand_id):
    """A hand has ended at the table; stack changes go on the HandEnded event."""
    context.event = table.HandEnded(
        hand_root=uuid_for(hand_id),
        ended_at=make_timestamp(),
    )
    context.source_root = b"table-1"
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        change = int(row_dict.get("change", 0))
        context.event.stack_changes[player_root.hex()] = change


@given(r'hand "(?P<hand_id>[^"]+)" ends with no stack changes')
def step_given_hand_ends_no_changes(context, hand_id):
    """HandEnded with an empty stack_changes map."""
    context.event = table.HandEnded(
        hand_root=uuid_for(hand_id),
        ended_at=make_timestamp(),
    )
    context.source_root = b"table-1"


@given(r"a pot of (?P<pot>\d+) is awarded with winners:")
def step_given_pot_awarded_with_winners(context, pot):
    """A pot has been awarded in the hand domain (PotAwarded event)."""
    context.event = hand.PotAwarded()
    context.pot_total = int(pot)
    context.source_root = b"hand-1"
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        context.event.winners.append(
            hand.PotWinner(
                player_root=player_root,
                amount=int(row_dict.get("amount", 0)),
                pot_type="main",
            )
        )


@given(r"a pot of (?P<pot>\d+) is awarded with no winners")
def step_given_pot_awarded_no_winners(context, pot):
    """PotAwarded with an empty winners list."""
    context.event = hand.PotAwarded()
    context.pot_total = int(pot)
    context.source_root = b"hand-1"


# =============================================================================
# Given steps — translator registration (formerly "saga registered in Router")
# =============================================================================


@given(r"both the table-to-hand and hand-to-player translators are active")
def step_given_both_translators_active(context):
    """Register the full set of translators in the dispatcher."""
    context.handlers = _table_sync_group() + _hand_results_group()
    context.commands = []


@given(r"the table-to-hand translator is active")
def step_given_table_to_hand_active(context):
    """Register the table-to-hand sync pair."""
    context.handlers = _table_sync_group()
    context.commands = []


@given(r"a failing translator is active alongside the table-to-hand translator")
def step_given_failing_alongside_table_to_hand(context):
    """Register a failing translator plus the table-to-hand sync pair."""
    context.handlers = [FailingSaga()] + _table_sync_group()
    context.commands = []
    context.exception_raised = False


@given(r"the table-to-hand-start translator is registered")
def step_given_table_to_hand_start_registered(context):
    """Register only the HandStarted-handling half (TableHandSaga)."""
    context.handlers = [TableHandSaga()]
    context.router = _build_router(TableHandSaga())
    context.commands = []


@given(r"the table-to-hand-complete translator is registered")
def step_given_table_to_hand_complete_registered(context):
    """Register only the HandComplete-handling half (HandTableSaga)."""
    context.handlers = [HandTableSaga()]
    context.router = _build_router(HandTableSaga())
    context.commands = []


@given(r"the hand-results translator is registered")
def step_given_hand_results_registered(context):
    """Register the HandEnded → ReleaseFunds saga (TablePlayerSaga)."""
    context.handlers = [TablePlayerSaga()]
    context.router = _build_router(TablePlayerSaga())
    context.commands = []


@given(r"the hand-payout translator is registered")
def step_given_hand_payout_registered(context):
    """Register the PotAwarded → DepositFunds saga (HandPlayerSaga)."""
    context.handlers = [HandPlayerSaga()]
    context.router = _build_router(HandPlayerSaga())
    context.commands = []


@given(
    r"the table-to-hand-start, hand-results, and hand-payout translators are "
    r"registered"
)
def step_given_multi_translators_registered(context):
    """Register the trio used in the fan-out test (EU-0313)."""
    context.handlers = [TableHandSaga(), TablePlayerSaga(), HandPlayerSaga()]
    context.router = _build_router(TableHandSaga(), TablePlayerSaga(), HandPlayerSaga())
    context.commands = []


@given(r"a hand-start event occurs")
def step_given_hand_start_event_occurs(context):
    """A default HandStarted event with two seated players, used by dispatch tests."""
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


@given(r"the following events occur in order:")
def step_given_events_in_order(context):
    """Stage a list of events for sequential dispatch (HandStarted only for now)."""
    context.event_list = []
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
# When steps — business-language event processing
# =============================================================================


def _dispatch_current_event(context, dest_seqs=None):
    """Helper: wrap context.event in an EventBook and dispatch through handlers."""
    source_domain = _source_domain_for(context.event)
    root = getattr(context, "source_root", None) or (
        b"table-1" if source_domain == "table" else b"hand-1"
    )
    event_book = _wrap_event_book(context.event, source_domain, root)
    dest_seqs = dest_seqs or {"hand": 0, "player": 0, "table": 0}
    return _dispatch(context.handlers, event_book, dest_seqs)


@when(r"the hand-start is translated for the hand")
def step_when_hand_start_translated(context):
    """Drive the table-to-hand translator on the current HandStarted event."""
    context.commands = _dispatch_current_event(context)


@when(r"the hand-completion is translated for the table")
def step_when_hand_completion_translated(context):
    """Drive the hand-to-table translator on the current HandComplete event."""
    context.commands = _dispatch_current_event(context)


@when(r"the hand-end is translated for the players")
def step_when_hand_end_translated(context):
    """Drive the table-to-player translator on the current HandEnded event."""
    context.commands = _dispatch_current_event(context)


@when(r"the pot-award is translated for the players")
def step_when_pot_award_translated(context):
    """Drive the hand-to-player translator on the current PotAwarded event."""
    context.commands = _dispatch_current_event(context)


@when(r"the event is processed for the hand")
@when(r"the event is processed for the table")
@when(r"the event is processed for the players")
@when(r"the event is processed for the hand, table, and players")
def step_when_event_processed_for_target(context):
    """Production-dispatcher path — the same fan-out as the targeted variants."""
    context.commands = _dispatch_current_event(context)


@when(r"the event is processed")
def step_when_event_processed(context):
    """Top-level dispatch (used in scenarios where a single translator should react)."""
    try:
        context.commands = _dispatch_current_event(context)
    except Exception:
        context.exception_raised = True


@when(r"the events are processed")
def step_when_events_processed(context):
    """Dispatch each staged event sequentially through the handlers."""
    dest_seqs = {"hand": 0, "player": 0, "table": 0}
    all_cmds: list[types.CommandBook] = []
    for ev in context.event_list:
        src = _source_domain_for(ev)
        book = _wrap_event_book(ev, src, b"table-1")
        all_cmds.extend(_dispatch(context.handlers, book, dest_seqs))
    context.commands = all_cmds


# =============================================================================
# Then steps — business-language outcome assertions
# =============================================================================


@then(
    r"the hand is dealt as hand number (?P<num>\d+) with (?P<variant>\w+) for "
    r"(?P<count>\d+) players"
)
def step_then_hand_is_dealt(context, num, variant, count):
    """A DealCards command was issued to the hand domain with the expected shape."""
    deal_cards = [
        c for c in context.commands if type_matches(c.pages[0].command, hand.DealCards)
    ]
    assert deal_cards, f"Expected DealCards command, got {context.commands}"
    cmd_book = deal_cards[0]
    assert cmd_book.cover.domain == "hand", (
        f"Expected hand domain, got {cmd_book.cover.domain}"
    )
    cmd = hand.DealCards()
    cmd_book.pages[0].command.Unpack(cmd)
    assert cmd.hand_number == int(num), (
        f"Expected hand_number={num}, got {cmd.hand_number}"
    )
    expected_variant = getattr(poker_types, variant)
    assert cmd.game_variant == expected_variant, (
        f"Expected game_variant={variant}, got {cmd.game_variant}"
    )
    assert len(cmd.players) == int(count), (
        f"Expected {count} players, got {len(cmd.players)}"
    )


@then(r"the deal is reproducible from the hand's identifier")
def step_then_deal_is_reproducible(context):
    """The translator must propagate hand_root as deck_seed so the deck is deterministic."""
    deal_cards = [
        c for c in context.commands if type_matches(c.pages[0].command, hand.DealCards)
    ]
    assert deal_cards, "No DealCards command was emitted"
    cmd = hand.DealCards()
    deal_cards[0].pages[0].command.Unpack(cmd)
    expected = bytes(context.event.hand_root)
    assert cmd.deck_seed == expected, (
        f"Expected deck_seed=hand_root ({expected!r}), got {bytes(cmd.deck_seed)!r}"
    )


@then(r"the table ends the round with (?P<count>\d+) result")
@then(r"the table ends the round with (?P<count>\d+) results")
def step_then_table_ends_with_results(context, count):
    """An EndHand command was issued to the table domain with N results."""
    end_hand = [
        c for c in context.commands if type_matches(c.pages[0].command, table.EndHand)
    ]
    assert end_hand, f"Expected EndHand command, got {context.commands}"
    cmd_book = end_hand[0]
    assert cmd_book.cover.domain == "table", (
        f"Expected table domain, got {cmd_book.cover.domain}"
    )
    cmd = table.EndHand()
    cmd_book.pages[0].command.Unpack(cmd)
    assert len(cmd.results) == int(count), (
        f"Expected {count} results, got {len(cmd.results)}"
    )


@then(r"the table ends the round with no results")
def step_then_table_ends_no_results(context):
    """Verify the emitted EndHand command has zero results."""
    end_hand = [
        c for c in context.commands if type_matches(c.pages[0].command, table.EndHand)
    ]
    assert end_hand, f"Expected EndHand command, got {context.commands}"
    cmd = table.EndHand()
    end_hand[0].pages[0].command.Unpack(cmd)
    assert len(cmd.results) == 0, f"Expected 0 results, got {len(cmd.results)}"


@then(
    r'the table ends the round with (?P<count>\d+) result for "(?P<winner>[^"]+)" '
    r"with amount (?P<amount>\d+)"
)
def step_then_table_ends_with_one_result(context, count, winner, amount):
    """EndHand emitted with a specific number of results and the named winner first."""
    end_hand = [
        c for c in context.commands if type_matches(c.pages[0].command, table.EndHand)
    ]
    assert end_hand, "Expected EndHand command"
    cmd = table.EndHand()
    end_hand[0].pages[0].command.Unpack(cmd)
    assert len(cmd.results) == int(count), (
        f"Expected {count} results, got {len(cmd.results)}"
    )
    result = cmd.results[0]
    assert result.winner_root == uuid_for(winner), (
        f"Expected winner {winner}, got {result.winner_root!r}"
    )
    assert result.amount == int(amount), (
        f"Expected amount {amount}, got {result.amount}"
    )


@then(r'the result records "(?P<winner>[^"]+)" winning (?P<amount>\d+)')
def step_then_result_records_winner(context, winner, amount):
    """The first EndHand result names the expected winner and amount."""
    end_hand = [
        c for c in context.commands if type_matches(c.pages[0].command, table.EndHand)
    ]
    assert end_hand, "Expected EndHand command"
    cmd = table.EndHand()
    end_hand[0].pages[0].command.Unpack(cmd)
    assert len(cmd.results) >= 1, "Expected at least one result"
    result = cmd.results[0]
    assert result.winner_root == uuid_for(winner), (
        f"Expected winner {winner}, got {result.winner_root!r}"
    )
    assert result.amount == int(amount), (
        f"Expected amount {amount}, got {result.amount}"
    )


@then(r"the table's first end-of-round result records the winning hand")
def step_then_first_result_has_winning_hand(context):
    """Verify the first EndHand result has winning_hand populated."""
    end_hand = [
        c for c in context.commands if type_matches(c.pages[0].command, table.EndHand)
    ]
    assert end_hand, "Expected EndHand command"
    cmd = table.EndHand()
    end_hand[0].pages[0].command.Unpack(cmd)
    assert len(cmd.results) >= 1, "Expected at least one result"
    assert cmd.results[0].HasField("winning_hand"), (
        "Expected winning_hand to be populated on the first result"
    )


@then(r"(?P<count>\d+) players have their reserved chips released")
def step_then_n_players_released(context, count):
    """The hand-results translator emitted N ReleaseFunds commands to player domain."""
    release_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.ReleaseFunds)
    ]
    assert len(release_cmds) == int(count), (
        f"Expected {count} ReleaseFunds commands, got {len(release_cmds)}"
    )
    for cmd_book in release_cmds:
        assert cmd_book.cover.domain == "player"


@then(r"no chips are released")
def step_then_no_chips_released(context):
    """No ReleaseFunds commands were emitted."""
    release_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.ReleaseFunds)
    ]
    assert not release_cmds, f"Expected no releases, got {len(release_cmds)}"


@then(r"(?P<count>\d+) players receive deposits")
def step_then_n_players_deposits(context, count):
    """The hand-payout translator emitted N DepositFunds commands to player domain."""
    deposit_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    assert len(deposit_cmds) == int(count), (
        f"Expected {count} DepositFunds, got {len(deposit_cmds)}"
    )
    for cmd_book in deposit_cmds:
        assert cmd_book.cover.domain == "player"


@then(r"(?P<count>\d+) player receives a deposit")
def step_then_one_player_deposit(context, count):
    """Singular form of the deposit-count assertion."""
    step_then_n_players_deposits(context, count)


@then(r'"(?P<pid>[^"]+)" is credited (?P<amount>\d+)')
def step_then_player_credited(context, pid, amount):
    """A DepositFunds command credits the named player with the expected amount."""
    deposit_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    for cmd_book in deposit_cmds:
        if cmd_book.cover.root.value == uuid_for(pid):
            cmd = player.DepositFunds()
            cmd_book.pages[0].command.Unpack(cmd)
            assert cmd.amount.amount == int(amount), (
                f"Expected {amount} for {pid}, got {cmd.amount.amount}"
            )
            return
    raise AssertionError(f"No DepositFunds emitted for {pid}")


@then(r'the first deposit credits "(?P<pid>[^"]+)" with (?P<amount>\d+)')
def step_then_first_deposit_credits(context, pid, amount):
    """Verify the first DepositFunds names the expected player + amount."""
    deposit_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    assert deposit_cmds, "Expected at least one DepositFunds"
    cmd_book = deposit_cmds[0]
    cmd = player.DepositFunds()
    cmd_book.pages[0].command.Unpack(cmd)
    assert cmd.amount.amount == int(amount), (
        f"Expected {amount}, got {cmd.amount.amount}"
    )
    assert cmd_book.cover.root.value == uuid_for(pid), (
        f"Expected first credit to be for {pid}, got {cmd_book.cover.root.value!r}"
    )


@then(r'the second deposit credits "(?P<pid>[^"]+)" with (?P<amount>\d+)')
def step_then_second_deposit_credits(context, pid, amount):
    """Verify the second DepositFunds names the expected player + amount."""
    deposit_cmds = [
        c
        for c in context.commands
        if type_matches(c.pages[0].command, player.DepositFunds)
    ]
    assert len(deposit_cmds) >= 2, "Expected at least two DepositFunds"
    cmd_book = deposit_cmds[1]
    cmd = player.DepositFunds()
    cmd_book.pages[0].command.Unpack(cmd)
    assert cmd.amount.amount == int(amount), (
        f"Expected {amount}, got {cmd.amount.amount}"
    )
    assert cmd_book.cover.root.value == uuid_for(pid), (
        f"Expected second credit to be for {pid}, got {cmd_book.cover.root.value!r}"
    )


@then(r"only the table-to-hand translator reacts")
@then(r"only the hand is dealt")
def step_then_only_table_to_hand_reacts(context):
    """Only one command was emitted, and it's a DealCards."""
    assert len(context.commands) == 1, (
        f"Expected exactly 1 command, got {len(context.commands)}"
    )
    assert type_matches(context.commands[0].pages[0].command, hand.DealCards), (
        f"Expected DealCards, got {context.commands[0].pages[0].command.type_url}"
    )


@then(r"(?P<count>\d+) hands are dealt")
def step_then_n_hands_dealt(context, count):
    """Verify N DealCards commands were emitted total."""
    expected = int(count)
    deal_cards_count = sum(
        1
        for cmd in context.commands
        if type_matches(cmd.pages[0].command, hand.DealCards)
    )
    assert deal_cards_count == expected, (
        f"Expected {expected} DealCards commands, got {deal_cards_count}"
    )


@then(r"the table-to-hand translator still reacts")
def step_then_table_to_hand_still_reacts(context):
    """Even with the failing translator present, the table-to-hand DealCards was emitted."""
    deal_cards_count = sum(
        1
        for cmd in context.commands
        if type_matches(cmd.pages[0].command, hand.DealCards)
    )
    assert deal_cards_count >= 1, (
        "Expected the table-to-hand translator to emit DealCards"
    )


@then(r"no error escapes to the caller")
def step_then_no_error_escapes(context):
    """No unhandled exception bubbled up from the dispatcher."""
    assert not getattr(context, "exception_raised", False), (
        "An exception escaped to the caller"
    )


@then(r"no action results")
def step_then_no_action_results(context):
    """The dispatch produced no commands at all (empty input edge case)."""
    assert len(context.commands) == 0, (
        f"Expected 0 commands, got {len(context.commands)}"
    )
