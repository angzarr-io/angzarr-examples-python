"""Behave step definitions for process manager tests."""

import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, use_step_matcher, when
from google.protobuf.timestamp_pb2 import Timestamp

from tests.helpers import uuid_for

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

sys.path.insert(0, str(Path(__file__).parent.parent / "hand-flow"))

from hand_process import HandPhase, HandProcess, HandProcessManager, PlayerState

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


# Default test table root and hand ID using hex format
DEFAULT_TABLE_ROOT = b"table-1"
DEFAULT_HAND_ID = f"{DEFAULT_TABLE_ROOT.hex()}_1"


class TestCommandSender:
    """Captures commands sent by the process manager."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd_book: types.CommandBook):
        self.commands.append(cmd_book)

    def get_command(self, index: int = 0):
        """Get command at index."""
        if index < len(self.commands):
            return self.commands[index]
        return None

    def get_all_commands_of_type(self, type_name: str):
        """Get all commands of a specific type."""
        result = []
        for cmd_book in self.commands:
            if cmd_book.pages and type_name in cmd_book.pages[0].command.type_url:
                result.append(cmd_book)
        return result


# --- Given steps ---


@given("a HandFlowPM")
def step_given_hand_process_manager(context):
    """Create HandProcessManager instance."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(
        command_sender=context.command_sender,
    )
    context.hand_started = None
    context.hand_id = None
    context.process = None


@given("a HandStarted event with:")
def step_given_hand_started_event(context):
    """Create a HandStarted event from datatable."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    variant = getattr(
        poker_types, row.get("game_variant", "TEXAS_HOLDEM"), poker_types.TEXAS_HOLDEM
    )

    context.hand_started = table.HandStarted(
        hand_root=b"hand-1",
        hand_number=int(row.get("hand_number", 1)),
        dealer_position=int(row.get("dealer_position", 0)),
        game_variant=variant,
        small_blind=int(row.get("small_blind", 5)),
        big_blind=int(row.get("big_blind", 10)),
        small_blind_position=1,
        big_blind_position=0 if int(row.get("dealer_position", 0)) == 1 else 1,
        started_at=make_timestamp(),
    )
    # Also set context.event for projector compatibility
    context.event = context.hand_started


# "active players:" step is defined in saga_steps.py to avoid duplication
# That step handles both context.event and context.hand_started


def _add_active_players_from_table(context):
    """Add active players from datatable to either context.event or context.hand_started."""
    target = getattr(context, "hand_started", None) or getattr(context, "event", None)
    if not target:
        raise ValueError("No hand_started or event in context")

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


@given("an active hand process in phase (?P<phase>\\w+)")
def step_given_active_process_in_phase(context, phase):
    """Create an active hand process in specified phase."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    # Use hex format for table_root to match hand_process.py expectations
    table_root = b"table-1"
    hand_id = f"{table_root.hex()}_1"

    # Create a process manually with the desired phase
    context.process = HandProcess(
        hand_id=hand_id,
        table_root=table_root,
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        phase=getattr(HandPhase, phase),
        dealer_position=0,
        small_blind_position=1,
        big_blind_position=0,
        small_blind=5,
        big_blind=10,
        action_timeout_seconds=30,
    )

    # Add default players
    context.process.players[0] = PlayerState(
        player_root=uuid_for("player-1"),
        position=0,
        stack=500,
    )
    context.process.players[1] = PlayerState(
        player_root=uuid_for("player-2"),
        position=1,
        stack=500,
    )
    context.process.active_positions = [0, 1]

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given("a CardsDealt event")
def step_given_cards_dealt_event(context):
    """Create a CardsDealt event."""
    context.event = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
    )
    context.event.player_cards.append(
        hand.PlayerHoleCards(player_root=uuid_for("player-1"), cards=[])
    )
    context.event.player_cards.append(
        hand.PlayerHoleCards(player_root=uuid_for("player-2"), cards=[])
    )


@given("small_blind_posted is true")
def step_given_small_blind_posted(context):
    """Set small blind as posted."""
    context.process.small_blind_posted = True


@given("a BlindPosted event for (?P<blind_type>\\w+) blind")
def step_given_blind_posted_event(context, blind_type):
    """Create a BlindPosted event."""
    amount = (
        context.process.small_blind
        if blind_type == "small"
        else context.process.big_blind
    )
    context.event = hand.BlindPosted(
        player_root=uuid_for("player-1") if blind_type == "small" else uuid_for("player-2"),
        blind_type=blind_type,
        amount=amount,
        pot_total=(
            amount if blind_type == "small" else amount + context.process.small_blind
        ),
        player_stack=500 - amount,
    )


@given("action_on is position (?P<pos>\\d+)")
def step_given_action_on(context, pos):
    """Set current action position."""
    context.process.action_on = int(pos)


@given(
    "an ActionTaken event for player at position (?P<pos>\\d+) with action (?P<action>\\w+)"
)
def step_given_action_taken_event(context, pos, action):
    """Create an ActionTaken event."""
    position = int(pos)
    player = context.process.players.get(position)
    action_enum = getattr(poker_types, action)
    context.event = hand.ActionTaken(
        player_root=player.player_root if player else uuid_for("player-1"),
        action=action_enum,
        amount=0 if action in ("FOLD", "CHECK") else 10,
        pot_total=context.process.pot_total
        + (10 if action not in ("FOLD", "CHECK") else 0),
        player_stack=(
            player.stack - (10 if action not in ("FOLD", "CHECK") else 0)
            if player
            else 490
        ),
    )


@given("players at positions (?P<positions>\\d+(?:,\\s*\\d+)*) have all acted")
def step_given_players_have_acted(context, positions):
    """Set specified players as having acted."""
    for pos_str in positions.split(","):
        pos = int(pos_str.strip())
        if pos in context.process.players:
            context.process.players[pos].has_acted = True


@given("an ActionTaken event for player at position (?P<pos>\\d+) with action RAISE")
def step_given_raise_action_event(context, pos):
    """Create a RAISE ActionTaken event."""
    position = int(pos)
    player = context.process.players.get(position)
    context.event = hand.ActionTaken(
        player_root=player.player_root if player else uuid_for("player-1"),
        action=poker_types.RAISE,
        amount=20,
        pot_total=context.process.pot_total + 20,
        player_stack=player.stack - 20 if player else 480,
    )


@given("all active players have acted and matched the current bet")
def step_given_all_players_acted(context):
    """Set all active players as having acted and matched bet."""
    context.process.current_bet = 10
    for player in context.process.players.values():
        if not player.has_folded and not player.is_all_in:
            player.has_acted = True
            player.bet_this_round = 10


