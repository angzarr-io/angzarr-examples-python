"""Table aggregate business seam.

Ported from the hand-written ``table/agg/handlers/table.py`` baseline onto the
angzarr-cli generated harness. The baseline kept its own ``_TableState`` /
``_SeatState`` dataclasses with computed properties; this implementation folds
events directly into the **proto** ``TableState`` message and reads/writes the
proto seat fields. The poker rules (seating, blinds, buy-in bounds, join/leave,
start/end hand, rebuy chips, DealCards rejection) are preserved faithfully.

State model mapping (dataclass -> proto ``TableState``):

  * ``_TableState.seats: dict[pos -> _SeatState]`` -> ``state.seats`` is a
    ``repeated Seat``; helpers below treat it as a position-keyed collection.
  * ``_SeatState.stack: int`` -> ``Seat.stack`` is a ``Currency`` message, so a
    seat's chip count lives at ``seat.stack.amount`` (int64).
  * ``_SeatState.is_active`` / ``is_sitting_out`` -> ``Seat.is_active`` /
    ``Seat.is_sitting_out``.
  * Scalar table fields (table_id, table_name, blinds, buy-in bounds,
    max_players, dealer_position, hand_count, current_hand_root, status) map
    one-to-one onto the like-named ``TableState`` fields.

The handler never stamps page sequences: the core stamps consecutive
sequences on the EventBook pages it receives (see the binding's command
round-trip). Each command handler returns an ``EventBook`` (one packed event)
or raises a ``CodedError`` (via :func:`angzarr_router_ffi.reject`) to reject.
"""

from __future__ import annotations

import hashlib
from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as _buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.examples.v1 import rebuy_pb2 as _rebuy
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.v1 import command_handler_pb2 as _ch
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.table_aggregate_angzarr import (
    TableAggregateHandler,
)


# --- module-level helpers operating on the proto TableState ---
#
# The baseline carried these as _TableState/_SeatState dataclass methods. Here
# they are free functions that read/write the proto state directly.


def _now() -> Timestamp:
    """Wall-clock timestamp for ``*_at`` event fields. The seam exposes no
    injected clock (CommandContext carries only sequence evidence), so the
    handler stamps the current time, matching the baseline ``now()`` helper."""
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _exists(state: _table.TableState) -> bool:
    """A table exists once TableCreated has been folded (table_id is set)."""
    return bool(state.table_id)


def _root(name: str) -> bytes:
    """The example derives a table's root deterministically from its name (the
    same scheme the harness/coordinator uses), so a name-addressed command can
    name another table by root."""
    return hashlib.sha256(name.encode()).digest()[:16]


def _find_player_seat(state: _table.TableState, player_root: bytes):
    """The seat occupied by ``player_root``, or ``None``."""
    for seat in state.seats:
        if seat.player_root == player_root:
            return seat
    return None


def _get_seat(state: _table.TableState, position: int):
    """The seat at ``position``, or ``None``."""
    for seat in state.seats:
        if seat.position == position:
            return seat
    return None


def _occupied_positions(state: _table.TableState) -> set[int]:
    return {seat.position for seat in state.seats}


def _find_available_seat(state: _table.TableState, preferred: int = -1) -> Optional[int]:
    """Lowest free position, honoring ``preferred`` when valid and open."""
    occupied = _occupied_positions(state)
    if 0 <= preferred < state.max_players and preferred not in occupied:
        return preferred
    for pos in range(state.max_players):
        if pos not in occupied:
            return pos
    return None


def _next_dealer_position(state: _table.TableState) -> int:
    """The next occupied seat after the current dealer (wraps around)."""
    if not state.seats:
        return 0
    positions = sorted(seat.position for seat in state.seats)
    current_idx = 0
    for i, pos in enumerate(positions):
        if pos == state.dealer_position:
            current_idx = i
            break
    next_idx = (current_idx + 1) % len(positions)
    return positions[next_idx]


def _book(*events) -> _t.EventBook:
    """Pack one or more typed events into an EventBook (the core stamps the
    page sequences)."""
    book = _t.EventBook()
    for ev in events:
        book.pages.add().event.CopyFrom(_az.pack(ev))
    return book


