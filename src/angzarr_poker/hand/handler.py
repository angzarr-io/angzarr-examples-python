"""Hand aggregate business seam — dealing + blinds subset.

Implements the deal and blind-posting slice of ``HandAggregateHandler`` on the
angzarr-cli generated seam: ``deal_cards`` builds a 52-card deck, deterministically
shuffles it (seeded from table_root + hand_number — there is no deck seed on the
command in the v1 contract), deals the per-variant hole-card count, and emits
``CardsDealt``; ``post_blind`` caps the blind at the player's stack (all-in) and
emits ``BlindPosted`` carrying the absolute stack and pot after posting. State is
the proto ``HandState``; the appliers fold those two events.

The remaining command/applier methods (player actions, community cards, draw,
showdown, pot award) are not ported yet — they raise NotImplementedError so an
unported path fails loudly rather than silently no-op'ing.
"""

from __future__ import annotations

import hashlib
import random
from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as _hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.hand_aggregate_angzarr import (
    HandAggregateHandler,
)

# Hole cards dealt per player by variant (the dealing subset).
_HOLE_CARDS = {
    _pt.TEXAS_HOLDEM: 2,
    _pt.OMAHA: 4,
    _pt.FIVE_CARD_DRAW: 5,
}

_RANKS = [
    _pt.TWO,
    _pt.THREE,
    _pt.FOUR,
    _pt.FIVE,
    _pt.SIX,
    _pt.SEVEN,
    _pt.EIGHT,
    _pt.NINE,
    _pt.TEN,
    _pt.JACK,
    _pt.QUEEN,
    _pt.KING,
    _pt.ACE,
]
_SUITS = [_pt.CLUBS, _pt.DIAMONDS, _pt.HEARTS, _pt.SPADES]


def _now() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _book(*events) -> _t.EventBook:
    book = _t.EventBook()
    for ev in events:
        book.pages.add().event.CopyFrom(_az.pack(ev))
    return book


def _fresh_deck() -> list:
    return [_pt.Card(suit=s, rank=r) for s in _SUITS for r in _RANKS]


def _shuffled_deck(table_root: bytes, hand_number: int) -> list:
    """A deterministic shuffle from the hand's identity. Fallback for hands dealt
    without a preceding Shuffle command (e.g. legacy paths); reproducible for
    replay without being part of the command."""
    seed = int.from_bytes(
        hashlib.sha256(table_root + hand_number.to_bytes(8, "big")).digest()[:8], "big"
    )
    deck = _fresh_deck()
    random.Random(seed).shuffle(deck)
    return deck


def _deck_from_seed(seed: bytes) -> list:
    """A deterministic deck order from an explicit Shuffle seed (the production
    saga passes ``seed = hand_root``). Same determinism contract as
    ``_shuffled_deck`` — reproducible for replay — but driven by the seed the
    command carries rather than re-derived from hand identity."""
    n = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big")
    deck = _fresh_deck()
    random.Random(n).shuffle(deck)
    return deck


def _find_player(state: _hand.HandState, player_root: bytes):
    for p in state.players:
        if p.player_root == player_root:
            return p
    return None


def _pot_total(state: _hand.HandState) -> int:
    return sum(p.total_invested for p in state.players)


