"""Projector unit steps — OutputProjector "game display" (player-funds slice).

Exercises the PROJECTOR component type: events are folded through the registered
projector (via the FFI Router.dispatch_projector) and finish() returns a
Projection whose payload carries the rendered display lines. The When steps build
player-funds events; the Then steps decode the projection and assert the display
text.
"""

from __future__ import annotations

from behave import given, then, use_step_matcher, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."
DOMAIN = "player"


def _know(context, name):
    context.world.output_projector.names[uuid_for(name).hex()] = name


# --- table + hand-lifecycle rendering (EU-0503..0508) ---


@given("the game display knows {names}")
def _given_knows(context, names):
    for n in names.replace(" and ", ",").split(","):
        _know(context, n.strip())


@when("{name} reserves {amt:d} chips")
def _when_reserves(context, name, amt):
    ev = player.FundsReserved(amount=pt.Currency(amount=amt))
    context.world.dispatch_projector("player", [(P + "FundsReserved", ev)])


@when("a table is created with:")
def _when_table_created(context):
    row = context.table[0]
    ev = table.TableCreated(
        table_name=row["table_name"],
        game_variant=getattr(pt, row["game_variant"]),
        small_blind=int(row["small_blind"]),
        big_blind=int(row["big_blind"]),
        min_buy_in=int(row["min_buy_in"]),
        max_buy_in=int(row["max_buy_in"]),
    )
    context.world.dispatch_projector("table", [(P + "TableCreated", ev)])


@when("{name} joins at seat {seat:d} with a buy-in of {amt:d}")
def _when_joins(context, name, seat, amt):
    ev = table.PlayerJoined(
        player_root=uuid_for(name), seat_position=seat, buy_in_amount=amt
    )
    context.world.dispatch_projector("table", [(P + "PlayerJoined", ev)])


@when("{name} leaves cashing out {amt:d} chips")
def _when_leaves(context, name, amt):
    ev = table.PlayerLeft(player_root=uuid_for(name), chips_cashed_out=amt)
    context.world.dispatch_projector("table", [(P + "PlayerLeft", ev)])


@when("hand {num:d} starts with dealer at seat {seat:d} and blinds {sb:d}/{bb:d}")
def _when_hand_starts(context, num, seat, sb, bb):
    context.proj_hand = table.HandStarted(
        hand_number=num, dealer_position=seat, small_blind=sb, big_blind=bb
    )


@when('the active players are {names} at seats {seats}')
def _when_active_players(context, names, seats):
    name_list = [n.strip().strip('"') for n in names.split(",")]
    seat_list = [int(s) for s in seats.split(",")]
    for nm, st in zip(name_list, seat_list):
        _know(context, nm)
        context.proj_hand.active_players.add(player_root=uuid_for(nm), position=st, stack=0)
    context.world.dispatch_projector("table", [(P + "HandStarted", context.proj_hand)])


# Regex (scoped): the unquoted name distinguishes this display step from the
# table aggregate's quoted `the hand ends with "X" winning N`.
use_step_matcher("re")


@when(r"the hand ends with (?P<name>[^\"\s]\S*) winning (?P<amt>\d+)")
def _when_hand_ends_winner(context, name, amt):
    ev = hand.HandComplete()
    ev.winners.add(player_root=uuid_for(name), amount=int(amt))
    context.world.dispatch_projector("hand", [(P + "HandComplete", ev)])


use_step_matcher("parse")


@given("the game display")
def _given_display(context):
    pass  # the OutputProjector is registered in the World


@when("{name} registers")
def _when_registers(context, name):
    context.world.dispatch_projector(
        DOMAIN, [(P + "PlayerRegistered", player.PlayerRegistered(display_name=name))]
    )


@when("{name} deposits {amt:d} chips bringing her balance to {bal:d}")
def _when_deposits(context, name, amt, bal):
    ev = player.FundsDeposited(amount=pt.Currency(amount=amt), new_balance=pt.Currency(amount=bal))
    context.world.dispatch_projector(DOMAIN, [(P + "FundsDeposited", ev)])


@when("{name} withdraws {amt:d} chips bringing her balance to {bal:d}")
def _when_withdraws(context, name, amt, bal):
    ev = player.FundsWithdrawn(amount=pt.Currency(amount=amt), new_balance=pt.Currency(amount=bal))
    context.world.dispatch_projector(DOMAIN, [(P + "FundsWithdrawn", ev)])


@then('the display shows "{text}"')
def _then_display_shows(context, text):
    lines = context.world.output_projector.lines
    assert any(text in line for line in lines), f"{text!r} not in display lines {lines}"
