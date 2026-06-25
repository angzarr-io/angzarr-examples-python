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


# --- hand-event rendering (EU-0509..0524) ---

_RANK_IN = {"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
_SUIT_IN = {"c": 1, "d": 2, "h": 3, "s": 4}
_RANK_NAME = {"Jack": 11, "Queen": 12, "King": 13, "Ace": 14}


def _card(s):
    return pt.Card(
        rank=_RANK_IN.get(s[0], int(s[0]) if s[0].isdigit() else 0),
        suit=_SUIT_IN[s[1]],
    )


def _cards(s):
    return [_card(c) for c in s.split()]


def _proj(context, fq, ev):
    context.world.dispatch_projector("hand", [(P + fq, ev)])


@when("the display records {name} dealt {cards}")
def _when_dealt(context, name, cards):
    ev = hand.CardsDealt()
    pc = ev.player_cards.add(player_root=uuid_for(name))
    pc.cards.extend(_cards(cards))
    _proj(context, "CardsDealt", ev)


@when("the display records {name} posting the small blind of {amt:d}")
def _when_blind(context, name, amt):
    _proj(
        context,
        "BlindPosted",
        hand.BlindPosted(player_root=uuid_for(name), blind_type="SMALL", amount=amt),
    )


@when("the display records {name} folding")
def _when_fold(context, name):
    _proj(context, "ActionTaken", hand.ActionTaken(player_root=uuid_for(name), action=1))


@when("the display records {name} calling {amt:d} with the pot at {pot:d}")
def _when_call(context, name, amt, pot):
    _proj(
        context,
        "ActionTaken",
        hand.ActionTaken(player_root=uuid_for(name), action=3, amount=amt, pot_total=pot),
    )


@when("the display records {name} raising to {amt:d} with the pot at {pot:d}")
def _when_raise(context, name, amt, pot):
    _proj(
        context,
        "ActionTaken",
        hand.ActionTaken(player_root=uuid_for(name), action=5, amount=amt, pot_total=pot),
    )


@when("the display records {name} going all-in for {amt:d} with the pot at {pot:d}")
def _when_allin(context, name, amt, pot):
    _proj(
        context,
        "ActionTaken",
        hand.ActionTaken(player_root=uuid_for(name), action=6, amount=amt, pot_total=pot),
    )


@when("the display records the flop {cards}")
def _when_flop(context, cards):
    c = _cards(cards)
    _proj(context, "CommunityCardsDealt", hand.CommunityCardsDealt(cards=c, phase=2, all_community_cards=c))


@when("the display records the turn {card}")
def _when_turn(context, card):
    c = _cards(card)
    _proj(context, "CommunityCardsDealt", hand.CommunityCardsDealt(cards=c, phase=3, all_community_cards=c))


@when("the display records the showdown beginning")
def _when_showdown(context):
    _proj(context, "ShowdownStarted", hand.ShowdownStarted())


@when("the display records {name} revealing {cards} with a pair")
def _when_reveal(context, name, cards):
    ev = hand.CardsRevealed(player_root=uuid_for(name))
    ev.cards.extend(_cards(cards))
    ev.ranking.rank_type = 2  # PAIR
    _proj(context, "CardsRevealed", ev)


@when("the display records {name} mucking")
def _when_muck(context, name):
    _proj(context, "CardsMucked", hand.CardsMucked(player_root=uuid_for(name)))


@when("{name} wins a pot of {amt:d}")
def _when_wins_pot(context, name, amt):
    ev = hand.PotAwarded()
    ev.winners.add(player_root=uuid_for(name), amount=amt)
    _proj(context, "PotAwarded", ev)


@when("the hand finishes with final stacks:")
def _when_final_stacks(context):
    ev = hand.HandComplete()
    for row in context.table:
        ev.final_stacks.add(
            player_root=uuid_for(row["player"]),
            stack=int(row["stack"]),
            has_folded=row["has_folded"].strip() == "true",
        )
    _proj(context, "HandComplete", ev)


@when("{name} times out and is auto-folded")
def _when_timeout(context, name):
    _proj(context, "PlayerTimedOut", hand.PlayerTimedOut(player_root=uuid_for(name), default_action=1))


@when("cards are shown for each suit:")
def _when_suits(context):
    ev = hand.CommunityCardsDealt(phase=2)
    for row in context.table:
        ev.cards.add(suit=getattr(pt, row["suit"]), rank=int(row["rank"]))
    ev.all_community_cards.extend(ev.cards)
    _proj(context, "CommunityCardsDealt", ev)


@then('a {desc} displays as "{sym}"')
@then('an {desc} displays as "{sym}"')
def _then_rank_renders(context, desc, sym):
    from angzarr_poker.projectors.output import _rank

    value = _RANK_NAME.get(desc, int(desc) if desc.isdigit() else 0)
    assert _rank(value) == sym, f"rank {desc} rendered {_rank(value)!r}, want {sym!r}"


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
