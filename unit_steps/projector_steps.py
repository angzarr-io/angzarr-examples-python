"""Projector unit steps — OutputProjector "game display" (player-funds slice).

Exercises the PROJECTOR component type: events are folded through the registered
projector (via the FFI Router.dispatch_projector) and finish() returns a
Projection whose payload carries the rendered display lines. The When steps build
player-funds events; the Then steps decode the projection and assert the display
text.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import player_pb2 as player
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt

P = "io.angzarr.examples.v1."
DOMAIN = "player"


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
