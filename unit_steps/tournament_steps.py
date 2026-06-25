"""Tournament aggregate unit steps — lifecycle slice.

Create / open-close registration / enroll, driven through the FFI core. "exists"
Givens seed a prior-events history the core folds; When steps dispatch a command;
Then steps assert the emitted event, the coded rejection, or (for enrollment) the
rejection EVENT the handler emits so the reservation PM sees the outcome. One
tournament per scenario (the default root).
"""

from __future__ import annotations

from behave import given, then, use_step_matcher, when

from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as trn
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "tournament"
P = "io.angzarr.examples.v1."

# Defaults for a seeded "tournament exists" history (mirror "Test Tournament").
_DEF = dict(buy_in=100, starting_stack=1000, max_players=100, min_players=10)


def _root_or_empty(name: str) -> bytes:
    """A player/reservation root, or b"" for the empty string (so the empty
    player_root scenario reaches the handler's required-field guard)."""
    return uuid_for(name) if name else b""


def _seed_created(context, name, **overrides):
    cfg = dict(_DEF, **overrides)
    context.world.seed_event(
        DOMAIN, P + "TournamentCreated", trn.TournamentCreated(name=name, **cfg)
    )


def _seed_enrolled(context, pid):
    context.world.seed_event(
        DOMAIN,
        P + "TournamentPlayerEnrolled",
        trn.TournamentPlayerEnrolled(
            player_root=uuid_for(pid), fee_paid=_DEF["buy_in"], starting_stack=_DEF["starting_stack"]
        ),
    )


# --- Given: seed prior state ---


@given("the tournament has not yet been created")
def _given_uncreated(context):
    pass


@given(
    'tournament "{name}" exists with {buy_in:d} buy-in, {stack:d} starting stack, '
    "max {max_p:d} players, min {min_p:d} players"
)
def _given_exists(context, name, buy_in, stack, max_p, min_p):
    _seed_created(
        context, name, buy_in=buy_in, starting_stack=stack, max_players=max_p, min_players=min_p
    )


@given("a tournament with registration open")
def _given_reg_open(context):
    _seed_created(context, "Test Tournament")
    context.world.seed_event(DOMAIN, P + "RegistrationOpened", trn.RegistrationOpened())


@given('player "{pid}" is enrolled')
def _given_enrolled(context, pid):
    _seed_enrolled(context, pid)


# --- When: dispatch a command ---


@when("registration opens")
def _when_open(context):
    context.world.dispatch(DOMAIN, P + "OpenRegistration", trn.OpenRegistration())


@when("registration closes")
def _when_close(context):
    context.world.dispatch(DOMAIN, P + "CloseRegistration", trn.CloseRegistration())


# Regex matcher (scoped): the create/enroll commands carry quoted fields that can
# be EMPTY ('tournament ""...', 'player ""...') to exercise the required-field
# guards — parse's "{field}" won't match an empty capture, so use [^"]*.
use_step_matcher("re")


@when(
    r'tournament "(?P<name>[^"]*)" is created with (?P<buy_in>\d+) buy-in, '
    r"(?P<stack>\d+) starting stack, max (?P<max_p>\d+) players, min (?P<min_p>\d+) players"
)
def _when_create(context, name, buy_in, stack, max_p, min_p):
    cmd = trn.CreateTournament(
        name=name,
        buy_in=int(buy_in),
        starting_stack=int(stack),
        max_players=int(max_p),
        min_players=int(min_p),
    )
    context.world.dispatch(DOMAIN, P + "CreateTournament", cmd)


@when(r'player "(?P<pid>[^"]*)" enrolls with reservation "(?P<res>[^"]*)"')
def _when_enroll(context, pid, res):
    cmd = trn.EnrollPlayer(player_root=_root_or_empty(pid), reservation_id=_root_or_empty(res))
    context.world.dispatch(DOMAIN, P + "EnrollPlayer", cmd)


use_step_matcher("parse")


# --- Then: assert emitted event / coded rejection / rejection event ---


