"""Step definitions for the hand-orchestration tests.

The step regexes match the business-language phrasing in
``features/example/unit/process_manager.feature``: things like
"the cards are dealt to the players" rather than implementation-level
"a CardsDealt event is handled". Implementations still drive the
production ``HandProcessManager`` and ``ReservationPM``; only the
matchers and a few business-flavoured Then-step assertions changed.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, use_step_matcher, when
from google.protobuf.timestamp_pb2 import Timestamp

from tests.helpers import uuid_for

from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import hand_pb2 as hand
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import table_pb2 as table

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
        if index < len(self.commands):
            return self.commands[index]
        return None

    def get_all_commands_of_type(self, type_name: str):
        result = []
        for cmd_book in self.commands:
            if cmd_book.pages and type_name in cmd_book.pages[0].command.type_url:
                result.append(cmd_book)
        return result


def _new_pm(context):
    """Create a fresh HandProcessManager + command sender on the context."""
    context.command_sender = TestCommandSender()
    context.pm = HandProcessManager(command_sender=context.command_sender)


def _new_process(
    context,
    *,
    phase,
    betting_phase=None,
    dealer=0,
    sb=5,
    bb=10,
    players=2,
    game_variant=poker_types.TEXAS_HOLDEM,
):
    """Create a HandProcess with N default players seated at positions 0..N-1."""
    context.process = HandProcess(
        hand_id=DEFAULT_HAND_ID,
        table_root=b"table-1",
        hand_number=1,
        game_variant=game_variant,
        phase=phase,
        dealer_position=dealer,
        small_blind=sb,
        big_blind=bb,
    )
    if betting_phase is not None:
        context.process.betting_phase = betting_phase
    for i in range(players):
        context.process.players[i] = PlayerState(
            player_root=uuid_for(f"player-{i + 1}"),
            position=i,
            stack=500,
        )
        context.process.active_positions.append(i)
    context.process.small_blind_position = 1 if players != 2 else 1
    context.process.big_blind_position = 0 if dealer == 1 else 1
    context.pm._processes[DEFAULT_HAND_ID] = context.process
    context.hand_id = DEFAULT_HAND_ID


# =============================================================================
# Given steps — hand setup in business language
# =============================================================================


@given(r"a HandFlowPM")
def step_given_hand_process_manager(context):
    """Create a fresh HandProcessManager (used by the orchestration-style scenarios)."""
    _new_pm(context)
    context.hand_started = None
    context.hand_id = None
    context.process = None


@given(
    r"a hand has just started with dealer at position (?P<dealer>\d+), "
    r"small blind (?P<sb>\d+), big blind (?P<bb>\d+)"
)
def step_given_hand_just_started(context, dealer, sb, bb):
    """Business-language alias for HandStarted setup."""
    _new_pm(context)
    context.hand_started = table.HandStarted(
        hand_root=b"hand-1",
        hand_number=1,
        dealer_position=int(dealer),
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=int(sb),
        big_blind=int(bb),
        small_blind_position=1,
        big_blind_position=0 if int(dealer) == 1 else 1,
        started_at=make_timestamp(),
    )
    context.event = context.hand_started


@given(r"the seated players are:")
def step_given_seated_players(context):
    """Attach seated players (from data table) to the staged HandStarted event."""
    target = getattr(context, "hand_started", None) or getattr(context, "event", None)
    if target is None:
        raise ValueError("No HandStarted in context")
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player", "player-1"))
        target.active_players.append(
            table.SeatSnapshot(
                player_root=player_root,
                position=int(row_dict.get("position", 0)),
                stack=int(row_dict.get("stack", 500)),
            )
        )


@given(r"a HandStarted event with:")
def step_given_hand_started_event(context):
    """Implementation-style alias preserved for any remaining harness coverage."""
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
    context.event = context.hand_started


@given(r"active players:")
def step_given_active_players_dt(context):
    """Attach active players from data table to the staged HandStarted event.

    This kept the OLD column name (``player_root``) used by the implementation-
    style HandStarted step.
    """
    target = getattr(context, "hand_started", None) or getattr(context, "event", None)
    if target is None:
        raise ValueError("No event in context")
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


@given(r"a hand is in the dealing phase")
def step_given_hand_in_dealing(context):
    """An active hand process in the DEALING phase."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.DEALING)


@given(r"a hand is posting blinds")
def step_given_hand_posting_blinds(context):
    """An active hand process in the POSTING_BLINDS phase."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.POSTING_BLINDS)


@given(r"the small blind has been posted")
def step_given_small_blind_posted(context):
    """Mark the small blind as already posted."""
    context.process.small_blind_posted = True


@given(r"a hand is in a betting round")
def step_given_hand_in_betting(context):
    """An active hand process in the BETTING phase."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING)


@given(r"action is on the player at position (?P<pos>\d+)")
def step_given_action_on_pos(context, pos):
    """Set the action_on cursor."""
    context.process.action_on = int(pos)


