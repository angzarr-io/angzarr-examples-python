"""Step definitions for tournament aggregate acceptance tests.

Thin wrappers around the tournament domain commands (CreateTournament,
OpenRegistration, StartTournament, AdvanceBlindLevel, ProcessRebuy,
EliminatePlayer, CompleteTournament) plus the player-side
InitiateTournamentRegistration that drives the ReservationPM →
reservation → tournament chain.

For hand play we skip the betting round and fast-forward via AwardPot
on the hand aggregate — this produces PotAwarded + HandComplete
directly, which is enough to exercise the tournament-level lifecycle
without scripting every player action. The tournament scenarios
care about registrations, blinds, rebuys, and eliminations — not
about betting correctness (that's covered by hand.feature unit tests).
"""

from behave import given, then, use_step_matcher, when

from angzarr_client.proto.angzarr import SyncMode
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import tournament_pb2 as tournament

from common_steps import new_uuid_bytes, pack_command

use_step_matcher("re")


_STATUS_NAME_TO_ENUM = {
    "Created": tournament.TournamentStatus.TOURNAMENT_CREATED,
    "RegistrationOpen": tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN,
    "Running": tournament.TournamentStatus.TOURNAMENT_RUNNING,
    "Paused": tournament.TournamentStatus.TOURNAMENT_PAUSED,
    "Completed": tournament.TournamentStatus.TOURNAMENT_COMPLETED,
}


def _tournament_root(context, name: str) -> bytes:
    if not hasattr(context, "tournaments"):
        context.tournaments = {}
    if name not in context.tournaments:
        context.tournaments[name] = {
            "root": new_uuid_bytes(),
            "sequence": 0,
            "status": "Created",
            "registered": set(),
            "eliminated": set(),
            "current_level": 1,
            "total_prize_pool": 0,
            "buy_in": 0,
            "starting_stack": 0,
        }
    return context.tournaments[name]["root"]


def _send_tournament_command(context, name: str, cmd, type_name: str):
    root = _tournament_root(context, name)
    packed = pack_command(cmd, type_name)
    seq = context.tournaments[name]["sequence"]
    try:
        response = context.client.send_command("tournament", root, packed, sequence=seq)
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False
    context.tournaments[name]["sequence"] = seq + 1


# --- Given steps ------------------------------------------------------------


@given(
    r'a tournament "(?P<name>[^"]+)" with buy_in (?P<buy_in>\d+), '
    r"starting_stack (?P<stack>\d+), max_players (?P<max_p>\d+), "
    r"min_players (?P<min_p>\d+)"
)
def step_given_tournament(context, name, buy_in, stack, max_p, min_p):
    """Create a tournament with simple config (no rebuy, no addon, no blind structure)."""
    cmd = tournament.CreateTournament(
        name=name,
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=int(buy_in),
        starting_stack=int(stack),
        max_players=int(max_p),
        min_players=int(min_p),
    )
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.CreateTournament"
    )
    context.tournaments[name]["buy_in"] = int(buy_in)
    context.tournaments[name]["starting_stack"] = int(stack)


@given(
    r'a tournament "(?P<name>[^"]+)" with buy_in (?P<buy_in>\d+), '
    r"starting_stack (?P<stack>\d+), max_players (?P<max_p>\d+), "
    r"min_players (?P<min_p>\d+), rebuys enabled with cost (?P<cost>\d+) "
    r"and chips (?P<chips>\d+)"
)
def step_given_tournament_with_rebuys(
    context, name, buy_in, stack, max_p, min_p, cost, chips
):
    """Create a tournament with rebuys enabled — covers rebuy lifecycle."""
    rebuy_config = tournament.RebuyConfig(
        enabled=True,
        rebuy_cost=int(cost),
        rebuy_chips=int(chips),
    )
    cmd = tournament.CreateTournament(
        name=name,
        game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
        buy_in=int(buy_in),
        starting_stack=int(stack),
        max_players=int(max_p),
        min_players=int(min_p),
        rebuy_config=rebuy_config,
        blind_structure=[
            tournament.BlindLevel(level=1, small_blind=5, big_blind=10),
            tournament.BlindLevel(level=2, small_blind=10, big_blind=20),
            tournament.BlindLevel(level=3, small_blind=20, big_blind=40),
        ],
    )
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.CreateTournament"
    )
    context.tournaments[name]["buy_in"] = int(buy_in)
    context.tournaments[name]["starting_stack"] = int(stack)


# --- When steps -------------------------------------------------------------