class HandAggregate:
    """Implements ``HandAggregateHandler`` for the dealing + blinds subset."""

    # --- command handlers ---

    def shuffle(
        self, cmd: _hand.Shuffle, state: _hand.HandState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        """Establish the deck for the hand. The production saga emits this with
        ``seed = hand_root`` for a deterministic per-hand shuffle; tests can pin
        a layout with an explicit ``deck``. Exactly one of the two must be set —
        an empty Shuffle is rejected so the cluster never silently falls back to
        a non-deterministic deck. Emits ``DeckShuffled`` whose deck the applier
        stores on the hand so ``deal_cards`` draws from it."""
        if state.remaining_deck:
            raise _az.reject(
                "DECK_ALREADY_SHUFFLED", "The deck has already been shuffled"
            )
        has_deck = len(cmd.deck) > 0
        has_seed = len(cmd.seed) > 0
        if has_deck == has_seed:
            raise _az.reject(
                "DECK_SOURCE_REQUIRED", "Exactly one of deck or seed must be set"
            )
        if has_deck:
            deck = list(cmd.deck)
            if len(deck) != 52 or len({(c.suit, c.rank) for c in deck}) != 52:
                raise _az.reject(
                    "INVALID_DECK",
                    "A pinned deck must be all 52 cards with no duplicates",
                )
        else:
            deck = _deck_from_seed(cmd.seed)
        return _book(_hand.DeckShuffled(deck=deck, shuffled_at=_now()))

    def deal_cards(
        self, cmd: _hand.DealCards, state: _hand.HandState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if state.players or state.status:
            raise _az.reject("HAND_ALREADY_DEALT", "Hand has already been dealt")
        if len(cmd.players) < 2:
            raise _az.reject(
                "NOT_ENOUGH_PLAYERS", "At least 2 players are required to deal"
            )

        hole = _HOLE_CARDS.get(cmd.game_variant)
        if hole is None:
            raise _az.reject(
                "UNSUPPORTED_VARIANT", "Unsupported game variant for dealing"
            )

        # Draw from the deck a preceding Shuffle established (DeckShuffled →
        # state.remaining_deck); fall back to the identity-derived shuffle for
        # hands dealt without one.
        if state.remaining_deck:
            deck = list(state.remaining_deck)
        else:
            deck = _shuffled_deck(cmd.table_root, cmd.hand_number)
        cursor = 0
        player_cards = []
        for p in cmd.players:
            dealt = deck[cursor : cursor + hole]
            cursor += hole
            player_cards.append(
                _hand.PlayerHoleCards(player_root=p.player_root, cards=dealt)
            )

        event = _hand.CardsDealt(
            table_root=cmd.table_root,
            hand_number=cmd.hand_number,
            game_variant=cmd.game_variant,
            player_cards=player_cards,
            dealer_position=cmd.dealer_position,
            players=cmd.players,
            remaining_deck=deck[cursor:],
            betting_format=cmd.betting_format,
            dealt_at=_now(),
        )
        return _book(event)

    def post_blind(
        self, cmd: _hand.PostBlind, state: _hand.HandState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        player = _find_player(state, cmd.player_root)
        if player is None:
            raise _az.reject("PLAYER_NOT_IN_HAND", "Player is not in this hand")

        posted = min(cmd.amount, player.stack)  # all-in cap
        new_stack = player.stack - posted
        event = _hand.BlindPosted(
            player_root=cmd.player_root,
            blind_type=cmd.blind_type,
            amount=posted,
            player_stack=new_stack,
            pot_total=_pot_total(state) + posted,
            posted_at=_now(),
        )
        return _book(event)

    # --- event appliers ---

    def apply_deck_shuffled(
        self, state: _hand.HandState, event: _hand.DeckShuffled
    ) -> None:
        del state.remaining_deck[:]
        state.remaining_deck.extend(event.deck)

    def apply_cards_dealt(
        self, state: _hand.HandState, event: _hand.CardsDealt
    ) -> None:
        state.table_root = event.table_root
        state.hand_number = event.hand_number
        state.game_variant = event.game_variant
        state.dealer_position = event.dealer_position
        # Replace (not extend): CardsDealt.remaining_deck is the authoritative
        # post-deal deck. A preceding DeckShuffled may have stored the full 52
        # here; the deal consumed the hole cards, so the leftover supersedes it.
        del state.remaining_deck[:]
        state.remaining_deck.extend(event.remaining_deck)
        state.status = "betting"
        cards_by_player = {pc.player_root: pc.cards for pc in event.player_cards}
        for p in event.players:
            ph = state.players.add()
            ph.player_root = p.player_root
            ph.position = p.position
            ph.stack = p.stack
            ph.hole_cards.extend(cards_by_player.get(p.player_root, []))

    def apply_blind_posted(
        self, state: _hand.HandState, event: _hand.BlindPosted
    ) -> None:
        player = _find_player(state, event.player_root)
        if player is not None:
            player.stack = event.player_stack
            player.total_invested += event.amount
            player.bet_this_round += event.amount
            if event.player_stack == 0:
                player.is_all_in = True

    # --- not-yet-ported seam (fail loudly rather than silently no-op) ---

    def player_action(self, cmd, state, cctx):
        raise NotImplementedError("player_action not ported")

    def deal_community_cards(self, cmd, state, cctx):
        raise NotImplementedError("deal_community_cards not ported")

    def request_draw(self, cmd, state, cctx):
        raise NotImplementedError("request_draw not ported")

    def reveal_cards(self, cmd, state, cctx):
        raise NotImplementedError("reveal_cards not ported")

    def award_pot(
        self, cmd: _hand.AwardPot, state: _hand.HandState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        """Fast-forward hand completion: pay the named winners and finish the
        hand. Tournament acceptance uses this to close a hand without scripting
        every betting action — the pot award is the observable outcome the
        downstream saga (PotAwarded → DepositFunds) and read models react to."""
        if not cmd.awards:
            raise _az.reject("NO_AWARDS", "AwardPot must name at least one winner")
        winners = [
            _hand.PotWinner(
                player_root=a.player_root, amount=a.amount, pot_type=a.pot_type
            )
            for a in cmd.awards
        ]
        return _book(_hand.PotAwarded(winners=winners, awarded_at=_now()))

    def post_blinds(self, cmd, state, cctx):
        raise NotImplementedError("post_blinds not ported")

    def apply_action_taken(self, state, event):
        raise NotImplementedError("apply_action_taken not ported")

    def apply_betting_round_complete(self, state, event):
        raise NotImplementedError("apply_betting_round_complete not ported")

    def apply_community_cards_dealt(self, state, event):
        raise NotImplementedError("apply_community_cards_dealt not ported")

    def apply_draw_completed(self, state, event):
        raise NotImplementedError("apply_draw_completed not ported")

    def apply_showdown_started(self, state, event):
        raise NotImplementedError("apply_showdown_started not ported")

    def apply_pot_awarded(
        self, state: _hand.HandState, event: _hand.PotAwarded
    ) -> None:
        # The pot is awarded; credit each winner's stack and finish the hand.
        credit = {w.player_root: w.amount for w in event.winners}
        for p in state.players:
            p.stack += credit.get(p.player_root, 0)
        state.status = "complete"

    def apply_hand_complete(self, state, event):
        raise NotImplementedError("apply_hand_complete not ported")


# Static guarantee that the class satisfies the generated Protocol.
_: HandAggregateHandler = HandAggregate()