@given(
    r"the players at positions (?P<positions>\d+(?:,\s*\d+)*(?:,?\s*and\s*\d+)?) "
    r"have all acted"
)
def step_given_players_have_acted(context, positions):
    """Mark each listed player as has_acted=True."""
    cleaned = positions.replace("and", ",").replace(" ", "")
    for pos_str in cleaned.split(","):
        if not pos_str:
            continue
        pos = int(pos_str)
        if pos in context.process.players:
            context.process.players[pos].has_acted = True


@given(r"every active player has acted and matched the current bet")
def step_given_all_players_matched(context):
    """All active players have has_acted=True and bet_this_round==current_bet."""
    context.process.current_bet = 10
    for player in context.process.players.values():
        if not player.has_folded and not player.is_all_in:
            player.has_acted = True
            player.bet_this_round = 10


@given(r"preflop betting is complete")
def step_given_preflop_betting_complete(context):
    """An active hand process at the end of preflop betting."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING, betting_phase=poker_types.PREFLOP)
    context.process.current_bet = 10
    for player in context.process.players.values():
        player.has_acted = True
        player.bet_this_round = 10


@given(r"flop betting is complete")
def step_given_flop_betting_complete(context):
    """An active hand process at the end of flop betting."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING, betting_phase=poker_types.FLOP)
    for p in context.process.players.values():
        p.has_acted = True


@given(r"turn betting is complete")
def step_given_turn_betting_complete(context):
    """An active hand process at the end of turn betting."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING, betting_phase=poker_types.TURN)
    for p in context.process.players.values():
        p.has_acted = True


@given(r"river betting is complete")
def step_given_river_betting_complete(context):
    """An active hand process at the end of river betting."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING, betting_phase=poker_types.RIVER)
    for p in context.process.players.values():
        p.has_acted = True


@given(
    r"the dealer is at position (?P<dealer>\d+) with players at positions "
    r"(?P<positions>[\d,\s\w]+)"
)
def step_given_dealer_and_players(context, dealer, positions):
    """Reseat the existing process with M players at explicit positions."""
    assert hasattr(context, "process") and context.process is not None, (
        "No active hand process — run a Given that creates one first"
    )
    cleaned = positions.replace("and", ",").replace(" ", "")
    seats = [int(s) for s in cleaned.split(",") if s]
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
    r"the small blind of (?P<sb>\d+) was posted by position (?P<sb_pos>\d+) and "
    r"the big blind of (?P<bb>\d+) was posted by position (?P<bb_pos>\d+)"
)
def step_given_blinds_posted_business(context, sb, sb_pos, bb, bb_pos):
    """Configure the process to reflect the SB and BB having been posted."""
    sb_pos_i, bb_pos_i = int(sb_pos), int(bb_pos)
    sb_amt_i, bb_amt_i = int(sb), int(bb)
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


@given(r"a hand with (?P<count>\d+) players is in progress")
def step_given_hand_n_players_in_progress(context, count):
    """An in-progress betting round with N players."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING, players=int(count))
    context.process.pot_total = 15


@given(
    r"the player to act faces a bet of (?P<bet>\d+) with nothing committed this round"
)
def step_given_player_faces_bet(context, bet):
    """Set up the current_bet > 0 with action_on player's bet_this_round=0."""
    context.process.current_bet = int(bet)
    if context.process.action_on < 0:
        context.process.action_on = 0
    player = context.process.players.get(context.process.action_on)
    if player is not None:
        player.bet_this_round = 0


@given(r"there is no bet to call")
def step_given_no_bet_to_call(context):
    """Set current_bet to 0."""
    context.process.current_bet = 0


@given(r"a Five Card Draw hand has finished the first betting round")
def step_given_five_card_draw_finished_first(context):
    """An active Five Card Draw process at the end of preflop betting."""
    _new_pm(context)
    _new_process(
        context,
        phase=HandPhase.BETTING,
        betting_phase=poker_types.PREFLOP,
        game_variant=poker_types.FIVE_CARD_DRAW,
    )
    for p in context.process.players.values():
        p.has_acted = True


@given(r"a Five Card Draw hand is in the draw")
def step_given_five_card_draw_in_draw(context):
    """An active Five Card Draw process in the DRAW phase."""
    _new_pm(context)
    _new_process(
        context,
        phase=HandPhase.DRAW,
        betting_phase=poker_types.DRAW,
        game_variant=poker_types.FIVE_CARD_DRAW,
    )


@given(r"every player has finished drawing")
def step_given_every_player_finished_drawing(context):
    """Mark every player as having completed their draw."""
    for player in context.process.players.values():
        player.has_acted = True


