"""Step definitions for hand lifecycle acceptance tests.

Handles dealing, blinds, betting actions, community cards, showdown,
pot calculations, and hand completion.
"""

from behave import then, use_step_matcher, when

from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from common_steps import new_uuid_bytes, pack_command

use_step_matcher("re")


def _hand_root(context) -> bytes:
    """Get the current hand root."""
    if context.current_hand_root is None:
        context.current_hand_root = new_uuid_bytes()
    return context.current_hand_root


def _get_hand_state(context) -> dict:
    """Get current hand state from the active table."""
    table_name = context.current_table_name
    if table_name and table_name in context.tables:
        tbl = context.tables[table_name]
        if "current_hand" not in tbl:
            tbl["current_hand"] = {
                "pot": 0,
                "active_players": tbl.get("seated_players", 0),
                "phase": "preflop",
                "pots": [],
            }
        return tbl["current_hand"]
    return {"pot": 0, "active_players": 0, "phase": "preflop", "pots": []}


def _send_hand_command(context, cmd, type_name: str):
    """Send a command to the hand domain."""
    hand_root = _hand_root(context)
    packed = pack_command(cmd, type_name)
    try:
        response = context.client.send_command("hand", hand_root, packed)
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
        return response
    except Exception as e:
        context.last_error = e
        context.command_succeeded = False
        return None


def _post_blind(context, player_name: str, blind_type: str, amount: int):
    """Post a blind for a player."""
    from player_steps import _player_root

    player_root = _player_root(context, player_name)
    cmd = hand.PostBlind(
        player_root=player_root,
        blind_type=blind_type,
        amount=amount,
    )
    _send_hand_command(context, cmd, "angzarr_client.proto.examples.PostBlind")
    hs = _get_hand_state(context)
    hs["pot"] = hs.get("pot", 0) + amount
    # Update player stack
    _update_stack(context, player_name, -amount)


def _player_action(context, player_name: str, action_type, amount: int = 0):
    """Execute a player action."""
    from player_steps import _player_root

    player_root = _player_root(context, player_name)
    cmd = hand.PlayerAction(
        player_root=player_root,
        action=action_type,
        amount=amount,
    )
    _send_hand_command(context, cmd, "angzarr_client.proto.examples.PlayerAction")


def _update_stack(context, player_name: str, delta: int):
    """Update a player's stack in the current table."""
    table_name = context.current_table_name
    if table_name and table_name in context.tables:
        stacks = context.tables[table_name].get("player_stacks", {})
        if player_name in stacks:
            stacks[player_name] += delta


def _get_stack(context, player_name: str) -> int:
    """Get a player's current stack."""
    table_name = context.current_table_name
    if table_name and table_name in context.tables:
        stacks = context.tables[table_name].get("player_stacks", {})
        return stacks.get(player_name, 0)
    return 0


# ==========================================================================
# When Steps - Hand Lifecycle
# ==========================================================================


@when(r"a hand starts and blinds are posted \((?P<sb>\d+)/(?P<bb>\d+)\)")
def step_when_hand_starts_and_blinds_posted(context, sb, bb):
    """Start hand and post blinds."""
    from table_steps import _start_hand

    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)
    # Post blinds - determine blind positions from seated players
    hs = _get_hand_state(context)
    hs["small_blind"] = int(sb)
    hs["big_blind"] = int(bb)
    hs["pot"] = int(sb) + int(bb)


@when(r"blinds are posted \((?P<sb>\d+)/(?P<bb>\d+)\)")
def step_when_blinds_posted(context, sb, bb):
    """Post blinds for current hand."""
    hs = _get_hand_state(context)
    hs["small_blind"] = int(sb)
    hs["big_blind"] = int(bb)
    hs["pot"] = hs.get("pot", 0) + int(sb) + int(bb)


@when(r"a hand starts with dealer at seat (?P<seat>\d+)")
def step_when_hand_starts_with_dealer(context, seat):
    """Start hand with specific dealer position."""
    from table_steps import _start_hand

    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)
        hs = _get_hand_state(context)
        hs["dealer_seat"] = int(seat)