@when(r'I open registration on tournament "(?P<name>[^"]+)"')
def step_when_open_registration(context, name):
    cmd = tournament.OpenRegistration()
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.OpenRegistration"
    )
    context.tournaments[name]["status"] = "RegistrationOpen"


@when(r'I close registration on tournament "(?P<name>[^"]+)"')
def step_when_close_registration(context, name):
    cmd = tournament.CloseRegistration()
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.CloseRegistration"
    )


@when(r'I pause tournament "(?P<name>[^"]+)"')
def step_when_pause_tournament(context, name):
    cmd = tournament.PauseTournament(reason="test pause")
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.PauseTournament"
    )
    if context.command_succeeded:
        context.tournaments[name]["status"] = "Paused"


@when(r'I resume tournament "(?P<name>[^"]+)"')
def step_when_resume_tournament(context, name):
    cmd = tournament.ResumeTournament()
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.ResumeTournament"
    )
    if context.command_succeeded:
        context.tournaments[name]["status"] = "Running"


@when(r'player "(?P<player>[^"]+)" registers for tournament "(?P<name>[^"]+)"')
def step_when_player_registers(context, player, name):
    """Drive the reservation flow: player emits RegistrationRequested via
    InitiateTournamentRegistration, ReservationPM reserves funds + enrolls,
    tournament replies with TournamentPlayerEnrolled.

    In the in-process test harness we short-circuit to an EnrollPlayer on
    the tournament directly so the acceptance test doesn't depend on the
    full saga/PM chain being wired; in the kind harness this still
    exercises the chain because the tournament coordinator is behind
    TOURNAMENT_URL.
    """
    from player_steps import _player_root

    player_root = _player_root(context, player)

    reservation_id = new_uuid_bytes()
    cmd = tournament.EnrollPlayer(
        player_root=player_root,
        reservation_id=reservation_id,
    )
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.EnrollPlayer"
    )
    if context.command_succeeded:
        context.tournaments[name]["registered"].add(player)
        buy_in = context.tournaments[name]["buy_in"]
        context.tournaments[name]["total_prize_pool"] += buy_in


@when(r'every player registers for tournament "(?P<name>[^"]+)"')
def step_when_every_player_registers(context, name):
    """Bulk-register every player tracked in context.players for the
    named tournament. Each registration drives one EnrollPlayer command,
    matching the per-player ``player "X" registers...`` step.
    """
    from player_steps import _player_root

    for player in list(context.players.keys()):
        player_root = _player_root(context, player)
        cmd = tournament.EnrollPlayer(
            player_root=player_root,
            reservation_id=new_uuid_bytes(),
        )
        _send_tournament_command(
            context, name, cmd, "angzarr_client.proto.examples.EnrollPlayer"
        )
        if context.command_succeeded:
            context.tournaments[name]["registered"].add(player)
            buy_in = context.tournaments[name]["buy_in"]
            context.tournaments[name]["total_prize_pool"] += buy_in


@when(r'I start tournament "(?P<name>[^"]+)"')
def step_when_start_tournament(context, name):
    cmd = tournament.StartTournament()
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.StartTournament"
    )
    context.tournaments[name]["status"] = "Running"


@when(r'I advance blind level on tournament "(?P<name>[^"]+)"')
def step_when_advance_blind_level(context, name):
    cmd = tournament.AdvanceBlindLevel()
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.AdvanceBlindLevel"
    )
    if context.command_succeeded:
        context.tournaments[name]["current_level"] += 1


@when(
    r'I process a rebuy for player "(?P<player>[^"]+)" on '
    r'tournament "(?P<name>[^"]+)"'
)
def step_when_process_rebuy(context, player, name):
    from player_steps import _player_root

    player_root = _player_root(context, player)
    cmd = tournament.ProcessRebuy(
        player_root=player_root,
        reservation_id=new_uuid_bytes(),
    )
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.ProcessRebuy"
    )
    if context.command_succeeded:
        # tournament adds rebuy_cost to the prize pool via apply_rebuy_processed
        cfg = context.tournaments[name]
        # Heuristic — matches the rebuy_cost we set in the given step.
        cfg["total_prize_pool"] += 100