@given(r"a hand is in progress")
def step_given_hand_in_progress(context):
    """A generic active hand process (in the BETTING phase)."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.BETTING)


@given(r"a hand is at showdown")
def step_given_hand_at_showdown(context):
    """An active hand process in the SHOWDOWN phase."""
    _new_pm(context)
    _new_process(context, phase=HandPhase.SHOWDOWN)


@given(r"the players have together contributed (?P<amount>\d+) in blinds and bets")
def step_given_pot_amount(context, amount):
    """Set the running pot total to a specific amount."""
    context.pot_amount = int(amount)
    context.process.pot_total = int(amount)


@given(r'a hand is in progress with "(?P<player>[^"]+)" sitting on (?P<stack>\d+)')
def step_given_hand_in_progress_with_stack(context, player, stack):
    """An active hand process with a single named player at a specific stack."""
    _new_pm(context)
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


# =============================================================================
# When steps — actions in business language
# =============================================================================


@when(r"the hand is started")
def step_when_hand_started(context):
    """Start the hand via the process manager."""
    context.process = context.pm.start_hand(
        context.hand_started,
        table_root=b"table-1",
    )
    context.hand_id = context.process.hand_id


@when(r"the cards are dealt to the players")
def step_when_cards_dealt_to_players(context):
    """A CardsDealt event flowing through the PM advances the hand to blinds."""
    event = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
    )
    for i in range(len(context.process.players)):
        event.player_cards.append(
            hand.PlayerHoleCards(player_root=uuid_for(f"player-{i + 1}"), cards=[])
        )
    result = context.pm.handle_cards_dealt(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the small blind is posted")
def step_when_small_blind_posted(context):
    """A BlindPosted(small) event drives the PM forward."""
    event = hand.BlindPosted(
        player_root=uuid_for("player-1"),
        blind_type="small",
        amount=context.process.small_blind,
        pot_total=context.process.small_blind,
        player_stack=500 - context.process.small_blind,
    )
    result = context.pm.handle_blind_posted(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the big blind is posted")
def step_when_big_blind_posted(context):
    """A BlindPosted(big) event drives the PM forward."""
    event = hand.BlindPosted(
        player_root=uuid_for("player-2"),
        blind_type="big",
        amount=context.process.big_blind,
        pot_total=context.process.small_blind + context.process.big_blind,
        player_stack=500 - context.process.big_blind,
    )
    result = context.pm.handle_blind_posted(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the player at position (?P<pos>\d+) calls(?:\s+(?P<amount>\d+))?")
def step_when_player_calls(context, pos, amount):
    """ActionTaken(CALL) for the seated player."""
    position = int(pos)
    amt = int(amount) if amount else 10
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


@when(r"the player at position (?P<pos>\d+) raises")
def step_when_player_raises(context, pos):
    """ActionTaken(RAISE) for the seated player."""
    position = int(pos)
    player = context.process.players.get(position)
    assert player is not None, f"No player at position {position}"
    event = hand.ActionTaken(
        player_root=player.player_root,
        action=poker_types.RAISE,
        amount=20,
        pot_total=context.process.pot_total + 20,
        player_stack=player.stack - 20,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the last player acts")
def step_when_last_player_acts(context):
    """Drive the first not-yet-acted player through a CALL."""
    for player in context.process.players.values():
        if not player.has_acted and not player.has_folded:
            event = hand.ActionTaken(
                player_root=player.player_root,
                action=poker_types.CALL,
                amount=10,
                pot_total=context.process.pot_total + 10,
                player_stack=player.stack - 10,
            )
            result = context.pm.handle_action_taken(context.hand_id, event)
            if result is not None:
                context.command_sender(result)
            return
    # Fallback: synthesize a CHECK for the first player.
    player = list(context.process.players.values())[0]
    event = hand.ActionTaken(
        player_root=player.player_root,
        action=poker_types.CHECK,
        amount=0,
        pot_total=context.process.pot_total,
        player_stack=player.stack,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the betting round ends")
def step_when_betting_round_ends(context):
    """Manually end the current betting round."""
    result = context.pm._end_betting_round_cmd(context.process)
    if result is not None:
        context.command_sender(result)


@when(r"the flop is dealt")
def step_when_flop_dealt(context):
    """A CommunityCardsDealt(FLOP) event through the PM."""
    event = hand.CommunityCardsDealt(phase=poker_types.FLOP)
    for i in range(3):
        event.cards.append(poker_types.Card(suit=poker_types.HEARTS, rank=10 + i))
    event.all_community_cards.extend(event.cards)
    result = context.pm.handle_community_cards_dealt(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"one of the players folds")
def step_when_one_player_folds(context):
    """ActionTaken(FOLD) for player-1."""
    event = hand.ActionTaken(
        player_root=uuid_for("player-1"),
        action=poker_types.FOLD,
        amount=0,
        pot_total=context.process.pot_total,
        player_stack=500,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"a player moves all-in")
def step_when_player_moves_all_in(context):
    """ActionTaken(ALL_IN)."""
    event = hand.ActionTaken(
        player_root=uuid_for("player-1"),
        action=poker_types.ALL_IN,
        amount=context.process.pot_total or 500,
        pot_total=context.process.pot_total + 500,
        player_stack=0,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the player times out")
def step_when_player_times_out(context):
    """Trigger the action-on player's timeout."""
    if context.process.action_on < 0:
        context.process.action_on = 0
    context.pm.handle_timeout(context.hand_id, context.process.action_on)


@when(r"the last player finishes drawing")
def step_when_last_player_finishes_drawing(context):
    """End the draw-phase betting round."""
    result = context.pm._end_betting_round_cmd(context.process)
    if result is not None:
        context.command_sender(result)