@then('the tournament is named "{name}"')
def _then_named(context, name):
    ev = context.world.emitted(P + "TournamentCreated", trn.TournamentCreated())
    assert ev.name == name, f"name = {ev.name!r}, want {name!r}"


@then("the buy-in is {n:d}")
def _then_buyin(context, n):
    ev = context.world.emitted(P + "TournamentCreated", trn.TournamentCreated())
    assert ev.buy_in == n, f"buy_in = {ev.buy_in}, want {n}"


@then("the starting stack is {n:d}")
def _then_stack(context, n):
    ev = context.world.emitted(P + "TournamentCreated", trn.TournamentCreated())
    assert ev.starting_stack == n, f"starting_stack = {ev.starting_stack}, want {n}"


@then("the create-tournament is refused because it already exists")
def _then_create_dup(context):
    assert_rejected(context, "TOURNAMENT_EXISTS")


@then("the create-tournament is refused because the name is required")
def _then_create_name(context):
    assert_rejected(context, "NAME_REQUIRED")


@then("the create-tournament is refused because the buy-in must be positive")
def _then_create_buyin(context):
    assert_rejected(context, "BUY_IN_NOT_POSITIVE")


@then("the create-tournament is refused because the starting stack must be positive")
def _then_create_stack(context):
    assert_rejected(context, "STARTING_STACK_NOT_POSITIVE")


@then("the create-tournament is refused because the minimum must be at least 2 players")
def _then_create_min(context):
    assert_rejected(context, "MIN_PLAYERS_TOO_LOW")


@then(
    "the create-tournament is refused because the minimum of {min_p:d} players "
    "exceeds the maximum of {max_p:d}"
)
def _then_create_min_max(context, min_p, max_p):
    # Business-language assertion; the stable code + bound detail are verified in
    # the step, not leaked into the feature.
    assert_rejected(context, "MIN_PLAYERS_EXCEEDS_MAX")
    extras = context.world.err.extras
    assert extras.get("lhs") == str(min_p), f"lhs = {extras.get('lhs')!r}, want {min_p}"
    assert extras.get("rhs") == str(max_p), f"rhs = {extras.get('rhs')!r}, want {max_p}"


@then('the command is rejected with code "{code}"')
def _then_rejected_code(context, code):
    assert context.world.err is not None, "expected a coded rejection, got acceptance"
    assert context.world.err.code == code, f"code = {context.world.err.code!r}, want {code!r}"


@then('the rejection field "{field}" equals "{value}"')
def _then_rejection_field(context, field, value):
    assert context.world.err is not None, "expected a coded rejection, got acceptance"
    got = context.world.err.extras.get(field)
    assert got == value, f"rejection field {field!r} = {got!r}, want {value!r}"


@then("registration is open")
def _then_reg_open(context):
    context.world.emitted(P + "RegistrationOpened", trn.RegistrationOpened())


@then("opening registration is refused because the tournament does not exist")
def _then_open_no_tourney(context):
    assert_rejected(context, "TOURNAMENT_NOT_FOUND")


@then("opening registration is refused because it is already open")
def _then_open_already(context):
    assert_rejected(context, "REGISTRATION_ALREADY_OPEN")


@then("registration is closed")
def _then_reg_closed(context):
    context.world.emitted(P + "RegistrationClosed", trn.RegistrationClosed())


@then("closing registration is refused because it is not open")
def _then_close_not_open(context):
    assert_rejected(context, "REGISTRATION_NOT_OPEN")


@then('player "{pid}" is enrolled paying a fee of {n:d}')
def _then_enrolled_fee(context, pid, n):
    ev = context.world.emitted(P + "TournamentPlayerEnrolled", trn.TournamentPlayerEnrolled())
    assert ev.player_root == uuid_for(pid), "enrolled a different player"
    assert ev.fee_paid == n, f"fee_paid = {ev.fee_paid}, want {n}"


@then("the enrollment is rejected because a player identity is required")
def _then_enroll_no_identity(context):
    ev = context.world.emitted(
        P + "TournamentEnrollmentRejected", trn.TournamentEnrollmentRejected()
    )
    assert "player identity" in ev.reason.lower(), (
        f"rejection reason = {ev.reason!r}, want the player-identity-required reason"
    )


