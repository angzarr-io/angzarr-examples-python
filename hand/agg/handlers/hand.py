"""Hand aggregate - rich domain model."""

import random
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import applies, command_handler, handles, now
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand_proto
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from ..errors import (
    AwardPlayerNotInHand,
    AwardsExceedPot,
    BetBelowMinRaise,
    BetExceedsStack,
    BlindAmountMustBePositive,
    CannotBetOverExistingBet,
    CannotCheckWithBet,
    CannotRaiseWithoutBet,
    CommunityCardsNotUsedInVariant,
    DrawNotSupportedInVariant,
    DuplicateCardIndices,
    FoldedPlayerCannotWin,
    HandAlreadyComplete,
    HandAlreadyDealt,
    HandNotDealt,
    InvalidAction,
    InvalidCardIndex,
    MustDealAtLeast1Card,
    NeedAtLeast2Players,
    NoAwardsSpecified,
    NoMorePhases,
    NoPlayersInHand,
    NotEnoughCardsInDeck,
    NotInBettingPhase,
    NotInShowdownPhase,
    NothingToCall,
    PlayerHasFolded,
    PlayerIsAllIn,
    PlayerNotInHand,
    PlayerRootRequired,
    RaiseBelowMin,
    RaiseExceedsStack,
    TooManyDiscards,
    WinnerNotEligibleForPot,
    WrongCardCountForPhase,
)
from .game_rules import get_game_rules


@dataclass
class _PlayerHandInfo:
    """State for a player in the hand."""

    player_root: bytes = b""
    position: int = 0
    hole_cards: list = field(default_factory=list)
    stack: int = 0
    bet_this_round: int = 0
    total_invested: int = 0
    has_acted: bool = False
    has_folded: bool = False
    is_all_in: bool = False


@dataclass
class _PotInfo:
    """State for a pot."""

    amount: int = 0
    eligible_players: list = field(default_factory=list)
    pot_type: str = "main"


@dataclass
class _HandState:
    """Internal state representation."""

    hand_id: str = ""
    table_root: bytes = b""
    hand_number: int = 0
    game_variant: int = 0
    remaining_deck: list = field(default_factory=list)
    players: dict = field(default_factory=dict)
    community_cards: list = field(default_factory=list)
    current_phase: int = 0
    action_on_position: int = -1
    current_bet: int = 0
    min_raise: int = 0
    pots: list = field(default_factory=list)
    dealer_position: int = 0
    small_blind_position: int = 0
    big_blind_position: int = 0
    small_blind: int = 0
    big_blind: int = 0
    status: str = ""


_APPLIER_REGISTRY: list[tuple[type, str]] = []