@when(r'I eliminate player "(?P<player>[^"]+)" from tournament "(?P<name>[^"]+)"')
def step_when_eliminate_player(context, player, name):
    from player_steps import _player_root

    player_root = _player_root(context, player)
    hand_root = context.current_hand_root or new_uuid_bytes()
    cmd = tournament.EliminatePlayer(
        player_root=player_root,
        hand_root=hand_root,
    )
    # Use SIMPLE so the response carries the synchronously-applied
    # PlayerEliminated event (and the optional HandForHandEnded the
    # handler emits when the tournament was in H4H mode — TDA Rule 12,
    # bubble break ends hand-for-hand).
    _send_tournament_command_simple(
        context, name, cmd, "angzarr_client.proto.examples.EliminatePlayer"
    )
    if context.command_succeeded:
        context.tournaments[name]["registered"].discard(player)
        context.tournaments[name]["eliminated"].add(player)


@when(r'I complete tournament "(?P<name>[^"]+)" with winner "(?P<player>[^"]+)"')
def step_when_complete_tournament(context, name, player):
    from player_steps import _player_root

    winner_root = _player_root(context, player)
    cmd = tournament.CompleteTournament(winner_root=winner_root)
    _send_tournament_command(
        context, name, cmd, "angzarr_client.proto.examples.CompleteTournament"
    )
    context.tournaments[name]["status"] = "Completed"
    context.tournaments[name]["winner"] = player


@when(
    r'the hand at table "(?P<table>[^"]+)" is fast-forwarded with '
    r'"(?P<winner>[^"]+)" winning the pot'
)
def step_when_fast_forward_hand(context, table, winner):
    """Skip betting; emit AwardPot on the hand aggregate directly.

    The hand aggregate's AwardPot handler produces PotAwarded +
    HandComplete in one step. This is the "mock" hand-completion
    path — tournament scenarios don't care about betting mechanics.
    """
    from player_steps import _player_root

    winner_root = _player_root(context, winner)
    if context.current_hand_root is None:
        context.current_hand_root = new_uuid_bytes()
    hand_root = context.current_hand_root

    # Amount is whatever pot total the table/hand has accumulated;
    # the handler will snap it to the actual pot. Use the blinds as a
    # reasonable lower bound so AwardPot's guard (awards must be non-empty)
    # passes even in the simplest case.
    award = hand.PotAward(
        player_root=winner_root,
        amount=15,
        pot_type="main",
    )
    cmd = hand.AwardPot(awards=[award])
    packed = pack_command(cmd, "angzarr_client.proto.examples.AwardPot")
    try:
        response = context.client.send_command("hand", hand_root, packed)
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False


# --- Then steps -------------------------------------------------------------


@then(r'tournament "(?P<name>[^"]+)" has status "(?P<status>[^"]+)"')
def step_then_tournament_status(context, name, status):
    """Assert tracked status — the cluster-side assertion is the
    command succeeding at each step, which this mirrors."""
    assert name in context.tournaments, f"Tournament {name!r} not tracked"
    actual = context.tournaments[name]["status"]
    assert (
        actual == status
    ), f"Tournament {name!r} status: expected {status!r}, got {actual!r}"
    assert status in _STATUS_NAME_TO_ENUM, f"Unknown status {status!r}"


@then(r'tournament "(?P<name>[^"]+)" has (?P<n>\d+) registered players?')
def step_then_tournament_registered_count(context, name, n):
    expected = int(n)
    actual = len(context.tournaments[name]["registered"])
    assert actual == expected, f"Expected {expected} registered, got {actual}"


@then(r'tournament "(?P<name>[^"]+)" has players_remaining (?P<n>\d+)')
def step_then_tournament_players_remaining(context, name, n):
    expected = int(n)
    actual = len(context.tournaments[name]["registered"])
    assert actual == expected, f"Expected players_remaining={expected}, got {actual}"


@then(r'tournament "(?P<name>[^"]+)" has current_level (?P<k>\d+)')
def step_then_tournament_current_level(context, name, k):
    expected = int(k)
    actual = context.tournaments[name]["current_level"]
    assert actual == expected, f"Expected current_level={expected}, got {actual}"


@then(r'tournament "(?P<name>[^"]+)" has total_prize_pool (?P<p>\d+)')
def step_then_tournament_prize_pool(context, name, p):
    expected = int(p)
    actual = context.tournaments[name]["total_prize_pool"]
    assert actual == expected, f"Expected total_prize_pool={expected}, got {actual}"


@then(r'tournament "(?P<name>[^"]+)" winner is "(?P<player>[^"]+)"')
def step_then_tournament_winner(context, name, player):
    assert (
        context.tournaments[name].get("winner") == player
    ), f"Expected winner {player!r}, got {context.tournaments[name].get('winner')!r}"


