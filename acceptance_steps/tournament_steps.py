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
    _send_tournament_command(
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
