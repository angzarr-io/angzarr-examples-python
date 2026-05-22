"""Table aggregate - rich domain model."""

import hashlib
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Optional

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import applies, command_handler, handles, now
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in_proto
from angzarr_client.proto.examples.v1 import rebuy_pb2 as rebuy_proto
from angzarr_client.proto.examples.v1 import table_pb2 as table_proto

from table.agg.errors import (
    AmountMustBePositive,
    BigBlindMustExceedSmallBlind,
    BuyInAboveMax,
    BuyInBelowMin,
    CannotLeaveDuringHand,
    HaltDeficitBelowMin,
    HandAlreadyInProgress,
    HandRootMismatch,
    MaxBuyInMustExceedMinBuyIn,
    MaxPlayersOutOfRange,
    MinBuyInMustBePositive,
    NoHandInProgress,
    NotEnoughPlayersToStartHand,
    PlayerAlreadySeated,
    PlayerNotSeated,
    PlayerRootRequired,
    SeatOccupied,
    SeatPositionMismatch,
    SmallBlindMustBePositive,
    TableAlreadyExists,
    TableAlreadyHalted,
    TableHaltedAwaitingRebalance,
    TableHandForHandRoundComplete,
    TableIsFull,
    TableNameRequired,
    TableNotFound,
    TableNotHalted,
)

# TDA Rule 11D — "Play will halt on tables 3+ players short (by
# elimination) than the table with the most players once the blinds
# are impacted." The threshold is part of the rule, not a runtime
# parameter; encoded here so the table aggregate can reject
# below-threshold halt commands without re-deriving the count.
MIN_HALT_FOR_BALANCING_DEFICIT = 3


@dataclass
class _SeatState:
    """State of a single seat at the table."""

    position: int
    player_root: bytes
    stack: int
    is_active: bool = True
    is_sitting_out: bool = False


@dataclass
class _TableState:
    """Internal state representation."""

    table_id: str = ""
    table_name: str = ""
    game_variant: int = 0
    small_blind: int = 0
    big_blind: int = 0
    min_buy_in: int = 0
    max_buy_in: int = 0
    max_players: int = 9
    action_timeout_seconds: int = 30
    seats: dict = field(default_factory=dict)  # position -> _SeatState
    dealer_position: int = 0
    # Last hand's blind positions, retained between hands so the
    # dead-button advancement rule (TDA Rule 6) can compute the next
    # BB without re-deriving from the seat layout alone.
    last_big_blind_position: int = -1
    last_small_blind_position: int = -1
    hand_count: int = 0
    current_hand_root: bytes = b""
    status: str = ""
    # TDA Rule 12 — hand-for-hand at the bubble. Per-table status tracks
    # the table's slot in the synchronised round.  "WAITING" means the
    # table has been told to play one H4H hand; "COMPLETE" means that
    # hand finished and the table is parked until the operator/saga
    # arms it for the next round (or ends H4H entirely on the bubble
    # break).  Empty string is the cash-game/non-H4H default.
    hand_for_hand_status: str = ""
    # When in H4H, identifies the tournament the table is currently
    # serving so per-table completion events can be routed back to the
    # right tournament aggregate by saga-tournament-table-h4h. Empty
    # bytes outside H4H or for non-tournament tables.
    hand_for_hand_tournament_root: bytes = b""
    # uuid5(NAMESPACE_OID, table_name).bytes — matches the test-helper
    # convention and the cross-language byte-parity invariant. Populated
    # in apply_table_created so emitted events can stamp the root
    # without re-deriving from the name at every call site.
    table_root: bytes = b""
    # TDA Rule 11D — set by apply_table_halted_for_balancing; cleared by
    # apply_table_resumed_for_balancing. Gates StartHand.
    halted_for_balancing: bool = False
    # Players-short relative to the largest table at halt time.  Carried
    # for diagnostic surfacing in the StartHand-while-halted rejection.
    halted_deficit: int = 0


# Module-level registry of (event_type, applier_method_name) for replay.
# Populated after class definition.
_APPLIER_REGISTRY: list[tuple[type, str]] = []