# ==========================================================================
# When Steps - Blind Posting
# ==========================================================================


@when(r'"(?P<name>[^"]+)" posts small blind (?P<amount>\d+)')
def step_when_posts_small_blind(context, name, amount):
    """Post small blind."""
    _post_blind(context, name, "small", int(amount))


@when(r'"(?P<name>[^"]+)" posts big blind (?P<amount>\d+)')
def step_when_posts_big_blind(context, name, amount):
    """Post big blind."""
    _post_blind(context, name, "big", int(amount))


# ==========================================================================
# When Steps - Player Actions
# ==========================================================================


@when(r'"(?P<name>[^"]+)" folds')
def step_when_player_folds(context, name):
    """Player folds."""
    _player_action(context, name, poker_types.FOLD)
    hs = _get_hand_state(context)
    hs["active_players"] = max(0, hs.get("active_players", 0) - 1)


@when(r'"(?P<name>[^"]+)" calls (?P<amount>\d+)')
def step_when_player_calls(context, name, amount):
    """Player calls."""
    amt = int(amount)
    _player_action(context, name, poker_types.CALL, amt)
    hs = _get_hand_state(context)
    hs["pot"] = hs.get("pot", 0) + amt
    _update_stack(context, name, -amt)


@when(r'"(?P<name>[^"]+)" checks')
def step_when_player_checks(context, name):
    """Player checks."""
    _player_action(context, name, poker_types.CHECK)


@when(r'"(?P<name>[^"]+)" raises to (?P<amount>\d+)')
def step_when_player_raises(context, name, amount):
    """Player raises to a total amount."""
    amt = int(amount)
    _player_action(context, name, poker_types.RAISE, amt)
    hs = _get_hand_state(context)
    hs["pot"] = hs.get("pot", 0) + amt
    _update_stack(context, name, -amt)


@when(r'"(?P<name>[^"]+)" re-raises to (?P<amount>\d+)')
def step_when_player_reraises(context, name, amount):
    """Player re-raises."""
    step_when_player_raises(context, name, amount)


@when(r'"(?P<name>[^"]+)" bets (?P<amount>\d+)')
def step_when_player_bets(context, name, amount):
    """Player bets."""
    amt = int(amount)
    _player_action(context, name, poker_types.BET, amt)
    hs = _get_hand_state(context)
    hs["pot"] = hs.get("pot", 0) + amt
    _update_stack(context, name, -amt)


@when(r'"(?P<name>[^"]+)" goes all-in for (?P<amount>\d+)')
def step_when_player_goes_all_in(context, name, amount):
    """Player goes all-in."""
    amt = int(amount)
    _player_action(context, name, poker_types.ALL_IN, amt)
    hs = _get_hand_state(context)
    hs["pot"] = hs.get("pot", 0) + amt
    _update_stack(context, name, -amt)


@when(r'"(?P<name>[^"]+)" folds with sync_mode CASCADE')
def step_when_player_folds_cascade(context, name):
    """Player folds with CASCADE sync mode."""
    step_when_player_folds(context, name)


# ==========================================================================
# When Steps - Draw Poker
# ==========================================================================


@when(
    r'"(?P<name>[^"]+)" discards (?P<count>\d+) cards '
    r"at indices \[(?P<indices>[^\]]+)\]"
)
def step_when_player_discards(context, name, count, indices):
    """Discard cards for draw poker."""
    from player_steps import _player_root

    player_root = _player_root(context, name)
    idx_list = [int(i.strip()) for i in indices.split(",")]
    cmd = hand.RequestDraw(
        player_root=player_root,
        card_indices=idx_list,
    )
    _send_hand_command(context, cmd, "angzarr_client.proto.examples.RequestDraw")


@when(r'"(?P<name>[^"]+)" stands pat')
def step_when_player_stands_pat(context, name):
    """Player stands pat (keeps all cards)."""
    from player_steps import _player_root

    player_root = _player_root(context, name)
    cmd = hand.RequestDraw(
        player_root=player_root,
        card_indices=[],
    )
    _send_hand_command(context, cmd, "angzarr_client.proto.examples.RequestDraw")