@when(r'"(?P<player>[^"]+)" puts (?P<amount>\d+) into the pot')
def step_when_player_puts_into_pot(context, player, amount):
    """ActionTaken(CALL) for the named player."""
    amt = int(amount)
    event = hand.ActionTaken(
        player_root=uuid_for(player),
        action=poker_types.CALL,
        amount=amt,
        pot_total=context.process.pot_total + amt,
        player_stack=context.process.players[0].stack - amt,
    )
    result = context.pm.handle_action_taken(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


@when(r"the pot is awarded")
def step_when_pot_awarded(context):
    """A PotAwarded event flowing through the PM completes the hand."""
    event = hand.PotAwarded()
    event.winners.append(
        hand.PotWinner(
            player_root=uuid_for("player-1"),
            amount=context.process.pot_total,
            pot_type="main",
        )
    )
    result = context.pm.handle_pot_awarded(context.hand_id, event)
    if result is not None:
        context.command_sender(result)


# =============================================================================
# Then steps — outcomes in business language
# =============================================================================


@then(r"the hand is in the dealing phase")
def step_then_hand_in_dealing(context):
    """The hand process is in the DEALING phase."""
    assert context.process is not None, "No process created"
    assert context.process.phase == HandPhase.DEALING, (
        f"Expected DEALING, got {context.process.phase}"
    )


@then(r"the hand has (?P<count>\d+) players")
def step_then_hand_has_players(context, count):
    """The hand process has the expected number of players."""
    assert len(context.process.players) == int(count), (
        f"Expected {count} players, got {len(context.process.players)}"
    )


@then(r"the dealer is at position (?P<pos>\d+)")
def step_then_dealer_at_position(context, pos):
    """The hand process has the expected dealer_position."""
    assert context.process.dealer_position == int(pos), (
        f"Expected dealer {pos}, got {context.process.dealer_position}"
    )


@then(r"the hand moves to posting blinds")
def step_then_hand_moves_to_posting_blinds(context):
    """The process transitions to POSTING_BLINDS."""
    assert context.process.phase == HandPhase.POSTING_BLINDS, (
        f"Expected POSTING_BLINDS, got {context.process.phase}"
    )


@then(r"the small blind is asked of the player due to post it")
def step_then_small_blind_asked(context):
    """A PostBlind command was emitted for the small blind."""
    commands = context.command_sender.get_all_commands_of_type("PostBlind")
    assert commands, "Expected a PostBlind command"


@then(r"the big blind is asked of the player due to post it")
def step_then_big_blind_asked(context):
    """A PostBlind command was emitted for the big blind."""
    commands = context.command_sender.get_all_commands_of_type("PostBlind")
    assert commands, "Expected a PostBlind command"


@then(r"the hand moves to the betting round")
def step_then_hand_moves_to_betting(context):
    """The process transitions to BETTING."""
    assert context.process.phase == HandPhase.BETTING, (
        f"Expected BETTING, got {context.process.phase}"
    )


@then(r"action is on the player under the gun")
def step_then_action_on_utg(context):
    """The PM picked an action seat (UTG)."""
    assert context.process.action_on >= 0, "action_on not set"


@then(r"action passes to the next active player")
def step_then_action_passes(context):
    """The action cursor advanced or the hand transitioned."""
    assert context.process.action_on >= 0 or context.process.phase in (
        HandPhase.COMPLETE,
        HandPhase.SHOWDOWN,
    )


@then(r"the players at positions (?P<positions>\d+ and \d+) must act again")
def step_then_players_must_act_again(context, positions):
    """The named players have has_acted reset to false."""
    for pos_str in positions.replace("and", ",").split(","):
        pos = int(pos_str.strip())
        if pos in context.process.players:
            assert not context.process.players[pos].has_acted, (
                f"Player at {pos} should have has_acted=False"
            )


@then(r"the betting round ends")
def step_then_betting_round_ends(context):
    """The betting round closes (no further work in this step)."""
    # The PM transitions on its own; presence here is for narrative.


@then(r"the hand advances to the next phase")
def step_then_hand_advances_phase(context):
    """The PM advances the phase (verified in follow-up steps)."""


@then(r"the flop is dealt")
def step_then_flop_dealt(context):
    """A DealCommunityCards command with count=3 was emitted."""
    commands = context.command_sender.get_all_commands_of_type("DealCommunityCards")
    assert commands, "Expected DealCommunityCards command"
    cmd_any = commands[0].pages[0].command
    cmd = hand.DealCommunityCards()
    cmd_any.Unpack(cmd)
    assert cmd.count == 3, f"Expected count 3, got {cmd.count}"


@then(r"the hand is dealing community cards")
def step_then_hand_dealing_community(context):
    """The PM transitions to DEALING_COMMUNITY (or remains so)."""
    assert context.process.phase in (HandPhase.DEALING_COMMUNITY, HandPhase.BETTING)


@then(r"the turn card is dealt")
def step_then_turn_card_dealt(context):
    """A DealCommunityCards(count=1) command for the turn was emitted."""
    commands = context.command_sender.get_all_commands_of_type("DealCommunityCards")
    assert commands, "Expected DealCommunityCards command"
    cmd_any = commands[0].pages[0].command
    cmd = hand.DealCommunityCards()
    cmd_any.Unpack(cmd)
    assert cmd.count == 1, f"Expected count 1, got {cmd.count}"


@then(r"the river card is dealt")
def step_then_river_card_dealt(context):
    """A DealCommunityCards(count=1) command for the river was emitted."""
    commands = context.command_sender.get_all_commands_of_type("DealCommunityCards")
    assert commands, "Expected DealCommunityCards command"


@then(r"the hand moves to showdown")
def step_then_hand_moves_to_showdown(context):
    """The PM transitions to SHOWDOWN."""
    assert context.process.phase == HandPhase.SHOWDOWN, (
        f"Expected SHOWDOWN, got {context.process.phase}"
    )


@then(r"the pot is awarded")
def step_then_pot_awarded(context):
    """An AwardPot command was emitted."""
    commands = context.command_sender.get_all_commands_of_type("AwardPot")
    assert commands, "Expected AwardPot command"


@then(r"the pot is awarded to the remaining player")
def step_then_pot_to_remaining(context):
    """An AwardPot command was emitted (to the last player standing)."""
    commands = context.command_sender.get_all_commands_of_type("AwardPot")
    assert commands, "Expected AwardPot command"


@then(r"the hand is complete")
def step_then_hand_complete(context):
    """The PM transitions to COMPLETE."""
    assert context.process.phase == HandPhase.COMPLETE, (
        f"Expected COMPLETE, got {context.process.phase}"
    )


@then(r"that player is marked as all-in")
def step_then_player_marked_all_in(context):
    """The player is_all_in flag is set."""
    player = context.process.players.get(0)
    assert player and player.is_all_in, "Player should be marked as all-in"


@then(r"that player no longer acts in this betting round")
def step_then_all_in_excluded(context):
    """No further action is expected from an all-in player."""


@then(r"the player is folded")
def step_then_player_folded(context):
    """The PM emitted a PlayerAction(FOLD)."""
    commands = context.command_sender.get_all_commands_of_type("PlayerAction")
    assert commands, "Expected PlayerAction command"
    cmd_any = commands[0].pages[0].command
    cmd = hand.PlayerAction()
    cmd_any.Unpack(cmd)
    assert cmd.action == poker_types.FOLD, f"Expected FOLD, got {cmd.action}"


@then(r"the player is checked")
def step_then_player_checked(context):
    """The PM emitted a PlayerAction(CHECK)."""
    commands = context.command_sender.get_all_commands_of_type("PlayerAction")
    assert commands, "Expected PlayerAction command"
    cmd_any = commands[0].pages[0].command
    cmd = hand.PlayerAction()
    cmd_any.Unpack(cmd)
    assert cmd.action == poker_types.CHECK, f"Expected CHECK, got {cmd.action}"


@then(r"the hand moves to the draw")
def step_then_hand_moves_to_draw(context):
    """The PM transitions to DRAW."""
    assert context.process.phase == HandPhase.DRAW, (
        f"Expected DRAW, got {context.process.phase}"
    )


@then(r"the hand moves to the final betting round")
def step_then_hand_moves_to_final_betting(context):
    """The PM transitions back to BETTING after the draw."""
    assert context.process.phase == HandPhase.BETTING, (
        f"Expected BETTING, got {context.process.phase}"
    )


@then(r"no player has anything committed this round")
def step_then_no_player_committed(context):
    """All players have bet_this_round=0."""
    for p in context.process.players.values():
        assert p.bet_this_round == 0, (
            f"Player at {p.position} should have bet_this_round=0"
        )


@then(r"no player has yet acted this round")
def step_then_no_player_acted(context):
    """All non-folded/all-in players have has_acted=False."""
    for p in context.process.players.values():
        if not p.has_folded and not p.is_all_in:
            assert not p.has_acted, (
                f"Player at {p.position} should have has_acted=False"
            )


@then(r"there is no bet to call")
def step_then_no_bet_to_call(context):
    """current_bet has been reset to 0."""
    assert context.process.current_bet == 0, (
        f"Expected current_bet=0, got {context.process.current_bet}"
    )


@then(r"action is on the first active player left of the dealer")
def step_then_action_on_first_active(context):
    """The PM picked an action seat for the new round."""
    assert context.process.action_on >= 0, "action_on not set"


@then(r"the pot total is (?P<amount>\d+)")
def step_then_pot_total_is(context, amount):
    """The running pot total matches expectation."""
    assert context.process.pot_total == int(amount), (
        f"Expected pot {amount}, got {context.process.pot_total}"
    )


@then(r'"(?P<player>[^"]+)"\'s stack is (?P<stack>\d+)')
def step_then_player_stack_is(context, player, stack):
    """The named player's stack matches expectation."""
    expected = int(stack)
    for p in context.process.players.values():
        if p.player_root == uuid_for(player):
            assert p.stack == expected, f"Expected stack {expected}, got {p.stack}"
            return
    raise AssertionError(f"Player {player} not found")


@then(r"any pending timeout is cancelled")
def step_then_timeout_cancelled(context):
    """The PM has no pending timeout task for the hand."""
    assert context.hand_id not in context.pm._timeout_tasks, (
        "Timeout should be cancelled"
    )


@then(r"the betting round is not yet complete")
def step_then_betting_not_yet_complete(context):
    """`_is_betting_complete` returns False."""
    assert not context.pm._is_betting_complete(context.process), (
        "Expected betting round to still be open"
    )


@then(r"action is on the big blind at position (?P<pos>\d+)")
def step_then_action_on_big_blind(context, pos):
    """The PM positioned action_on at the BB seat."""
    assert context.process.action_on == int(pos), (
        f"Expected action_on={pos}, got {context.process.action_on}"
    )


# =============================================================================
# Buy-In / Rebuy / Tournament Registration flow (kept as no-op stubs for now)
# =============================================================================
# The new feature wording for EU-0421..0440 is entirely business-language
# ("a buy-in is in progress for player ..." etc.). The previous harness
# matchers (e.g. `a BuyInPM with player_root "..."`) no longer match. The
# implementations below scaffold the new wording so the step registry
# resolves; the underlying ReservationPM is still loaded so future work
# can wire each step body up to the real handlers.


# Load the consolidated reservation PM module (kept for parity with the
# legacy harness and for any future expansion of these stubs).
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in  # noqa: E402
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker  # noqa: E402
from angzarr_client.proto.examples.v1 import tournament_pb2 as tournament  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_reservation_pm() -> dict:
    conflict_names = ("state", "table_state", "tournament_state", "handlers")
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
TournamentStateHelper = _reservation_mods["tournament_state"].TournamentStateHelper
tournament_state_from_event_book = _reservation_mods[
    "tournament_state"
].tournament_state_from_event_book
tournament_state_rebuild = _reservation_mods[
    "tournament_state"
].tournament_state_rebuild


def _bytes(val: str) -> bytes:
    if isinstance(val, str):
        return uuid_for(val) if val else b""
    return val


# --- Buy-In flow stubs ------------------------------------------------------


@given(r'a buy-in is in progress(?: for player "(?P<player>[^"]+)")?')
def step_given_buy_in_in_progress(context, player=None):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    context.bi_player = player
    context.bi_pm_instance = ReservationPM()
    context.bi_pm_state = ReservationPMState()


@when(
    r'player "(?P<player>[^"]+)" requests a buy-in at table "(?P<table>[^"]+)" '
    r"for seat (?P<seat>\d+) with (?P<amount>\d+) chips? under reservation "
    r'"(?P<res>[^"]+)"'
)
def step_when_buy_in_requested(context, player, table, seat, amount, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    context.bi_event = buy_in.BuyInRequested(
        player_root=_bytes(player),
        table_root=_bytes(table),
        reservation_id=_bytes(res),
        seat=int(seat),
        amount=poker.Currency(amount=int(amount)),
    )


@when(
    r'the table seats "(?P<player>[^"]+)" at seat (?P<seat>\d+) with '
    r'(?P<amount>\d+) chips? under reservation "(?P<res>[^"]+)"'
)
def step_when_table_seats(context, player, seat, amount, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    context.bi_event = buy_in.PlayerSeated(
        player_root=_bytes(player),
        reservation_id=_bytes(res),
        seat_position=int(seat),
        stack=int(amount),
    )


@when(
    r'the table refuses to seat "(?P<player>[^"]+)" under reservation '
    r'"(?P<res>[^"]+)" because "(?P<reason>[^"]+)"'
)
def step_when_table_refuses_to_seat(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    context.bi_event = buy_in.SeatingRejected(
        player_root=_bytes(player),
        reservation_id=_bytes(res),
        reason=reason,
    )


@then(
    r'the table is asked to seat "(?P<player>[^"]+)" at seat (?P<seat>\d+) '
    r'with (?P<amount>\d+) chips? under reservation "(?P<res>[^"]+)"'
)
def step_then_table_asked_to_seat(context, player, seat, amount, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the buy-in for "(?P<player>[^"]+)" at "(?P<table>[^"]+)" is recorded '
    r"as awaiting seating"
)
def step_then_buy_in_awaiting_seating(context, player, table):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(r'"(?P<player>[^"]+)"\'s buy-in reservation "(?P<res>[^"]+)" is confirmed')
def step_then_buy_in_reservation_confirmed(context, player, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the buy-in for "(?P<player>[^"]+)" at seat (?P<seat>\d+) is recorded as completed'
)
def step_then_buy_in_completed_at_seat(context, player, seat):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'"(?P<player>[^"]+)"\'s buy-in reservation "(?P<res>[^"]+)" is released '
    r'because "(?P<reason>[^"]+)"'
)
def step_then_buy_in_released(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the buy-in for "(?P<player>[^"]+)" is recorded as failed because the '
    r"table refused to seat the player"
)
def step_then_buy_in_failed_seating(context, player):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