@command_handler(domain="table", state=_TableState)
class Table:
    """Table aggregate with event sourcing.

    Supports two call shapes:
      - Stateful (used by tests): ``Table(event_book=None)`` — instance owns
        ``self._state`` and ``self._events``. Handler methods called with just
        the command mutate state and track the emitted event.
      - Router-dispatched: the router passes ``(cmd, state, seq)`` to each
        handler method. State is rebuilt per-dispatch via ``@applies``
        methods; the emitted event is packed into a ``BusinessResponse`` by
        the router.
    """

    def __init__(self, event_book: types.EventBook | None = None) -> None:
        self._state = _TableState()
        self._events = types.EventBook()
        if event_book is not None:
            for page in event_book.pages:
                new_page = types.EventPage()
                new_page.CopyFrom(page)
                self._events.pages.append(new_page)
                if page.HasField("event"):
                    self._apply_any(page.event, self._state)

    # --- Compatibility helpers for tests (not used by the router path) ---

    def _get_state(self) -> _TableState:
        return self._state

    def event_book(self) -> types.EventBook:
        return self._events

    def _emit(self, event) -> None:
        """Pack, track, and apply an event (stateful call path)."""
        any_msg = ProtoAny()
        any_msg.Pack(event, type_url_prefix="type.googleapis.com/")
        page = types.EventPage(
            event=any_msg,
            header=types.PageHeader(sequence=len(self._events.pages)),
        )
        self._events.pages.append(page)
        self._apply_any(any_msg, self._state)

    def _apply_any(self, event_any: ProtoAny, state: _TableState) -> None:
        for event_type, method_name in _APPLIER_REGISTRY:
            expected = f"type.googleapis.com/{event_type.DESCRIPTOR.full_name}"
            if event_any.type_url == expected:
                evt = event_type()
                event_any.Unpack(evt)
                getattr(self, method_name)(state, evt)
                return

    # --- Event appliers ---

    @applies(table_proto.TableCreated)
    def apply_table_created(
        self, state: _TableState, event: table_proto.TableCreated
    ) -> None:
        state.table_id = f"table_{event.table_name}"
        state.table_name = event.table_name
        state.table_root = _uuid.uuid5(_uuid.NAMESPACE_OID, event.table_name).bytes
        state.game_variant = event.game_variant
        state.small_blind = event.small_blind
        state.big_blind = event.big_blind
        state.min_buy_in = event.min_buy_in
        state.max_buy_in = event.max_buy_in
        state.max_players = event.max_players
        state.action_timeout_seconds = event.action_timeout_seconds
        state.status = "waiting"

    @applies(table_proto.PlayerJoined)
    def apply_player_joined(
        self, state: _TableState, event: table_proto.PlayerJoined
    ) -> None:
        state.seats[event.seat_position] = _SeatState(
            position=event.seat_position,
            player_root=event.player_root,
            stack=event.stack,
        )

    @applies(table_proto.PlayerLeft)
    def apply_player_left(
        self, state: _TableState, event: table_proto.PlayerLeft
    ) -> None:
        state.seats.pop(event.seat_position, None)

    @applies(table_proto.PlayerSatOut)
    def apply_player_sat_out(
        self, state: _TableState, event: table_proto.PlayerSatOut
    ) -> None:
        for seat in state.seats.values():
            if seat.player_root == event.player_root:
                seat.is_sitting_out = True
                break

    @applies(table_proto.PlayerSatIn)
    def apply_player_sat_in(
        self, state: _TableState, event: table_proto.PlayerSatIn
    ) -> None:
        for seat in state.seats.values():
            if seat.player_root == event.player_root:
                seat.is_sitting_out = False
                break

    @applies(table_proto.HandStarted)
    def apply_hand_started(
        self, state: _TableState, event: table_proto.HandStarted
    ) -> None:
        state.hand_count = event.hand_number
        state.current_hand_root = event.hand_root
        state.dealer_position = event.dealer_position
        state.last_small_blind_position = event.small_blind_position
        state.last_big_blind_position = event.big_blind_position
        state.status = "in_hand"

    @applies(table_proto.HandEnded)
    def apply_hand_ended(
        self, state: _TableState, event: table_proto.HandEnded
    ) -> None:
        state.current_hand_root = b""
        state.status = "waiting"
        for player_hex, delta in event.stack_changes.items():
            player_root = bytes.fromhex(player_hex)
            for seat in state.seats.values():
                if seat.player_root == player_root:
                    seat.stack += delta
                    break
        # TDA Rule 12 — if this hand was the table's H4H synchronised
        # hand, the completion parks the table at COMPLETE until the
        # operator/saga arms it for the next round.
        if state.hand_for_hand_status == "WAITING":
            state.hand_for_hand_status = "COMPLETE"

    @applies(table_proto.TableHandForHandWaiting)
    def apply_table_h4h_waiting(
        self, state: _TableState, event: table_proto.TableHandForHandWaiting
    ) -> None:
        state.hand_for_hand_status = "WAITING"
        if event.tournament_root:
            state.hand_for_hand_tournament_root = event.tournament_root

    @applies(table_proto.TableHandForHandRoundComplete)
    def apply_table_h4h_round_complete(
        self,
        state: _TableState,
        _event: table_proto.TableHandForHandRoundComplete,
    ) -> None:
        state.hand_for_hand_status = "COMPLETE"

    @applies(table_proto.TableHandForHandEnded)
    def apply_table_h4h_ended(
        self, state: _TableState, _event: table_proto.TableHandForHandEnded
    ) -> None:
        state.hand_for_hand_status = ""
        state.hand_for_hand_tournament_root = b""

    @applies(table_proto.ChipsAdded)
    def apply_chips_added(
        self, state: _TableState, event: table_proto.ChipsAdded
    ) -> None:
        for seat in state.seats.values():
            if seat.player_root == event.player_root:
                seat.stack = event.new_stack
                break

    @applies(table_proto.PlayerHandKilledByPenalty)
    def apply_player_hand_killed_by_penalty(
        self, state: _TableState, event: table_proto.PlayerHandKilledByPenalty
    ) -> None:
        """TDA Rule 71C — debit the killed seat's stack by the posted
        blinds. The seat itself stays at the table; only the hand is
        dead for this round."""
        seat = state.seats.get(event.seat_position)
        if seat is None or event.stack_charged == 0:
            return
        seat.stack = max(0, seat.stack - event.stack_charged)

    @applies(buy_in_proto.PlayerSeated)
    def apply_player_seated(
        self, state: _TableState, event: buy_in_proto.PlayerSeated
    ) -> None:
        state.seats[event.seat_position] = _SeatState(
            position=event.seat_position,
            player_root=event.player_root,
            stack=event.stack,
        )

    @applies(buy_in_proto.SeatingRejected)
    def apply_seating_rejected(
        self, state: _TableState, event: buy_in_proto.SeatingRejected
    ) -> None:
        # SeatingRejected carries no state change for the table — the seat
        # was never occupied. Recorded for audit / replay completeness.
        return None

    @applies(rebuy_proto.RebuyChipsAdded)
    def apply_rebuy_chips_added(
        self, state: _TableState, event: rebuy_proto.RebuyChipsAdded
    ) -> None:
        for seat in state.seats.values():
            if seat.player_root == event.player_root:
                seat.stack = event.new_stack
                break

    @applies(table_proto.TableHaltedForBalancing)
    def apply_table_halted_for_balancing(
        self, state: _TableState, event: table_proto.TableHaltedForBalancing
    ) -> None:
        state.halted_for_balancing = True
        state.halted_deficit = event.deficit

    @applies(table_proto.TableResumedForBalancing)
    def apply_table_resumed_for_balancing(
        self, state: _TableState, _event: table_proto.TableResumedForBalancing
    ) -> None:
        state.halted_for_balancing = False
        state.halted_deficit = 0

    # --- State accessors (operate on self._state; used by tests) ---

    @property
    def exists(self) -> bool:
        return bool(self._state.table_id)

    @property
    def table_id(self) -> str:
        return self._state.table_id

    @property
    def table_name(self) -> str:
        return self._state.table_name

    @property
    def game_variant(self) -> int:
        return self._state.game_variant

    @property
    def small_blind(self) -> int:
        return self._state.small_blind

    @property
    def big_blind(self) -> int:
        return self._state.big_blind

    @property
    def min_buy_in(self) -> int:
        return self._state.min_buy_in

    @property
    def max_buy_in(self) -> int:
        return self._state.max_buy_in

    @property
    def max_players(self) -> int:
        return self._state.max_players

    @property
    def seats(self) -> dict:
        return self._state.seats

    @property
    def dealer_position(self) -> int:
        return self._state.dealer_position

    @property
    def hand_count(self) -> int:
        return self._state.hand_count

    @property
    def current_hand_root(self) -> bytes:
        return self._state.current_hand_root

    @property
    def status(self) -> str:
        return self._state.status

    @property
    def player_count(self) -> int:
        return len(self._state.seats)

    @property
    def active_player_count(self) -> int:
        return sum(1 for s in self._state.seats.values() if not s.is_sitting_out)

    @property
    def is_full(self) -> bool:
        return len(self._state.seats) >= self._state.max_players

    def get_seat(self, position: int) -> Optional[_SeatState]:
        return self._state.seats.get(position)

    def find_player_seat(self, player_root: bytes) -> Optional[_SeatState]:
        for seat in self._state.seats.values():
            if seat.player_root == player_root:
                return seat
        return None

    def _find_available_seat(self, preferred: int = -1) -> Optional[int]:
        state = self._state
        if preferred >= 0 and preferred < state.max_players:
            if preferred not in state.seats:
                return preferred
        for pos in range(state.max_players):
            if pos not in state.seats:
                return pos
        return None

    def _next_dealer_position(self) -> int:
        state = self._state
        if not state.seats:
            return 0
        positions = sorted(state.seats.keys())
        current_idx = 0
        for i, pos in enumerate(positions):
            if pos == state.dealer_position:
                current_idx = i
                break
        next_idx = (current_idx + 1) % len(positions)
        return positions[next_idx]

    def _advance_blinds_with_dead_button(self) -> tuple[int, int, int] | None:
        """Compute (dealer_position, sb_position, bb_position) for the
        next hand using the TDA dead-button rule.

        Invariant: every player must pay the BB exactly once per orbit.
        Rules applied:
        - First hand (prev BB unset): standard advance from dealer.
        - Heads-up (2 active players): button alternates — dealer moves
          to the next active seat CW from prev dealer; that seat is SB
          (heads-up structural rule); the other player is BB.
        - 3+ players: BB advances to the next active seat CW from prev
          BB. SB and dealer are derived clockwise-backward from BB
          through the active seats.
        - Dead-button override (3+ players): if the prev BB seat was
          *vacated* between hands AND the standard advance would land
          SB on an empty seat number that lies between the active SB
          and BB seats, the button "freezes" at the prior dealer; SB
          is then the next active seat after the vacated BB seat, and
          BB is the next active after SB.

        Returns None when the seats can't support a hand (< 2 active).
        """
        state = self._state
        active = sorted(
            pos for pos, seat in state.seats.items() if not seat.is_sitting_out
        )
        if len(active) < 2:
            return None

        # First hand: prior BB position is unset (-1). WSOP Rule 85:
        # the button begins in the seat with the first chip stack to
        # the dealer's right (counter-clockwise), which is the
        # highest-numbered active seat.
        prev_bb = state.last_big_blind_position
        prev_dealer = state.dealer_position
        if prev_bb < 0:
            dealer = max(active)
            return self._derive_blind_positions(active, dealer)

        # Heads-up: button alternates each hand. The prev dealer is the
        # OUT-going button; the new dealer is the next active seat CW.
        if len(active) == 2:
            if prev_dealer in active:
                d_idx = active.index(prev_dealer)
                new_dealer = active[(d_idx + 1) % 2]
            else:
                # Prev dealer busted — pick the active seat following
                # the vacated dealer seat (or the first active).
                new_dealer = next(
                    (s for s in active if s > prev_dealer),
                    active[0],
                )
            new_sb = new_dealer  # heads-up structural rule
            new_bb = next(s for s in active if s != new_dealer)
            return (new_dealer, new_sb, new_bb)

        # 3+ players: dead-button special case. If the prev BB seat is
        # gone (busted between hands), the button freezes at the prior
        # dealer; SB advances to the next active seat after the
        # vacated BB seat; BB follows.
        prev_bb_busted = prev_bb not in active
        if prev_bb_busted:
            new_dealer = (
                prev_dealer if prev_dealer in active else self._next_dealer_position()
            )
            new_sb = next(
                (s for s in active if s > prev_bb),
                active[0],
            )
            sb_idx = active.index(new_sb)
            new_bb = active[(sb_idx + 1) % len(active)]
            return (new_dealer, new_sb, new_bb)

        # Standard advance: BB → next active CW from prev BB.
        new_bb = next(
            (s for s in active if s > prev_bb),
            active[0],
        )
        bb_idx = active.index(new_bb)
        new_sb = active[(bb_idx - 1) % len(active)]
        sb_idx = active.index(new_sb)
        new_dealer = active[(sb_idx - 1) % len(active)]
        return (new_dealer, new_sb, new_bb)

    def _derive_blind_positions(
        self, active: list[int], dealer: int
    ) -> tuple[int, int, int]:
        """Standard blind derivation from a known dealer position. Used
        for the first hand when prior BB position is unset.
        """
        if dealer in active:
            d_idx = active.index(dealer)
        else:
            d_idx = 0
        if len(active) == 2:
            sb = active[d_idx]
            bb = active[(d_idx + 1) % 2]
            return (dealer, sb, bb)
        sb = active[(d_idx + 1) % len(active)]
        bb = active[(d_idx + 2) % len(active)]
        return (dealer, sb, bb)

    # --- Command handlers ---
    #
    # Each handler accepts an optional ``state`` (and ``seq``) so the router
    # can dispatch via ``method(cmd, state, seq)``. When called without state
    # (the stateful test path), the handler operates on ``self._state`` and
    # the emitted event is applied back through ``_emit``. When called by the
    # router, the method temporarily binds ``self._state`` to the router's
    # freshly-rebuilt state so property accessors work unchanged.

    def _router_bind(self, state):
        """Context manager replacement: swap self._state for router's state."""
        saved = self._state
        self._state = state
        return saved

    # region handlers
    @handles(table_proto.CreateTable)
    def handle_create_table(
        self,
        cmd: table_proto.CreateTable,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableCreated:
        """Create a new table."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if self.exists:
                raise TableAlreadyExists()
            if not cmd.table_name:
                raise TableNameRequired()
            if cmd.small_blind <= 0:
                raise SmallBlindMustBePositive(value=cmd.small_blind)
            if cmd.big_blind <= 0 or cmd.big_blind < cmd.small_blind:
                raise BigBlindMustExceedSmallBlind(
                    lhs=cmd.big_blind, rhs=cmd.small_blind
                )
            if cmd.min_buy_in <= 0:
                raise MinBuyInMustBePositive(value=cmd.min_buy_in)
            if cmd.max_buy_in < cmd.min_buy_in:
                raise MaxBuyInMustExceedMinBuyIn(lhs=cmd.max_buy_in, rhs=cmd.min_buy_in)
            if cmd.max_players < 2 or cmd.max_players > 10:
                raise MaxPlayersOutOfRange(got=cmd.max_players)

            event = table_proto.TableCreated(
                table_name=cmd.table_name,
                game_variant=cmd.game_variant,
                small_blind=cmd.small_blind,
                big_blind=cmd.big_blind,
                min_buy_in=cmd.min_buy_in,
                max_buy_in=cmd.max_buy_in,
                max_players=cmd.max_players,
                action_timeout_seconds=cmd.action_timeout_seconds or 30,
                created_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    # endregion

    @handles(table_proto.JoinTable)
    def handle_join_table(
        self,
        cmd: table_proto.JoinTable,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.PlayerJoined:
        """Add a player to the table."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if not cmd.player_root:
                raise PlayerRootRequired()
            if self.find_player_seat(cmd.player_root):
                raise PlayerAlreadySeated()
            if self.is_full:
                raise TableIsFull()
            if cmd.buy_in_amount < self.min_buy_in:
                raise BuyInBelowMin(got=cmd.buy_in_amount, bound=self.min_buy_in)
            if cmd.buy_in_amount > self.max_buy_in:
                raise BuyInAboveMax(got=cmd.buy_in_amount, bound=self.max_buy_in)
            if cmd.preferred_seat >= 0 and cmd.preferred_seat < self.max_players:
                if self.get_seat(cmd.preferred_seat) is not None:
                    raise SeatOccupied(seat=cmd.preferred_seat)
                seat_position = cmd.preferred_seat
            else:
                seat_position = self._find_available_seat(-1)

            event = table_proto.PlayerJoined(
                player_root=cmd.player_root,
                seat_position=seat_position,
                buy_in_amount=cmd.buy_in_amount,
                stack=cmd.buy_in_amount,
                joined_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.LeaveTable)
    def handle_leave_table(
        self,
        cmd: table_proto.LeaveTable,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.PlayerLeft:
        """Remove a player from the table."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if not cmd.player_root:
                raise PlayerRootRequired()

            seat = self.find_player_seat(cmd.player_root)
            if not seat:
                raise PlayerNotSeated()
            if self.status == "in_hand":
                raise CannotLeaveDuringHand()

            event = table_proto.PlayerLeft(
                player_root=cmd.player_root,
                seat_position=seat.position,
                chips_cashed_out=seat.stack,
                left_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.StartHand)
    def handle_start_hand(
        self,
        cmd: table_proto.StartHand,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.HandStarted:
        """Start a new hand."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if self.status == "in_hand":
                raise HandAlreadyInProgress()
            # TDA Rule 11D — a table halted for balancing refuses to
            # start the next hand until the coordinator issues
            # ResumePlayAtTable.
            if self._state.halted_for_balancing:
                raise TableHaltedAwaitingRebalance(deficit=self._state.halted_deficit)
            # TDA Rule 12 — once a table has finished its synchronised
            # H4H hand it must wait for the round-complete signal before
            # the next hand can begin. The operator/saga issues
            # EndTableHandForHand to clear the COMPLETE state.
            if self._state.hand_for_hand_status == "COMPLETE":
                raise TableHandForHandRoundComplete()
            if self.active_player_count < 2:
                raise NotEnoughPlayersToStartHand(
                    requested=2,
                    available=self.active_player_count,
                )

            s = self._state

            hand_number = s.hand_count + 1
            hand_root_input = f"angzarr.poker.hand.{s.table_id}.{hand_number}"
            hand_hash = hashlib.sha256(hand_root_input.encode()).digest()
            hand_root = hand_hash[:16]

            advance = self._advance_blinds_with_dead_button()
            if advance is None:
                # Defensive fallback to naive rotation if not enough seats
                # — handler-level guard above already caught < 2 players,
                # so this is unreachable in practice.
                dealer_position = self._next_dealer_position()
                active_positions = sorted(
                    pos for pos, seat in s.seats.items() if not seat.is_sitting_out
                )
                dealer_position, sb_position, bb_position = (
                    self._derive_blind_positions(active_positions, dealer_position)
                )
            else:
                dealer_position, sb_position, bb_position = advance
            active_positions = sorted(
                pos for pos, seat in s.seats.items() if not seat.is_sitting_out
            )

            active_players = []
            for pos in active_positions:
                seat = s.seats[pos]
                active_players.append(
                    table_proto.SeatSnapshot(
                        position=pos,
                        player_root=seat.player_root,
                        stack=seat.stack,
                    )
                )

            event = table_proto.HandStarted(
                hand_root=hand_root,
                hand_number=hand_number,
                dealer_position=dealer_position,
                small_blind_position=sb_position,
                big_blind_position=bb_position,
                game_variant=s.game_variant,
                small_blind=s.small_blind,
                big_blind=s.big_blind,
                blind_level=cmd.blind_level,
                started_at=now(),
            )
            event.active_players.extend(active_players)

            if not router_mode:
                self._emit(event)

            # TDA Rule 71C — for each player on penalty, post their
            # blinds from their stack and emit a kill event. The seat
            # remains active (cards dealt) but the hand is marked dead.
            on_penalty = {b.hex() for b in cmd.players_on_penalty}
            if on_penalty:
                for pos in active_positions:
                    seat = s.seats[pos]
                    if seat.player_root.hex() not in on_penalty:
                        continue
                    charge = 0
                    if pos == sb_position:
                        charge += s.small_blind
                    if pos == bb_position:
                        charge += s.big_blind
                    kill_event = table_proto.PlayerHandKilledByPenalty(
                        player_root=seat.player_root,
                        hand_root=hand_root,
                        seat_position=pos,
                        stack_charged=charge,
                        killed_at=now(),
                    )
                    if not router_mode:
                        self._emit(kill_event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.EndHand)
    def handle_end_hand(
        self,
        cmd: table_proto.EndHand,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.HandEnded:
        """End the current hand."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if self.status != "in_hand":
                raise NoHandInProgress()
            if cmd.hand_root != self.current_hand_root:
                raise HandRootMismatch()

            stack_changes = {}
            for result in cmd.results:
                player_hex = result.winner_root.hex()
                if player_hex not in stack_changes:
                    stack_changes[player_hex] = 0
                stack_changes[player_hex] += result.amount

            event = table_proto.HandEnded(
                hand_root=cmd.hand_root,
                stack_changes=stack_changes,
                ended_at=now(),
            )
            event.results.extend(cmd.results)

            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(buy_in_proto.SeatPlayer)
    def handle_seat_player(
        self,
        cmd: buy_in_proto.SeatPlayer,
        state: _TableState | None = None,
        seq: int | None = None,
    ):
        """PM-orchestrated seating: validate and emit PlayerSeated or
        SeatingRejected. Unlike JoinTable this handler never raises — the
        rejection is an event so the PM can compensate.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()

            reason: str | None = None
            seat_position = cmd.seat

            if not cmd.player_root:
                reason = "player_root is required"
            elif self.find_player_seat(cmd.player_root) is not None:
                reason = "Player already seated"
            elif cmd.amount < self.min_buy_in:
                reason = f"Buy-in must be at least {self.min_buy_in}"
            elif cmd.amount > self.max_buy_in:
                reason = "Buy-in above maximum"
            elif 0 <= cmd.seat < self.max_players:
                if self.get_seat(cmd.seat) is not None:
                    reason = "Seat is occupied"
            elif cmd.seat == -1:
                if cmd.tournament_mode:
                    # TDA Rule 7 / WSOP Rule 34 — RNG-driven seat pick
                    # over all currently-open seats. Deterministic seed
                    # for replay: derived from rng_seed when supplied,
                    # else from player_root + table_id.
                    import hashlib
                    import random as _random

                    open_seats = sorted(
                        s for s in range(self.max_players) if self.get_seat(s) is None
                    )
                    if not open_seats:
                        reason = "Table is full"
                    else:
                        seed_in = cmd.rng_seed or (
                            cmd.player_root + self.table_id.encode()
                        )
                        seed_bytes = hashlib.sha256(seed_in).digest()[:16]
                        rng = _random.Random(int.from_bytes(seed_bytes[:8], "big"))
                        seat_position = rng.choice(open_seats)
                        # Stash the seed for the event below.
                        cmd_seed_used = seed_bytes
                else:
                    found = self._find_available_seat(-1)
                    if found is None:
                        reason = "Table is full"
                    else:
                        seat_position = found
            else:
                reason = "Invalid seat position"

            if reason is None:
                event = buy_in_proto.PlayerSeated(
                    player_root=cmd.player_root,
                    reservation_id=cmd.reservation_id,
                    seat_position=seat_position,
                    stack=cmd.amount,
                    rng_seed=(
                        locals().get("cmd_seed_used", b"")
                        if cmd.tournament_mode
                        else b""
                    ),
                    seated_at=now(),
                )
            else:
                event = buy_in_proto.SeatingRejected(
                    player_root=cmd.player_root,
                    reservation_id=cmd.reservation_id,
                    requested_seat=cmd.seat,
                    reason=reason,
                    rejected_at=now(),
                )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(rebuy_proto.AddRebuyChips)
    def handle_add_rebuy_chips(
        self,
        cmd: rebuy_proto.AddRebuyChips,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> rebuy_proto.RebuyChipsAdded:
        """PM-orchestrated rebuy chip top-up."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if not cmd.player_root:
                raise PlayerRootRequired()
            if cmd.amount <= 0:
                raise AmountMustBePositive(value=cmd.amount)
            seat = self.find_player_seat(cmd.player_root)
            if seat is None:
                raise PlayerNotSeated()
            if seat.position != cmd.seat:
                raise SeatPositionMismatch(expected=seat.position, got=cmd.seat)

            event = rebuy_proto.RebuyChipsAdded(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                seat=cmd.seat,
                amount=cmd.amount,
                new_stack=seat.stack + cmd.amount,
                added_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.EnterTableHandForHand)
    def handle_enter_table_h4h(
        self,
        cmd: table_proto.EnterTableHandForHand,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableHandForHandWaiting:
        """Park the table at WAITING for the current synchronised round.

        ``cmd.tournament_root`` is the tournament this H4H run belongs
        to; it rides on the emitted event so the apply can stash it on
        state for routing the eventual completion event back via
        saga-tournament-table-h4h.

        Idempotent: re-entering when already WAITING just re-emits.
        Re-entering after COMPLETE returns to WAITING — the saga uses
        ``EndTableHandForHand`` first when the previous-round complete
        state needs explicit clearing.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            event = table_proto.TableHandForHandWaiting(
                entered_at=now(),
                tournament_root=cmd.tournament_root,
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.MarkTableHandForHandHandComplete)
    def handle_mark_table_h4h_complete(
        self,
        cmd: table_proto.MarkTableHandForHandHandComplete,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableHandForHandRoundComplete:
        """Operator/saga signal that this table's synchronised H4H hand
        finished. Emits ``TableHandForHandRoundComplete`` whose apply
        flips ``hand_for_hand_status`` to COMPLETE — same end state as
        applying a real ``HandEnded``, which is what the real saga path
        does once it observes a HandEnded from the table aggregate.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            event = table_proto.TableHandForHandRoundComplete(
                hand_root=cmd.hand_root,
                completed_at=now(),
                tournament_root=self._state.hand_for_hand_tournament_root,
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.EndTableHandForHand)
    def handle_end_table_h4h(
        self,
        _cmd: table_proto.EndTableHandForHand,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableHandForHandEnded:
        """Clear the table's H4H status — back to normal cash-game pace.

        Issued either between H4H rounds (re-arm with
        ``EnterTableHandForHand`` immediately after) or once after
        ``HandForHandEnded`` on the tournament when the bubble breaks.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            event = table_proto.TableHandForHandEnded(ended_at=now())
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.HaltForBalancing)
    def handle_halt_for_balancing(
        self,
        cmd: table_proto.HaltForBalancing,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableHaltedForBalancing:
        """TDA Rule 11D — halt play at a table short ``deficit`` players
        relative to the largest table. The coordinator (tournament
        detection saga) is responsible for the cross-table comparison;
        this handler owns the per-table halt fact and the ``StartHand``
        gate that follows, plus the rule's deficit threshold."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if cmd.deficit < MIN_HALT_FOR_BALANCING_DEFICIT:
                raise HaltDeficitBelowMin(
                    min_deficit=MIN_HALT_FOR_BALANCING_DEFICIT,
                    got=cmd.deficit,
                )
            if self._state.halted_for_balancing:
                raise TableAlreadyHalted()
            event = table_proto.TableHaltedForBalancing(
                table_root=self._state.table_root,
                deficit=cmd.deficit,
                halted_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(table_proto.ResumePlayAtTable)
    def handle_resume_play_at_table(
        self,
        _cmd: table_proto.ResumePlayAtTable,
        state: _TableState | None = None,
        seq: int | None = None,
    ) -> table_proto.TableResumedForBalancing:
        """TDA Rule 11D — resume play at a halted table once rebalancing
        has closed the deficit. The coordinator decides; the table
        clears the halt flag and is open to ``StartHand`` again."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TableNotFound()
            if not self._state.halted_for_balancing:
                raise TableNotHalted()
            event = table_proto.TableResumedForBalancing(
                table_root=self._state.table_root,
                resumed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved


# Build the applier registry (event_type → method_name) from the class.
for _name in dir(Table):
    _attr = getattr(Table, _name, None)
    _marker = getattr(_attr, "__angzarr_applies__", None)
    if _marker is not None:
        _APPLIER_REGISTRY.append((_marker, _name))