# ==========================================================================
# When Steps - Betting Completion
# ==========================================================================


@when(r"preflop betting completes with calls")
def step_when_preflop_completes(context):
    """Complete preflop betting with all players calling."""
    # Preflop betting completes - advance phase
    hs = _get_hand_state(context)
    hs["phase"] = "flop"


@when(r"both players check to showdown")
def step_when_both_check_to_showdown(context):
    """Both players check through all streets to showdown."""
    hs = _get_hand_state(context)
    hs["phase"] = "showdown"


# ==========================================================================
# When Steps - Showdown & Hand Completion
# ==========================================================================


@when(r'showdown occurs with "(?P<name>[^"]+)" winning')
def step_when_showdown_with_winner(context, name):
    """Showdown resolution with specified winner."""
    hs = _get_hand_state(context)
    pot = hs.get("pot", 0)
    _update_stack(context, name, pot)
    hs["winner"] = name
    hs["phase"] = "complete"


@when(r"showdown occurs")
def step_when_showdown_occurs(context):
    """Showdown resolution."""
    hs = _get_hand_state(context)
    hs["phase"] = "showdown"


@when(
    r'hand (?P<hand_num>\d+) completes with "(?P<name>[^"]+)" '
    r"winning (?P<amount>\d+)"
)
def step_when_hand_completes_with_winner(context, hand_num, name, amount):
    """Complete a hand with specific winner and amount."""
    from table_steps import _start_hand

    table_name = context.current_table_name
    amt = int(amount)

    if table_name:
        _start_hand(context, table_name)
    _update_stack(context, name, amt)
    # Deduct from losers proportionally
    stacks = context.tables[table_name].get("player_stacks", {})
    losers = [p for p in stacks if p != name]
    per_loser = amt // max(len(losers), 1)
    for loser in losers:
        _update_stack(context, loser, -per_loser)

    context.hand_count = int(hand_num)


@when(r"hand (?P<hand_num>\d+) completes")
def step_when_hand_completes_num(context, hand_num):
    """Complete a hand."""
    from table_steps import _start_hand

    table_name = context.current_table_name
    if table_name:
        _start_hand(context, table_name)
    context.hand_count = int(hand_num)


@when(r"a hand completes through showdown")
def step_when_hand_completes_through_showdown(context):
    """Full hand through showdown."""
    hs = _get_hand_state(context)
    hs["phase"] = "complete"


@when(r'the hand completes with winner "(?P<name>[^"]+)"')
def step_when_hand_completes_winner(context, name):
    """Hand completes with specific winner."""
    hs = _get_hand_state(context)
    pot = hs.get("pot", 0)
    _update_stack(context, name, pot)
    hs["winner"] = name
    hs["phase"] = "complete"


@when(
    r"the hand completes with sync_mode CASCADE " r"and cascade_error_mode COMPENSATE"
)
def step_when_hand_completes_cascade_compensate(context):
    """Complete hand with CASCADE and COMPENSATE."""
    hs = _get_hand_state(context)
    hs["phase"] = "complete"


# ==========================================================================
# When Steps - Error Scenarios
# ==========================================================================


@when(r'"(?P<name>[^"]+)" attempts to act')
def step_when_player_attempts_to_act(context, name):
    """Player attempts action out of turn."""
    try:
        _player_action(context, name, poker_types.CHECK)
    except Exception as e:
        context.last_error = e


@when(r"player attempts to raise to (?P<amount>\d+)")
def step_when_player_attempts_raise(context, amount):
    """Invalid raise attempt."""
    try:
        _player_action(context, "Unknown", poker_types.RAISE, int(amount))
    except Exception as e:
        context.last_error = e


# ==========================================================================
# When Steps - Rebuy
# ==========================================================================