@then('the enrollment is rejected because of "{reason}"')
def _then_enroll_rejected(context, reason):
    ev = context.world.emitted(
        P + "TournamentEnrollmentRejected", trn.TournamentEnrollmentRejected()
    )
    assert reason.lower() in ev.reason.lower(), (
        f"rejection reason = {ev.reason!r}, want keyword {reason!r}"
    )


# ===========================================================================
# Slice 2: start / blind levels / eliminate / pause-resume / rebuy
# ===========================================================================

# A two-level blind structure; level 2 is small blind 50 / ante 10 (EU-0825).
_TWO_LEVELS = [
    trn.BlindLevel(level=1, small_blind=25, big_blind=50, ante=0, duration_minutes=20),
    trn.BlindLevel(level=2, small_blind=50, big_blind=100, ante=10, duration_minutes=20),
]


# The poker example's standard player-name sequence (matches the features).
_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Henry", "Ivy", "Jack"]


def _seed_running(context, enrolled=2, min_p=2, max_p=10, levels=None):
    """Seed a RUNNING tournament: created (+ optional blind structure) → open →
    ``enrolled`` players from the standard name sequence → started. The first
    enrolled is "Alice", so a later step can eliminate/rebuy a registered
    ("Alice") vs unregistered ("ghost") player."""
    overrides = dict(min_players=min_p, max_players=max_p)
    if levels is not None:
        overrides["blind_structure"] = levels
    _seed_created(context, "Test Tournament", **overrides)
    context.world.seed_event(DOMAIN, P + "RegistrationOpened", trn.RegistrationOpened())
    for name in _NAMES[:enrolled]:
        _seed_enrolled(context, name)
    context.world.seed_event(
        DOMAIN, P + "TournamentStarted", trn.TournamentStarted(total_players=enrolled)
    )


# --- Given: running / blind-structure variants ---


@given("a tournament for {min_p:d} to {max_p:d} players with registration open")
def _given_reg_open_minmax(context, min_p, max_p):
    _seed_created(context, "Test Tournament", min_players=min_p, max_players=max_p)
    context.world.seed_event(DOMAIN, P + "RegistrationOpened", trn.RegistrationOpened())


@given("a running tournament for {min_p:d} to {max_p:d} players with {n:d} enrolled")
def _given_running_enrolled(context, min_p, max_p, n):
    _seed_running(context, enrolled=n, min_p=min_p, max_p=max_p)


@given("a running tournament with a two-level blind structure")
def _given_running_two_levels(context):
    _seed_running(context, levels=_TWO_LEVELS)


@given("a running tournament at the final defined blind level")
def _given_running_final_level(context):
    _seed_running(context, levels=_TWO_LEVELS)
    context.world.seed_event(
        DOMAIN, P + "BlindLevelAdvanced", trn.BlindLevelAdvanced(level=2)
    )


@given("a running tournament with no blind structure")
def _given_running_no_structure(context):
    _seed_running(context)


# --- When: lifecycle transitions ---


@when("the tournament starts")
def _when_start(context):
    context.world.dispatch(DOMAIN, P + "StartTournament", trn.StartTournament())


@when("the blind level advances")
def _when_advance_blind(context):
    context.world.dispatch(DOMAIN, P + "AdvanceBlindLevel", trn.AdvanceBlindLevel())


@when('player "{pid}" requests a rebuy')
def _when_rebuy(context, pid):
    context.world.dispatch(
        DOMAIN, P + "ProcessRebuy", trn.ProcessRebuy(player_root=uuid_for(pid))
    )


@when('player "{pid}" is eliminated')
def _when_eliminate(context, pid):
    context.world.dispatch(
        DOMAIN, P + "EliminatePlayer", trn.EliminatePlayer(player_root=uuid_for(pid))
    )