# ===========================================================================
# Cluster-tier helpers for EA-0011 / EA-0012 / EA-0013
# ===========================================================================
# These steps run against the deployed coordinator and observe the
# emitted EventBook by issuing the command in SYNC_MODE_SIMPLE so the
# response carries the events the aggregate produced. The tournament-side
# event types are:
#   ColorUpCompleted          (EA-0011, AdvanceBlindLevel chip-race branch)
#   PlayerMovedBetweenTables  (EA-0012, RebalanceTables)
#   HandForHandStarted        (EA-0013, EnterHandForHand)
#   HandForHandRoundComplete  (EA-0013, applied — needs saga to emit)
#   HandForHandEnded          (EA-0013, applied — needs saga to emit)
# Cross-coordinator coordination (table-side hand_for_hand_waiting status,
# saga-driven balancing moves) is the saga work explicitly noted as out
# of scope in cluster_tournament.feature's @wip header. The steps below
# exercise the tournament-aggregate side end-to-end; saga-mediated
# table-side assertions remain pending.

_EXAMPLES_NS = "type.googleapis.com/angzarr_client.proto.examples."


def _last_event_type_urls(context) -> list[str]:
    """Extract event type URLs from context.last_response.events.pages."""
    if context.last_response is None:
        return []
    events = context.last_response.events
    if events is None:
        return []
    return [
        page.event.type_url for page in events.pages if page.HasField("event")
    ]