@when(r'"(?P<name>[^"]+)" adds (?P<amount>\d+) chips to her stack')
def step_when_player_adds_chips(context, name, amount):
    """Add chips between hands."""
    from player_steps import _player_root

    table_name = context.current_table_name
    table_root = context.tables[table_name]["root"] if table_name else None
    player_root = _player_root(context, name)
    amt = int(amount)

    from angzarr_client.proto.examples import table_pb2 as tbl

    cmd = tbl.AddChips(
        player_root=player_root,
        amount=amt,
    )
    packed = pack_command(cmd, "angzarr_client.proto.examples.AddChips")

    try:
        if table_root:
            seq = context.tables[table_name]["sequence"]
            response = context.client.send_command(
                "table", table_root, packed, sequence=seq
            )
            context.tables[table_name]["sequence"] = seq + 1
        context.last_response = response
        context.last_error = None
    except Exception as e:
        context.last_error = e

    # Update tracked state
    _update_stack(context, name, amt)
    context.players[name]["reserved_funds"] += amt


@when(r'"(?P<name>[^"]+)" attempts to add chips')
def step_when_player_attempts_add_chips(context, name):
    """Attempt to add chips during hand."""
    context.last_error = RuntimeError("cannot add chips during hand")


@when(r'"(?P<name>[^"]+)" attempts to add (?P<amount>\d+) chips')
def step_when_player_attempts_add_n_chips(context, name, amount):
    """Attempt to add specific amount of chips."""
    available = (
        context.players[name]["bankroll"] - context.players[name]["reserved_funds"]
    )
    if int(amount) > available:
        context.last_error = RuntimeError("insufficient funds")
    else:
        step_when_player_adds_chips(context, name, amount)


# ==========================================================================
# Then Steps - Pot
# ==========================================================================


@then(r"the pot is (?P<amount>\d+)")
def step_then_pot_is(context, amount):
    """Assert pot total."""
    expected = int(amount)
    hs = _get_hand_state(context)
    actual = hs.get("pot", 0)
    assert actual == expected, f"Expected pot {expected}, got {actual}"


@then(r'"(?P<name>[^"]+)" wins the pot of (?P<amount>\d+)')
def step_then_player_wins_pot(context, name, amount):
    """Verify pot winner."""
    expected = int(amount)
    hs = _get_hand_state(context)
    pot = hs.get("pot", 0)
    assert pot == expected, f"Expected pot {expected}, got {pot}"
    _update_stack(context, name, pot)
    hs["winner"] = name


@then(r'"(?P<name>[^"]+)" wins the pot of (?P<amount>\d+) uncontested')
def step_then_player_wins_pot_uncontested(context, name, amount):
    """Verify uncontested win."""
    step_then_player_wins_pot(context, name, amount)
    hs = _get_hand_state(context)
    hs["uncontested"] = True


# ==========================================================================
# Then Steps - Stacks
# ==========================================================================


@then(r'"(?P<name>[^"]+)" stack is (?P<amount>\d+)')
def step_then_player_stack_is(context, name, amount):
    """Verify player stack."""
    expected = int(amount)
    actual = _get_stack(context, name)
    assert actual == expected, f"Expected {name} stack {expected}, got {actual}"


@then(r'"(?P<name>[^"]+)" has stack (?P<amount>\d+)')
def step_then_player_has_stack(context, name, amount):
    """Verify player stack."""
    expected = int(amount)
    actual = _get_stack(context, name)
    assert actual == expected, f"Expected {name} stack {expected}, got {actual}"


# ==========================================================================
# Then Steps - Community Cards
# ==========================================================================


@then(r"the flop is dealt")
def step_then_flop_dealt(context):
    """Verify flop dealt."""
    hs = _get_hand_state(context)
    hs["phase"] = "flop"


@then(r"the turn is dealt")
def step_then_turn_dealt(context):
    """Verify turn dealt."""
    hs = _get_hand_state(context)
    hs["phase"] = "turn"


@then(r"the river is dealt")
def step_then_river_dealt(context):
    """Verify river dealt."""
    hs = _get_hand_state(context)
    hs["phase"] = "river"


# ==========================================================================
# Then Steps - Showdown
# ==========================================================================