class TableAggregate:
    """Implements ``TableAggregateHandler``: the strict business seam for the
    Table aggregate."""

    # --- command handlers ---

    def create_table(
        self,
        cmd: _table.CreateTable,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if _exists(state):
            raise _az.reject("TABLE_EXISTS", "Table already exists")
        if not cmd.table_name:
            raise _az.reject("INVALID_ARGUMENT", "table_name is required")
        if cmd.small_blind <= 0:
            raise _az.reject("INVALID_ARGUMENT", "small_blind must be positive")
        if cmd.big_blind <= 0 or cmd.big_blind < cmd.small_blind:
            raise _az.reject("INVALID_ARGUMENT", "big_blind must be >= small_blind")
        if cmd.min_buy_in <= 0:
            raise _az.reject("INVALID_ARGUMENT", "min_buy_in must be positive")
        if cmd.max_buy_in < cmd.min_buy_in:
            raise _az.reject("INVALID_ARGUMENT", "max_buy_in must be >= min_buy_in")
        if cmd.max_players < 2 or cmd.max_players > 10:
            raise _az.reject("INVALID_ARGUMENT", "max_players must be 2-10")

        event = _table.TableCreated(
            table_name=cmd.table_name,
            game_variant=cmd.game_variant,
            small_blind=cmd.small_blind,
            big_blind=cmd.big_blind,
            min_buy_in=cmd.min_buy_in,
            max_buy_in=cmd.max_buy_in,
            max_players=cmd.max_players,
            action_timeout_seconds=cmd.action_timeout_seconds or 30,
            created_at=_now(),
        )
        return _book(event)

    def join_table(
        self,
        cmd: _table.JoinTable,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        if not cmd.player_root:
            raise _az.reject("INVALID_ARGUMENT", "player_root is required")
        if _find_player_seat(state, cmd.player_root) is not None:
            raise _az.reject("PLAYER_ALREADY_SEATED", "Player already seated at table")
        if len(state.seats) >= state.max_players:
            raise _az.reject("TABLE_FULL", "Table is full")
        if cmd.buy_in_amount < state.min_buy_in:
            raise _az.reject(
                "INVALID_ARGUMENT", f"Buy-in must be at least {state.min_buy_in}"
            )
        if cmd.buy_in_amount > state.max_buy_in:
            raise _az.reject(
                "INVALID_ARGUMENT", f"Buy-in cannot exceed {state.max_buy_in}"
            )
        if 0 <= cmd.preferred_seat < state.max_players:
            if _get_seat(state, cmd.preferred_seat) is not None:
                raise _az.reject("SEAT_OCCUPIED", "Seat is occupied")
            seat_position = cmd.preferred_seat
        else:
            seat_position = _find_available_seat(state, -1)

        event = _table.PlayerJoined(
            player_root=cmd.player_root,
            seat_position=seat_position,
            buy_in_amount=cmd.buy_in_amount,
            stack=cmd.buy_in_amount,
            joined_at=_now(),
        )
        return _book(event)

    def leave_table(
        self,
        cmd: _table.LeaveTable,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        if not cmd.player_root:
            raise _az.reject("INVALID_ARGUMENT", "player_root is required")

        seat = _find_player_seat(state, cmd.player_root)
        if seat is None:
            raise _az.reject("PLAYER_NOT_SEATED", "Player is not seated at table")
        if state.status == "in_hand":
            raise _az.reject("HAND_IN_PROGRESS", "Cannot leave table during a hand")

        event = _table.PlayerLeft(
            player_root=cmd.player_root,
            seat_position=seat.position,
            chips_cashed_out=seat.stack.amount,
            left_at=_now(),
        )
        return _book(event)

    def start_hand(
        self,
        cmd: _table.StartHand,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        if state.halted_for_balancing:
            # TDA Rule 11D: a halted table starts no new hands until resumed.
            raise _az.reject("TABLE_HALTED_FOR_BALANCING", "Table is halted for balancing")
        if state.status == "in_hand":
            raise _az.reject("HAND_IN_PROGRESS", "Hand already in progress")

        active_seats = [s for s in state.seats if not s.is_sitting_out]
        if len(active_seats) < 2:
            raise _az.reject("NOT_ENOUGH_PLAYERS", "Not enough players to start hand")

        hand_number = state.hand_count + 1
        hand_root_input = f"angzarr.poker.hand.{state.table_id}.{hand_number}"
        hand_root = hashlib.sha256(hand_root_input.encode()).digest()[:16]

        if state.hand_count == 0:
            # WSOP Rule 85: on the first hand the button is deterministic — the
            # seat with the first chip stack to the dealer's right (counter-
            # clockwise), i.e. the highest-numbered occupied seat. Later hands
            # advance the button to the next occupied seat.
            dealer_position = max(s.position for s in active_seats)
        else:
            dealer_position = _next_dealer_position(state)

        active_positions = sorted(s.position for s in active_seats)
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

        by_position = {s.position: s for s in active_seats}
        active_players = [
            _table.SeatSnapshot(
                position=pos,
                player_root=by_position[pos].player_root,
                stack=by_position[pos].stack.amount,
            )
            for pos in active_positions
        ]

        event = _table.HandStarted(
            hand_root=hand_root,
            hand_number=hand_number,
            dealer_position=dealer_position,
            small_blind_position=sb_position,
            big_blind_position=bb_position,
            game_variant=state.game_variant,
            small_blind=state.small_blind,
            big_blind=state.big_blind,
            started_at=_now(),
        )
        event.active_players.extend(active_players)
        return _book(event)

    def end_hand(
        self,
        cmd: _table.EndHand,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        if state.status != "in_hand":
            raise _az.reject("NO_HAND_IN_PROGRESS", "No hand in progress")
        if cmd.hand_root != state.current_hand_root:
            raise _az.reject("HAND_ROOT_MISMATCH", "Hand root mismatch")

        stack_changes: dict[str, int] = {}
        for result in cmd.results:
            player_hex = result.winner_root.hex()
            stack_changes[player_hex] = stack_changes.get(player_hex, 0) + result.amount

        event = _table.HandEnded(
            hand_root=cmd.hand_root,
            stack_changes=stack_changes,
            ended_at=_now(),
        )
        event.results.extend(cmd.results)
        return _book(event)

    def seat_player(
        self,
        cmd: _buy_in.SeatPlayer,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        """PM-orchestrated seating: validate and emit PlayerSeated or
        SeatingRejected. Unlike join_table this never raises a business
        rejection for a seating failure -- the rejection is an *event* so the
        process manager can compensate. (A nonexistent table is still a hard
        rejection.)"""
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")

        reason: Optional[str] = None
        seat_position = cmd.seat

        if not cmd.player_root:
            reason = "player_root is required"
        elif _find_player_seat(state, cmd.player_root) is not None:
            reason = "Player already seated"
        elif cmd.amount < state.min_buy_in:
            reason = f"Buy-in must be at least {state.min_buy_in}"
        elif cmd.amount > state.max_buy_in:
            reason = "Buy-in above maximum"
        elif 0 <= cmd.seat < state.max_players:
            if _get_seat(state, cmd.seat) is not None:
                reason = "Seat is occupied"
        elif cmd.seat == -1:
            found = _find_available_seat(state, -1)
            if found is None:
                reason = "Table is full"
            else:
                seat_position = found
        else:
            reason = "Invalid seat position"

        if reason is None:
            event = _buy_in.PlayerSeated(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                seat_position=seat_position,
                stack=cmd.amount,
                seated_at=_now(),
            )
        else:
            event = _buy_in.SeatingRejected(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                requested_seat=cmd.seat,
                reason=reason,
                rejected_at=_now(),
            )
        return _book(event)

    def add_rebuy_chips(
        self,
        cmd: _rebuy.AddRebuyChips,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        """PM-orchestrated rebuy chip top-up."""
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        if not cmd.player_root:
            raise _az.reject("INVALID_ARGUMENT", "player_root is required")
        if cmd.amount <= 0:
            raise _az.reject("INVALID_ARGUMENT", "amount must be positive")
        seat = _find_player_seat(state, cmd.player_root)
        if seat is None:
            raise _az.reject(
                "PLAYER_NOT_SEATED", "Player is not seated at this table"
            )
        if seat.position != cmd.seat:
            raise _az.reject("SEAT_MISMATCH", "Seat position mismatch")

        event = _rebuy.RebuyChipsAdded(
            player_root=cmd.player_root,
            reservation_id=cmd.reservation_id,
            seat=cmd.seat,
            amount=cmd.amount,
            new_stack=seat.stack.amount + cmd.amount,
            added_at=_now(),
        )
        return _book(event)

    # --- event appliers (fold events into the proto TableState in place) ---

    def apply_table_created(
        self, state: _table.TableState, event: _table.TableCreated
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

    def apply_player_joined(
        self, state: _table.TableState, event: _table.PlayerJoined
    ) -> None:
        _add_seat(state, event.seat_position, event.player_root, event.stack)

    def apply_player_left(
        self, state: _table.TableState, event: _table.PlayerLeft
    ) -> None:
        _remove_seat(state, event.seat_position)

    def apply_player_sat_out(
        self, state: _table.TableState, event: _table.PlayerSatOut
    ) -> None:
        seat = _find_player_seat(state, event.player_root)
        if seat is not None:
            seat.is_sitting_out = True

    def apply_player_sat_in(
        self, state: _table.TableState, event: _table.PlayerSatIn
    ) -> None:
        seat = _find_player_seat(state, event.player_root)
        if seat is not None:
            seat.is_sitting_out = False

    def apply_hand_started(
        self, state: _table.TableState, event: _table.HandStarted
    ) -> None:
        state.hand_count = event.hand_number
        state.current_hand_root = event.hand_root
        state.dealer_position = event.dealer_position
        state.status = "in_hand"

    def apply_hand_ended(
        self, state: _table.TableState, event: _table.HandEnded
    ) -> None:
        state.current_hand_root = b""
        state.status = "waiting"
        for player_hex, delta in event.stack_changes.items():
            player_root = bytes.fromhex(player_hex)
            seat = _find_player_seat(state, player_root)
            if seat is not None:
                seat.stack.amount += delta

    def apply_chips_added(
        self, state: _table.TableState, event: _table.ChipsAdded
    ) -> None:
        seat = _find_player_seat(state, event.player_root)
        if seat is not None:
            seat.stack.amount = event.new_stack

    def apply_player_seated(
        self, state: _table.TableState, event: _buy_in.PlayerSeated
    ) -> None:
        _add_seat(state, event.seat_position, event.player_root, event.stack)

    def apply_seating_rejected(
        self, state: _table.TableState, event: _buy_in.SeatingRejected
    ) -> None:
        # SeatingRejected carries no state change for the table -- the seat was
        # never occupied. Recorded for audit / replay completeness.
        return None

    def apply_rebuy_chips_added(
        self, state: _table.TableState, event: _rebuy.RebuyChipsAdded
    ) -> None:
        seat = _find_player_seat(state, event.player_root)
        if seat is not None:
            seat.stack.amount = event.new_stack

    # --- Rule 11A balancing (source-table BB-next decision) ---

    def balance_tables(
        self, cmd: _table.BalanceTables, state: _table.TableState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        active = [s for s in state.seats if not s.is_sitting_out]
        if not active:
            raise _az.reject("NO_PLAYERS_TO_MOVE", "No players to move")
        positions = sorted(s.position for s in active)
        dealer = state.dealer_position
        dealer_idx = positions.index(dealer) if dealer in positions else 0
        # TDA Rule 11A: the player who will be big blind on the next hand moves.
        # After the button advances one seat, the next BB is three seats past the
        # current button. The destination seat is chosen at the destination table.
        bb_next_pos = positions[(dealer_idx + 3) % len(positions)]
        moved = next(s for s in active if s.position == bb_next_pos)
        return _book(
            _table.BalancingMoveDecided(
                player_root=moved.player_root,
                source_table_root=_root(cmd.source_table_name),
                destination_table_root=_root(cmd.destination_table_name),
                moved_at=_now(),
            )
        )

    def apply_balancing_move_decided(
        self, state: _table.TableState, event: _table.BalancingMoveDecided
    ) -> None:
        remaining = [s for s in state.seats if s.player_root != event.player_root]
        if len(remaining) != len(state.seats):
            del state.seats[:]
            state.seats.extend(remaining)

    # --- Rule 11D halt/resume execution (coordinator-issued) ---

    def halt_for_balancing(
        self, cmd: _table.HaltForBalancing, state: _table.TableState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        return _book(_table.TableHaltedForBalancing(deficit=cmd.deficit, halted_at=_now()))

    def resume_play_at_table(
        self, cmd: _table.ResumePlayAtTable, state: _table.TableState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _az.reject("TABLE_NOT_FOUND", "Table does not exist")
        return _book(_table.TableResumedForBalancing(resumed_at=_now()))

    def apply_table_halted_for_balancing(
        self, state: _table.TableState, event: _table.TableHaltedForBalancing
    ) -> None:
        state.halted_for_balancing = True

    def apply_table_resumed_for_balancing(
        self, state: _table.TableState, event: _table.TableResumedForBalancing
    ) -> None:
        state.halted_for_balancing = False

    # --- rejection compensator ---

    def on_deal_cards_rejected(
        self,
        n: _t.Notification,
        rejection: _t.RejectionNotification,
        state: _table.TableState,
        cctx: _az.CommandContext,
    ) -> Optional[_ch.BusinessResponse]:
        """The baseline had no DealCards rejection compensator for the Table
        aggregate. DealCards is owned by the Hand aggregate; the table emits no
        compensating events here, so the rejection is acknowledged with no
        response (no events, no revocation)."""
        return None


def _add_seat(
    state: _table.TableState, position: int, player_root: bytes, stack: int
) -> None:
    """Insert (or replace) a seat. ``Seat.stack`` is a ``Currency`` message, so
    the chip count is written to ``stack.amount``."""
    _remove_seat(state, position)
    seat = state.seats.add()
    seat.position = position
    seat.player_root = player_root
    seat.stack.CopyFrom(_pt.Currency(amount=stack))
    seat.is_active = True
    seat.is_sitting_out = False


def _remove_seat(state: _table.TableState, position: int) -> None:
    """Drop the seat at ``position`` from the repeated ``seats`` field."""
    remaining = [s for s in state.seats if s.position != position]
    if len(remaining) != len(state.seats):
        del state.seats[:]
        state.seats.extend(remaining)


# Static guarantee that the class satisfies the generated Protocol.
_: TableAggregateHandler = TableAggregate()