@command_handler(domain="hand", state=_HandState)
class Hand:
    """Hand aggregate with event sourcing.

    Supports two call shapes:
      - Stateful: ``Hand(event_book=None)`` — instance owns ``self._state``
        and ``self._events``; handler methods mutate state and track events.
      - Router-dispatched: router passes ``(cmd, state, seq)``; handler binds
        ``self._state`` temporarily and returns the emitted event(s).
    """

    def __init__(self, event_book: types.EventBook | None = None) -> None:
        self._state = _HandState()
        self._events = types.EventBook()
        if event_book is not None:
            for page in event_book.pages:
                new_page = types.EventPage()
                new_page.CopyFrom(page)
                self._events.pages.append(new_page)
                if page.HasField("event"):
                    self._apply_any(page.event, self._state)

    # --- Compatibility helpers (test path) ---

    def _get_state(self) -> _HandState:
        return self._state

    def event_book(self) -> types.EventBook:
        return self._events

    def _emit(self, event) -> None:
        any_msg = ProtoAny()
        any_msg.Pack(event, type_url_prefix="type.googleapis.com/")
        page = types.EventPage(
            event=any_msg,
            header=types.PageHeader(sequence=len(self._events.pages)),
        )
        self._events.pages.append(page)
        self._apply_any(any_msg, self._state)

    def _apply_any(self, event_any: ProtoAny, state: _HandState) -> None:
        for event_type, method_name in _APPLIER_REGISTRY:
            expected = f"type.googleapis.com/{event_type.DESCRIPTOR.full_name}"
            if event_any.type_url == expected:
                evt = event_type()
                event_any.Unpack(evt)
                getattr(self, method_name)(state, evt)
                return

    def _router_bind(self, state):
        saved = self._state
        self._state = state
        return saved

    # --- Event appliers ---

    @applies(hand_proto.CommunityCardsDealt)
    def apply_community_cards_dealt(
        self, state: _HandState, event: hand_proto.CommunityCardsDealt
    ) -> None:
        for card in event.cards:
            dealt_card = (card.suit, card.rank)
            state.community_cards.append(dealt_card)
            if dealt_card in state.remaining_deck:
                state.remaining_deck.remove(dealt_card)
        state.current_phase = event.phase
        state.status = "betting"
        for player in state.players.values():
            player.bet_this_round = 0
            player.has_acted = False
        state.current_bet = 0

    @applies(hand_proto.CardsDealt)
    def apply_cards_dealt(
        self, state: _HandState, event: hand_proto.CardsDealt
    ) -> None:
        state.hand_id = f"{event.table_root.hex()}_{event.hand_number}"
        state.table_root = event.table_root
        state.hand_number = event.hand_number
        state.game_variant = event.game_variant
        state.dealer_position = event.dealer_position
        state.status = "betting"
        state.current_phase = poker_types.PREFLOP

        for player in event.players:
            state.players[player.position] = _PlayerHandInfo(
                player_root=player.player_root,
                position=player.position,
                stack=player.stack,
            )

        dealt_cards = set()
        for pc in event.player_cards:
            for pos, player in state.players.items():
                if player.player_root == pc.player_root:
                    player.hole_cards = [(c.suit, c.rank) for c in pc.cards]
                    for c in pc.cards:
                        dealt_cards.add((c.suit, c.rank))

        full_deck = []
        for suit in [
            poker_types.CLUBS,
            poker_types.DIAMONDS,
            poker_types.HEARTS,
            poker_types.SPADES,
        ]:
            for rank in range(2, 15):
                card = (suit, rank)
                if card not in dealt_cards:
                    full_deck.append(card)
        random.shuffle(full_deck)
        state.remaining_deck = full_deck

        state.pots = [
            _PotInfo(
                amount=0,
                eligible_players=[p.player_root for p in state.players.values()],
                pot_type="main",
            )
        ]

    @applies(hand_proto.BlindPosted)
    def apply_blind_posted(
        self, state: _HandState, event: hand_proto.BlindPosted
    ) -> None:
        for player in state.players.values():
            if player.player_root == event.player_root:
                player.stack = event.player_stack
                player.bet_this_round = event.amount
                player.total_invested += event.amount
                if event.blind_type == "small":
                    state.small_blind_position = player.position
                    state.small_blind = event.amount
                elif event.blind_type == "big":
                    state.big_blind_position = player.position
                    state.big_blind = event.amount
                    state.current_bet = event.amount
                    state.min_raise = event.amount
                break
        if state.pots:
            state.pots[0].amount = event.pot_total
        state.status = "betting"

    @applies(hand_proto.ActionTaken)
    def apply_action_taken(
        self, state: _HandState, event: hand_proto.ActionTaken
    ) -> None:
        for player in state.players.values():
            if player.player_root == event.player_root:
                player.stack = event.player_stack
                player.has_acted = True
                if event.action == poker_types.FOLD:
                    player.has_folded = True
                elif event.action in (
                    poker_types.CALL,
                    poker_types.BET,
                    poker_types.RAISE,
                ):
                    player.bet_this_round += event.amount
                    player.total_invested += event.amount
                elif event.action == poker_types.ALL_IN:
                    player.is_all_in = True
                    player.bet_this_round += event.amount
                    player.total_invested += event.amount
                if event.action in (
                    poker_types.BET,
                    poker_types.RAISE,
                    poker_types.ALL_IN,
                ):
                    if player.bet_this_round > state.current_bet:
                        raise_amount = player.bet_this_round - state.current_bet
                        state.current_bet = player.bet_this_round
                        state.min_raise = max(state.min_raise, raise_amount)
                break
        if state.pots:
            state.pots[0].amount = event.pot_total
        state.action_on_position = -1

    @applies(hand_proto.BettingRoundComplete)
    def apply_betting_round_complete(
        self, state: _HandState, event: hand_proto.BettingRoundComplete
    ) -> None:
        """Reset per-round betting state and advance Five Card Draw from
        preflop → draw. Other variants get their phase change from
        CommunityCardsDealt; this applier handles the one transition that
        has no community-card event.

        Real-poker NLHE convention: ``min_raise`` resets to the big blind
        at the start of every street. Carrying preflop's increment forward
        would spuriously reject legal flop/turn/river bets that exceed BB
        but fall short of the prior preflop raise increment.
        """
        for player in state.players.values():
            player.bet_this_round = 0
            player.has_acted = False
        state.current_bet = 0
        state.min_raise = state.big_blind

        for snap in event.stacks:
            for player in state.players.values():
                if player.player_root == snap.player_root:
                    player.stack = snap.stack
                    player.is_all_in = snap.is_all_in
                    player.has_folded = snap.has_folded
                    break

        if state.game_variant == poker_types.FIVE_CARD_DRAW:
            if event.completed_phase == poker_types.PREFLOP:
                state.current_phase = poker_types.DRAW

    @applies(hand_proto.ShowdownStarted)
    def apply_showdown_started(
        self, state: _HandState, event: hand_proto.ShowdownStarted
    ) -> None:
        state.status = "showdown"

    @applies(hand_proto.DrawCompleted)
    def apply_draw_completed(
        self, state: _HandState, event: hand_proto.DrawCompleted
    ) -> None:
        for player in state.players.values():
            if player.player_root == event.player_root:
                pre = list(player.hole_cards)
                new_hole = [(c.suit, c.rank) for c in event.new_cards]
                player.hole_cards = new_hole
                # Each card now in the hand that wasn't there before came off
                # the deck; remove from `remaining_deck` to keep the deck and
                # hands consistent for replay.
                pre_set = set(pre)
                for card in new_hole:
                    if card not in pre_set and card in state.remaining_deck:
                        state.remaining_deck.remove(card)
                break

    @applies(hand_proto.PotAwarded)
    def apply_pot_awarded(
        self, state: _HandState, event: hand_proto.PotAwarded
    ) -> None:
        for winner in event.winners:
            for player in state.players.values():
                if player.player_root == winner.player_root:
                    player.stack += winner.amount
                    break

    @applies(hand_proto.HandComplete)
    def apply_hand_complete(
        self, state: _HandState, event: hand_proto.HandComplete
    ) -> None:
        state.status = "complete"

    # --- State accessors ---

    @property
    def exists(self) -> bool:
        return self._state.status != ""

    @property
    def hand_id(self) -> str:
        return self._state.hand_id

    @property
    def table_root(self) -> bytes:
        return self._state.table_root

    @property
    def hand_number(self) -> int:
        return self._state.hand_number

    @property
    def game_variant(self) -> int:
        return self._state.game_variant

    @property
    def status(self) -> str:
        return self._state.status

    @property
    def current_phase(self) -> int:
        return self._state.current_phase

    @property
    def current_bet(self) -> int:
        return self._state.current_bet

    @property
    def min_raise(self) -> int:
        return self._state.min_raise

    @property
    def small_blind(self) -> int:
        return self._state.small_blind

    @property
    def big_blind(self) -> int:
        return self._state.big_blind

    @property
    def community_cards(self) -> list:
        return self._state.community_cards

    @property
    def players(self) -> dict:
        return self._state.players

    @property
    def remaining_deck(self) -> list:
        return self._state.remaining_deck

    def get_pot_total(self) -> int:
        return sum(p.amount for p in self._state.pots)

    def get_player(self, player_root: bytes) -> Optional[_PlayerHandInfo]:
        for p in self._state.players.values():
            if p.player_root == player_root:
                return p
        return None

    def get_active_players(self) -> list:
        return [
            p
            for p in self._state.players.values()
            if not p.has_folded and not p.is_all_in
        ]

    def get_players_in_hand(self) -> list:
        return [p for p in self._state.players.values() if not p.has_folded]

    def compute_side_pots(self) -> Tuple[list, int]:
        """Compute layered pots from current per-player ``total_invested``.

        Real poker (TDA Rule 42): when stacks differ at all-in, the pot
        layers into a main pot eligible to all contributors and one or
        more side pots eligible only to the players whose contribution
        reached or exceeded each layer's all-in level. Folded players'
        chips remain in the lowest layer they participated in.

        Returns ``(pots, uncontested_return)`` where:
          - ``pots`` is a list of ``_PotInfo`` ordered main → side_1 → ...
          - ``uncontested_return`` is the chip count that the deepest
            stack over-bet beyond what any opponent could match (returned
            to that player; not part of any pot).

        Eligibility = the set of un-folded ``player_root``s whose
        ``total_invested`` is at least the layer's level.
        """
        s = self._state
        contributions: list[tuple[bytes, int, bool]] = [
            (p.player_root, p.total_invested, p.has_folded)
            for p in s.players.values()
            if p.total_invested > 0
        ]
        if not contributions:
            return [], 0

        # Layer levels are the distinct invested amounts of un-folded
        # players, ascending. Folded players' contributions count toward
        # whichever layers they reached but they are never eligible to win.
        active_levels = sorted(
            {amount for _, amount, folded in contributions if not folded}
        )
        if not active_levels:
            # Everyone folded. Whatever is in the pot goes uncontested to
            # whoever was last to act — caller decides; here just return
            # one main pot with the full sum and no eligibles.
            total = sum(amount for _, amount, _ in contributions)
            return ([_PotInfo(amount=total, eligible_players=[], pot_type="main")], 0)

        pots: list[_PotInfo] = []
        prev_level = 0
        for idx, level in enumerate(active_levels):
            layer_amount = 0
            eligible: list[bytes] = []
            for root, invested, folded in contributions:
                slice_size = max(0, min(invested, level) - prev_level)
                layer_amount += slice_size
                if not folded and invested >= level:
                    eligible.append(root)
            pot_type = "main" if idx == 0 else f"side_{idx}"
            pots.append(
                _PotInfo(
                    amount=layer_amount,
                    eligible_players=eligible,
                    pot_type=pot_type,
                )
            )
            prev_level = level

        # Uncontested over-bet: any chips the deepest stack invested
        # beyond the highest active all-in level (no one could match).
        deepest_active = active_levels[-1]
        uncontested = 0
        for root, invested, folded in contributions:
            if not folded and invested > deepest_active:
                uncontested += invested - deepest_active

        return pots, uncontested

    # --- Command handlers ---

    @handles(hand_proto.DealCards)
    def handle_deal_cards(
        self,
        cmd: hand_proto.DealCards,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.CardsDealt:
        """Deal cards to start the hand."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if self.exists:
                raise HandAlreadyDealt()
            if not cmd.players:
                raise NoPlayersInHand()
            if len(cmd.players) < 2:
                raise NeedAtLeast2Players(got=len(cmd.players))

            rules = get_game_rules(cmd.game_variant)
            player_roots = [p.player_root for p in cmd.players]
            deal_result = rules.deal_hole_cards(
                deck=[],
                players=player_roots,
                seed=cmd.deck_seed if cmd.deck_seed else None,
            )

            player_cards = []
            for player_root, cards in deal_result.player_cards.items():
                pc = hand_proto.PlayerHoleCards(player_root=player_root)
                for suit, rank in cards:
                    pc.cards.append(poker_types.Card(suit=suit, rank=rank))
                player_cards.append(pc)

            event = hand_proto.CardsDealt(
                table_root=cmd.table_root,
                hand_number=cmd.hand_number,
                game_variant=cmd.game_variant,
                dealer_position=cmd.dealer_position,
                dealt_at=now(),
            )
            event.player_cards.extend(player_cards)
            event.players.extend(cmd.players)

            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.PostBlind)
    def handle_post_blind(
        self,
        cmd: hand_proto.PostBlind,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.BlindPosted:
        """Post a blind."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status == "complete":
                raise HandAlreadyComplete()
            if not cmd.player_root:
                raise PlayerRootRequired()

            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            if player.has_folded:
                raise PlayerHasFolded()
            if cmd.amount <= 0:
                raise BlindAmountMustBePositive(value=cmd.amount)

            actual_amount = min(cmd.amount, player.stack)
            new_stack = player.stack - actual_amount
            new_pot_total = self.get_pot_total() + actual_amount

            event = hand_proto.BlindPosted(
                player_root=cmd.player_root,
                blind_type=cmd.blind_type,
                amount=actual_amount,
                player_stack=new_stack,
                pot_total=new_pot_total,
                posted_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.PlayerAction)
    def handle_player_action(
        self,
        cmd: hand_proto.PlayerAction,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.ActionTaken:
        """Process a player action."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status != "betting":
                raise NotInBettingPhase()
            if not cmd.player_root:
                raise PlayerRootRequired()

            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            if player.has_folded:
                raise PlayerHasFolded()
            if player.is_all_in:
                raise PlayerIsAllIn()

            action = cmd.action
            amount = cmd.amount
            call_amount = self.current_bet - player.bet_this_round
            chips_put_in = amount
            event_amount = amount

            if action == poker_types.FOLD:
                chips_put_in = 0
                event_amount = 0
            elif action == poker_types.CHECK:
                if call_amount > 0:
                    raise CannotCheckWithBet()
                chips_put_in = 0
                event_amount = 0
            elif action == poker_types.CALL:
                if call_amount == 0:
                    raise NothingToCall()
                chips_put_in = min(call_amount, player.stack)
                event_amount = chips_put_in
                if player.stack - chips_put_in == 0:
                    action = poker_types.ALL_IN
            elif action == poker_types.BET:
                if self.current_bet > 0:
                    raise CannotBetOverExistingBet()
                if amount < self.min_raise and amount < player.stack:
                    raise BetBelowMinRaise(got=amount, bound=self.min_raise)
                if amount > player.stack:
                    raise BetExceedsStack(got=amount, bound=player.stack)
                chips_put_in = amount
                event_amount = amount
                if player.stack - chips_put_in == 0:
                    action = poker_types.ALL_IN
            elif action == poker_types.RAISE:
                if self.current_bet == 0:
                    raise CannotRaiseWithoutBet()
                raise_amount = amount - self.current_bet
                to_put_in = amount - player.bet_this_round
                if raise_amount < self.min_raise and to_put_in < player.stack:
                    raise RaiseBelowMin(got=amount, bound=self.min_raise)
                if to_put_in > player.stack:
                    raise RaiseExceedsStack(got=amount, bound=player.stack)
                chips_put_in = to_put_in
                event_amount = chips_put_in
                if player.stack - chips_put_in == 0:
                    action = poker_types.ALL_IN
            elif action == poker_types.ALL_IN:
                chips_put_in = player.stack
                event_amount = chips_put_in
            else:
                raise InvalidAction(got=action)

            new_stack = player.stack - chips_put_in
            new_pot_total = self.get_pot_total() + chips_put_in

            event = hand_proto.ActionTaken(
                player_root=cmd.player_root,
                action=action,
                amount=event_amount,
                player_stack=new_stack,
                pot_total=new_pot_total,
                # amount_to_call is the absolute new current_bet level — the
                # threshold a subsequent actor must reach to call. Consumers
                # compute their owed amount as
                # amount_to_call - their.bet_this_round.
                amount_to_call=max(
                    self.current_bet, player.bet_this_round + chips_put_in
                ),
                action_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.DealCommunityCards)
    def handle_deal_community_cards(
        self,
        cmd: hand_proto.DealCommunityCards,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.CommunityCardsDealt:
        """Deal community cards."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status == "complete":
                raise HandAlreadyComplete()
            if cmd.count <= 0:
                raise MustDealAtLeast1Card(got=cmd.count, bound=1)

            s = self._state
            rules = get_game_rules(s.game_variant)

            if rules.variant == poker_types.FIVE_CARD_DRAW:
                raise CommunityCardsNotUsedInVariant()

            transition = rules.get_next_phase(s.current_phase)
            if not transition:
                raise NoMorePhases()
            if transition.community_cards_to_deal != cmd.count:
                phase_name = poker_types.BettingPhase.Name(transition.next_phase)
                raise WrongCardCountForPhase(
                    expected=transition.community_cards_to_deal,
                    got=cmd.count,
                    phase=phase_name,
                )
            if len(s.remaining_deck) < cmd.count:
                raise NotEnoughCardsInDeck(
                    requested=cmd.count, available=len(s.remaining_deck)
                )

            new_cards = s.remaining_deck[: cmd.count]
            all_community = s.community_cards + new_cards

            event = hand_proto.CommunityCardsDealt(
                phase=transition.next_phase,
                dealt_at=now(),
            )
            for suit, rank in new_cards:
                event.cards.append(poker_types.Card(suit=suit, rank=rank))
            for suit, rank in all_community:
                event.all_community_cards.append(poker_types.Card(suit=suit, rank=rank))

            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.RequestDraw)
    def handle_request_draw(
        self,
        cmd: hand_proto.RequestDraw,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.DrawCompleted:
        """Handle draw request for Five Card Draw."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status == "complete":
                raise HandAlreadyComplete()
            if not cmd.player_root:
                raise PlayerRootRequired()

            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            if player.has_folded:
                raise PlayerHasFolded()

            s = self._state
            if s.game_variant != poker_types.FIVE_CARD_DRAW:
                raise DrawNotSupportedInVariant()

            indices = list(cmd.card_indices)
            if len(indices) > 5:
                raise TooManyDiscards(got=len(indices), bound=5)
            if len(set(indices)) != len(indices):
                raise DuplicateCardIndices()
            for idx in indices:
                if idx < 0 or idx >= len(player.hole_cards):
                    raise InvalidCardIndex(got=idx)

            cards_to_draw = len(indices)
            if len(s.remaining_deck) < cards_to_draw:
                raise NotEnoughCardsInDeck(
                    requested=cards_to_draw, available=len(s.remaining_deck)
                )

            drawn = s.remaining_deck[:cards_to_draw]
            updated_hole = list(player.hole_cards)
            for i, idx in enumerate(indices):
                updated_hole[idx] = drawn[i]

            event = hand_proto.DrawCompleted(
                player_root=cmd.player_root,
                cards_discarded=len(indices),
                cards_drawn=cards_to_draw,
                drawn_at=now(),
            )
            for suit, rank in updated_hole:
                event.new_cards.append(poker_types.Card(suit=suit, rank=rank))

            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.RevealCards)
    def handle_reveal_cards(
        self,
        cmd: hand_proto.RevealCards,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> Union[hand_proto.CardsRevealed, hand_proto.CardsMucked]:
        """Reveal or muck cards at showdown."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status != "showdown":
                raise NotInShowdownPhase()
            if not cmd.player_root:
                raise PlayerRootRequired()

            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            if player.has_folded:
                raise PlayerHasFolded()

            if cmd.muck:
                event = hand_proto.CardsMucked(
                    player_root=cmd.player_root,
                    mucked_at=now(),
                )
                if not router_mode:
                    self._emit(event)
                return event

            s = self._state
            rules = get_game_rules(s.game_variant)
            rank_type, score, kickers = rules.evaluate_hand(
                player.hole_cards,
                s.community_cards,
            )

            event = hand_proto.CardsRevealed(
                player_root=cmd.player_root,
                ranking=poker_types.HandRanking(
                    rank_type=rank_type,
                    kickers=[k for k in kickers],
                    score=score,
                ),
                revealed_at=now(),
            )
            for suit, rank in player.hole_cards:
                event.cards.append(poker_types.Card(suit=suit, rank=rank))

            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.AwardPot)
    def handle_award_pot(
        self,
        cmd: hand_proto.AwardPot,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> Tuple[hand_proto.PotAwarded, hand_proto.HandComplete]:
        """Award pot and complete the hand."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status == "complete":
                raise HandAlreadyComplete()
            if not cmd.awards:
                raise NoAwardsSpecified()

            s = self._state

            for award in cmd.awards:
                player = self.get_player(award.player_root)
                if not player:
                    raise AwardPlayerNotInHand()
                if player.has_folded:
                    raise FoldedPlayerCannotWin()

            # Per-pot eligibility (TDA Rule 42): an award assigned to a
            # specific pot_type must target a player who was eligible for
            # that pot. We compute layered pots from current invested
            # amounts and check each award's pot_type membership.
            computed_pots, _uncontested = self.compute_side_pots()
            if computed_pots:
                eligibility = {
                    pot.pot_type: set(pot.eligible_players) for pot in computed_pots
                }
                for award in cmd.awards:
                    pot_type = award.pot_type or "main"
                    eligible_set = eligibility.get(pot_type)
                    if (
                        eligible_set is not None
                        and award.player_root not in eligible_set
                    ):
                        raise WinnerNotEligibleForPot(
                            pot_type=pot_type,
                            player_root=award.player_root.hex(),
                        )

            total_awarded = sum(a.amount for a in cmd.awards)
            pot_total = self.get_pot_total()
            if total_awarded > pot_total:
                raise AwardsExceedPot(got=total_awarded, bound=pot_total)
            awards = list(cmd.awards)
            if total_awarded != pot_total and pot_total > 0 and len(awards) > 0:
                awards[0].amount = pot_total - sum(a.amount for a in awards[1:])

            winners = []
            for award in awards:
                winners.append(
                    hand_proto.PotWinner(
                        player_root=award.player_root,
                        amount=award.amount,
                        pot_type=award.pot_type,
                    )
                )

            pot_event = hand_proto.PotAwarded(awarded_at=now())
            pot_event.winners.extend(winners)

            final_stacks = []
            for player in s.players.values():
                player_amount = sum(
                    a.amount for a in awards if a.player_root == player.player_root
                )
                final_stacks.append(
                    hand_proto.PlayerStackSnapshot(
                        player_root=player.player_root,
                        stack=player.stack + player_amount,
                        is_all_in=player.is_all_in,
                        has_folded=player.has_folded,
                    )
                )

            complete_event = hand_proto.HandComplete(
                table_root=s.table_root,
                hand_number=s.hand_number,
                completed_at=now(),
            )
            complete_event.winners.extend(winners)
            complete_event.final_stacks.extend(final_stacks)

            if not router_mode:
                self._emit(pot_event)
                self._emit(complete_event)
            return pot_event, complete_event
        finally:
            if router_mode:
                self._state = saved


# Populate the applier registry after class definition.
for _name in dir(Hand):
    _attr = getattr(Hand, _name, None)
    _marker = getattr(_attr, "__angzarr_applies__", None)
    if _marker is not None:
        _APPLIER_REGISTRY.append((_marker, _name))