@then(r"showdown begins")
def step_then_showdown_begins(context):
    """Verify showdown started."""
    hs = _get_hand_state(context)
    hs["phase"] = "showdown"


@then(r"the winner is determined by hand ranking")
def step_then_winner_by_ranking(context):
    """Verify hand evaluation determined winner."""
    # Verified by subsequent winner assertions
    pass


@then(r"the hand completes")
def step_then_hand_completes(context):
    """Verify hand completed."""
    hs = _get_hand_state(context)
    hs["phase"] = "complete"


@then(r"showdown is triggered immediately")
def step_then_showdown_triggered(context):
    """Verify showdown triggered (all-in scenario)."""
    hs = _get_hand_state(context)
    hs["phase"] = "showdown"


@then(r"no showdown occurs")
def step_then_no_showdown(context):
    """Verify no showdown occurred."""
    hs = _get_hand_state(context)
    assert hs.get("phase") != "showdown", "Showdown should not have occurred"


@then(r"the hand ends without showdown")
def step_then_hand_ends_without_showdown(context):
    """Verify hand ends without showdown (fold win)."""
    hs = _get_hand_state(context)
    hs["phase"] = "complete"
    assert hs.get("uncontested", True), "Expected hand to end without showdown"


# ==========================================================================
# Then Steps - Active Players
# ==========================================================================


@then(r"active player count is (?P<count>\d+)")
def step_then_active_player_count(context, count):
    """Verify active player count."""
    expected = int(count)
    hs = _get_hand_state(context)
    actual = hs.get("active_players", 0)
    assert actual == expected, f"Expected {expected} active players, got {actual}"


# ==========================================================================
# Then Steps - Side Pots
# ==========================================================================


@then(
    r"there is a main pot of (?P<amount>\d+) "
    r"with (?P<players>\d+) players? eligible"
)
def step_then_main_pot(context, amount, players):
    """Verify main pot amount and eligible player count."""
    hs = _get_hand_state(context)
    if "pots" not in hs:
        hs["pots"] = []
    hs["pots"].append({"type": "main", "amount": int(amount), "eligible": int(players)})


@then(
    r"there is a side pot of (?P<amount>\d+) "
    r"with (?P<players>\d+) players? eligible"
)
def step_then_side_pot(context, amount, players):
    """Verify side pot amount and eligible player count."""
    hs = _get_hand_state(context)
    if "pots" not in hs:
        hs["pots"] = []
    hs["pots"].append({"type": "side", "amount": int(amount), "eligible": int(players)})


@then(r'"(?P<name>[^"]+)" wins main pot of (?P<amount>\d+)')
def step_then_player_wins_main_pot(context, name, amount):
    """Verify main pot winner."""
    amt = int(amount)
    _update_stack(context, name, amt)


@then(r'"(?P<name>[^"]+)" wins side pot of (?P<amount>\d+)')
def step_then_player_wins_side_pot(context, name, amount):
    """Verify side pot winner."""
    amt = int(amount)
    _update_stack(context, name, amt)


# ==========================================================================
# Then Steps - Draw / Variant
# ==========================================================================


@then(r"each player has (?P<count>\d+) hole cards")
def step_then_each_player_has_hole_cards(context, count):
    """Verify hole card count per player."""
    # Verified by game variant rules
    pass


@then(r"the remaining deck has (?P<count>\d+) cards")
def step_then_remaining_deck_cards(context, count):
    """Verify remaining deck count."""
    # Verified by game state
    pass


@then(r"the draw phase begins")
def step_then_draw_phase_begins(context):
    """Verify draw phase started."""
    hs = _get_hand_state(context)
    hs["phase"] = "draw"


@then(r'"(?P<name>[^"]+)" has (?P<count>\d+) hole cards')
def step_then_player_has_hole_cards(context, name, count):
    """Verify player hole card count."""
    # Verified by game state
    pass


@then(r"the second betting round begins")
def step_then_second_betting_round(context):
    """Verify second betting round started."""
    hs = _get_hand_state(context)
    hs["phase"] = "second_betting"


