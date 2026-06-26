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
from google.protobuf import symbol_database as _symbol_database

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as pt
from angzarr_poker.hand.aggregate.handler import HandAggregate, _fresh_deck
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

DOMAIN = "hand"
P = "io.angzarr.examples.v1."
_TABLE_ROOT = uuid_for("table-main")

_SYM = _symbol_database.Default()
# One handler instance reused to fold a scenario's event history (prior +
# last-emitted) back into a HandState for state-shape assertions — the same
# appliers the FFI core runs, so the rebuilt state matches the cluster's.
_AGG = HandAggregate()
_APPLIERS = {
    "CardsDealt": HandAggregate.apply_cards_dealt,
    "DeckShuffled": HandAggregate.apply_deck_shuffled,
    "BlindPosted": HandAggregate.apply_blind_posted,
    "ActionTaken": HandAggregate.apply_action_taken,
    "BettingRoundComplete": HandAggregate.apply_betting_round_complete,
    "CommunityCardsDealt": HandAggregate.apply_community_cards_dealt,
    "ShowdownStarted": HandAggregate.apply_showdown_started,
    "PotAwarded": HandAggregate.apply_pot_awarded,
    "HandComplete": HandAggregate.apply_hand_complete,
}


def _rebuild_state(context, include_last_emitted: bool = True) -> hand.HandState:
    """Fold the (hand, root b"") prior history — optionally plus the last
    dispatch's emitted events — back into a fresh HandState via the handler
    appliers, so a Then can assert on rebuilt phase / deck / player shape."""
    state = hand.HandState()
    pages = []
    book = context.world._prior.get((DOMAIN, b"".hex()))
    if book is not None:
        pages.extend(book.pages)
    if include_last_emitted and context.world.resp is not None:
        pages.extend(context.world.resp.events.pages)
    for page in pages:
        name = page.event.type_url.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        ev_cls = getattr(hand, name, None)
        applier = _APPLIERS.get(name)
        if ev_cls is None or applier is None:
            continue
        ev = ev_cls()
        ev.ParseFromString(page.event.value)
        applier(_AGG, state, ev)
    return state


def _state_player(state, pid):
    root = uuid_for(pid)
    for p in state.players:
        if p.player_root == root:
            return p
    return None


def _last_emitted_field(context, field):
    """Decode the last emitted event of the last dispatch that carries ``field``
    and return its value. Works across BlindPosted / ActionTaken (both expose
    pot_total / player_stack), so one Then serves the blind and action paths."""
    value = None
    for page in context.world.emitted_pages():
        full_name = page.event.type_url.rsplit("/", 1)[-1]
        try:
            msg = _SYM.GetSymbol(full_name)()
        except KeyError:
            continue
        msg.ParseFromString(page.event.value)
        if field in {f.name for f in msg.DESCRIPTOR.fields}:
            value = getattr(msg, field)
    return value