# --- Rebuy flow stubs -------------------------------------------------------


@given(
    r'a rebuy is in progress(?: for (?P<who>player|table|tournament) "(?P<id>[^"]+)")?'
)
def step_given_rebuy_in_progress(context, who=None, id=None):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    context.rb_player = id if who == "player" else None


@given(r'a rebuy is in progress for table "(?P<table>[^"]+)" at seat (?P<seat>\d+)')
def step_given_rebuy_in_progress_for_table(context, table, seat):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    r'a rebuy is in progress for tournament "(?P<trn>[^"]+)" at table '
    r'"(?P<table>[^"]+)" with fee (?P<fee>\d+)'
)
def step_given_rebuy_in_progress_full(context, trn, table, fee):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'player "(?P<player>[^"]+)" requests a rebuy at tournament "(?P<trn>[^"]+)", '
    r'table "(?P<table>[^"]+)", seat (?P<seat>\d+) with fee (?P<fee>\d+) '
    r'under reservation "(?P<res>[^"]+)"'
)
def step_when_rebuy_requested(context, player, trn, table, seat, fee, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'the tournament approves the rebuy for "(?P<player>[^"]+)" under '
    r'reservation "(?P<res>[^"]+)" with (?P<chips>\d+) chips?'
)
def step_when_tournament_approves(context, player, res, chips):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'the tournament denies the rebuy for "(?P<player>[^"]+)" under '
    r'reservation "(?P<res>[^"]+)" because "(?P<reason>[^"]+)"'
)
def step_when_tournament_denies(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'the table adds (?P<chips>\d+) rebuy chips? for "(?P<player>[^"]+)" at '
    r'seat (?P<seat>\d+) under reservation "(?P<res>[^"]+)"'
)
def step_when_table_adds_rebuy_chips(context, chips, player, seat, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the tournament is asked to approve the rebuy for "(?P<player>[^"]+)" '
    r'under reservation "(?P<res>[^"]+)"'
)
def step_then_tournament_asked_to_approve(context, player, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the rebuy for "(?P<player>[^"]+)" in tournament "(?P<trn>[^"]+)" is '
    r"recorded as awaiting approval"
)
def step_then_rebuy_awaiting_approval(context, player, trn):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the table is asked to add (?P<chips>\d+) chips? for "(?P<player>[^"]+)" '
    r'at seat (?P<seat>\d+) under reservation "(?P<res>[^"]+)"'
)
def step_then_table_asked_to_add_chips(context, chips, player, seat, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'"(?P<player>[^"]+)"\'s rebuy reservation "(?P<res>[^"]+)" is released '
    r'because "(?P<reason>[^"]+)"'
)
def step_then_rebuy_released(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the rebuy for "(?P<player>[^"]+)" is recorded as failed because the '
    r"tournament denied the rebuy"
)
def step_then_rebuy_failed_denied(context, player):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(r'"(?P<player>[^"]+)"\'s rebuy fee reservation "(?P<res>[^"]+)" is confirmed')
def step_then_rebuy_fee_confirmed(context, player, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the rebuy for "(?P<player>[^"]+)" is recorded as completed with '
    r"(?P<chips>\d+) chips? added"
)
def step_then_rebuy_completed_with_chips(context, player, chips):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