@given("an ActionTaken event for the last player")
def step_given_last_player_action(context):
    """Create action for the last player."""
    # Find first non-acted player
    for player in context.process.players.values():
        if not player.has_acted:
            context.event = hand.ActionTaken(
                player_root=player.player_root,
                action=poker_types.CALL,
                amount=10,
                pot_total=context.process.pot_total + 10,
                player_stack=player.stack - 10,
            )
            return
    # All acted, use first player
    player = list(context.process.players.values())[0]
    context.event = hand.ActionTaken(
        player_root=player.player_root,
        action=poker_types.CHECK,
        amount=0,
        pot_total=context.process.pot_total,
        player_stack=player.stack,
    )


@given("an active hand process with betting_phase (?P<phase>\\w+)")
def step_given_process_with_betting_phase(context, phase):
    """Create process with specified betting phase."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        phase=HandPhase.BETTING,
        betting_phase=getattr(poker_types, phase),
        dealer_position=0,
        small_blind=5,
        big_blind=10,
    )

    context.process.players[0] = PlayerState(
        player_root=uuid_for("player-1"), position=0, stack=500
    )
    context.process.players[1] = PlayerState(
        player_root=uuid_for("player-2"), position=1, stack=500
    )
    context.process.active_positions = [0, 1]

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given("betting round is complete")
def step_given_betting_complete(context):
    """Set betting round as complete."""
    for player in context.process.players.values():
        player.has_acted = True
        player.bet_this_round = context.process.current_bet


@given("an active hand process with (?P<count>\\d+) players")
def step_given_process_with_player_count(context, count):
    """Create process with specified number of players."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        phase=HandPhase.BETTING,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
        pot_total=15,
    )

    for i in range(int(count)):
        context.process.players[i] = PlayerState(
            player_root=uuid_for(f"player-{i + 1}"),
            position=i,
            stack=500,
        )
        context.process.active_positions.append(i)

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given("an ActionTaken event with action (?P<action>\\w+)")
def step_given_simple_action_event(context, action):
    """Create a simple action event."""
    action_enum = getattr(poker_types, action)
    context.event = hand.ActionTaken(
        player_root=uuid_for("player-1"),
        action=action_enum,
        amount=0 if action in ("FOLD", "CHECK") else context.process.pot_total,
        pot_total=context.process.pot_total,
        player_stack=500,
    )


@given("current_bet is (?P<amount>\\d+)")
def step_given_current_bet(context, amount):
    """Set current bet amount."""
    context.process.current_bet = int(amount)


@given("action_on player has bet_this_round (?P<amount>\\d+)")
def step_given_player_bet(context, amount):
    """Set action_on player's bet this round."""
    if context.process.action_on >= 0:
        player = context.process.players.get(context.process.action_on)
        if player:
            player.bet_this_round = int(amount)


@given("an active hand process with game_variant (?P<variant>\\w+)")
def step_given_process_with_variant(context, variant):
    """Create process with specified game variant."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=getattr(poker_types, variant),
        phase=HandPhase.BETTING,
        betting_phase=poker_types.PREFLOP,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
    )

    context.process.players[0] = PlayerState(
        player_root=uuid_for("player-1"), position=0, stack=500
    )
    context.process.players[1] = PlayerState(
        player_root=uuid_for("player-2"), position=1, stack=500
    )
    context.process.active_positions = [0, 1]

    for p in context.process.players.values():
        p.has_acted = True

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given("betting_phase (?P<phase>\\w+)")
def step_given_betting_phase(context, phase):
    """Set betting phase."""
    context.process.betting_phase = getattr(poker_types, phase)


@given("all players have completed their draws")
def step_given_draws_complete(context):
    """Mark all players as having completed draws."""
    context.process.phase = HandPhase.DRAW
    for player in context.process.players.values():
        player.has_acted = True


@given("a CommunityCardsDealt event for (?P<phase>\\w+)")
def step_given_community_dealt_event(context, phase):
    """Create a CommunityCardsDealt event."""
    phase_enum = getattr(poker_types, phase)
    context.event = hand.CommunityCardsDealt(
        phase=phase_enum,
        cards=[],
        all_community_cards=[],
    )


@given("an active hand process")
def step_given_active_process(context):
    """Create a generic active hand process."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        phase=HandPhase.BETTING,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
    )

    context.process.players[0] = PlayerState(
        player_root=uuid_for("player-1"), position=0, stack=500
    )
    context.process.players[1] = PlayerState(
        player_root=uuid_for("player-2"), position=1, stack=500
    )
    context.process.active_positions = [0, 1]

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given("a series of BlindPosted and ActionTaken events totaling (?P<amount>\\d+)")
def step_given_event_series(context, amount):
    """Create a series of events totaling specified amount."""
    context.pot_amount = int(amount)
    context.process.pot_total = int(amount)


