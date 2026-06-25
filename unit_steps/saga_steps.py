"""Saga unit steps — TableHandSaga (HandStarted -> Shuffle + DealCards).

Exercises the SAGA component type: a stateless translator dispatched with a
source event (via the FFI Router.dispatch_saga) that emits commands to other
domains. The Given steps build the source HandStarted event; the When dispatches
it through the saga; the Then steps assert the emitted commands and their fields.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."


# --- generic translator dispatch (one source event -> emitted commands) ---


def _set_event(context, source_domain, fq, msg):
    context.saga_source = source_domain
    context.saga_fq = fq
    context.saga_event = msg


def _dispatch_translation(context):
    context.world.dispatch_saga(context.saga_source, P + context.saga_fq, context.saga_event)


def _emitted_cmds(context):
    """(domain, root_bytes, fq, payload_bytes) for every emitted command."""
    out = []
    if context.world.resp is None:
        return out
    for book in context.world.resp.commands:
        for page in book.pages:
            out.append(
                (
                    book.cover.domain,
                    book.cover.root.value,
                    page.command.type_url.rsplit("/", 1)[-1],
                    page.command.value,
                )
            )
    return out


def _cmds_of(context, fq):
    return [c for c in _emitted_cmds(context) if c[2] == P + fq]


def _command(context, fq):
    """The emitted command page of type ``fq`` bound for the hand domain."""
    for domain, full_fq, page in context.world.emitted_commands():
        if domain == "hand" and full_fq == P + fq:
            return page
    raise AssertionError(
        f"no {fq} command to hand; got {[(d, f) for d, f, _ in context.world.emitted_commands()]}"
    )


@given("a TableSyncSaga")
def _given_saga(context):
    pass  # registered in the World


@given("a HandStarted event from table domain with:")
def _given_hand_started(context):
    row = context.table[0]
    context.saga_event = table.HandStarted(
        hand_root=uuid_for(row["hand_root"]),
        hand_number=int(row["hand_number"]),
        game_variant=getattr(pt, row["game_variant"]),
        dealer_position=int(row["dealer_position"]),
    )


@given("active players:")
def _given_active_players(context):
    for row in context.table:
        context.saga_event.active_players.add(
            position=int(row["position"]),
            player_root=uuid_for(row["player_root"]),
            stack=int(row["stack"]),
        )


@when("the saga handles the event")
def _when_saga_handles(context):
    context.world.dispatch_saga("table", P + "HandStarted", context.saga_event, {"hand": 0})


@then("the saga emits a Shuffle command to hand domain")
def _then_emits_shuffle(context):
    _command(context, "Shuffle")


@then("the Shuffle command has seed equal to the hand_root")
def _then_shuffle_seed(context):
    page = _command(context, "Shuffle")
    shuffle = hand.Shuffle.FromString(page.value)
    assert shuffle.seed == context.saga_event.hand_root, "Shuffle seed != hand_root"


@then("the saga emits a DealCards command to hand domain")
def _then_emits_deal(context):
    _command(context, "DealCards")


@then("the command has game_variant {variant}")
def _then_deal_variant(context, variant):
    deal = hand.DealCards.FromString(_command(context, "DealCards").value)
    assert deal.game_variant == getattr(pt, variant), f"variant = {deal.game_variant}"


@then("the command has {n:d} players")
def _then_deal_players(context, n):
    deal = hand.DealCards.FromString(_command(context, "DealCards").value)
    assert len(deal.players) == n, f"players = {len(deal.players)}, want {n}"


@then("the command has hand_number {n:d}")
def _then_deal_hand_number(context, n):
    deal = hand.DealCards.FromString(_command(context, "DealCards").value)
    assert deal.hand_number == n, f"hand_number = {deal.hand_number}, want {n}"


# ===========================================================================
# Additional translators: hand->table (EndHand), table->player (ReleaseFunds),
# hand->player (DepositFunds), + the production-dispatcher phrasings.
# ===========================================================================

from behave import use_step_matcher  # noqa: E402

# No-op registration Givens — every translator is already registered in the World.
use_step_matcher("re")


@given(r".*translators? (?:is|are) (?:registered|active).*")
def _given_translators_registered(context):
    pass


use_step_matcher("parse")


# --- Given: build the source event ---


@given('a hand at table "{name}" completes with pot total {total:d}')
@given('a hand at table "{name}" completes')
def _given_hand_complete(context, name, total=0):
    _set_event(context, "hand", "HandComplete", hand.HandComplete(table_root=uuid_for(name)))


def _add_winners(context, detail):
    for row in context.table:
        w = context.saga_event.winners.add(
            player_root=uuid_for(row["player_root"]), amount=int(row["amount"])
        )
        if detail:
            w.winning_hand.SetInParent()  # mark present so the result carries it


@given("the winners are:")
def _given_winners(context):
    _add_winners(context, detail=False)


@given("the winners include winning-hand detail:")
def _given_winners_detail(context):
    _add_winners(context, detail=True)


@given("there are no winners")
def _given_no_winners(context):
    pass


@given("a hand-start event occurs")
def _given_hand_start_occurs(context):
    _set_event(
        context,
        "table",
        "HandStarted",
        table.HandStarted(hand_number=1, game_variant=pt.TEXAS_HOLDEM),
    )


@given('hand "{h}" ends with the following stack changes:')
def _given_hand_ended(context, h):
    ev = table.HandEnded(hand_root=uuid_for(h))
    for row in context.table:
        ev.stack_changes[uuid_for(row["player_root"]).hex()] = int(row["change"])
    _set_event(context, "table", "HandEnded", ev)


@given('hand "{h}" ends with no stack changes')
def _given_hand_ended_empty(context, h):
    _set_event(context, "table", "HandEnded", table.HandEnded(hand_root=uuid_for(h)))


@given("a pot of {total:d} is awarded with winners:")
def _given_pot_awarded(context, total):
    ev = hand.PotAwarded()
    for row in context.table:
        ev.winners.add(player_root=uuid_for(row["player_root"]), amount=int(row["amount"]))
    _set_event(context, "hand", "PotAwarded", ev)


@given("a pot of {total:d} is awarded with no winners")
def _given_pot_awarded_empty(context, total):
    _set_event(context, "hand", "PotAwarded", hand.PotAwarded())


@given('a hand "{h}" begins as hand number {num:d} with {variant} and dealer at position {pos:d}')
def _given_hand_begins(context, h, num, variant, pos):
    _set_event(
        context,
        "table",
        "HandStarted",
        table.HandStarted(
            hand_root=uuid_for(h),
            hand_number=num,
            game_variant=getattr(pt, variant),
            dealer_position=pos,
        ),
    )


@given("the active players are:")
def _given_active_players_table(context):
    for row in context.table:
        context.saga_event.active_players.add(
            position=int(row["position"]),
            player_root=uuid_for(row["player_root"]),
            stack=int(row["stack"]),
        )


@given("there are no active players")
def _given_no_active_players(context):
    pass


@given("the following events occur in order:")
def _given_events_in_order(context):
    context.saga_events = [row["event_type"] for row in context.table]


# --- When: dispatch the translation ---


@when("the hand-completion is translated for the table")
@when("the hand-end is translated for the players")
@when("the pot-award is translated for the players")
@when("the event is processed for the hand")
@when("the event is processed for the table")
@when("the event is processed for the players")
@when("the event is processed for the hand, table, and players")
@when("the event is processed")
def _when_translate(context):
    _dispatch_translation(context)


@when("the events are processed")
def _when_translate_each(context):
    context.deal_count = 0
    for _ in context.saga_events:
        ev = table.HandStarted(hand_number=1, game_variant=pt.TEXAS_HOLDEM)
        context.world.dispatch_saga("table", P + "HandStarted", ev)
        context.deal_count += len(_cmds_of(context, "DealCards"))


# --- Then: hand -> table (EndHand) ---


def _end_hand(context):
    cmds = _cmds_of(context, "EndHand")
    assert cmds, f"no EndHand command; got {[c[2] for c in _emitted_cmds(context)]}"
    return table.EndHand.FromString(cmds[0][3])


@then("the table ends the round with {n:d} result")
@then("the table ends the round with {n:d} result for \"{pid}\" with amount {amt:d}")
def _then_end_round(context, n, pid=None, amt=None):
    ev = _end_hand(context)
    assert len(ev.results) == n, f"results = {len(ev.results)}, want {n}"
    if pid is not None:
        assert ev.results[0].winner_root == uuid_for(pid)
        assert ev.results[0].amount == amt


@then("the table ends the round with no results")
def _then_end_no_results(context):
    assert len(_end_hand(context).results) == 0


@then('the result records "{pid}" winning {amt:d}')
def _then_result_records(context, pid, amt):
    ev = _end_hand(context)
    match = [r for r in ev.results if r.winner_root == uuid_for(pid) and r.amount == amt]
    assert match, f"no result for {pid} winning {amt}"


@then("the table's first end-of-round result records the winning hand")
def _then_winning_hand_detail(context):
    ev = _end_hand(context)
    assert ev.results and ev.results[0].HasField("winning_hand"), "winning hand not carried"


# --- Then: table -> player (ReleaseFunds) ---


@then("{n:d} players have their reserved chips released")
def _then_released(context, n):
    assert len(_cmds_of(context, "ReleaseFunds")) == n, (
        f"released = {len(_cmds_of(context, 'ReleaseFunds'))}, want {n}"
    )


@then("no chips are released")
@then("no action results")
def _then_no_action(context):
    assert not _emitted_cmds(context), "expected no emitted commands"


# --- Then: hand -> player (DepositFunds) ---


@then("{n:d} players receive deposits")
@then("{n:d} player receives a deposit")
def _then_deposits(context, n):
    assert len(_cmds_of(context, "DepositFunds")) == n, (
        f"deposits = {len(_cmds_of(context, 'DepositFunds'))}, want {n}"
    )


def _assert_deposit_at(context, idx, pid, amt):
    _, root, _fq, payload = _cmds_of(context, "DepositFunds")[idx]
    assert root == uuid_for(pid), f"deposit {idx} to wrong player"
    assert player.DepositFunds.FromString(payload).amount.amount == amt


@then('"{pid}" is credited {amt:d}')
def _then_credited(context, pid, amt):
    match = [
        d for d in _cmds_of(context, "DepositFunds")
        if d[1] == uuid_for(pid) and player.DepositFunds.FromString(d[3]).amount.amount == amt
    ]
    assert match, f"{pid} not credited {amt}"


@then('the first deposit credits "{pid}" with {amt:d}')
def _then_first_deposit(context, pid, amt):
    _assert_deposit_at(context, 0, pid, amt)


@then('the second deposit credits "{pid}" with {amt:d}')
def _then_second_deposit(context, pid, amt):
    _assert_deposit_at(context, 1, pid, amt)


# --- Then: table -> hand (DealCards), routing ---


@then("the hand is dealt as hand number {num:d} with {variant} for {p:d} players")
def _then_dealt(context, num, variant, p):
    deal = hand.DealCards.FromString(_cmds_of(context, "DealCards")[0][3])
    assert deal.hand_number == num
    assert deal.game_variant == getattr(pt, variant)
    assert len(deal.players) == p, f"players = {len(deal.players)}, want {p}"


@then("{n:d} hands are dealt")
def _then_n_dealt(context, n):
    assert context.deal_count == n, f"dealt {context.deal_count}, want {n}"


@then("only the hand is dealt")
@then("only the table-to-hand translator reacts")
@then("the table-to-hand translator still reacts")
def _then_only_dealt(context):
    assert _cmds_of(context, "DealCards"), "expected a DealCards"
    assert not _cmds_of(context, "EndHand"), "unexpected table command"
    assert not _cmds_of(context, "ReleaseFunds"), "unexpected player release"
    assert not _cmds_of(context, "DepositFunds"), "unexpected player deposit"


@then("no error escapes to the caller")
def _then_no_error(context):
    assert context.world.err is None
