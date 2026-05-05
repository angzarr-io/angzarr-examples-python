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
    ActionClockNotOnThisPlayer,
    AwardPlayerNotInHand,
    AwardsExceedPot,
    BetBelowMinRaise,
    BetExceedsStack,
    BlindAmountMustBePositive,
    BoundToCallOrRaise,
    CannotBetOverExistingBet,
    CannotCheckWithBet,
    CannotPostAnteAfterBlinds,
    CannotRaiseWithoutBet,
    CommunityCardsNotUsedInVariant,
    DrawNotSupportedInVariant,
    DuplicateCardIndices,
    FaceUpRequired,
    FoldedPlayerCannotWin,
    HandAlreadyComplete,
    DoubledBetNotAllowed4thStreet,
    OpenPairLocksLowerLimit,
    RaiseCapReached,
    StudMuckByPickupForbidden,
    StudTooManyCards,
    HandAlreadyDealt,
    HandNotDealt,
    IncompleteReveal,
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
    PlayerAbsentAtDeal,
    PlayerHasFolded,
    PlayerIsAllIn,
    PlayerNotInHand,
    PlayerRootRequired,
    RaiseBelowMin,
    RaiseExceedsStack,
    RevealOutOfOrder,
    TabledWinnerCannotBeKilled,
    TooManyDiscards,
    WinnerNotEligibleForPot,
    WrongCardCountForPhase,
)
from ..betting_format import (
    apply_limit_short_all_in,
    bet_the_pot_in_no_limit_min,
    correct_declared_underraise,
    interpret_silent_push,
    is_limit_raise_cap_reached,
    pot_limit_max_raise_to_preflop,
)
from ..raise_tracking import reset_per_round
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
    # TDA Rule 30 — true when the player was absent at the initial
    # deal. The hand is killed immediately and may not be resurrected;
    # action attempts are rejected with code PLAYER_ABSENT_AT_DEAL.
    is_absent_at_deal: bool = False
    # TDA Rule 13C — populated when the player tabled their hand at
    # showdown (apply_cards_revealed sets it from the event ranking).
    # ``None`` means the player has not tabled. Used by handle_award_pot
    # to reject awards that would kill a properly-tabled stronger hand.
    tabled_ranking: object | None = None
    # TDA Rule 46 — chips already on the table from a prior bet on the
    # current street. Resets to 0 on every street boundary; tracked so
    # silent top-ups vs pull-backs can be interpreted correctly.
    prior_bet_on_street: int = 0
    # TDA Rule 46B — set true when the player has pulled back a prior
    # chip while facing a raise; subsequent fold attempts are rejected
    # with code BOUND_TO_CALL_OR_RAISE.
    bound_to_call_or_raise: bool = False
    # Stud variants only — the player's accumulated up-cards across
    # 3rd-6th street. Populated on apply_stud_street_dealt; empty for
    # non-stud variants. Down-cards live in ``hole_cards``.
    up_cards: list = field(default_factory=list)


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
    # Ordered queue of player_roots awaiting showdown reveal (head = next
    # to act). Populated by ShowdownStarted; advanced by CardsRevealed /
    # CardsMucked appliers.
    showdown_order: list = field(default_factory=list)
    # TDA Rule 16: when ShowdownStarted carries face_up_required=True, no
    # remaining hand may be mucked. Latched on ShowdownStarted.
    face_up_required: bool = False
    # Betting format (TDA Rules 47B, 48, 52B, 54B/D). 0 means
    # BETTING_FORMAT_UNSPECIFIED — defaults to NO_LIMIT semantics for
    # backward compatibility with hands dealt before the field existed.
    betting_format: int = 0
    # Fixed-limit only: small_bet pre-flop/flop, big_bet on later streets.
    small_bet: int = 0
    big_bet: int = 0
    # Fixed-limit only: cap on raises per round (Rule 48). 0 means
    # "use house default" (4); negative means uncapped (heads-up).
    raise_cap_per_round: int = 0
    # Fixed-limit only: count of RAISE actions on the current street.
    # The opening BET is *not* counted.
    raises_this_round: int = 0
    # Stud-only ante posted at the deal (per-player). Hold'em/Omaha use
    # SB/BB instead and leave this at 0.
    ante: int = 0
    # Stud-only state (TDA RP-10). 0 = STUD_STREET_UNSPECIFIED for
    # non-stud variants; otherwise tracks the currently-active street
    # so 4th-street-specific limit rules (RP-10F open-pair lock) can
    # fire on the BET handler.
    current_stud_street: int = 0
    # Stud-only — true when at least one player on the current street is
    # showing an open pair in their up-cards. Affects fixed-limit bet
    # validation (RP-10F locks Stud Hi to small_bet on 4th street; WSOP
    # extends this to Stud Hi/Lo, EU-1339; Razz does NOT lock — Robert's
    # §RAZZ #3, EU-1341).
    open_pair_on_current_street: bool = False
    # Stud-only — true once the bring-in has been posted (via
    # BringInPosted applier) so subsequent bet-completion logic can
    # distinguish "completing the bring-in" from "raising over a bet".
    bring_in_resolved: bool = False
    # Stud-only — the bring-in amount paid by the bring-in player, used
    # by the BET_COMPLETION handler to determine the chip delta a
    # completion actor must put in (small_bet - bring_in).
    bring_in_amount: int = 0


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

    @applies(hand_proto.BringInPosted)
    def apply_bring_in_posted(
        self, state: _HandState, event: hand_proto.BringInPosted
    ) -> None:
        """Stud-only — record the bring-in posting on the player's
        ``bet_this_round`` and pin ``state.current_bet`` to the bring-in
        amount so the next actor faces a known target. Bring-in is the
        forced-bet equivalent of the big blind for stud hands."""
        for player in state.players.values():
            if player.player_root == event.player_root:
                player.stack = event.player_stack
                player.bet_this_round = event.amount
                player.total_invested += event.amount
                if player.stack == 0:
                    player.is_all_in = True
                break
        state.current_bet = event.amount
        state.bring_in_resolved = True
        state.bring_in_amount = event.amount

    @applies(hand_proto.StudStreetDealt)
    def apply_stud_street_dealt(
        self, state: _HandState, event: hand_proto.StudStreetDealt
    ) -> None:
        """Advance stud street and append per-player up cards.

        The event carries the new ``street`` (StudStreet enum) plus a
        ``up_cards`` list of PlayerUpCards rows — one new visible card
        per remaining player on 4th-6th street, none on 7th street
        (which is dealt face down). After updating per-player up_cards
        we recompute ``state.open_pair_on_current_street`` so the
        downstream BET handler can apply RP-10F / WSOP open-pair locks.
        """
        state.current_stud_street = event.street
        for row in event.up_cards:
            for player in state.players.values():
                if player.player_root == row.player_root:
                    for c in row.up_cards:
                        player.up_cards.append((c.suit, c.rank))
        # An "open pair" is two of the same rank visible in any single
        # player's up_cards. Recompute across all active players each
        # street boundary — RP-10F applies to "a pair showing" anywhere.
        state.open_pair_on_current_street = False
        for player in state.players.values():
            if player.has_folded:
                continue
            seen: dict[int, int] = {}
            for _, rank in player.up_cards:
                seen[rank] = seen.get(rank, 0) + 1
                if seen[rank] >= 2:
                    state.open_pair_on_current_street = True
                    break
            if state.open_pair_on_current_street:
                break
        # Reset per-street betting state so the new street's bets count
        # cleanly against limit caps and current_bet.
        for player in state.players.values():
            player.bet_this_round = 0
            player.has_acted = False
            player.prior_bet_on_street = 0
        state.current_bet = 0
        state.raises_this_round = 0

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
        # Betting-format fields (TDA Rules 47B, 48, 52B, 54B/D). Default
        # to NO_LIMIT when unset for backward compatibility.
        state.betting_format = (
            event.betting_format
            if event.betting_format != poker_types.BETTING_FORMAT_UNSPECIFIED
            else poker_types.BETTING_FORMAT_NO_LIMIT
        )
        state.small_bet = event.small_bet
        state.big_bet = event.big_bet
        state.raise_cap_per_round = event.raise_cap_per_round
        state.ante = event.ante
        state.raises_this_round = 0
        # Stud variants begin on 3rd street with no open pair. Non-stud
        # variants leave these at the unspecified defaults.
        if event.game_variant in (
            poker_types.SEVEN_CARD_STUD,
            poker_types.RAZZ,
            poker_types.STUD_HI_LO_8B,
        ):
            state.current_stud_street = poker_types.THIRD_STREET
            state.open_pair_on_current_street = False

        for player in event.players:
            # TDA Rule 30: an absent-at-deal seat receives cards but the
            # hand is killed immediately. Mark the player folded so pot
            # eligibility excludes them and any later action is gated by
            # PlayerAbsentAtDeal (checked before the generic folded path
            # so the rejection carries the correct code/message).
            absent = bool(getattr(player, "absent_at_deal", False))
            # TDA Rule 27 — declared rebuy chips are added to the
            # effective stack for this hand.
            rebuy = int(getattr(player, "declared_rebuy_amount", 0) or 0)
            state.players[player.position] = _PlayerHandInfo(
                player_root=player.player_root,
                position=player.position,
                stack=player.stack + rebuy,
                has_folded=absent,
                is_absent_at_deal=absent,
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
        is_ante = event.blind_type in ("ante", "bb_ante")
        for player in state.players.values():
            if player.player_root == event.player_root:
                player.stack = event.player_stack
                # Antes go to the pot but do NOT count toward the player's
                # ``bet_this_round`` — they are not part of the betting
                # round's call/raise threshold (TDA Rule 7). Side-pot
                # accounting still tracks them via ``total_invested``.
                if not is_ante:
                    player.bet_this_round = event.amount
                player.total_invested += event.amount
                if player.stack == 0:
                    player.is_all_in = True
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
                        if (
                            event.action == poker_types.ALL_IN
                            and state.betting_format
                            == poker_types.BETTING_FORMAT_FIXED_LIMIT
                        ):
                            # TDA Rule 47B — limit 50% threshold reopens.
                            outcome = apply_limit_short_all_in(
                                current_bet=state.current_bet - raise_amount,
                                last_raise_increment=state.min_raise,
                                all_in_to=state.current_bet,
                            )
                            state.min_raise = outcome.last_raise_increment
                        else:
                            state.min_raise = max(state.min_raise, raise_amount)
                # TDA Rule 48 — count RAISE actions on the current street
                # for the limit raise-cap. Plain BET (the opening bet) is
                # NOT counted; only RAISE / ALL_IN-as-raise.
                if event.action == poker_types.RAISE:
                    state.raises_this_round += 1
                elif event.action == poker_types.ALL_IN:
                    # ALL_IN counts as a raise only if it actually raised
                    # the current_bet level (i.e. caller-position all-ins
                    # don't count).
                    if player.bet_this_round > 0 and player.bet_this_round == state.current_bet:
                        # The all-in IS the current_bet — count as a raise
                        # if it crossed the prior level. We approximate
                        # by counting any all-in that produced a raise
                        # via the block above (state.current_bet was just
                        # updated to player.bet_this_round).
                        if event.amount > 0:
                            state.raises_this_round += 1
                # TDA Rule 46 — track this player's chips on the table
                # this street so subsequent silent top-ups can be
                # interpreted (Rule 46C 50% threshold).
                player.prior_bet_on_street = player.bet_this_round
                # Action consumed any pull-back state once recorded.
                player.bound_to_call_or_raise = False
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
            # TDA Rule 46 — prior-bet tracking is per-street; reset on
            # every betting-round boundary.
            player.prior_bet_on_street = 0
            player.bound_to_call_or_raise = False
        # Pure helper computes the reset values per TDA Rule 47A.
        # Both this applier and the cucumber raise-tracking scenarios
        # call into the same helper so they cannot drift.
        reset = reset_per_round(state.big_blind)
        state.current_bet = reset.current_bet
        state.min_raise = reset.last_raise_increment
        # TDA Rule 48 — raise cap counter is per-street.
        state.raises_this_round = 0

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
        state.showdown_order = list(event.players_to_show)
        state.face_up_required = bool(event.face_up_required)

    @applies(hand_proto.ActionClockStarted)
    def apply_action_clock_started(
        self, state: _HandState, event: hand_proto.ActionClockStarted
    ) -> None:
        for player in state.players.values():
            if player.player_root == event.player_root:
                state.action_on_position = player.position
                break

    @applies(hand_proto.CardsRevealed)
    def apply_cards_revealed(
        self, state: _HandState, event: hand_proto.CardsRevealed
    ) -> None:
        # Pop the head of the showdown queue if it matches the revealer.
        if state.showdown_order and state.showdown_order[0] == event.player_root:
            state.showdown_order.pop(0)
        # TDA Rule 13C: record the tabled hand's ranking on the player so
        # handle_award_pot can detect awards that would kill a stronger
        # tabled hand.
        for player in state.players.values():
            if player.player_root == event.player_root:
                player.tabled_ranking = event.ranking
                break

    @applies(hand_proto.CardsMucked)
    def apply_cards_mucked(
        self, state: _HandState, event: hand_proto.CardsMucked
    ) -> None:
        if state.showdown_order and state.showdown_order[0] == event.player_root:
            state.showdown_order.pop(0)

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

        # Real-poker side-pot algorithm:
        #
        # 1. For each player, ``effective_contribution`` is capped at the
        #    maximum amount any opponent invested. Chips beyond that cap
        #    can never have been called and return to the player as an
        #    "uncontested over-bet" — but only if the player did not
        #    fold (folded chips stay in the pot).
        # 2. Pot layers form at distinct effective contribution amounts.
        #    Each layer's amount = sum of (effective_capped at level -
        #    prev_level) over all players. Eligibility = un-folded
        #    players whose effective contribution >= the level.
        # 3. A layer with no un-folded eligibles is folded into the
        #    previous pot (folded chips that never had a contest still
        #    belong to whichever pot they reached).

        # Effective contribution per player: capped at the deepest
        # opponent's investment.
        all_amounts = [c[1] for c in contributions]
        effective: dict[bytes, int] = {}
        for root, amount, _folded in contributions:
            others_max = max(
                (a for r, a, _f in contributions if r != root),
                default=0,
            )
            effective[root] = min(amount, others_max)

        # Uncontested return: only un-folded players reclaim over-bets.
        uncontested = 0
        for root, amount, folded in contributions:
            if not folded and amount > effective[root]:
                uncontested += amount - effective[root]

        # If no un-folded player has any contribution, everyone folded —
        # roll the whole thing into a single main pot with no eligibles.
        if not any(not folded for _, _, folded in contributions):
            total = sum(all_amounts)
            return (
                [_PotInfo(amount=total, eligible_players=[], pot_type="main")],
                0,
            )

        # Layer the effective contributions. Side pot boundaries form
        # only at distinct effective amounts of un-folded players —
        # folded players' chip levels feed the layer they reached, but
        # never split it into a new pot (folded chips have no claimant
        # whose all-in we need to honour).
        levels = sorted({effective[r] for r, _, folded in contributions if not folded})
        levels = [lvl for lvl in levels if lvl > 0]
        pots: list[_PotInfo] = []
        prev_level = 0
        for idx, level in enumerate(levels):
            layer_amount = 0
            eligible: list[bytes] = []
            for root, amount, folded in contributions:
                eff = effective[root]
                slice_size = max(0, min(eff, level) - prev_level)
                layer_amount += slice_size
                if not folded and eff >= level:
                    eligible.append(root)
            pot_type = "main" if idx == 0 else f"side_{idx}"
            if eligible:
                pots.append(
                    _PotInfo(
                        amount=layer_amount,
                        eligible_players=eligible,
                        pot_type=pot_type,
                    )
                )
            elif pots:
                # No un-folded eligibles for this layer — fold its
                # amount into the previous pot.
                pots[-1].amount += layer_amount
            else:
                # Edge case: no prior pot yet and no eligibles — open
                # a main pot with no eligibles. (Folded-only contributions
                # below the first un-folded layer.)
                pots.append(
                    _PotInfo(
                        amount=layer_amount,
                        eligible_players=[],
                        pot_type=pot_type,
                    )
                )
            prev_level = level

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
            # TDA Rule 27 — declared-rebuy players get a RebuyObligation
            # event alongside the deal. The hand carries the rebuy chips
            # as effective stack via the per-player ``effective_stack``
            # property (computed from stack + declared_rebuy_amount).
            for player in cmd.players:
                if getattr(player, "declared_rebuy_amount", 0) > 0:
                    obligation = hand_proto.RebuyObligation(
                        player_root=player.player_root,
                        amount=player.declared_rebuy_amount,
                        hand_root=cmd.table_root,
                        obligated_at=now(),
                    )
                    if not router_mode:
                        self._emit(obligation)
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

            # Antes must be posted BEFORE the small/big blind (TDA Rule 7).
            # Once a non-ante blind has been recorded, ante posting is
            # rejected.
            is_ante = cmd.blind_type in ("ante", "bb_ante")
            blinds_already_posted = (
                self._state.small_blind > 0 or self._state.big_blind > 0
            )
            if is_ante and blinds_already_posted:
                raise CannotPostAnteAfterBlinds()

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
            # TDA Rule 30 — absent-at-deal hands are dead. Reject before
            # the folded check so the rejection carries the correct code
            # (the seat is technically marked has_folded for pot accounting
            # but the rejection reason is the absence, not a voluntary
            # fold).
            if player.is_absent_at_deal:
                raise PlayerAbsentAtDeal()
            if player.has_folded:
                raise PlayerHasFolded()
            if player.is_all_in:
                raise PlayerIsAllIn()

            action = cmd.action
            amount = cmd.amount
            call_amount = self.current_bet - player.bet_this_round
            chips_put_in = amount
            event_amount = amount

            # TDA Rule 46B — folds are rejected when the player is bound
            # to call-or-raise after pulling back a prior chip.
            if action == poker_types.FOLD and player.bound_to_call_or_raise:
                raise BoundToCallOrRaise()

            # TDA Rule 43A (NL/PL only): silent chip push interpretation.
            # When the command carries BET_METHOD_CHIP_ONLY and the action
            # arrives as RAISE / BET (with a chip amount), reinterpret per
            # the 50% threshold.
            bet_method = cmd.bet_method
            betting_format = self._state.betting_format or poker_types.BETTING_FORMAT_NO_LIMIT
            is_silent_push = (
                bet_method == poker_types.BET_METHOD_CHIP_ONLY
                and betting_format != poker_types.BETTING_FORMAT_FIXED_LIMIT
                and action in (poker_types.RAISE, poker_types.BET)
            )
            if is_silent_push:
                outcome = interpret_silent_push(
                    pushed_amount=amount,
                    current_bet=self.current_bet,
                    prior_bet_on_street=player.bet_this_round,
                    last_raise_increment=self.min_raise,
                    player_stack=player.stack,
                    chip_count=cmd.chip_count,
                )
                action = outcome.action
                if outcome.action in (poker_types.BET, poker_types.RAISE, poker_types.ALL_IN):
                    amount = outcome.target_amount
                # CALL uses self.current_bet implicitly below.

            # TDA Rule 52A — declared raise below minimum is corrected to
            # the minimum (rather than rejected) when the verbal qualifier
            # signals an explicit RAISE intent. Default UNSPECIFIED keeps
            # the legacy reject path so pre-bet-method scenarios still
            # surface as rejections.
            is_declared_raise = (
                action == poker_types.RAISE
                and bet_method
                in (
                    poker_types.BET_METHOD_VERBAL_FIRST,
                    poker_types.BET_METHOD_MIXED,
                )
            )
            if is_declared_raise and self.current_bet > 0:
                amount = correct_declared_underraise(
                    declared_amount=amount,
                    current_bet=self.current_bet,
                    last_raise_increment=self.min_raise,
                )

            if action == poker_types.FOLD:
                # TDA Rule 66 — stud players who muck by picking up
                # their upcards have a dead hand AND a procedural
                # violation. The aggregate rejects the FOLD when the
                # caller signals pickup-style mucking via verbal_context;
                # the floor then applies Rule 66 separately.
                if (
                    self._state.game_variant
                    in (
                        poker_types.SEVEN_CARD_STUD,
                        poker_types.RAZZ,
                        poker_types.STUD_HI_LO_8B,
                    )
                    and (cmd.verbal_context or "").upper() == "PICKUP_UPCARDS"
                ):
                    raise StudMuckByPickupForbidden()
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
            elif action == poker_types.BET_COMPLETION:
                # WSOP §Seven Card Games / Robert's §SC Stud #6 — bringing
                # the bring-in up to a full small-bet is a "completion",
                # not a raise. It does not count toward the fixed-limit
                # raise cap; up to 4 raises remain. The chip delta the
                # actor puts in is (small_bet - bring_in_amount); the
                # actor's bet_this_round becomes small_bet.
                target = amount or self._state.small_bet
                chips_put_in = target - player.bet_this_round
                event_amount = chips_put_in
                if player.stack - chips_put_in == 0:
                    action = poker_types.ALL_IN
            elif action == poker_types.BET:
                if self.current_bet > 0:
                    raise CannotBetOverExistingBet()
                # TDA RP-10F / WSOP — open pair on 4th street locks the
                # bet to the lower limit (small_bet) for Stud Hi and
                # Stud Hi/Lo. Razz explicitly does NOT lock (Robert's
                # §RAZZ #3) — limit advances normally regardless of an
                # open pair. The error code differs by variant so the
                # rule citation reads naturally in the rejection logs.
                if (
                    self._state.betting_format
                    == poker_types.BETTING_FORMAT_FIXED_LIMIT
                    and self._state.current_stud_street
                    == poker_types.FOURTH_STREET
                    and self._state.open_pair_on_current_street
                    and self._state.small_bet > 0
                    and amount > self._state.small_bet
                ):
                    if self._state.game_variant == poker_types.SEVEN_CARD_STUD:
                        raise DoubledBetNotAllowed4thStreet(
                            max_bet=self._state.small_bet
                        )
                    if self._state.game_variant == poker_types.STUD_HI_LO_8B:
                        raise OpenPairLocksLowerLimit(
                            max_bet=self._state.small_bet
                        )
                    # Razz (poker_types.RAZZ) intentionally falls through —
                    # the open pair has no effect on Razz limits.
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
                # TDA Rule 48 — fixed-limit raise cap. Heads-up exception
                # applies when only 2 active players remain.
                if betting_format == poker_types.BETTING_FORMAT_FIXED_LIMIT:
                    active_players = sum(
                        1
                        for p in self._state.players.values()
                        if not p.has_folded and not p.is_absent_at_deal
                    )
                    if is_limit_raise_cap_reached(
                        raises_this_round=self._state.raises_this_round,
                        raise_cap_per_round=self._state.raise_cap_per_round,
                        is_heads_up=active_players <= 2,
                    ):
                        cap = (
                            self._state.raise_cap_per_round
                            if self._state.raise_cap_per_round > 0
                            else 4
                        )
                        raise RaiseCapReached(max_raises_per_round=cap)
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

    @handles(hand_proto.StartActionClock)
    def handle_start_action_clock(
        self,
        cmd: hand_proto.StartActionClock,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.ActionClockStarted:
        """Start a TDA Rule 29 action clock on the seat to act.

        Rejected if the named player is not currently to act. The "seat
        to act" is whatever the most recent ``ActionClockStarted`` /
        action-bearing event recorded in ``state.action_on_position``;
        when no such event has fired yet (action_on_position == -1) the
        clock is allowed for any seated, non-folded, non-all-in player —
        starting the clock IS the act of pinning the action.
        """
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
            if player.is_all_in:
                raise PlayerIsAllIn()

            on_pos = self._state.action_on_position
            if on_pos != -1 and on_pos != player.position:
                raise ActionClockNotOnThisPlayer()

            event = hand_proto.ActionClockStarted(
                player_root=cmd.player_root,
                seconds=cmd.seconds,
                started_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.DeclareAction)
    def handle_declare_action(
        self,
        cmd: hand_proto.DeclareAction,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.ActionTaken:
        """Apply TDA Rules 40-42 / 51-55 — verbal-only in-turn declaration.

        Verbal declarations bind the player even before chips move:
        - "raise" without amount → minimum legal raise (Rule 42).
        - "all-in" → entire stack (Rule 40).
        - "call" / "call N" → matches current_bet, possibly corrected
          on undercall (Rule 51).
        - "bet N" / "raise N" → declared amount, corrected on
          underraise (Rule 52A).
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            if self.status != "betting":
                raise NotInBettingPhase()
            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            if player.has_folded:
                raise PlayerHasFolded()
            if player.is_all_in:
                raise PlayerIsAllIn()

            action = cmd.action
            amount = cmd.amount

            # TDA Rule 42 — verbal raise without amount commits to min legal.
            if action == poker_types.RAISE and amount == 0:
                amount = self.current_bet + self.min_raise

            # TDA Rule 40 — verbal all-in commits the entire stack.
            if action == poker_types.ALL_IN:
                amount = player.bet_this_round + player.stack

            # TDA Rule 55 — invalid declarations bind to legal action.
            # "call" with no bet → CHECK; "raise" with no bet → BET (min);
            # "check" facing a bet → CALL_OR_FOLD (default to CALL since
            # the verbal intent is "I want to do nothing").
            if action == poker_types.CALL and self.current_bet == 0:
                action = poker_types.CHECK
                amount = 0
            elif action == poker_types.RAISE and self.current_bet == 0:
                action = poker_types.BET
                if amount == 0 or amount < self.big_blind:
                    amount = self.big_blind
            elif action == poker_types.CHECK and self.current_bet > player.bet_this_round:
                # "check" facing a bet — Rule 55 says player may call or
                # fold but cannot raise. We default to CALL (the
                # least-aggressive option that doesn't kill the hand).
                action = poker_types.CALL
                amount = self.current_bet

            # Build a PlayerAction equivalent and dispatch through the
            # main handler to reuse Rules 43A / 47B / 48 / 52A / SA logic.
            forwarded = hand_proto.PlayerAction(
                player_root=cmd.player_root,
                action=action,
                amount=amount,
                bet_method=poker_types.BET_METHOD_VERBAL_FIRST,
            )
            # When called through the main path the existing handler
            # re-binds router state internally; recurse via _state.
            if router_mode:
                return self.handle_player_action(forwarded, self._state, seq)
            return self.handle_player_action(forwarded)
        finally:
            if router_mode:
                self._state = saved

    @handles(hand_proto.PullBackPriorChip)
    def handle_pull_back_prior_chip(
        self,
        cmd: hand_proto.PullBackPriorChip,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.PriorChipPulledBack | None:
        """TDA Rule 46B — record a prior-chip pull-back and bind player.

        Emits a PriorChipPulledBack event when the player has a prior
        bet on the street and is facing a raise. Subsequent fold
        attempts will be rejected with BOUND_TO_CALL_OR_RAISE.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            player = self.get_player(cmd.player_root)
            if not player:
                raise PlayerNotInHand()
            facing_raise = self.current_bet > player.bet_this_round
            has_prior = player.bet_this_round > 0
            if not (facing_raise and has_prior):
                return None
            event = hand_proto.PriorChipPulledBack(
                player_root=cmd.player_root,
                chips_pulled=cmd.chips_pulled,
                pulled_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(hand_proto.PriorChipPulledBack)
    def apply_prior_chip_pulled_back(
        self, state: _HandState, event: hand_proto.PriorChipPulledBack
    ) -> None:
        """Set bound_to_call_or_raise on the affected player."""
        for p in state.players.values():
            if p.player_root == event.player_root:
                p.bound_to_call_or_raise = True
                break

    @handles(hand_proto.CorrectIllegalBet)
    def handle_correct_illegal_bet(
        self,
        cmd: hand_proto.CorrectIllegalBet,
        state: _HandState | None = None,
        seq: int | None = None,
    ) -> hand_proto.UnderbetCorrected:
        """Apply TDA Rule 52A/B — bet correction in either direction.

        Rule 52B (PL_ILLEGAL_OVERBET): reduces over-paid players to the
        corrected amount and refunds the difference.
        Rule 52A (NL_DECLARED_UNDERRAISE): raises underpaid players up
        to the corrected amount, debiting the difference from stack.
        Players whose ``bet_this_round`` already equals corrected are
        unaffected.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise HandNotDealt()
            corrected = cmd.corrected_amount
            adjustments = []
            for p in self._state.players.values():
                if p.bet_this_round > 0 and p.bet_this_round != corrected:
                    diff = p.bet_this_round - corrected
                    adjustments.append(
                        hand_proto.UnderbetAdjustment(
                            player_root=p.player_root,
                            prior_contribution=p.bet_this_round,
                            new_contribution=corrected,
                            refund_to_stack=diff,
                        )
                    )
            event = hand_proto.UnderbetCorrected(
                reason=cmd.reason,
                corrected_amount=corrected,
                adjustments=adjustments,
                corrected_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(hand_proto.UnderbetCorrected)
    def apply_underbet_corrected(
        self, state: _HandState, event: hand_proto.UnderbetCorrected
    ) -> None:
        """Apply UnderbetCorrected: refund chips and reduce contributions."""
        for adj in event.adjustments:
            for p in state.players.values():
                if p.player_root == adj.player_root:
                    p.bet_this_round = adj.new_contribution
                    p.total_invested -= adj.refund_to_stack
                    p.stack += adj.refund_to_stack
                    p.prior_bet_on_street = adj.new_contribution
                    break
        if event.corrected_amount < state.current_bet:
            state.current_bet = event.corrected_amount
        # Reduce running pot by total refunds.
        if state.pots:
            refund_total = sum(a.refund_to_stack for a in event.adjustments)
            state.pots[0].amount = max(0, state.pots[0].amount - refund_total)

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

            # Robert's §SC Stud #18 — stud card-count enforcement runs
            # BEFORE the showdown-order check because a wrong-count hand
            # is structurally dead regardless of whose turn it is. A
            # hand with 8 cards cannot become live by waiting for its
            # turn; surfacing STUD_TOO_MANY_CARDS first gives the floor
            # the right diagnostic without REVEAL_OUT_OF_ORDER masking.
            s = self._state
            stud_total: int | None = None
            if s.game_variant in (
                poker_types.SEVEN_CARD_STUD,
                poker_types.RAZZ,
                poker_types.STUD_HI_LO_8B,
            ):
                stud_total = len(player.hole_cards) + len(player.up_cards)
                if stud_total > 7:
                    raise StudTooManyCards(got=stud_total)

            # Showdown order (TDA Rule 36): if the queue is populated,
            # only the head player may reveal/muck. Out-of-order attempts
            # are rejected.
            order = self._state.showdown_order
            if order and order[0] != cmd.player_root:
                raise RevealOutOfOrder()

            if cmd.muck:
                # TDA Rule 16 — when the showdown was opened with the
                # face-up flag (at least one player all-in, action closed)
                # mucking is no longer permitted; the rule requires every
                # remaining hand to be tabled.
                if self._state.face_up_required:
                    raise FaceUpRequired()
                event = hand_proto.CardsMucked(
                    player_root=cmd.player_root,
                    mucked_at=now(),
                )
                if not router_mode:
                    self._emit(event)
                return event

            # Robert's §SC Stud #18 — < 7 cards: floor decides whether
            # the hand is ruled live. Emitted AFTER the order check so
            # only the player whose turn it is gets the floor-decision
            # path. (Too-many is enforced earlier — see above.)
            if stud_total is not None and stud_total < 7:
                fdr = hand_proto.FloorDecisionRequired(
                    player_root=cmd.player_root,
                    reason="MISSING_SEVENTH_CARD",
                    requested_at=now(),
                )
                if not router_mode:
                    self._emit(fdr)
                return fdr

            # TDA Rule 13A — proper tabling shows ALL hole cards. Empty
            # ``tabled_indices`` is the legacy "table all" default; a
            # non-empty list shorter than the player's hole-card count
            # is a partial reveal and is rejected.
            tabled = list(cmd.tabled_indices)
            required = len(player.hole_cards)
            if tabled and len(tabled) < required:
                raise IncompleteReveal(got=len(tabled), bound=required)

            rules = get_game_rules(s.game_variant)
            rank_type, score, kickers = rules.evaluate_hand(
                player.hole_cards,
                s.community_cards,
            )

            # TDA Rule 19 — "playing the board" means the player's best
            # 5-card hand is identical to the community board (no hole
            # cards used). Only meaningful for board-game variants. We
            # compute it by re-evaluating using just the community
            # cards and comparing the score.
            plays_board = False
            if s.community_cards and len(s.community_cards) >= 5:
                board_rank, board_score, _ = rules.evaluate_hand(
                    [], s.community_cards
                )
                plays_board = (
                    rank_type == board_rank and score == board_score
                )
            event = hand_proto.CardsRevealed(
                player_root=cmd.player_root,
                ranking=poker_types.HandRanking(
                    rank_type=rank_type,
                    kickers=[k for k in kickers],
                    score=score,
                ),
                revealed_at=now(),
                plays_the_board=plays_board,
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

            # TDA Rule 13C — a properly tabled winner cannot be killed
            # by an erroneous award. If any seated player tabled their
            # hand, no award may name a winner whose tabled ranking is
            # strictly weaker (or who didn't table at all).
            tabled = [p for p in s.players.values() if p.tabled_ranking is not None]
            if tabled:
                strongest = max(tabled, key=lambda p: p.tabled_ranking.score)
                strongest_score = strongest.tabled_ranking.score
                for award in cmd.awards:
                    awardee = self.get_player(award.player_root)
                    awardee_score = (
                        awardee.tabled_ranking.score
                        if awardee and awardee.tabled_ranking is not None
                        else -1
                    )
                    if awardee_score < strongest_score:
                        raise TabledWinnerCannotBeKilled(
                            tabled_winner=strongest.player_root.hex(),
                        )

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
            # The pot ceiling for AWARDS_EXCEED_POT is the maximum chips
            # legitimately in play: the legacy single-pot accumulator
            # OR the sum of computed side pots plus any uncontested
            # over-bet (which logically belongs to the winner's stack
            # but may be expressed as part of the AwardPot when there
            # is only a single pot). Whichever is larger.
            legacy_total = self.get_pot_total()
            computed_total = sum(p.amount for p in computed_pots) + _uncontested
            pot_total = max(legacy_total, computed_total)
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