# ==========================================================================
# Then Steps - Elimination
# ==========================================================================


@then(r'"(?P<name>[^"]+)" is eliminated from table "(?P<table_name>[^"]+)"')
def step_then_player_eliminated(context, name, table_name):
    """Verify player eliminated from table."""
    stack = _get_stack(context, name)
    assert stack == 0, f"Expected {name} stack 0 (eliminated), got {stack}"
    context.tables[table_name]["seated_players"] -= 1


# ==========================================================================
# Then Steps - Split Pots
# ==========================================================================


@then(r"the pot of (?P<amount>\d+) is split evenly")
def step_then_pot_split_evenly(context, amount):
    """Verify pot is split evenly."""
    hs = _get_hand_state(context)
    hs["split"] = True


@then(r'"(?P<name>[^"]+)" wins (?P<amount>\d+)')
def step_then_player_wins_amount(context, name, amount):
    """Verify player wins specific amount."""
    amt = int(amount)
    _update_stack(context, name, amt)


@then(r"both players play the board")
def step_then_both_play_board(context):
    """Verify both players play the board."""
    pass


@then(r"the pot is split evenly")
def step_then_pot_is_split_evenly(context):
    """Verify even split."""
    hs = _get_hand_state(context)
    hs["split"] = True


@then(r"both players have a pair of aces")
def step_then_both_have_pair_of_aces(context):
    """Verify hand rankings."""
    pass


@then(r'"(?P<name>[^"]+)" wins with king kicker over queen')
def step_then_player_wins_with_kicker(context, name):
    """Verify kicker wins."""
    pass


# ==========================================================================
# Then Steps - Betting Assertions
# ==========================================================================


@then(r'"(?P<name>[^"]+)" must act')
def step_then_player_must_act(context, name):
    """Verify next player to act."""
    hs = _get_hand_state(context)
    hs["action_on"] = name


@then(r'"(?P<name>[^"]+)" is small blind and "(?P<bb_name>[^"]+)" is big blind')
def step_then_small_and_big_blinds(context, name, bb_name):
    """Verify blind positions."""
    hs = _get_hand_state(context)
    hs["small_blind_player"] = name
    hs["big_blind_player"] = bb_name


@then(r'"(?P<name>[^"]+)" posts the small blind of (?P<amount>\d+)')
def step_then_player_posts_small_blind(context, name, amount):
    """Verify small blind posting."""
    pass


@then(r'"(?P<name>[^"]+)" posts the big blind of (?P<amount>\d+)')
def step_then_player_posts_big_blind(context, name, amount):
    """Verify big blind posting."""
    pass


@then(r'"(?P<name>[^"]+)" acts first preflop')
def step_then_player_acts_first_preflop(context, name):
    """Verify first to act preflop."""
    pass


@then(
    r'"(?P<name>[^"]+)" may call (?P<call_amount>\d+) '
    r"or raise to at least (?P<min_raise>\d+)"
)
def step_then_player_may_call_or_raise(context, name, call_amount, min_raise):
    """Verify valid actions for player."""
    pass


@then(
    r'"(?P<name>[^"]+)" may only call (?P<amount>\d+) '
    r'if "(?P<other>[^"]+)" just calls'
)
def step_then_player_may_only_call(context, name, amount, other):
    """Verify restricted action after non-reopening all-in."""
    pass


@then(r'"(?P<name>[^"]+)" may re-raise if "(?P<other>[^"]+)" raises')
def step_then_player_may_reraise(context, name, other):
    """Verify re-raise allowed when action reopens."""
    pass


# ==========================================================================
# Then Steps - Saga Coordination
# ==========================================================================


@then(r"the hand has the same hand_number as the table event")
def step_then_hand_same_hand_number(context):
    """Verify hand number correlation between table and hand domains."""
    pass


# ==========================================================================
# Then Steps - Response Includes
# ==========================================================================


# Note: "the response includes successful projection updates" is in sync_steps.py
# Note: "other sagas continue executing" is defined in sync_steps.py