def _action_taken(context):
    """Decode the ActionTaken the last PlayerAction emitted."""
    return context.world.emitted(P + "ActionTaken", hand.ActionTaken())


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
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=variant,
            players=players,
            # A real post-deal deck so community-card streets have cards to
            # draw. Hole cards aren't material to the betting scenarios, so we
            # just consume them off the top to leave 52 - 2*n.
            remaining_deck=_fresh_deck()[2 * n_players :],
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
    players = _player_rows(context)
    context.world.seed_event(
        DOMAIN,
        P + "CardsDealt",
        hand.CardsDealt(
            table_root=_TABLE_ROOT,
            hand_number=1,
            game_variant=_VARIANTS[variant],
            players=players,
            remaining_deck=_fresh_deck()[2 * len(players) :],
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
    from angzarr_poker.hand.aggregate.handler import _HOLE_CARDS, _deck_from_seed

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
    # The absolute stack after the last emission — BlindPosted on the blind
    # path, ActionTaken on the betting path; both carry player_stack.
    stack = _last_emitted_field(context, "player_stack")
    assert stack == n, f"stack = {stack}, want {n}"


@then("the pot is {n:d}")
def _then_pot_is(context, n):
    pot = _last_emitted_field(context, "pot_total")
    assert pot == n, f"pot = {pot}, want {n}"


@then("{pid} is all-in")
def _then_all_in(context, pid):
    stack = _last_emitted_field(context, "player_stack")
    assert stack == 0, f"expected all-in (stack 0), got {stack}"


# ==========================================================================
# Betting-round + community-card steps (player actions, flop/turn/river).
# Player-1 (seat 0) is the small blind and acts first; player-2 (seat 1)
# is the big blind. The "bringing the pot to N" Givens post SB 5 / BB 10
# (= pot 15, current_bet 10), the standard heads-up setup these scenarios
# share. State-shape Thens fold the scenario's event history back into a
# HandState via _rebuild_state.
# ==========================================================================

_ACTION_BY_VERB = {
    "folds": pt.FOLD,
    "checks": pt.CHECK,
}


@given("a {variant} hand has been dealt to {n:d} players")
def _given_dealt_n_no_stack(context, variant, n):
    # Stack-less form (EU-0019/0020) — default to 1000; these scenarios
    # don't assert on stacks, only on community-card progression.
    _seed_dealt(context, n, 1000, _VARIANTS[variant])


def _post_blinds(context):
    """Drive real PostBlind commands: SB 5 from player-1, BB 10 from
    player-2, folding each emitted BlindPosted into the rebuild history so
    the subsequent action rebuilds over current_bet=10 / pot=15."""
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for("player-1"), blind_type="small", amount=5),
    )
    context.world.fold_emitted(DOMAIN)
    context.world.dispatch(
        DOMAIN,
        P + "PostBlind",
        hand.PostBlind(player_root=uuid_for("player-2"), blind_type="big", amount=10),
    )
    context.world.fold_emitted(DOMAIN)


@given("blinds have been posted bringing the pot to {pot:d}")
@given("blinds have been posted bringing the pot to {pot:d} with the bet at {bet:d}")
def _given_blinds_posted(context, pot, bet=None):
    _post_blinds(context)


def _seed_round_complete(context, phase):
    context.world.seed_event(
        DOMAIN,
        P + "BettingRoundComplete",
        hand.BettingRoundComplete(completed_phase=phase),
    )


@given("the preflop betting round is complete")
def _given_preflop_complete(context):
    _seed_round_complete(context, pt.PREFLOP)


@given("the flop betting round is complete")
def _given_flop_complete(context):
    _seed_round_complete(context, pt.FLOP)


@given("the turn betting round is complete")
def _given_turn_complete(context):
    _seed_round_complete(context, pt.TURN)


def _deal_community(context, count):
    context.world.dispatch(
        DOMAIN, P + "DealCommunityCards", hand.DealCommunityCards(count=count)
    )


@given("the flop has been dealt")
def _given_flop_dealt(context):
    _deal_community(context, 3)
    context.world.fold_emitted(DOMAIN)


@given("the flop and turn have been dealt")
def _given_flop_and_turn_dealt(context):
    _deal_community(context, 3)
    context.world.fold_emitted(DOMAIN)
    _deal_community(context, 1)
    context.world.fold_emitted(DOMAIN)


# --- player action When steps ---


def _act(context, pid, action, amount=0):
    context.world.dispatch(
        DOMAIN,
        P + "PlayerAction",
        hand.PlayerAction(player_root=uuid_for(pid), action=action, amount=amount),
    )


@when("{pid} folds")
def _when_folds(context, pid):
    _act(context, pid, pt.FOLD)


@when("{pid} checks")
@when("{pid} attempts to check")
def _when_checks(context, pid):
    _act(context, pid, pt.CHECK)


@when("{pid} calls for {amt:d}")
def _when_calls(context, pid, amt):
    _act(context, pid, pt.CALL, amt)


@when("{pid} bets {amt:d}")
@when("{pid} attempts to bet {amt:d}")
def _when_bets(context, pid, amt):
    _act(context, pid, pt.BET, amt)


@when("{pid} raises to {amt:d}")
def _when_raises(context, pid, amt):
    _act(context, pid, pt.RAISE, amt)


@when("{pid} goes all-in for {amt:d}")
def _when_all_in(context, pid, amt):
    _act(context, pid, pt.ALL_IN, amt)


# --- community-card When steps ---


@when("the dealer deals the flop")
def _when_deal_flop(context):
    context.deck_before = len(
        _rebuild_state(context, include_last_emitted=False).remaining_deck
    )
    _deal_community(context, 3)


