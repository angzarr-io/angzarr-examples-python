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


@given("a tournament with max_players {max_p:d} and min_players {min_p:d} and registration open")
def _given_reg_open_bounds(context, max_p, min_p):
    _seed_created(context, "Test Tournament", max_players=max_p, min_players=min_p)
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


@then("the create-tournament is refused because buy_in must be positive")
def _then_create_buyin(context):
    assert_rejected(context, "BUY_IN_NOT_POSITIVE")


@then("the create-tournament is refused because starting_stack must be positive")
def _then_create_stack(context):
    assert_rejected(context, "STARTING_STACK_NOT_POSITIVE")


@then("the create-tournament is refused because min_players must be at least 2")
def _then_create_min(context):
    assert_rejected(context, "MIN_PLAYERS_TOO_LOW")


@then("the create-tournament is refused because min_players exceeds max_players")
def _then_create_min_max(context):
    assert_rejected(context, "MIN_PLAYERS_EXCEEDS_MAX")


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


@then('the enrollment is rejected because of "{reason}"')
def _then_enroll_rejected(context, reason):
    ev = context.world.emitted(
        P + "TournamentEnrollmentRejected", trn.TournamentEnrollmentRejected()
    )
    assert reason.lower() in ev.reason.lower(), (
        f"rejection reason = {ev.reason!r}, want keyword {reason!r}"
    )