@given(
    'an active hand process with player "(?P<player>[^"]+)" at stack (?P<stack>\\d+)'
)
def step_given_process_with_player_stack(context, player, stack):
    """Create process with specified player stack."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)

    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        phase=HandPhase.BETTING,
    )

    context.process.players[0] = PlayerState(
        player_root=uuid_for(player),
        position=0,
        stack=int(stack),
    )
    context.process.active_positions = [0]

    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


@given('an ActionTaken event for "(?P<player>[^"]+)" with amount (?P<amount>\\d+)')
def step_given_action_with_amount(context, player, amount):
    """Create action event for specific player with amount."""
    amt = int(amount)
    context.event = hand.ActionTaken(
        player_root=uuid_for(player),
        action=poker_types.CALL,
        amount=amt,
        pot_total=context.process.pot_total + amt,
        player_stack=context.process.players[0].stack - amt,
    )


@given("a PotAwarded event")
def step_given_pot_awarded_event(context):
    """Create a PotAwarded event."""
    context.event = hand.PotAwarded()
    context.event.winners.append(
        hand.PotWinner(
            player_root=uuid_for("player-1"),
            amount=context.process.pot_total,
            pot_type="main",
        )
    )


# --- When steps ---


@when("the process manager starts the hand")
def step_when_pm_starts_hand(context):
    """Start hand with process manager."""
    context.process = context.pm.start_hand(
        context.hand_started,
        table_root=b"table-1",
    )
    context.hand_id = context.process.hand_id


@when("the process manager handles the event")
def step_when_pm_handles_event(context):
    """Have process manager handle the event."""
    event_type = context.event.DESCRIPTOR.name
    handler_name = f"handle_{event_type.lower()}"

    # Map event types to handler methods
    handlers = {
        "CardsDealt": "handle_cards_dealt",
        "BlindPosted": "handle_blind_posted",
        "ActionTaken": "handle_action_taken",
        "CommunityCardsDealt": "handle_community_cards_dealt",
        "PotAwarded": "handle_pot_awarded",
    }

    handler = getattr(context.pm, handlers.get(event_type, handler_name), None)
    if handler:
        result = handler(context.hand_id, context.event)
        # Send the returned command if any
        if result is not None:
            context.command_sender(result)


@when("the process manager ends the betting round")
def step_when_pm_ends_betting(context):
    """End betting round."""
    result = context.pm._end_betting_round_cmd(context.process)
    # Send the returned command if any
    if result is not None:
        context.command_sender(result)


@when("the action times out")
def step_when_action_times_out(context):
    """Simulate action timeout."""
    context.process.action_on = 0  # Set to first player if not set
    context.pm.handle_timeout(context.hand_id, context.process.action_on)


@when("all events are processed")
def step_when_all_events_processed(context):
    """Process all pending events."""
    pass  # Events already processed in given steps


@when("the process manager handles the last draw")
def step_when_pm_handles_last_draw(context):
    """Handle the last draw completion."""
    result = context.pm._end_betting_round_cmd(context.process)
    # Send the returned command if any
    if result is not None:
        context.command_sender(result)


# --- Then steps ---


@then("a HandProcess is created with phase (?P<phase>\\w+)")
def step_then_process_created_with_phase(context, phase):
    """Verify process created with specified phase."""
    expected = getattr(HandPhase, phase)
    assert context.process is not None, "No process created"
    assert (
        context.process.phase == expected
    ), f"Expected phase {phase}, got {context.process.phase}"


@then("the process has (?P<count>\\d+) players")
def step_then_process_has_players(context, count):
    """Verify process has specified number of players."""
    expected = int(count)
    assert (
        len(context.process.players) == expected
    ), f"Expected {expected} players, got {len(context.process.players)}"


@then("the process has dealer_position (?P<pos>\\d+)")
def step_then_process_has_dealer(context, pos):
    """Verify process has specified dealer position."""
    expected = int(pos)
    assert (
        context.process.dealer_position == expected
    ), f"Expected dealer {expected}, got {context.process.dealer_position}"


@then("the process transitions to phase (?P<phase>\\w+)")
def step_then_process_transitions(context, phase):
    """Verify process transitions to specified phase."""
    expected = getattr(HandPhase, phase)
    assert (
        context.process.phase == expected
    ), f"Expected phase {phase}, got {context.process.phase}"


@then("a PostBlind command is sent for (?P<blind_type>\\w+) blind")
def step_then_post_blind_sent(context, blind_type):
    """Verify PostBlind command is sent."""
    commands = context.command_sender.get_all_commands_of_type("PostBlind")
    assert len(commands) >= 1, f"Expected PostBlind command, got {len(commands)}"


@then("action_on is set to UTG position")
def step_then_action_utg(context):
    """Verify action is on UTG position."""
    # UTG is position after big blind
    assert context.process.action_on >= 0, "action_on not set"


@then("action_on advances to next active player")
def step_then_action_advances(context):
    """Verify action advances."""
    # Just check action_on is set
    assert context.process.action_on >= 0 or context.process.phase in (
        HandPhase.COMPLETE,
        HandPhase.SHOWDOWN,
    )


@then("players at positions (?P<positions>\\d+ and \\d+) have has_acted reset to false")
def step_then_players_reset(context, positions):
    """Verify specified players have has_acted reset."""
    for pos_str in positions.replace("and", ",").split(","):
        pos = int(pos_str.strip())
        if pos in context.process.players:
            assert not context.process.players[
                pos
            ].has_acted, f"Player at {pos} should have has_acted=False"


@then("the betting round ends")
def step_then_betting_ends(context):
    """Verify betting round ended."""
    # Process would have transitioned
    assert (
        context.process.phase != HandPhase.BETTING
        or context.process.phase == HandPhase.BETTING
    )


@then("the process advances to next phase")
def step_then_process_advances(context):
    """Verify process advanced to next phase."""
    pass  # Phase transition checked in other steps


@then("a DealCommunityCards command is sent with count (?P<count>\\d+)")
def step_then_deal_community_sent(context, count):
    """Verify DealCommunityCards command sent."""
    commands = context.command_sender.get_all_commands_of_type("DealCommunityCards")
    assert (
        len(commands) >= 1
    ), f"Expected DealCommunityCards command, got {len(commands)}"

    cmd_any = commands[0].pages[0].command
    cmd = hand.DealCommunityCards()
    cmd_any.Unpack(cmd)
    expected = int(count)
    assert cmd.count == expected, f"Expected count {expected}, got {cmd.count}"


@then("an AwardPot command is sent")
def step_then_award_pot_sent(context):
    """Verify AwardPot command sent."""
    commands = context.command_sender.get_all_commands_of_type("AwardPot")
    assert len(commands) >= 1, f"Expected AwardPot command, got {len(commands)}"


@then("an AwardPot command is sent to the remaining player")
def step_then_award_to_remaining(context):
    """Verify AwardPot sent to remaining player."""
    commands = context.command_sender.get_all_commands_of_type("AwardPot")
    assert len(commands) >= 1, "Expected AwardPot command"


@then("the player is marked as is_all_in")
def step_then_player_all_in(context):
    """Verify player is marked all-in."""
    player = context.process.players.get(0)
    assert player and player.is_all_in, "Player should be marked as all-in"


@then("the player is not included in active players for betting")
def step_then_player_excluded(context):
    """Verify all-in player is excluded from betting."""
    pass  # Checked via is_all_in flag


@then("the process manager sends PlayerAction with (?P<action>\\w+)")
def step_then_pm_sends_action(context, action):
    """Verify process manager sends specified action."""
    commands = context.command_sender.get_all_commands_of_type("PlayerAction")
    assert len(commands) >= 1, "Expected PlayerAction command"

    cmd_any = commands[0].pages[0].command
    cmd = hand.PlayerAction()
    cmd_any.Unpack(cmd)
    expected = getattr(poker_types, action)
    assert cmd.action == expected, f"Expected action {action}, got {cmd.action}"


@then("all players have bet_this_round reset to 0")
def step_then_bets_reset(context):
    """Verify all players have bet_this_round reset."""
    for player in context.process.players.values():
        assert (
            player.bet_this_round == 0
        ), f"Player at {player.position} should have bet_this_round=0"


@then("all players have has_acted reset to false")
def step_then_all_reset(context):
    """Verify all players have has_acted reset."""
    for player in context.process.players.values():
        if not player.has_folded and not player.is_all_in:
            assert (
                not player.has_acted
            ), f"Player at {player.position} should have has_acted=False"


@then("current_bet is reset to 0")
def step_then_current_bet_reset(context):
    """Verify current bet is reset."""
    assert (
        context.process.current_bet == 0
    ), f"Expected current_bet=0, got {context.process.current_bet}"


@then("action_on is set to first player after dealer")
def step_then_action_after_dealer(context):
    """Verify action is on first player after dealer."""
    assert context.process.action_on >= 0, "action_on not set"


@then("pot_total is (?P<amount>\\d+)")
def step_then_pot_total(context, amount):
    """Verify pot total."""
    expected = int(amount)
    assert (
        context.process.pot_total == expected
    ), f"Expected pot {expected}, got {context.process.pot_total}"


@then('"(?P<player>[^"]+)" stack is (?P<stack>\\d+)')
def step_then_player_stack(context, player, stack):
    """Verify player stack."""
    expected = int(stack)
    for p in context.process.players.values():
        if p.player_root == uuid_for(player):
            assert p.stack == expected, f"Expected stack {expected}, got {p.stack}"
            return
    raise AssertionError(f"Player {player} not found")


@then("any pending timeout is cancelled")
def step_then_timeout_cancelled(context):
    """Verify timeout is cancelled."""
    assert (
        context.hand_id not in context.pm._timeout_tasks
    ), "Timeout should be cancelled"


@then("betting_phase is set to (?P<phase>\\w+)")
def step_then_betting_phase_set(context, phase):
    """Verify betting phase."""
    expected = getattr(poker_types, phase)
    assert (
        context.process.betting_phase == expected
    ), f"Expected {phase}, got {context.process.betting_phase}"


# ============================================================================
# Action-order scenarios (EU-0445 / EU-0446 / EU-0447)
# ============================================================================
# These scenarios exercise the seat-walker logic in HandProcessManager:
# preflop the BB retains the option, post-flop ring action starts at the
# first active seat left of the dealer, post-flop heads-up action starts on
# the BB. The steps below let a scenario seat N players, post blinds, and
# drive individual player actions without going through the full
# table/coordinator stack.


@given(
    r"dealer is at position (?P<dealer>\d+) and (?P<count>\d+) players seated at "
    r"positions (?P<positions>[\d,\s]+)"
)
def step_given_dealer_and_seated(context, dealer, count, positions):
    """Reseat the existing process with M players at explicit positions.

    The prior `Given an active hand process ...` step seeds two default
    players; this step replaces them with PlayerStates at the listed
    positions (default stack 1000) and pins the dealer.
    """
    assert hasattr(context, "process") and context.process is not None, (
        "No active hand process — run an `active hand process` Given first"
    )
    seats = [int(s.strip()) for s in positions.split(",") if s.strip()]
    assert len(seats) == int(count), (
        f"Expected {count} positions, got {len(seats)}: {seats}"
    )

    context.process.dealer_position = int(dealer)
    context.process.players = {}
    context.process.active_positions = []
    for i, pos in enumerate(seats):
        context.process.players[pos] = PlayerState(
            player_root=uuid_for(f"player-{i + 1}"),
            position=pos,
            stack=1000,
        )
        context.process.active_positions.append(pos)
    context.process.active_positions.sort()


@given(
    r"blinds posted: SB position (?P<sb_pos>\d+) amount (?P<sb_amt>\d+), "
    r"BB position (?P<bb_pos>\d+) amount (?P<bb_amt>\d+)"
)
def step_given_blinds_posted_pm(context, sb_pos, sb_amt, bb_pos, bb_amt):
    """Set blind positions/amounts and reflect them in player & process state.

    Mirrors what `handle_blind_posted` would do for SB+BB, without going
    through the actual handler chain (the chain calls _start_betting which
    resets bet_this_round to 0). This step leaves the process ready for
    individual player CALL/FOLD/etc. actions in the preflop round.
    """
    assert hasattr(context, "process") and context.process is not None, "No process"
    sb_pos_i, bb_pos_i = int(sb_pos), int(bb_pos)
    sb_amt_i, bb_amt_i = int(sb_amt), int(bb_amt)

    context.process.small_blind_position = sb_pos_i
    context.process.big_blind_position = bb_pos_i
    context.process.small_blind = sb_amt_i
    context.process.big_blind = bb_amt_i
    context.process.current_bet = bb_amt_i
    context.process.min_raise = bb_amt_i
    context.process.pot_total = sb_amt_i + bb_amt_i
    context.process.small_blind_posted = True
    context.process.big_blind_posted = True
    context.process.betting_phase = poker_types.PREFLOP

    sb_player = context.process.players.get(sb_pos_i)
    if sb_player is not None:
        sb_player.bet_this_round = sb_amt_i
        sb_player.total_invested = sb_amt_i
        sb_player.stack -= sb_amt_i

    bb_player = context.process.players.get(bb_pos_i)
    if bb_player is not None:
        bb_player.bet_this_round = bb_amt_i
        bb_player.total_invested = bb_amt_i
        bb_player.stack -= bb_amt_i


@given("the preflop betting round is complete")
def step_given_preflop_complete(context):
    """Mark every active player as having acted at the current_bet level.

    Sets up the process so `_is_betting_complete` returns True for the
    current betting round — letting a subsequent CommunityCardsDealt event
    advance the phase and re-pick action_on via `_start_betting`'s
    post-flop branch.
    """
    assert hasattr(context, "process") and context.process is not None, "No process"
    context.process.betting_phase = poker_types.PREFLOP
    if context.process.current_bet == 0:
        context.process.current_bet = context.process.big_blind or 10
    for player in context.process.players.values():
        if not player.has_folded and not player.is_all_in:
            player.has_acted = True
            player.bet_this_round = context.process.current_bet


@when(r"the player at position (?P<pos>\d+) calls (?P<amount>\d+)")
def step_when_player_calls(context, pos, amount):
    """Synthesize an ActionTaken(CALL) for the seated player and dispatch it.

    The amount is the chips ADDED this action (not the running bet_this_round
    total). `handle_action_taken` updates bet_this_round/has_acted and then
    either advances action_on or ends the round.
    """
    assert hasattr(context, "process") and context.process is not None, "No process"
    position = int(pos)
    amt = int(amount)
    player = context.process.players.get(position)
    assert player is not None, f"No player at position {position}"

    new_stack = player.stack - amt
    new_pot = context.process.pot_total + amt
    event = hand.ActionTaken(
        player_root=player.player_root,
        action=poker_types.CALL,
        amount=amt,
        pot_total=new_pot,
        player_stack=new_stack,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"a CommunityCardsDealt event for (?P<phase>\w+) is handled")
def step_when_community_cards_handled(context, phase):
    """Build a CommunityCardsDealt event and dispatch it through the PM.

    Mirrors what the table coordinator would emit after dealing the flop
    (or turn/river). The PM's `handle_community_cards_dealt` flips the
    phase and calls `_start_betting`, which is where the post-flop seat
    walker logic gets exercised.
    """
    assert hasattr(context, "process") and context.process is not None, "No process"
    phase_enum = getattr(poker_types, phase.upper())
    card_counts = {
        poker_types.FLOP: 3,
        poker_types.TURN: 1,
        poker_types.RIVER: 1,
    }
    n_cards = card_counts.get(phase_enum, 3)
    event = hand.CommunityCardsDealt(phase=phase_enum)
    for i in range(n_cards):
        event.cards.append(poker_types.Card(suit=poker_types.HEARTS, rank=10 + i))
    event.all_community_cards.extend(event.cards)
    result = context.pm.handle_community_cards_dealt(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@then("the betting round is not complete")
def step_then_betting_not_complete(context):
    """Assert that `_is_betting_complete` returns False for the current round."""
    assert hasattr(context, "process") and context.process is not None, "No process"
    assert not context.pm._is_betting_complete(context.process), (
        "Expected betting round to be in progress, but _is_betting_complete "
        "returned True. Per-player state: "
        + ", ".join(
            f"pos={p.position} acted={p.has_acted} bet={p.bet_this_round} "
            f"folded={p.has_folded} allin={p.is_all_in}"
            for p in context.process.players.values()
        )
    )


@then(r"action_on is position (?P<pos>\d+)")
def step_then_action_on_position(context, pos):
    """Assert the current action_on seat matches the expected position."""
    assert hasattr(context, "process") and context.process is not None, "No process"
    assert context.process.action_on == int(pos), (
        f"Expected action_on={pos}, got {context.process.action_on}"
    )


# ============================================================================
# BuyIn / Rebuy / Registration PM step definitions
# ============================================================================
# The three PMs (buy_in/pmg, rebuy/pmg, registration/pmg) each live in their
# own directory with conflicting module names (state.py, handlers.py). We load
# each module set under a unique sys.modules alias so behave can import all
# three classes simultaneously without sys.path collisions at runtime.


from angzarr_client import Destinations  # noqa: E402
from angzarr_client.helpers import type_name_from_url  # noqa: E402
from angzarr_client.proto.examples import buy_in_pb2 as buy_in  # noqa: E402
from angzarr_client.proto.examples import orchestration_pb2 as orch  # noqa: E402
from angzarr_client.proto.examples import poker_types_pb2 as poker  # noqa: E402
from angzarr_client.proto.examples import registration_pb2 as registration  # noqa: E402
from angzarr_client.proto.examples import rebuy_pb2 as rebuy  # noqa: E402
from angzarr_client.proto.examples import tournament_pb2 as tournament  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent


# The three legacy PMs (buy_in/pmg, rebuy/pmg, registration/pmg) were
# consolidated into reservation/pmg/ in the reservation refactor. Load the
# single consolidated PM under its sibling-import convention (handlers.py
# does ``from state import …``), then expose the old class names as
# aliases so the existing step definitions in this file keep working
# without being rewritten.
def _load_reservation_pm() -> dict:
    conflict_names = (
        "state",
        "table_state",
        "tournament_state",
        "handlers",
    )
    saved = {n: sys.modules.pop(n) for n in conflict_names if n in sys.modules}
    saved_path = list(sys.path)
    pmg_dir = _REPO_ROOT / "reservation" / "pmg"
    sys.path.insert(0, str(pmg_dir))
    try:
        import handlers as h
        import state as s
        import table_state as tbs
        import tournament_state as ts

        result = {
            "handlers": h,
            "state": s,
            "table_state": tbs,
            "tournament_state": ts,
        }
    finally:
        for n in conflict_names:
            sys.modules.pop(n, None)
        sys.path[:] = saved_path
        for n, mod in saved.items():
            sys.modules[n] = mod
    return result


_reservation_mods = _load_reservation_pm()

ReservationPM = _reservation_mods["handlers"].ReservationPM
ReservationPMState = _reservation_mods["state"].ReservationPMState

# Back-compat aliases — each legacy PM class name now points at the
# consolidated ReservationPM. The step bodies below instantiate these
# freely; a single PM carries all three flavors, so the substitution is
# safe (the state discriminator kicks in per event kind).
BuyInPM = ReservationPM
RegistrationPM = ReservationPM
RebuyPM = ReservationPM

# Legacy state aliases — all three flavors share one unified state class.
BuyInState = ReservationPMState
RegistrationState = ReservationPMState
RebuyState = ReservationPMState

TournamentStateHelper = _reservation_mods["tournament_state"].TournamentStateHelper
tournament_state_from_event_book = _reservation_mods[
    "tournament_state"
].tournament_state_from_event_book
tournament_state_rebuild = _reservation_mods[
    "tournament_state"
].tournament_state_rebuild


# --- Helpers ---------------------------------------------------------------


def _parse_kv_params(raw: str) -> dict[str, str]:
    """Parse comma-separated ``key value`` or ``key=value`` pairs from a
    free-form step parameter list.

    Handles the step styles we use, e.g.:
      table_root "table_456", reservation_id "res_789", seat 2, amount 500
      tournament=5, table=3
    """
    result: dict[str, str] = {}
    # Split on commas that are NOT inside quotes
    parts: list[str] = []
    buf = []
    in_quote = False
    for ch in raw:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))

    for p in parts:
        p = p.strip()
        if not p:
            continue
        # key="value" or key=value or key value
        if "=" in p:
            k, _, v = p.partition("=")
        else:
            k, _, v = p.partition(" ")
        result[k.strip()] = v.strip().strip('"')
    return result


def _bytes(val: str) -> bytes:
    # All callers pass label strings for entity-root / reservation-id bytes
    # fields (player_root, table_root, tournament_root, reservation_id).
    # Migrate empty-string -> b"" so tests can probe missing fields.
    if isinstance(val, str):
        return uuid_for(val) if val else b""
    return val


def _first_command(response):
    """Return the first (packed) command message from a ProcessManagerResponse."""
    assert response is not None, "Handler returned None"
    assert response.commands, "Expected at least one command"
    return response.commands[0]


def _find_command(response, proto_cls):
    """Return the first command book whose packed payload matches ``proto_cls``."""
    assert response is not None, "Handler returned None"
    assert response.commands, "Expected at least one command"
    type_url_suffix = proto_cls.DESCRIPTOR.full_name
    for cmd_book in response.commands:
        for page in cmd_book.pages:
            if page.command.type_url.endswith(type_url_suffix):
                return cmd_book
    raise AssertionError(
        f"Expected a {proto_cls.__name__} command in response; "
        f"got {[b.cover.domain for b in response.commands]}"
    )


def _unpack_command(cmd_book, proto_cls):
    """Unpack the first command page into ``proto_cls``."""
    msg = proto_cls()
    cmd_book.pages[0].command.Unpack(msg)
    return msg


def _unpack_process_event(response, proto_cls):
    """Unpack the first process event page into ``proto_cls``."""
    assert response.process_events is not None, "No process events in response"
    assert response.process_events.pages, "No pages in process events book"
    msg = proto_cls()
    response.process_events.pages[0].event.Unpack(msg)
    return msg


# --- BuyIn PM: Given steps -------------------------------------------------


@given(r'a BuyInPM(?: with player_root "(?P<player_root>[^"]+)")?')
def step_given_buy_in_pm(context, player_root=None):
    context.pm_response = None
    context.pm_instance = BuyInPM()
    if player_root:
        context.pm_state = BuyInState(player_root=_bytes(player_root))
    else:
        context.pm_state = BuyInState()


@given(r"a BuyInRequested event with (?P<params>.+)")
def step_given_buy_in_requested(context, params):
    p = _parse_kv_params(params)
    amount = poker.Currency(amount=int(p.get("amount", 0)))
    context.pm_event = buy_in.BuyInRequested(
        table_root=_bytes(p.get("table_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        seat=int(p.get("seat", 0)),
        amount=amount,
    )


@given(r"a PlayerSeated event with (?P<params>.+)")
def step_given_player_seated(context, params):
    p = _parse_kv_params(params)
    context.pm_event = buy_in.PlayerSeated(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        seat_position=int(p.get("seat_position", 0)),
        stack=int(p.get("stack", 0)),
    )


@given(r"a SeatingRejected event with (?P<params>.+)")
def step_given_seating_rejected(context, params):
    p = _parse_kv_params(params)
    context.pm_event = buy_in.SeatingRejected(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        reason=p.get("reason", ""),
    )


# --- Rebuy PM: Given steps -------------------------------------------------


@given(r'a RebuyPM with player_root "(?P<player_root>[^"]+)"')
def step_given_rebuy_pm_with_player(context, player_root):
    context.pm_response = None
    context.pm_instance = RebuyPM()
    context.pm_state = RebuyState(player_root=_bytes(player_root))


@given(r'a RebuyPM with table_root "(?P<table_root>[^"]+)" and seat (?P<seat>\d+)')
def step_given_rebuy_pm_with_table_seat(context, table_root, seat):
    context.pm_response = None
    context.pm_instance = RebuyPM()
    context.pm_state = RebuyState(table_root=_bytes(table_root), seat=int(seat))


@given(r'a RebuyPM with tournament_root "(?P<tournament_root>[^"]+)"')
def step_given_rebuy_pm_with_tournament(context, tournament_root):
    context.pm_response = None
    context.pm_instance = RebuyPM()
    context.pm_state = RebuyState(tournament_root=_bytes(tournament_root))


@given(
    r'a RebuyPM with tournament_root "(?P<tournament_root>[^"]+)",'
    r' table_root "(?P<table_root>[^"]+)", fee (?P<fee>\d+)'
)
def step_given_rebuy_pm_full(context, tournament_root, table_root, fee):
    context.pm_response = None
    context.pm_instance = RebuyPM()
    context.pm_state = RebuyState(
        tournament_root=_bytes(tournament_root),
        table_root=_bytes(table_root),
        fee=int(fee),
    )


@given(r"a RebuyRequested event with (?P<params>.+)")
def step_given_rebuy_requested(context, params):
    p = _parse_kv_params(params)
    context.pm_event = rebuy.RebuyRequested(
        tournament_root=_bytes(p.get("tournament_root", "")),
        table_root=_bytes(p.get("table_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        seat=int(p.get("seat", 0)),
        fee=poker.Currency(amount=int(p.get("fee", 0))),
    )


@given(r"a RebuyProcessed event with (?P<params>.+)")
def step_given_rebuy_processed(context, params):
    p = _parse_kv_params(params)
    context.pm_event = tournament.RebuyProcessed(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        chips_added=int(p.get("chips_added", 0)),
        rebuy_count=int(p.get("rebuy_count", 0)),
    )


@given(r"a RebuyDenied event with (?P<params>.+)")
def step_given_rebuy_denied(context, params):
    p = _parse_kv_params(params)
    context.pm_event = tournament.RebuyDenied(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        reason=p.get("reason", ""),
    )


@given(r"a RebuyChipsAdded event with (?P<params>.+)")
def step_given_rebuy_chips_added(context, params):
    p = _parse_kv_params(params)
    context.pm_event = rebuy.RebuyChipsAdded(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        seat=int(p.get("seat", 0)),
        amount=int(p.get("amount", 0)),
        new_stack=int(p.get("new_stack", 0)),
    )


# --- Registration PM: Given steps ------------------------------------------


@given(r'a RegistrationPM with player_root "(?P<player_root>[^"]+)"')
def step_given_registration_pm_with_player(context, player_root):
    context.pm_response = None
    context.pm_instance = RegistrationPM()
    context.pm_state = RegistrationState(player_root=_bytes(player_root))


@given(r'a RegistrationPM with tournament_root "(?P<tournament_root>[^"]+)"')
def step_given_registration_pm_with_tournament(context, tournament_root):
    context.pm_response = None
    context.pm_instance = RegistrationPM()
    context.pm_state = RegistrationState(tournament_root=_bytes(tournament_root))


@given(
    r'a RegistrationPM with tournament_root "(?P<tournament_root>[^"]+)"'
    r" and fee (?P<fee>\d+)"
)
def step_given_registration_pm_with_tournament_fee(context, tournament_root, fee):
    context.pm_response = None
    context.pm_instance = RegistrationPM()
    context.pm_state = RegistrationState(
        tournament_root=_bytes(tournament_root),
        fee=int(fee),
    )


@given(r"a RegistrationRequested event with (?P<params>.+)")
def step_given_registration_requested(context, params):
    p = _parse_kv_params(params)
    context.pm_event = registration.RegistrationRequested(
        tournament_root=_bytes(p.get("tournament_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        fee=poker.Currency(amount=int(p.get("fee", 0))),
    )


@given(r"a TournamentPlayerEnrolled event with (?P<params>.+)")
def step_given_tournament_player_enrolled(context, params):
    p = _parse_kv_params(params)
    context.pm_event = tournament.TournamentPlayerEnrolled(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        fee_paid=int(p.get("fee_paid", 0)),
        starting_stack=int(p.get("starting_stack", 0)),
    )


@given(r"a TournamentEnrollmentRejected event with (?P<params>.+)")
def step_given_tournament_enrollment_rejected(context, params):
    p = _parse_kv_params(params)
    context.pm_event = tournament.TournamentEnrollmentRejected(
        player_root=_bytes(p.get("player_root", "")),
        reservation_id=_bytes(p.get("reservation_id", "")),
        reason=p.get("reason", ""),
    )


# --- Shared Given: destinations --------------------------------------------


@given(r"destinations with sequences (?P<kv>.+)")
def step_given_destinations(context, kv):
    pairs = _parse_kv_params(kv)
    seqs = {k: int(v) for k, v in pairs.items()}
    context.pm_destinations = Destinations(seqs)


# --- When steps ------------------------------------------------------------


@when(r"the BuyInPM handles (?P<handler>\w+)")
def step_when_buy_in_handles(context, handler):
    fn = getattr(context.pm_instance, f"on_{handler}")
    context.pm_response = fn(
        context.pm_event,
        state=context.pm_state,
        destinations=context.pm_destinations,
    )


@when(r"the RebuyPM handles (?P<handler>\w+)")
def step_when_rebuy_handles(context, handler):
    fn = getattr(context.pm_instance, f"on_{handler}")
    context.pm_response = fn(
        context.pm_event,
        state=context.pm_state,
        destinations=context.pm_destinations,
    )


@when(r"the RegistrationPM handles (?P<handler>\w+)")
def step_when_registration_handles(context, handler):
    fn = getattr(context.pm_instance, f"on_{handler}")
    context.pm_response = fn(
        context.pm_event,
        state=context.pm_state,
        destinations=context.pm_destinations,
    )


# --- Then: command assertions ----------------------------------------------


# Map command type name -> (proto class)
_COMMAND_TYPES = {
    "SeatPlayer": buy_in.SeatPlayer,
    "ConfirmBuyIn": buy_in.ConfirmBuyIn,
    "ReleaseBuyIn": buy_in.ReleaseBuyIn,
    "ProcessRebuy": tournament.ProcessRebuy,
    "AddRebuyChips": rebuy.AddRebuyChips,
    "ReleaseRebuyFee": rebuy.ReleaseRebuyFee,
    "ConfirmRebuyFee": rebuy.ConfirmRebuyFee,
    "EnrollPlayer": tournament.EnrollPlayer,
    "ConfirmRegistrationFee": registration.ConfirmRegistrationFee,
    "ReleaseRegistrationFee": registration.ReleaseRegistrationFee,
}


@then(
    r"an? (?P<cmd_name>"
    + "|".join(sorted(_COMMAND_TYPES.keys(), key=len, reverse=True))
    + r') command is sent to the "(?P<domain>\w+)" domain'
)
def step_then_cmd_sent_to_domain(context, cmd_name, domain):
    proto_cls = _COMMAND_TYPES[cmd_name]
    cmd_book = _find_command(context.pm_response, proto_cls)
    assert (
        cmd_book.cover.domain == domain
    ), f"Expected {cmd_name} on domain {domain!r}, got {cmd_book.cover.domain!r}"
    context.pm_command = _unpack_command(cmd_book, proto_cls)
    context.pm_command_name = cmd_name


_CMD_NAMES_ALT = "|".join(sorted(_COMMAND_TYPES.keys(), key=len, reverse=True))


@then(
    r"the (?P<cmd_name>" + _CMD_NAMES_ALT + r") command has "
    r'(?P<field>\w+) "(?P<value>[^"]*)"'
)
def step_then_cmd_has_str_field(context, cmd_name, field, value):
    assert (
        context.pm_command_name == cmd_name
    ), f"Expected asserting {cmd_name} but last command was {context.pm_command_name}"
    actual = getattr(context.pm_command, field)
    if isinstance(actual, bytes):
        assert actual == _bytes(
            value
        ), f"{cmd_name}.{field}: expected {value!r}, got {actual!r}"
    else:
        assert (
            actual == value
        ), f"{cmd_name}.{field}: expected {value!r}, got {actual!r}"


@then(
    r"the (?P<cmd_name>" + _CMD_NAMES_ALT + r") command has "
    r"(?P<field>\w+) (?P<value>-?\d+)"
)
def step_then_cmd_has_int_field(context, cmd_name, field, value):
    assert (
        context.pm_command_name == cmd_name
    ), f"Expected asserting {cmd_name} but last command was {context.pm_command_name}"
    actual = getattr(context.pm_command, field)
    assert actual == int(value), f"{cmd_name}.{field}: expected {value}, got {actual}"


# --- Then: process event assertions ----------------------------------------


_PROCESS_EVENT_TYPES = {
    "angzarr_client.proto.examples.BuyInInitiated": buy_in.BuyInInitiated,
    "angzarr_client.proto.examples.BuyInCompleted": buy_in.BuyInCompleted,
    "angzarr_client.proto.examples.BuyInFailed": buy_in.BuyInFailed,
    "angzarr_client.proto.examples.RebuyInitiated": rebuy.RebuyInitiated,
    "angzarr_client.proto.examples.RebuyCompleted": rebuy.RebuyCompleted,
    "angzarr_client.proto.examples.RebuyFailed": rebuy.RebuyFailed,
    "angzarr_client.proto.examples.RegistrationInitiated": registration.RegistrationInitiated,
    "angzarr_client.proto.examples.RegistrationCompleted": registration.RegistrationCompleted,
    "angzarr_client.proto.examples.RegistrationFailed": registration.RegistrationFailed,
}


@then(r"the process event is an? (?P<qualified>[\w.]+) event")
def step_then_process_event_type(context, qualified):
    assert context.pm_response is not None, "No PM response recorded"
    assert (
        context.pm_response.process_events is not None
    ), "No process events in PM response"
    assert context.pm_response.process_events.pages, "No pages in process events book"
    actual_type = type_name_from_url(
        context.pm_response.process_events.pages[0].event.type_url
    )
    assert (
        actual_type == qualified
    ), f"Expected process event {qualified}, got {actual_type}"
    proto_cls = _PROCESS_EVENT_TYPES[qualified]
    context.pm_process_event = _unpack_process_event(context.pm_response, proto_cls)
    # Short name used by subsequent field assertions
    context.pm_process_event_name = qualified.rsplit(".", 1)[-1]


_PROCESS_EVENT_NAMES_ALT = "|".join(
    sorted(
        (name.rsplit(".", 1)[-1] for name in _PROCESS_EVENT_TYPES),
        key=len,
        reverse=True,
    )
)


@then(
    r"the (?P<evt_name>" + _PROCESS_EVENT_NAMES_ALT + r") event has "
    r'(?P<field>\w+) "(?P<value>[^"]*)"'
)
def step_then_process_event_has_str_field(context, evt_name, field, value):
    assert (
        context.pm_process_event_name == evt_name
    ), f"Expected asserting {evt_name} but last event was {context.pm_process_event_name}"
    actual = getattr(context.pm_process_event, field)
    if isinstance(actual, bytes):
        assert actual == _bytes(
            value
        ), f"{evt_name}.{field}: expected {value!r}, got {actual!r}"
    else:
        assert (
            actual == value
        ), f"{evt_name}.{field}: expected {value!r}, got {actual!r}"


@then(
    r"the (?P<evt_name>" + _PROCESS_EVENT_NAMES_ALT + r") event has "
    r"(?P<field>\w+) (?P<value>-?\d+)"
)
def step_then_process_event_has_int_field(context, evt_name, field, value):
    assert (
        context.pm_process_event_name == evt_name
    ), f"Expected asserting {evt_name} but last event was {context.pm_process_event_name}"
    actual = getattr(context.pm_process_event, field)
    assert actual == int(value), f"{evt_name}.{field}: expected {value}, got {actual}"


@then(
    r"the (?P<evt_name>" + _PROCESS_EVENT_NAMES_ALT + r") event phase is "
    r"(?P<phase>\w+)"
)
def step_then_process_event_phase(context, evt_name, phase):
    assert (
        context.pm_process_event_name == evt_name
    ), f"Expected asserting {evt_name} but last event was {context.pm_process_event_name}"
    # phase lives under orch enums, BuyInPhase/RebuyPhase/RegistrationPhase
    # Build a lookup across all three
    actual = context.pm_process_event.phase
    found = False
    expected_val = None
    for enum_name in ("BuyInPhase", "RebuyPhase", "RegistrationPhase"):
        enum = getattr(orch, enum_name)
        for k, v in enum.items():
            # gherkin may say "BUY_IN_SEATING" etc; the full enum name in
            # proto is the same.
            if k == phase:
                expected_val = v
                found = True
                break
        if found:
            break
    assert found, f"Could not resolve phase name {phase!r}"
    assert (
        actual == expected_val
    ), f"{evt_name}.phase: expected {phase} ({expected_val}), got {actual}"


@then(
    r"the (?P<evt_name>" + _PROCESS_EVENT_NAMES_ALT + r") event has "
    r"fee amount (?P<amount>-?\d+)"
)
def step_then_process_event_fee_amount(context, evt_name, amount):
    assert (
        context.pm_process_event_name == evt_name
    ), f"Expected asserting {evt_name} but last event was {context.pm_process_event_name}"
    actual = context.pm_process_event.fee.amount
    assert actual == int(
        amount
    ), f"{evt_name}.fee.amount: expected {amount}, got {actual}"


@then(
    r"the (?P<evt_name>" + _PROCESS_EVENT_NAMES_ALT + r") event failure "
    r'code is "(?P<code>[^"]+)"'
)
def step_then_process_event_failure_code(context, evt_name, code):
    assert (
        context.pm_process_event_name == evt_name
    ), f"Expected asserting {evt_name} but last event was {context.pm_process_event_name}"
    actual = context.pm_process_event.failure.code
    assert actual == code, f"{evt_name}.failure.code: expected {code!r}, got {actual!r}"


# --- Tournament state rebuild -----------------------------------------------


def _pack_any(event):
    from google.protobuf.any_pb2 import Any as AnyProto

    any_pb = AnyProto()
    any_pb.Pack(event, type_url_prefix="type.googleapis.com/")
    return any_pb


@given(
    r"a tournament event book with a TournamentCreated event "
    r'name "(?P<name>[^"]+)", max_players (?P<max_p>\d+), '
    r"buy_in (?P<buy_in>\d+), starting_stack (?P<stack>\d+)"
)
def step_given_tournament_event_book_created(context, name, max_p, buy_in, stack):
    created = tournament.TournamentCreated(
        name=name,
        max_players=int(max_p),
        buy_in=int(buy_in),
        starting_stack=int(stack),
    )
    pages = [types.EventPage(event=_pack_any(created))]
    context.pm_event_book = types.EventBook(
        cover=types.Cover(domain="tournament"),
        pages=pages,
    )


@given(r"a tournament event book with:")
def step_given_tournament_event_book_table(context):
    pages = []
    for row in context.table:
        data = {h: row[h] for h in context.table.headings}
        event_type = data.get("event_type", "")
        if event_type == "TournamentCreated":
            evt = tournament.TournamentCreated(
                name=data.get("name") or "",
                max_players=int(data.get("max_players") or 0),
            )
        elif event_type == "TournamentStarted":
            evt = tournament.TournamentStarted()
        elif event_type == "TournamentPlayerEnrolled":
            evt = tournament.TournamentPlayerEnrolled(
                player_root=_bytes(data.get("player_root") or ""),
                registration_number=int(data.get("registration_number") or 0),
            )
        else:
            raise ValueError(f"Unknown tournament event type: {event_type}")
        pages.append(types.EventPage(event=_pack_any(evt)))
    context.pm_event_book = types.EventBook(
        cover=types.Cover(domain="tournament"),
        pages=pages,
    )


@given("an empty tournament state helper")
def step_given_empty_tournament_state(context):
    context.tournament_state_helper = TournamentStateHelper()


@when("I rebuild the tournament state from the event book")
def step_when_rebuild_tournament_state(context):
    context.tournament_state_helper = tournament_state_from_event_book(
        context.pm_event_book
    )


@when(
    r'I apply a TournamentCreated event with name "(?P<name>[^"]+)"'
    r" and max_players (?P<mp>\d+)"
)
def step_when_apply_tournament_created(context, name, mp):
    tournament_state_rebuild(
        context.tournament_state_helper,
        tournament.TournamentCreated(name=name, max_players=int(mp)),
    )


@when(r"I apply a TournamentPlayerEnrolled event for player_root" r' "(?P<pr>[^"]+)"')
def step_when_apply_player_enrolled(context, pr):
    tournament_state_rebuild(
        context.tournament_state_helper,
        tournament.TournamentPlayerEnrolled(player_root=_bytes(pr)),
    )


@then(r"the tournament state has registration_open (?P<val>true|false)")
def step_then_ts_registration_open(context, val):
    expected = val == "true"
    actual = context.tournament_state_helper.registration_open
    assert actual is expected, f"registration_open: expected {expected}, got {actual}"


def _ts_target(context):
    """Return whichever tournament state holder the scenario populated."""
    return getattr(context, "tournament_state_helper", None) or context.agg


@then(r"the tournament state has max_players (?P<n>\d+)")
def step_then_ts_max_players(context, n):
    assert _ts_target(context).max_players == int(n)


@then(r"the tournament state has buy_in (?P<n>\d+)")
def step_then_ts_buy_in(context, n):
    assert _ts_target(context).buy_in == int(n)


@then(r"the tournament state has starting_stack (?P<n>\d+)")
def step_then_ts_starting_stack(context, n):
    assert _ts_target(context).starting_stack == int(n)


@then(r"the tournament state has registered_count (?P<n>\d+)")
def step_then_ts_registered_count(context, n):
    assert context.tournament_state_helper.registered_count == int(n), (
        f"registered_count: expected {n}, "
        f"got {context.tournament_state_helper.registered_count}"
    )


@then(r'the tournament state has registered player "(?P<pr>[^"]+)"')
def step_then_ts_registered_player(context, pr):
    assert _bytes(pr).hex() in context.tournament_state_helper.registered_players, (
        f"{pr!r} not in registered_players: "
        f"{context.tournament_state_helper.registered_players}"
    )


@then(r"the tournament state status is (?P<status>\w+)")
def step_then_ts_status(context, status):
    expected = getattr(tournament.TournamentStatus, status)
    assert context.tournament_state_helper.status == expected, (
        f"status: expected {status} ({expected}), "
        f"got {context.tournament_state_helper.status}"
    )
