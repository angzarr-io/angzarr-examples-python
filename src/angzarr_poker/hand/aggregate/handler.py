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


# Hold'em / Omaha community-card street machine: current phase -> (next phase,
# cards dealt on that street). Five Card Draw has no community cards and is
# rejected up front; RIVER has no successor (the next step is showdown).
_NEXT_PHASE = {
    _pt.PREFLOP: (_pt.FLOP, 3),
    _pt.FLOP: (_pt.TURN, 1),
    _pt.TURN: (_pt.RIVER, 1),
}


def _next_active_position(state: _hand.HandState, after: int) -> int:
    """The seat after ``after`` that can still act (not folded, not all-in),
    wrapping around the table. ``-1`` when nobody is left to act. Bookkeeping
    only — turn-order is not enforced in this core subset."""
    live = sorted(
        p.position for p in state.players if not p.has_folded and not p.is_all_in
    )
    if not live:
        return -1
    for pos in live:
        if pos > after:
            return pos
    return live[0]


def _player_at(state: _hand.HandState, position: int):
    for p in state.players:
        if p.position == position:
            return p
    return None


def _turn_assigned(state: _hand.HandState, next_pos: int) -> _hand.TurnAssigned:
    """Announce the next-to-act seat and the raise-tracking surface it faces:
    ``amount_to_call`` is the absolute level to match (== current_bet) and
    ``min_raise`` the minimum legal raise increment (== state.min_raise). Read
    off the POST-event state the caller has already folded into a copy."""
    player = _player_at(state, next_pos)
    return _hand.TurnAssigned(
        player_root=player.player_root if player is not None else b"",
        seat_position=next_pos,
        amount_to_call=state.current_bet,
        min_raise=state.min_raise,
        phase=state.current_phase,
        assigned_at=_now(),
    )


def _round_complete(state: _hand.HandState) -> bool:
    """A betting round closes once every live seat that can still act has acted
    and matched the current bet (or everyone is all-in). A heads-up fold-out
    (one contender left) is the hand-end path, not a round close, so it returns
    False here."""
    contenders = [p for p in state.players if not p.has_folded]
    if len(contenders) < 2:
        return False
    actionable = [p for p in contenders if not p.is_all_in]
    return all(
        p.has_acted and p.bet_this_round == state.current_bet for p in actionable
    )


