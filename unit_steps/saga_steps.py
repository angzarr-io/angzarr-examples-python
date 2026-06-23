"""Saga unit steps — TableHandSaga (HandStarted -> Shuffle + DealCards).

Exercises the SAGA component type: a stateless translator dispatched with a
source event (via the FFI Router.dispatch_saga) that emits commands to other
domains. The Given steps build the source HandStarted event; the When dispatches
it through the saga; the Then steps assert the emitted commands and their fields.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."


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