@when('player "{pid}" is eliminated on hand "{hand}"')
def _when_eliminate_hand(context, pid, hand):
    context.world.dispatch(
        DOMAIN,
        P + "EliminatePlayer",
        trn.EliminatePlayer(player_root=uuid_for(pid), hand_root=uuid_for(hand)),
    )


@when('the tournament is paused with reason "{reason}"')
def _when_pause(context, reason):
    context.world.dispatch(DOMAIN, P + "PauseTournament", trn.PauseTournament(reason=reason))


@when("the tournament resumes")
def _when_resume(context):
    context.world.dispatch(DOMAIN, P + "ResumeTournament", trn.ResumeTournament())


# --- Then: outcomes ---


@then("the tournament is running with {n:d} players")
def _then_running_with(context, n):
    ev = context.world.emitted(P + "TournamentStarted", trn.TournamentStarted())
    assert ev.total_players == n, f"total_players = {ev.total_players}, want {n}"


@then("the start is refused because there are not enough players")
def _then_start_few(context):
    assert_rejected(context, "NOT_ENOUGH_PLAYERS")


@then("the rebuy is refused because the tournament is not running")
def _then_rebuy_not_running(context):
    assert_rejected(context, "TOURNAMENT_NOT_RUNNING")


@then('the rebuy is denied because of "{reason}"')
def _then_rebuy_denied(context, reason):
    ev = context.world.emitted(P + "RebuyDenied", trn.RebuyDenied())
    assert reason.lower() in ev.reason.lower(), (
        f"denial reason = {ev.reason!r}, want keyword {reason!r}"
    )


@then("the elimination is refused because the tournament is not running")
def _then_elim_not_running(context):
    assert_rejected(context, "TOURNAMENT_NOT_RUNNING")


@then("the elimination is refused because the player is not registered")
def _then_elim_not_registered(context):
    assert_rejected(context, "PLAYER_NOT_REGISTERED")


@then('the elimination records hand "{hand}"')
def _then_elim_hand(context, hand):
    ev = context.world.emitted(P + "PlayerEliminated", trn.PlayerEliminated())
    assert ev.hand_root == uuid_for(hand), "elimination recorded a different hand"


@then("the pause is refused because the tournament is not running")
def _then_pause_not_running(context):
    assert_rejected(context, "TOURNAMENT_NOT_RUNNING")


@then("the resume is refused because the tournament is not paused")
def _then_resume_not_paused(context):
    assert_rejected(context, "TOURNAMENT_NOT_PAUSED")


@then("the enrollment is refused because the tournament does not exist")
def _then_enroll_no_tourney(context):
    assert_rejected(context, "TOURNAMENT_NOT_FOUND")


@then("the tournament is at blind level {lvl:d} with small blind {sb:d} and ante {ante:d}")
def _then_blind_level(context, lvl, sb, ante):
    ev = context.world.emitted(P + "BlindLevelAdvanced", trn.BlindLevelAdvanced())
    assert ev.level == lvl, f"level = {ev.level}, want {lvl}"
    assert ev.small_blind == sb, f"small_blind = {ev.small_blind}, want {sb}"
    assert ev.ante == ante, f"ante = {ev.ante}, want {ante}"


@then("advancing the blind level is refused because the tournament is not running")
def _then_advance_not_running(context):
    assert_rejected(context, "TOURNAMENT_NOT_RUNNING")


@then("advancing the blind level is refused because level {current:d} is the last of {max_v:d} defined levels")
def _then_advance_last_level(context, current, max_v):
    assert_rejected(context, "BLIND_STRUCTURE_EXHAUSTED")
    extras = context.world.err.extras
    assert extras.get("current") == str(current), f"current = {extras.get('current')!r}, want {current}"
    assert extras.get("max_value") == str(max_v), f"max_value = {extras.get('max_value')!r}, want {max_v}"


@then("advancing the blind level is refused because no blind levels are defined")
def _then_advance_no_levels(context):
    assert_rejected(context, "BLIND_STRUCTURE_EXHAUSTED")
    assert context.world.err.extras.get("max_value") == "0", "expected zero defined levels"