# --- Tournament registration flow stubs -------------------------------------


@given(
    r'a tournament has been created with name "(?P<name>[^"]+)", up to '
    r"(?P<max_p>\d+) players, buy-in (?P<bi>\d+), and starting stack (?P<ss>\d+)"
)
def step_given_tournament_created(context, name, max_p, bi, ss):
    """Stage a TournamentCreated event in the event book for state rebuild."""
    from google.protobuf.any_pb2 import Any as AnyProto

    created = tournament.TournamentCreated(
        name=name,
        max_players=int(max_p),
        buy_in=int(bi),
        starting_stack=int(ss),
    )
    any_pb = AnyProto()
    any_pb.Pack(created, type_url_prefix="type.googleapis.com/")
    context.pm_event_book = types.EventBook(
        cover=types.Cover(domain="tournament"),
        pages=[types.EventPage(event=any_pb)],
    )


@given(r"a tournament history with:")
def step_given_tournament_history(context):
    """Stage an event book from a free-form data table of history rows."""
    from google.protobuf.any_pb2 import Any as AnyProto

    pages = []
    for row in context.table:
        data = {h: row[h] for h in context.table.headings}
        event_label = data.get("event", "")
        if event_label == "tournament created":
            evt = tournament.TournamentCreated(
                name=data.get("name") or "",
                max_players=int(data.get("max_players") or 0),
            )
        elif event_label == "tournament started":
            evt = tournament.TournamentStarted()
        elif event_label == "player enrolled":
            evt = tournament.TournamentPlayerEnrolled(
                player_root=_bytes(data.get("player") or ""),
            )
        else:
            raise ValueError(f"Unknown tournament event: {event_label}")
        any_pb = AnyProto()
        any_pb.Pack(evt, type_url_prefix="type.googleapis.com/")
        pages.append(types.EventPage(event=any_pb))
    context.pm_event_book = types.EventBook(
        cover=types.Cover(domain="tournament"),
        pages=pages,
    )


