"""Table aggregate - rich domain model."""

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import applies, command_handler, handles, now
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in_proto
from angzarr_client.proto.examples import rebuy_pb2 as rebuy_proto
from angzarr_client.proto.examples import table_pb2 as table_proto


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
    hand_count: int = 0
    current_hand_root: bytes = b""
    status: str = ""


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

    @applies(table_proto.ChipsAdded)
    def apply_chips_added(
        self, state: _TableState, event: table_proto.ChipsAdded
    ) -> None:
        for seat in state.seats.values():
            if seat.player_root == event.player_root:
                seat.stack = event.new_stack
                break

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

    # region oo_handlers
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
                raise CommandRejectedError("Table already exists")
            if not cmd.table_name:
                raise CommandRejectedError("table_name is required")
            if cmd.small_blind <= 0:
                raise CommandRejectedError.invalid_argument(
                    "small_blind must be positive"
                )
            if cmd.big_blind <= 0 or cmd.big_blind < cmd.small_blind:
                raise CommandRejectedError("big_blind must be >= small_blind")
            if cmd.min_buy_in <= 0:
                raise CommandRejectedError.invalid_argument(
                    "min_buy_in must be positive"
                )
            if cmd.max_buy_in < cmd.min_buy_in:
                raise CommandRejectedError("max_buy_in must be >= min_buy_in")
            if cmd.max_players < 2 or cmd.max_players > 10:
                raise CommandRejectedError("max_players must be 2-10")

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
                raise CommandRejectedError("Table does not exist")
            if not cmd.player_root:
                raise CommandRejectedError("player_root is required")
            if self.find_player_seat(cmd.player_root):
                raise CommandRejectedError("Player already seated at table")
            if self.is_full:
                raise CommandRejectedError("Table is full")
            if cmd.buy_in_amount < self.min_buy_in:
                raise CommandRejectedError.invalid_argument(
                    f"Buy-in must be at least {self.min_buy_in}"
                )
            if cmd.buy_in_amount > self.max_buy_in:
                raise CommandRejectedError.invalid_argument(
                    f"Buy-in cannot exceed {self.max_buy_in}"
                )
            if cmd.preferred_seat >= 0 and cmd.preferred_seat < self.max_players:
                if self.get_seat(cmd.preferred_seat) is not None:
                    raise CommandRejectedError("Seat is occupied")
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
                raise CommandRejectedError("Table does not exist")
            if not cmd.player_root:
                raise CommandRejectedError("player_root is required")

            seat = self.find_player_seat(cmd.player_root)
            if not seat:
                raise CommandRejectedError("Player is not seated at table")
            if self.status == "in_hand":
                raise CommandRejectedError("Cannot leave table during a hand")

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
                raise CommandRejectedError("Table does not exist")
            if self.status == "in_hand":
                raise CommandRejectedError("Hand already in progress")
            if self.active_player_count < 2:
                raise CommandRejectedError("Not enough players to start hand")

            s = self._state

            hand_number = s.hand_count + 1
            hand_root_input = f"angzarr.poker.hand.{s.table_id}.{hand_number}"
            hand_hash = hashlib.sha256(hand_root_input.encode()).digest()
            hand_root = hand_hash[:16]

            dealer_position = self._next_dealer_position()

            active_positions = sorted(
                pos for pos, seat in s.seats.items() if not seat.is_sitting_out
            )

            dealer_idx = 0
            for i, pos in enumerate(active_positions):
                if pos == dealer_position:
                    dealer_idx = i
                    break

            if len(active_positions) == 2:
                sb_position = active_positions[dealer_idx]
                bb_position = active_positions[(dealer_idx + 1) % 2]
            else:
                sb_position = active_positions[(dealer_idx + 1) % len(active_positions)]
                bb_position = active_positions[(dealer_idx + 2) % len(active_positions)]

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
                started_at=now(),
            )
            event.active_players.extend(active_players)

            if not router_mode:
                self._emit(event)
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
                raise CommandRejectedError("Table does not exist")
            if self.status != "in_hand":
                raise CommandRejectedError("No hand in progress")
            if cmd.hand_root != self.current_hand_root:
                raise CommandRejectedError("Hand root mismatch")

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
                raise CommandRejectedError("Table does not exist")

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
                raise CommandRejectedError("Table does not exist")
            if not cmd.player_root:
                raise CommandRejectedError("player_root is required")
            if cmd.amount <= 0:
                raise CommandRejectedError.invalid_argument("amount must be positive")
            seat = self.find_player_seat(cmd.player_root)
            if seat is None:
                raise CommandRejectedError("Player is not seated at this table")
            if seat.position != cmd.seat:
                raise CommandRejectedError("Seat position mismatch")

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


# Build the applier registry (event_type → method_name) from the class.
for _name in dir(Table):
    _attr = getattr(Table, _name, None)
    _marker = getattr(_attr, "__angzarr_applies__", None)
    if _marker is not None:
        _APPLIER_REGISTRY.append((_marker, _name))