def _betting_round_complete(state: _hand.HandState) -> _hand.BettingRoundComplete:
    """The street-close event, carrying the pot and a per-seat stack snapshot
    read off the post-final-action state."""
    return _hand.BettingRoundComplete(
        completed_phase=state.current_phase,
        pot_total=_pot_total(state),
        stacks=[
            _hand.PlayerStackSnapshot(
                player_root=p.player_root,
                stack=p.stack,
                is_all_in=p.is_all_in,
                has_folded=p.has_folded,
            )
            for p in state.players
        ],
        completed_at=_now(),
    )


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
        # The big blind opens the betting: announce the first actor and the
        # call/min-raise level it faces (raise-tracking surface). The small
        # blind doesn't open betting, so it assigns no turn.
        if cmd.blind_type == "big":
            after = _hand.HandState()
            after.CopyFrom(state)
            self.apply_blind_posted(after, event)
            nxt = _next_active_position(after, after.big_blind_position)
            if nxt >= 0:
                return _book(event, _turn_assigned(after, nxt))
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
        state.current_phase = _pt.PREFLOP
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
            # Establish the betting level the round opens at. The big blind
            # sets current_bet and the minimum raise increment (NLHE: min
            # raise == big blind at the start of the street). The proto
            # HandState carries no blind-amount fields, so the BB amount is
            # captured here via current_bet/min_raise.
            if event.blind_type == "small":
                state.small_blind_position = player.position
            elif event.blind_type == "big":
                state.big_blind_position = player.position
                if event.amount > state.current_bet:
                    state.current_bet = event.amount
                state.min_raise = event.amount
                # Remember the BB so each new street can reset the min raise.
                state.big_blind = event.amount

    # --- not-yet-ported seam (fail loudly rather than silently no-op) ---

    def player_action(
        self,
        cmd: _hand.PlayerAction,
        state: _hand.HandState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        """Process a No-Limit Hold'em betting action and emit ``ActionTaken``.

        Core NLHE only (TDA Rules 3/43/55): FOLD, CHECK (illegal facing a bet),
        CALL (capped at stack -> all-in), BET (rejected below the minimum or
        when a bet already exists), RAISE (min-raise enforced; capped at stack
        -> all-in), and ALL_IN. ``amount`` on the event is the chips this action
        adds to the pot; ``amount_to_call`` is the absolute level the next actor
        must reach. Advanced TDA behaviours (string-bet, chip-motion, verbal
        declarations, fixed-limit caps, turn-order enforcement) are out of scope.
        """
        if state.status != "betting":
            raise _az.reject(
                "NOT_IN_BETTING_PHASE", "The hand is not in a betting phase"
            )
        if not cmd.player_root:
            raise _az.reject("PLAYER_ROOT_REQUIRED", "A player must be identified")
        player = _find_player(state, cmd.player_root)
        if player is None:
            raise _az.reject("PLAYER_NOT_IN_HAND", "Player is not in this hand")
        if player.has_folded:
            raise _az.reject("PLAYER_HAS_FOLDED", "Player has already folded")
        if player.is_all_in:
            raise _az.reject("PLAYER_IS_ALL_IN", "Player is already all-in")

        action = cmd.action
        amount = cmd.amount
        call_amount = state.current_bet - player.bet_this_round
        chips_put_in = amount
        event_amount = amount

        if action == _pt.FOLD:
            chips_put_in = 0
            event_amount = 0
        elif action == _pt.CHECK:
            if call_amount > 0:
                raise _az.reject(
                    "CANNOT_CHECK_FACING_BET",
                    "A player cannot check when facing a bet",
                )
            chips_put_in = 0
            event_amount = 0
        elif action == _pt.CALL:
            if call_amount == 0:
                raise _az.reject("NOTHING_TO_CALL", "There is nothing to call")
            chips_put_in = min(call_amount, player.stack)  # all-in cap
            event_amount = chips_put_in
            if player.stack - chips_put_in == 0:
                action = _pt.ALL_IN
        elif action == _pt.BET:
            if state.current_bet > 0:
                raise _az.reject(
                    "BET_OVER_EXISTING_BET",
                    "There is already a bet to be matched",
                )
            if amount < state.min_raise and amount < player.stack:
                raise _az.reject("BET_BELOW_MIN", "The bet is below the minimum bet")
            if amount > player.stack:
                raise _az.reject(
                    "BET_EXCEEDS_STACK", "The bet exceeds the player's stack"
                )
            chips_put_in = amount
            event_amount = amount
            if player.stack - chips_put_in == 0:
                action = _pt.ALL_IN
        elif action == _pt.RAISE:
            if state.current_bet == 0:
                raise _az.reject("CANNOT_RAISE_NO_BET", "There is no bet to raise")
            raise_amount = amount - state.current_bet
            to_put_in = amount - player.bet_this_round
            if raise_amount < state.min_raise and to_put_in < player.stack:
                raise _az.reject(
                    "RAISE_BELOW_MIN", "The raise is below the minimum raise"
                )
            if to_put_in > player.stack:
                raise _az.reject(
                    "RAISE_EXCEEDS_STACK", "The raise exceeds the player's stack"
                )
            chips_put_in = to_put_in
            event_amount = chips_put_in
            if player.stack - chips_put_in == 0:
                action = _pt.ALL_IN
        elif action == _pt.ALL_IN:
            chips_put_in = player.stack
            event_amount = chips_put_in
        else:
            raise _az.reject("INVALID_ACTION", "The action type is not recognised")

        new_stack = player.stack - chips_put_in
        event = _hand.ActionTaken(
            player_root=cmd.player_root,
            action=action,
            amount=event_amount,
            player_stack=new_stack,
            pot_total=_pot_total(state) + chips_put_in,
            # Absolute level the next actor must reach to call; consumers owe
            # amount_to_call - their.bet_this_round.
            amount_to_call=max(state.current_bet, player.bet_this_round + chips_put_in),
            action_at=_now(),
        )
        # When this action closes the round (every live seat has acted and
        # matched, or all are all-in), emit BettingRoundComplete; otherwise hand
        # action to the next live seat with the post-action call/min-raise level.
        after = _hand.HandState()
        after.CopyFrom(state)
        self.apply_action_taken(after, event)
        if _round_complete(after):
            return _book(event, _betting_round_complete(after))
        nxt = after.action_on_position
        if nxt >= 0:
            return _book(event, _turn_assigned(after, nxt))
        return _book(event)

    def deal_community_cards(
        self,
        cmd: _hand.DealCommunityCards,
        state: _hand.HandState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        """Deal the next community-card street (flop/turn/river) for Hold'em or
        Omaha. Draws ``count`` cards off the front of the remaining deck (no
        burn in this core subset), appends to the board, advances the phase, and
        emits ``CommunityCardsDealt`` carrying the new cards and the full board.
        The applier resets per-round betting state on the new street."""
        if not state.players or not state.status:
            raise _az.reject("HAND_NOT_DEALT", "The hand has not been dealt")
        if state.status == "complete":
            raise _az.reject("HAND_ALREADY_COMPLETE", "The hand is already complete")
        if cmd.count <= 0:
            raise _az.reject(
                "MUST_DEAL_AT_LEAST_ONE", "At least one card must be dealt"
            )
        if state.game_variant == _pt.FIVE_CARD_DRAW:
            raise _az.reject(
                "NO_COMMUNITY_CARDS", "This variant has no community cards"
            )
        transition = _NEXT_PHASE.get(state.current_phase)
        if transition is None:
            raise _az.reject("NO_MORE_PHASES", "No further community-card phases")
        next_phase, expected = transition
        if expected != cmd.count:
            phase_name = _pt.BettingPhase.Name(next_phase)
            raise _az.reject(
                "WRONG_CARD_COUNT",
                f"The {phase_name.lower()} expects {expected} cards, got {cmd.count}",
            )
        if len(state.remaining_deck) < cmd.count:
            raise _az.reject("NOT_ENOUGH_CARDS", "Not enough cards remain in the deck")
        new_cards = list(state.remaining_deck[: cmd.count])
        all_community = list(state.community_cards) + new_cards
        event = _hand.CommunityCardsDealt(
            cards=new_cards,
            phase=next_phase,
            all_community_cards=all_community,
            dealt_at=_now(),
        )
        # Open the new street: announce the first live actor with the reset call
        # level (0) and minimum raise (the big blind).
        after = _hand.HandState()
        after.CopyFrom(state)
        self.apply_community_cards_dealt(after, event)
        nxt = _next_active_position(after, after.dealer_position)
        if nxt >= 0:
            return _book(event, _turn_assigned(after, nxt))
        return _book(event)

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

    def post_blinds(
        self, cmd: _hand.PostBlinds, state: _hand.HandState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        """Batch blind-posting command from the hand-flow process manager. The
        current v1 ``PostBlinds`` carries only ``hand_root`` and the proto
        ``HandState`` stores no blind-level amounts, so the aggregate has no
        authoritative source for the SB/BB values here; the singular
        ``PostBlind`` path (driven with explicit amounts) is what the tests and
        the production blind sequence use. Emits nothing rather than guessing."""
        return None

    def apply_action_taken(
        self, state: _hand.HandState, event: _hand.ActionTaken
    ) -> None:
        player = _find_player(state, event.player_root)
        if player is not None:
            player.stack = event.player_stack
            player.has_acted = True
            if event.action == _pt.FOLD:
                player.has_folded = True
            elif event.action in (_pt.CALL, _pt.BET, _pt.RAISE):
                player.bet_this_round += event.amount
                player.total_invested += event.amount
            elif event.action == _pt.ALL_IN:
                player.is_all_in = True
                player.bet_this_round += event.amount
                player.total_invested += event.amount
            # A bet/raise/all-in that crosses the current level raises it and
            # sets the new minimum raise increment (NLHE).
            if event.action in (_pt.BET, _pt.RAISE, _pt.ALL_IN):
                if player.bet_this_round > state.current_bet:
                    raise_increment = player.bet_this_round - state.current_bet
                    state.current_bet = player.bet_this_round
                    state.min_raise = max(state.min_raise, raise_increment)
        # Bookkeeping: advance the action marker to the next live seat.
        state.action_on_position = _next_active_position(
            state, player.position if player is not None else -1
        )

    def apply_turn_assigned(
        self, state: _hand.HandState, event: _hand.TurnAssigned
    ) -> None:
        """Notification event — the action marker follows the announced seat;
        no other state changes (current_bet/min_raise are set by the action
        that triggered the assignment)."""
        state.action_on_position = event.seat_position

    def apply_betting_round_complete(
        self, state: _hand.HandState, event: _hand.BettingRoundComplete
    ) -> None:
        """Reset per-round betting state at a street boundary: clear each seat's
        round bet and acted flag, drop the current bet, and reset the minimum
        raise to the big blind (NLHE: min raise == BB at the start of each
        street, TDA Rule 47A). For Five Card Draw, completing preflop advances
        the phase to the draw."""
        for p in state.players:
            p.bet_this_round = 0
            p.has_acted = False
        state.current_bet = 0
        state.min_raise = state.big_blind
        for snap in event.stacks:
            p = _find_player(state, snap.player_root)
            if p is not None:
                p.stack = snap.stack
                p.is_all_in = snap.is_all_in
                p.has_folded = snap.has_folded
        if (
            state.game_variant == _pt.FIVE_CARD_DRAW
            and event.completed_phase == _pt.PREFLOP
        ):
            state.current_phase = _pt.DRAW

    def apply_community_cards_dealt(
        self, state: _hand.HandState, event: _hand.CommunityCardsDealt
    ) -> None:
        for card in event.cards:
            state.community_cards.append(card)
            for i, dc in enumerate(state.remaining_deck):
                if dc.suit == card.suit and dc.rank == card.rank:
                    del state.remaining_deck[i]
                    break
        state.current_phase = event.phase
        state.status = "betting"
        # New street: per-round betting resets and the min raise returns to the
        # big blind (TDA Rule 47A).
        for p in state.players:
            p.bet_this_round = 0
            p.has_acted = False
        state.current_bet = 0
        state.min_raise = state.big_blind

    def apply_draw_completed(self, state, event):
        raise NotImplementedError("apply_draw_completed not ported")

    def apply_showdown_started(
        self, state: _hand.HandState, event: _hand.ShowdownStarted
    ) -> None:
        state.status = "showdown"

    def apply_pot_awarded(
        self, state: _hand.HandState, event: _hand.PotAwarded
    ) -> None:
        # The pot is awarded; credit each winner's stack and finish the hand.
        credit = {w.player_root: w.amount for w in event.winners}
        for p in state.players:
            p.stack += credit.get(p.player_root, 0)
        state.status = "complete"

    def apply_hand_complete(
        self, state: _hand.HandState, event: _hand.HandComplete
    ) -> None:
        # The hand is over; credit each winner's stack and finish the hand.
        credit = {w.player_root: w.amount for w in event.winners}
        for p in state.players:
            p.stack += credit.get(p.player_root, 0)
        for snap in event.final_stacks:
            p = _find_player(state, snap.player_root)
            if p is not None:
                p.stack = snap.stack
                p.is_all_in = snap.is_all_in
                p.has_folded = snap.has_folded
        state.status = "complete"


# Static guarantee that the class satisfies the generated Protocol.
_: HandAggregateHandler = HandAggregate()