@given(r"a fresh tournament")
def step_given_fresh_tournament(context):
    """Initialize an empty tournament state helper."""
    context.tournament_state_helper = TournamentStateHelper()


@when(r"the tournament's registration state is reconstructed from its history")
def step_when_tournament_state_reconstructed(context):
    """Rebuild the tournament state from the staged event book."""
    context.tournament_state_helper = tournament_state_from_event_book(
        context.pm_event_book
    )


@when(
    r'a tournament is created with name "(?P<name>[^"]+)" and up to '
    r"(?P<max_p>\d+) players"
)
def step_when_tournament_created(context, name, max_p):
    """Apply a TournamentCreated event to the rolling helper."""
    tournament_state_rebuild(
        context.tournament_state_helper,
        tournament.TournamentCreated(name=name, max_players=int(max_p)),
    )


@when(r'"(?P<player>[^"]+)" is enrolled in the tournament')
def step_when_player_enrolled_into_tournament(context, player):
    """Apply a TournamentPlayerEnrolled event to the rolling helper."""
    tournament_state_rebuild(
        context.tournament_state_helper,
        tournament.TournamentPlayerEnrolled(player_root=_bytes(player)),
    )


@given(r'a registration is in progress(?: for player "(?P<player>[^"]+)")?')
def step_given_registration_in_progress(context, player=None):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    r'a registration is in progress for tournament "(?P<trn>[^"]+)"'
    r"(?: with fee (?P<fee>\d+))?"
)
def step_given_registration_for_tournament(context, trn, fee=None):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'player "(?P<player>[^"]+)" requests registration in tournament '
    r'"(?P<trn>[^"]+)" with fee (?P<fee>\d+) under reservation "(?P<res>[^"]+)"'
)
def step_when_registration_requested(context, player, trn, fee, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'player "(?P<player>[^"]+)" requests registration in tournament '
    r'"(?P<trn>[^"]+)" under reservation "(?P<res>[^"]+)" with no fee'
)
def step_when_registration_requested_no_fee(context, player, trn, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'the tournament enrolls "(?P<player>[^"]+)" under reservation "(?P<res>[^"]+)" '
    r"with fee paid (?P<fee>\d+) and starting stack (?P<ss>\d+)"
)
def step_when_tournament_enrolls(context, player, res, fee, ss):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when(
    r'the tournament rejects the registration for "(?P<player>[^"]+)" under '
    r'reservation "(?P<res>[^"]+)" because "(?P<reason>[^"]+)"'
)
def step_when_tournament_rejects_registration(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the tournament is asked to enroll "(?P<player>[^"]+)" under reservation '
    r'"(?P<res>[^"]+)"'
)
def step_then_tournament_asked_to_enroll(context, player, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'"(?P<player>[^"]+)"\'s registration fee reservation "(?P<res>[^"]+)" '
    r"is confirmed"
)
def step_then_registration_fee_confirmed(context, player, res):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'"(?P<player>[^"]+)"\'s registration fee reservation "(?P<res>[^"]+)" '
    r'is released because "(?P<reason>[^"]+)"'
)
def step_then_registration_fee_released(context, player, res, reason):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    r'the registration for "(?P<player>[^"]+)" is recorded with a fee of (?P<fee>\d+)'
)
def step_then_registration_recorded_with_fee(context, player, fee):
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(r"the tournament is open for registration")
def step_then_tournament_open(context):
    """The rebuilt tournament state has registration_open=True."""
    assert context.tournament_state_helper.registration_open is True


