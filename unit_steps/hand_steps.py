"""Hand aggregate unit steps — dealing + blinds subset.

Drives the generated HandAggregate wiring through the FFI core. "dealt" Givens
seed a CardsDealt history the core folds to rebuild HandState; When steps dispatch
DealCards / PostBlind; Then steps assert the emitted event or the coded rejection.
Scenarios beyond dealing and blinds (betting actions, community cards, draw,
showdown, pot award, hand rankings) are not covered until those handler methods
are ported.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "hand"
P = "io.angzarr.examples.v1."
_TABLE_ROOT = uuid_for("table-main")

_VARIANTS = {
    "Texas Hold'em": pt.TEXAS_HOLDEM,
    "Omaha": pt.OMAHA,
    "Five Card Draw": pt.FIVE_CARD_DRAW,
}


def _deal_cmd(variant, players):
    return hand.DealCards(
        table_root=_TABLE_ROOT,
        hand_number=1,
        game_variant=_VARIANTS[variant],
        players=players,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
    )


def _player_rows(context):
    return [
        hand.PlayerInHand(
            player_root=uuid_for(row["player"]),
            position=int(row["position"]),
            stack=int(row["stack"]),
        )
        for row in context.table
    ]


def _seed_dealt(context, n_players, stack, variant=pt.TEXAS_HOLDEM):
    context.dealt_stack = stack
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=stack
        )
        for i in range(n_players)
    ]
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT, hand_number=1, game_variant=variant, players=players
        ),
    )


# --- Given ---


@given("the hand has not yet been dealt")
def _given_undealt(context):
    pass


@given("a {variant} hand has already been dealt")
def _given_already_dealt(context, variant):
    _seed_dealt(context, 2, 500, _VARIANTS[variant])


@given("a {variant} hand has been dealt to {n:d} players with {stack:d}-chip stacks")
def _given_dealt_n(context, variant, n, stack):
    _seed_dealt(context, n, stack, _VARIANTS[variant])


@given("a {variant} hand has been dealt to:")
def _given_dealt_table(context, variant):
    context.dealt_stack = None
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=_VARIANTS[variant],
            players=_player_rows(context),
        ),
    )


@given("{pid} has posted a blind of {amt:d}")
def _given_posted_blind(context, pid, amt):
    context.world.seed_event(
        DOMAIN,
        P + "BlindPosted",
        hand.BlindPosted(
            player_root=uuid_for(pid),
            blind_type="small",
            amount=amt,
            player_stack=context.dealt_stack - amt,
            pot_total=amt,
        ),
    )


# --- When ---


@when("a {variant} hand is dealt to:")
@when("an {variant} hand is dealt to:")
def _when_deal(context, variant):
    context.world.dispatch(
        DOMAIN, P + "DealCards", _deal_cmd(variant, _player_rows(context))
    )


@when("a {variant} hand is dealt to only 1 player")
def _when_deal_one(context, variant):
    players = [
        hand.PlayerInHand(player_root=uuid_for("player-1"), position=0, stack=500)
    ]
    context.world.dispatch(DOMAIN, P + "DealCards", _deal_cmd(variant, players))


def _deal_with_seed(context, variant, players, seed, root=b""):
    """Shuffle(seed) then DealCards against the same hand, folding the emitted
    DeckShuffled so the deal draws from the seeded deck — the production
    saga-driven order. Returns the emitted CardsDealt."""
    context.world.dispatch(
        DOMAIN,
        P + "Shuffle",
        hand.Shuffle(seed=seed.encode(), game_variant=_VARIANTS[variant]),
        root=root,
    )
    context.world.fold_emitted(DOMAIN, root=root)
    context.world.dispatch(
        DOMAIN, P + "DealCards", _deal_cmd(variant, players), root=root
    )
    return context.world.emitted(P + "CardsDealt", hand.CardsDealt())


@when('a {variant} hand is dealt with seed "{seed}" to:')
def _when_deal_with_seed(context, variant, seed):
    context.seed_deal = _deal_with_seed(context, variant, _player_rows(context), seed)


@when('the same {variant} hand is dealt twice with seed "{seed}"')
def _when_deal_twice_with_seed(context, variant, seed):
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=500
        )
        for i in range(2)
    ]
    # Two distinct hand instances (roots) so the second deal is a fresh hand,
    # not a re-deal of the first.
    context.deal_a = _deal_with_seed(
        context, variant, players, seed, root=uuid_for("seed-hand-a")
    )
    context.deal_b = _deal_with_seed(
        context, variant, players, seed, root=uuid_for("seed-hand-b")
    )


@when("the dealer attempts to deal the hand again")
def _when_deal_again(context):
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=500
        )
        for i in range(2)
    ]
    context.world.dispatch(DOMAIN, P + "DealCards", _deal_cmd("Texas Hold'em", players))


@when("{pid} posts the small blind of {amt:d}")
def _when_post_small(context, pid, amt):
    cmd = hand.PostBlind(player_root=uuid_for(pid), blind_type="small", amount=amt)
    context.world.dispatch(DOMAIN, P + "PostBlind", cmd)


@when("{pid} posts the big blind of {amt:d}")
def _when_post_big(context, pid, amt):
    cmd = hand.PostBlind(player_root=uuid_for(pid), blind_type="big", amount=amt)
    context.world.dispatch(DOMAIN, P + "PostBlind", cmd)


# --- Then ---


@then("each player has {n:d} hole cards")
def _then_hole_cards(context, n):
    ev = context.world.emitted(P + "CardsDealt", hand.CardsDealt())
    assert ev.player_cards, "no player_cards dealt"
    for pc in ev.player_cards:
        assert (
            len(pc.cards) == n
        ), f"{pc.player_root.hex()} has {len(pc.cards)} cards, want {n}"


@then("the remaining deck has {n:d} cards")
def _then_remaining_deck(context, n):
    ev = context.world.emitted(P + "CardsDealt", hand.CardsDealt())
    assert (
        len(ev.remaining_deck) == n
    ), f"remaining = {len(ev.remaining_deck)}, want {n}"


@then('player "{pid}" holds the cards expected for seed "{seed}"')
def _then_holds_expected(context, pid, seed):
    from angzarr_poker.hand.handler import _HOLE_CARDS, _deck_from_seed

    ev = context.seed_deal
    deck = _deck_from_seed(seed.encode())
    hole = _HOLE_CARDS[ev.game_variant]
    order = [p.player_root for p in ev.players]
    idx = order.index(uuid_for(pid))
    expected = deck[idx * hole : (idx + 1) * hole]
    actual = next(pc.cards for pc in ev.player_cards if pc.player_root == uuid_for(pid))
    assert list(actual) == list(expected), (
        f"{pid} holds cards that don't match the seed-derived deck — the deal "
        f"did not draw from the Shuffle(seed) deck"
    )


@then("both deals produce identical hole cards")
def _then_identical_deals(context):
    a = {pc.player_root: list(pc.cards) for pc in context.deal_a.player_cards}
    b = {pc.player_root: list(pc.cards) for pc in context.deal_b.player_cards}
    assert a == b, "the two deals with the same seed produced different hole cards"


@then("the deal is refused because the hand has already been dealt")
def _then_deal_dup(context):
    assert_rejected(context, "HAND_ALREADY_DEALT")


@then("the deal is refused because at least 2 players are required")
def _then_deal_few(context):
    assert_rejected(context, "NOT_ENOUGH_PLAYERS")


@then("the small blind is posted at {amt:d}")
def _then_small_posted(context, amt):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.amount == amt, f"small blind = {ev.amount}, want {amt}"


@then("the big blind is posted at {amt:d}")
def _then_big_posted(context, amt):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.amount == amt, f"big blind = {ev.amount}, want {amt}"


@then("{pid}'s stack is {n:d}")
def _then_stack_is(context, pid, n):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.player_stack == n, f"stack = {ev.player_stack}, want {n}"


@then("the pot is {n:d}")
def _then_pot_is(context, n):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.pot_total == n, f"pot = {ev.pot_total}, want {n}"


@then("{pid} is all-in")
def _then_all_in(context, pid):
    ev = context.world.emitted(P + "BlindPosted", hand.BlindPosted())
    assert ev.player_stack == 0, f"expected all-in (stack 0), got {ev.player_stack}"