@when("the dealer deals the turn")
def _when_deal_turn(context):
    context.deck_before = len(
        _rebuild_state(context, include_last_emitted=False).remaining_deck
    )
    _deal_community(context, 1)


@when("the dealer deals the river")
def _when_deal_river(context):
    context.deck_before = len(
        _rebuild_state(context, include_last_emitted=False).remaining_deck
    )
    _deal_community(context, 1)


# --- action Then steps ---


@then("{pid} is folded")
def _then_is_folded(context, pid):
    state = _rebuild_state(context)
    p = _state_player(state, pid)
    assert p is not None, f"{pid} not in hand"
    assert p.has_folded, f"{pid} is not folded"


@then("{pid}'s check is recorded")
def _then_check_recorded(context, pid):
    ev = _action_taken(context)
    assert ev.action == pt.CHECK, f"action = {ev.action}, want CHECK"
    assert ev.player_root == uuid_for(pid)


@then("{pid}'s call of {amt:d} is recorded")
def _then_call_recorded(context, pid, amt):
    ev = _action_taken(context)
    assert ev.action in (pt.CALL, pt.ALL_IN), f"action = {ev.action}, want CALL"
    assert ev.amount == amt, f"call amount = {ev.amount}, want {amt}"


@then("{pid}'s bet of {amt:d} is recorded")
def _then_bet_recorded(context, pid, amt):
    ev = _action_taken(context)
    assert ev.action in (pt.BET, pt.ALL_IN), f"action = {ev.action}, want BET"
    assert ev.amount == amt, f"bet amount = {ev.amount}, want {amt}"


@then("{pid}'s raise puts {amt:d} more chips into the pot")
def _then_raise_chips(context, pid, amt):
    ev = _action_taken(context)
    assert ev.action in (pt.RAISE, pt.ALL_IN), f"action = {ev.action}, want RAISE"
    assert ev.amount == amt, f"raise chips = {ev.amount}, want {amt}"


@then("{pid}'s all-in is recorded")
def _then_all_in_recorded(context, pid):
    ev = _action_taken(context)
    assert ev.action == pt.ALL_IN, f"action = {ev.action}, want ALL_IN"


@then("the next player owes {amt:d} to call")
def _then_owes_to_call(context, amt):
    ev = _action_taken(context)
    assert ev.amount_to_call == amt, f"amount_to_call = {ev.amount_to_call}, want {amt}"


@then("the check is refused because a player cannot check when facing a bet")
def _then_check_refused(context):
    assert_rejected(context, "CANNOT_CHECK_FACING_BET")


@then("the bet is refused because it is below the minimum bet")
def _then_bet_refused(context):
    assert_rejected(context, "BET_BELOW_MIN")


# --- community-card Then steps ---


@then("{n:d} community cards are revealed")
@then("{n:d} community card is revealed")
def _then_community_revealed(context, n):
    ev = context.world.emitted(P + "CommunityCardsDealt", hand.CommunityCardsDealt())
    assert len(ev.cards) == n, f"{len(ev.cards)} cards revealed, want {n}"


def _assert_phase(context, phase):
    state = _rebuild_state(context)
    want = getattr(pt, phase)
    assert (
        state.current_phase == want
    ), f"phase = {pt.BettingPhase.Name(state.current_phase)}, want {phase}"


# Explicit per-phase steps (not a generic {phase}) so they don't collide with
# the process manager's "the hand is in the dealing phase".
@then("the hand is in the FLOP phase")
def _then_flop_phase(context):
    _assert_phase(context, "FLOP")


@then("the hand is in the TURN phase")
def _then_turn_phase(context):
    _assert_phase(context, "TURN")


@then("the hand is in the RIVER phase")
def _then_river_phase(context):
    _assert_phase(context, "RIVER")


@then("{n:d} cards have been removed from the remaining deck")
def _then_cards_removed(context, n):
    after = len(_rebuild_state(context).remaining_deck)
    removed = context.deck_before - after
    assert removed == n, f"{removed} cards removed, want {n}"


@then("there are {n:d} community cards in play")
def _then_community_in_play(context, n):
    state = _rebuild_state(context)
    assert (
        len(state.community_cards) == n
    ), f"{len(state.community_cards)} community cards, want {n}"