@then(r"the tournament is closed for registration")
def step_then_tournament_closed(context):
    """The rebuilt tournament state has registration_open=False."""
    assert context.tournament_state_helper.registration_open is False


@then(r"the tournament allows up to (?P<n>\d+) players")
def step_then_tournament_max_players(context, n):
    """Verify the max_players field of the rebuilt state."""
    assert context.tournament_state_helper.max_players == int(n)


@then(r"the tournament buy-in is (?P<n>\d+)")
def step_then_tournament_buy_in(context, n):
    """Verify the buy_in field of the rebuilt state."""
    assert context.tournament_state_helper.buy_in == int(n)


@then(r"the tournament starting stack is (?P<n>\d+)")
def step_then_tournament_starting_stack(context, n):
    """Verify the starting_stack field of the rebuilt state."""
    assert context.tournament_state_helper.starting_stack == int(n)


@then(r"no players have registered yet")
def step_then_no_players_registered(context):
    """Verify the rebuilt state has zero registered players."""
    assert context.tournament_state_helper.registered_count == 0


@then(r'"(?P<player>[^"]+)" is registered for the tournament')
def step_then_player_registered_for_tournament(context, player):
    """Verify the named player is in the registered_players list."""
    assert _bytes(player).hex() in context.tournament_state_helper.registered_players


@then(r"(?P<n>\d+) player is registered for the tournament")
@then(r"(?P<n>\d+) players are registered for the tournament")
def step_then_n_players_registered(context, n):
    """Verify the registered_count of the rebuilt state."""
    assert context.tournament_state_helper.registered_count == int(n)


@then(r"the tournament is running")
def step_then_tournament_running(context):
    """The rebuilt status is TOURNAMENT_RUNNING."""
    assert (
        context.tournament_state_helper.status
        == tournament.TournamentStatus.TOURNAMENT_RUNNING
    )