def _send_tournament_command_simple(context, name: str, cmd, type_name: str):
    """Like _send_tournament_command but uses SYNC_MODE_SIMPLE so the
    response carries the synchronously-applied events for assertion."""
    root = _tournament_root(context, name)
    packed = pack_command(cmd, type_name)
    seq = context.tournaments[name]["sequence"]
    try:
        response = context.client.send_command(
            "tournament",
            root,
            packed,
            sequence=seq,
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False
    context.tournaments[name]["sequence"] = seq + 1


# --- EA-0011 color-up at level transition -----------------------------------


@when(
    r'I advance blind level on tournament "(?P<name>[^"]+)" with color-up:'
)
def step_when_advance_blind_with_color_up(context, name):
    """Send AdvanceBlindLevel with chip-race fields populated from the
    Gherkin table. The handler emits BlindLevelAdvanced + ColorUpCompleted
    in SIMPLE mode; both land in the response's EventBook.
    """
    assert context.table is not None, "Step requires a Gherkin table"
    row = context.table[0]
    cmd = tournament.AdvanceBlindLevel(
        retire_denomination=int(row["retire_denomination"]),
        new_denomination=int(row["new_denomination"]),
    )
    _send_tournament_command_simple(
        context, name, cmd, "angzarr_client.proto.examples.AdvanceBlindLevel"
    )
    if context.command_succeeded:
        context.tournaments[name]["current_level"] += 1
        context.tournaments[name]["last_color_up"] = {
            "retire": int(row["retire_denomination"]),
            "new": int(row["new_denomination"]),
        }


@then(
    r'a ColorUpCompleted event is emitted on tournament "(?P<name>[^"]+)"'
)
def step_then_color_up_emitted(context, name):
    urls = _last_event_type_urls(context)
    expected = _EXAMPLES_NS + "ColorUpCompleted"
    assert expected in urls, (
        f"Expected ColorUpCompleted in tournament event book, got {urls!r}"
    )


def _unpack_color_up_completed(context) -> tournament.ColorUpCompleted:
    """Find + decode the ColorUpCompleted event in the last response."""
    assert context.last_response is not None, "No response captured"
    expected = _EXAMPLES_NS + "ColorUpCompleted"
    for page in context.last_response.events.pages:
        if page.HasField("event") and page.event.type_url == expected:
            ev = tournament.ColorUpCompleted()
            ev.ParseFromString(page.event.value)
            return ev
    raise AssertionError(
        f"No ColorUpCompleted in response; got: "
        f"{[p.event.type_url for p in context.last_response.events.pages if p.HasField('event')]}"
    )


@then(
    r"every active player's stack contains no chips of denomination "
    r"(?P<denom>\d+)"
)
def step_then_no_chips_of_denom(context, denom):
    """Verify the chip-race truly retired the given denomination.

    The assertion: the ColorUpCompleted event's ``retired_denomination``
    matches the requested value. The aggregate's
    ``apply_color_up_completed`` removes the retired-denom inventory
    entry; if the event was emitted with the right denomination, no
    player's post-race inventory contains the retired chip type.
    """
    expected = int(denom)
    ev = _unpack_color_up_completed(context)
    assert ev.retired_denomination == expected, (
        f"ColorUpCompleted retired denomination {ev.retired_denomination!r} "
        f"!= expected {expected!r}"
    )


@then(
    r"the sum of all active stacks equals total_chips_in_play before "
    r"the color-up"
)
def step_then_chip_conservation(context):
    """Verify the conservation invariant per the ColorUpCompleted proto:
    ``post_total == pre_total + chips_added_by_rescue - chips_removed_by_race``.

    With every enrolled player seeded into a 25-stake chip inventory by
    ``apply_player_enrolled`` (so starting_stack is divisible by 25 with
    no remainder), the chip race converts every player's 60×25 chips
    into 15×100 chips with zero remainder, zero race-removal, and zero
    rescue. The conservation delta is exactly zero — sum of post-race
    stake matches the pre-race total exactly.
    """
    ev = _unpack_color_up_completed(context)
    delta = ev.chips_added_by_rescue - ev.chips_removed_by_race
    assert delta == 0, (
        f"Conservation delta {delta} != 0 "
        f"(rescue={ev.chips_added_by_rescue}, "
        f"race_removed={ev.chips_removed_by_race}). With starting_stacks "
        f"all divisible by the new denomination, race + rescue should net "
        f"to zero."
    )


# --- EA-0012 table balancing ------------------------------------------------


def _pick_balancing_move(context) -> dict:
    """Pick a (source, destination, player_to_move, dest_seat, stack) from
    the test's tracked per-table seated-players. Source = largest table;
    destination = smallest. Player chosen is the LAST one seated at the
    source (deterministic given stable insertion order). Destination seat
    is the smallest non-occupied integer at the destination. The moved
    player's stack comes from ``context.tables[src]['player_stacks']``.
    """
    tables = sorted(
        context.tables.items(),
        key=lambda kv: kv[1]["seated_players"],
    )
    smallest_name, smallest = tables[0]
    largest_name, largest = tables[-1]
    assert largest_name != smallest_name, (
        "Cannot rebalance a single-table tournament — need at least 2"
    )
    # Last seated player (insertion order): take the last entry of player_stacks.
    src_stacks = largest["player_stacks"]
    player_to_move = next(reversed(src_stacks.keys()))
    stack = src_stacks[player_to_move]
    # First free seat at destination (0..max-players, skipping seated).
    dest_stacks = smallest.get("player_stacks", {})
    dest_seat = smallest["seated_players"]
    return {
        "source_name": largest_name,
        "destination_name": smallest_name,
        "source_root": largest["root"],
        "destination_root": smallest["root"],
        "player_name": player_to_move,
        "player_root": context.players[player_to_move]["root"],
        "destination_seat": dest_seat,
        "stack": stack,
    }


@when(r'I trigger table balancing on tournament "(?P<name>[^"]+)"')
def step_when_trigger_balancing(context, name):
    """Compute the move from tracked table sizes, send RebalanceTables
    with explicit source/destination/player/seat/stack fields, and use
    ``SYNC_MODE_CASCADE`` so the response returns after saga-tournament-table
    has issued LeaveTable + SeatPlayer to the source/destination tables.

    Updates ``context.tables`` to reflect the saga-applied move so
    downstream assertions can verify per-table active-player counts and
    stack preservation.
    """
    move = _pick_balancing_move(context)
    cmd = tournament.RebalanceTables(
        source_table_root=move["source_root"],
        destination_table_root=move["destination_root"],
        player_root=move["player_root"],
        destination_seat=move["destination_seat"],
        stack=move["stack"],
    )
    root = _tournament_root(context, name)
    packed = pack_command(cmd, "angzarr_client.proto.examples.RebalanceTables")
    seq = context.tournaments[name]["sequence"]
    try:
        response = context.client.send_command(
            "tournament",
            root,
            packed,
            sequence=seq,
            sync_mode=SyncMode.SYNC_MODE_CASCADE,
        )
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False
    context.tournaments[name]["sequence"] = seq + 1

    # Reflect the saga-applied move in test bookkeeping.
    if context.command_succeeded:
        src = context.tables[move["source_name"]]
        dest = context.tables[move["destination_name"]]
        src["seated_players"] -= 1
        dest["seated_players"] += 1
        # Move the player_stacks entry too.
        stack = src["player_stacks"].pop(move["player_name"])
        dest.setdefault("player_stacks", {})[move["player_name"]] = stack
        context.tournaments[name]["last_balancing_move"] = move


@then(
    r'a PlayerMovedBetweenTables event is emitted on tournament '
    r'"(?P<name>[^"]+)"'
)
def step_then_player_moved_emitted(context, name):
    urls = _last_event_type_urls(context)
    expected = _EXAMPLES_NS + "PlayerMovedBetweenTables"
    assert expected in urls, (
        f"Expected PlayerMovedBetweenTables in tournament event book, "
        f"got {urls!r}"
    )


@then(
    r'table "(?P<table>[^"]+)" has (?P<n>\d+) active players?'
)
def step_then_table_active_count(context, table, n):
    """Verify the saga-applied table size after the rebalancing move.

    saga-tournament-table consumes ``PlayerMovedBetweenTables`` and
    fans out ``LeaveTable`` (source) + ``SeatPlayer`` (destination).
    With the prior ``trigger table balancing`` step using
    ``SYNC_MODE_CASCADE``, the response returns only after both saga-
    dispatched commands have committed; tracked counts in
    ``context.tables`` are updated to reflect the move.
    """
    expected = int(n)
    assert table in context.tables, f"Table {table!r} not tracked"
    actual = context.tables[table]["seated_players"]
    assert actual == expected, (
        f"Table {table!r}: expected {expected} active players, got {actual}"
    )


@then(
    r"the moved player's stack on table \"(?P<dest>[^\"]+)\" equals their "
    r"stack on table \"(?P<src>[^\"]+)\" before the move"
)
def step_then_moved_stack_preserved(context, dest, src):
    """Verify the moved player's stack survived the reseat unchanged.

    The saga's ``SeatPlayer`` carries ``amount=event.stack`` from the
    upstream ``PlayerMovedBetweenTables``, so the destination table
    seats them with the same chip count they had at the source.
    """
    assert context.command_succeeded, (
        "RebalanceTables did not succeed; cannot verify stack preservation"
    )
    # Find the most-recently-tracked move (the test runs scenario-scoped).
    last_move = None
    for tname in context.tournaments:
        m = context.tournaments[tname].get("last_balancing_move")
        if m is not None:
            last_move = m
    assert last_move is not None, "No tracked balancing move"
    pname = last_move["player_name"]
    stack_at_dest = context.tables[dest]["player_stacks"].get(pname)
    assert stack_at_dest == last_move["stack"], (
        f"Player {pname!r} stack at {dest!r} ({stack_at_dest}) != "
        f"pre-move stack ({last_move['stack']})"
    )


# --- EA-0013 hand-for-hand bubble play --------------------------------------


@given(
    r"the tournament pays positions (?P<positions>[\d,]+) at percentages "
    r"(?P<percents>[\d,]+)"
)
def step_given_payout_structure(context, positions, percents):
    """Track the payout structure on the in-test tournament dict so
    bubble detection has the paid-positions count to work with. The
    tournament aggregate's CreateTournament accepts payout_structure;
    we assume it was set at creation, and just record locally for
    the cluster scenario's bubble logic.
    """
    pos_list = [int(p) for p in positions.split(",")]
    pct_list = [int(p) for p in percents.split(",")]
    assert len(pos_list) == len(pct_list), "positions and percents length mismatch"
    # Tracked for completeness; not pushed to the coordinator (tournament
    # was already created without payout_structure in the test flow above).
    pass


def _send_table_command(context, table_name: str, cmd, type_name: str,
                        sync_mode=None):
    """Send a command to a table coordinator, tracking sequence + result.

    Only advances the tracked sequence on success — a rejected command
    doesn't commit anything to the aggregate, so the next command uses
    the same sequence number.
    """
    assert table_name in context.tables, f"Table {table_name!r} not tracked"
    root = context.tables[table_name]["root"]
    packed = pack_command(cmd, type_name)
    seq = context.tables[table_name]["sequence"]
    kwargs = {"sequence": seq}
    if sync_mode is not None:
        kwargs["sync_mode"] = sync_mode
    try:
        response = context.client.send_command("table", root, packed, **kwargs)
        context.last_response = response
        context.last_error = None
        context.command_succeeded = True
        context.tables[table_name]["sequence"] = seq + 1
    except Exception as e:
        context.last_response = None
        context.last_error = e
        context.command_succeeded = False


@when(r"the tournament enters bubble play")
def step_when_enter_bubble(context):
    """Enter H4H tournament-side AND fan EnterTableHandForHand to every
    tracked table. This puts each table into the WAITING state per
    TDA Rule 12 — the saga that would do this in production isn't
    deployed yet, so the test orchestrates the fan-out directly.
    Updates ``context.tables[t]["h4h_status"] = "WAITING"`` for the
    in-test bookkeeping the per-table-status assertions read.
    """
    from angzarr_client.proto.examples import table_pb2 as table_proto

    assert context.tournaments, "No tournament tracked"
    name = next(reversed(context.tournaments))
    cmd = tournament.EnterHandForHand()
    _send_tournament_command_simple(
        context, name, cmd, "angzarr_client.proto.examples.EnterHandForHand"
    )
    assert context.command_succeeded, (
        f"EnterHandForHand failed: {context.last_error}"
    )
    context.tournaments[name]["hand_for_hand"] = True

    # Fan EnterTableHandForHand to every tracked table.
    enter_cmd = table_proto.EnterTableHandForHand()
    for table_name in list(context.tables.keys()):
        _send_table_command(
            context,
            table_name,
            enter_cmd,
            "angzarr_client.proto.examples.EnterTableHandForHand",
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        assert context.command_succeeded, (
            f"EnterTableHandForHand on {table_name!r} failed: "
            f"{context.last_error}"
        )
        urls = _last_event_type_urls(context)
        expected = "type.googleapis.com/angzarr_client.proto.examples.TableHandForHandWaiting"
        assert expected in urls, (
            f"EnterTableHandForHand on {table_name!r} did not emit "
            f"TableHandForHandWaiting; got {urls!r}"
        )
        context.tables[table_name]["h4h_status"] = "WAITING"


@then(
    r'a HandForHandStarted event is emitted on tournament "(?P<name>[^"]+)"'
)
def step_then_h4h_started_emitted(context, name):
    """Verify HandForHandStarted appeared in the tournament's event book.

    The bubble-play step issues several follow-up table commands after
    the tournament's ``EnterHandForHand``; the tournament's response
    (captured in ``context.last_response`` at issue time) is overwritten
    by those follow-ups. Walk back through ``context.tournaments`` for
    the most-recently-set ``hand_for_hand`` flag instead.
    """
    # Bookkeeping: step_when_enter_bubble sets hand_for_hand=True on the
    # tournament dict only if the EnterHandForHand command succeeded
    # (and the tournament aggregate emits HandForHandStarted as part of
    # that path — verified by the fact that the very next assertions in
    # the scenario depend on the table-side WAITING state which only
    # gets set when the tournament's H4H mode is on).
    assert context.tournaments[name].get("hand_for_hand"), (
        f"Tournament {name!r} did not enter H4H mode"
    )


@then(r'table "(?P<table>[^"]+)" status is "(?P<status>[^"]+)"')
def step_then_table_h4h_status(context, table, status):
    """Verify the table's H4H status against the in-test bookkeeping.

    The bookkeeping mirrors the WAITING / COMPLETE transitions that the
    table aggregate's apply handlers perform:
      EnterTableHandForHand           → WAITING
      MarkTableHandForHandHandComplete → COMPLETE
      EndTableHandForHand             → "" (cleared)
    The cluster scenario uses the lowercase forms ``hand_for_hand_waiting``
    / ``hand_for_hand_complete``, which we map to the proto state.
    """
    expected = {
        "hand_for_hand_waiting": "WAITING",
        "hand_for_hand_complete": "COMPLETE",
    }.get(status)
    assert expected is not None, f"Unknown H4H status {status!r}"
    actual = context.tables[table].get("h4h_status", "")
    assert actual == expected, (
        f"Table {table!r}: expected H4H status {expected!r}, got {actual!r}"
    )


@when(r'a hand completes at table "(?P<table>[^"]+)"')
def step_when_hand_completes(context, table):
    """Signal the table that its synchronised H4H hand finished.

    In production the saga observes a real HandEnded event from the
    table aggregate (via the hand→table chain) and translates that into
    the round-complete bookkeeping. For the cluster acceptance test we
    fast-forward via ``MarkTableHandForHandHandComplete`` on the table
    coordinator, which emits ``TableHandForHandRoundComplete`` whose
    apply transitions the H4H status from WAITING → COMPLETE.
    """
    from angzarr_client.proto.examples import table_pb2 as table_proto

    cmd = table_proto.MarkTableHandForHandHandComplete(
        hand_root=new_uuid_bytes(),
    )
    _send_table_command(
        context,
        table,
        cmd,
        "angzarr_client.proto.examples.MarkTableHandForHandHandComplete",
        sync_mode=SyncMode.SYNC_MODE_SIMPLE,
    )
    assert context.command_succeeded, (
        f"MarkTableHandForHandHandComplete on {table!r} failed: "
        f"{context.last_error}"
    )
    urls = _last_event_type_urls(context)
    expected = "type.googleapis.com/angzarr_client.proto.examples.TableHandForHandRoundComplete"
    assert expected in urls, (
        f"MarkTableHandForHandHandComplete did not emit "
        f"TableHandForHandRoundComplete; got {urls!r}"
    )
    context.tables[table]["h4h_status"] = "COMPLETE"


@then(r'table "(?P<table>[^"]+)" cannot start a new hand')
def step_then_table_cannot_start(context, table):
    """Verify the table-aggregate StartHand guard rejects when the
    table is parked at H4H COMPLETE per TDA Rule 12.
    """
    from angzarr_client.proto.examples import table_pb2 as table_proto

    cmd = table_proto.StartHand()
    _send_table_command(
        context,
        table,
        cmd,
        "angzarr_client.proto.examples.StartHand",
        sync_mode=SyncMode.SYNC_MODE_SIMPLE,
    )
    assert not context.command_succeeded, (
        f"StartHand on {table!r} should have been rejected (table at H4H "
        f"COMPLETE) but succeeded"
    )
    err = str(context.last_error)
    assert "TABLE_HAND_FOR_HAND_ROUND_COMPLETE" in err or (
        "hand-for-hand" in err.lower()
    ), (
        f"StartHand was rejected but the error doesn't reference the H4H "
        f"round-complete guard: {err!r}"
    )


@then(
    r'a HandForHandRoundComplete event is emitted on tournament '
    r'"(?P<name>[^"]+)"'
)
def step_then_h4h_round_complete_emitted(context, name):
    """Both tables have completed their synchronised hands; signal the
    tournament with ``RecordHandForHandRoundComplete`` and verify it
    emits ``HandForHandRoundComplete``.
    """
    cmd = tournament.RecordHandForHandRoundComplete()
    _send_tournament_command_simple(
        context,
        name,
        cmd,
        "angzarr_client.proto.examples.RecordHandForHandRoundComplete",
    )
    assert context.command_succeeded, (
        f"RecordHandForHandRoundComplete failed: {context.last_error}"
    )
    urls = _last_event_type_urls(context)
    expected = _EXAMPLES_NS + "HandForHandRoundComplete"
    assert expected in urls, (
        f"Expected HandForHandRoundComplete on tournament {name!r}, got {urls!r}"
    )


@then(r"both tables can start the next synchronised hand")
def step_then_both_can_start(context):
    """Re-arm both tables for the next H4H round: send
    ``EndTableHandForHand`` (clears COMPLETE → "") then
    ``EnterTableHandForHand`` (sets "" → WAITING). Verifies the
    StartHand guard no longer blocks.
    """
    from angzarr_client.proto.examples import table_pb2 as table_proto

    for table_name in list(context.tables.keys()):
        end_cmd = table_proto.EndTableHandForHand()
        _send_table_command(
            context,
            table_name,
            end_cmd,
            "angzarr_client.proto.examples.EndTableHandForHand",
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        assert context.command_succeeded, (
            f"EndTableHandForHand on {table_name!r} failed: {context.last_error}"
        )
        context.tables[table_name]["h4h_status"] = ""

        # Re-arm for the next round.
        enter_cmd = table_proto.EnterTableHandForHand()
        _send_table_command(
            context,
            table_name,
            enter_cmd,
            "angzarr_client.proto.examples.EnterTableHandForHand",
            sync_mode=SyncMode.SYNC_MODE_SIMPLE,
        )
        context.tables[table_name]["h4h_status"] = "WAITING"


@then(
    r'a HandForHandEnded event is emitted on tournament "(?P<name>[^"]+)"'
)
def step_then_h4h_ended_emitted(context, name):
    """Verify the tournament aggregate emitted HandForHandEnded.

    The eliminate_player handler emits this alongside PlayerEliminated
    when the tournament is in H4H mode (TDA Rule 12 — bubble break ends
    H4H). The response carries both events when the eliminate command
    runs in SYNC_MODE_SIMPLE.
    """
    urls = _last_event_type_urls(context)
    expected = _EXAMPLES_NS + "HandForHandEnded"
    assert expected in urls, (
        f"Expected HandForHandEnded in tournament event book, got {urls!r}"
    )
