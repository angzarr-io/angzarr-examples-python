"""The TableAggregate on the generated ``TableAggregateHandler`` seam.

The table owns every chip in front of its players and the whole round
lifecycle: seats are held then confirmed, bets are placed, the round is dealt,
each seat acts in turn, and the action that finishes the last hand also plays
the dealer and settles the round in the same EventBook. Each command runs
``_guard_*`` → ``_validate_*`` → ``_compute_*``; the computations are pure and
fold the events they emit into a working copy of the state, so a later event
in the same book sees an earlier one. House rules are in :mod:`.rules`.
"""

from __future__ import annotations

import enum
import uuid

import angzarr_router_ffi as _az

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import event_book
from angzarr_blackjack.cards import (
    hand_value,
    is_blackjack,
    next_seed,
    shuffle,
)
from angzarr_blackjack.errors import invalid, precondition
from angzarr_blackjack.table.agg import rules

TableState = _table.TableState
Phase = TableState.Phase


class Effect(enum.Enum):
    APPLY = "apply"
    ALREADY_APPLIED = "already_applied"


def cashout_id(table_root: bytes, sequence: int) -> bytes:
    """UUIDv5(namespace = the table root as a UUID, name = "cashout/<sequence>")."""
    return uuid.uuid5(uuid.UUID(bytes=table_root), f"cashout/{sequence}").bytes


def seat_of(state: TableState, player_root: bytes) -> int | None:
    for number, seat in state.seated.items():
        if seat.player_root == player_root:
            return number
    return None


def wagered_seats(state: TableState) -> list[int]:
    return sorted(number for number, seat in state.seated.items() if seat.wager > 0)


def finished_hands(state: TableState) -> dict[int, bool]:
    return {number: state.seated[number].finished for number in wagered_seats(state)}


class _Book:
    """Events emitted by one command, folded as they are emitted into a copy
    of the state."""

    def __init__(self, aggregate: TableAggregate, state: TableState) -> None:
        self._aggregate = aggregate
        self.state = TableState()
        self.state.CopyFrom(state)
        self.events: list = []
        self.lasting_snapshot = False

    def emit(self, event) -> None:
        self.events.append(event)
        self._aggregate.apply(self.state, event)

    def to_event_book(self) -> _t.EventBook | None:
        if not self.events:
            return None
        book = event_book(*self.events)
        if self.lasting_snapshot:
            book.snapshot.state.CopyFrom(_az.pack(self.state))
            book.snapshot.retention = _t.SnapshotRetention.RETENTION_PERSIST
        return book


class TableAggregate:
    """Implements ``TableAggregateHandler``: seats, shoe, rounds, settlement."""

    def __init__(self) -> None:
        self._appliers = {
            _table.TableCreated: self.apply_table_created,
            _table.ShoeShuffled: self.apply_shoe_shuffled,
            _table.SeatHeld: self.apply_seat_held,
            _table.SeatReleased: self.apply_seat_released,
            _table.PlayerSeated: self.apply_player_seated,
            _table.ChipsAdded: self.apply_chips_added,
            _table.PlayerCashedOut: self.apply_player_cashed_out,
            _table.BetPlaced: self.apply_bet_placed,
            _table.RoundDealt: self.apply_round_dealt,
            _table.CardDealt: self.apply_card_dealt,
            _table.HandStood: self.apply_hand_stood,
            _table.HandDoubled: self.apply_hand_doubled,
            _table.DealerPlayed: self.apply_dealer_played,
            _table.RoundSettled: self.apply_round_settled,
        }

    def apply(self, state: TableState, event) -> None:
        self._appliers[type(event)](state, event)

    def _run(
        self, guard, validate, compute, cmd, state, cctx=None
    ) -> _t.EventBook | None:
        guard(state)
        effect = validate(cmd, state)
        book = _Book(self, state)
        if effect is not Effect.ALREADY_APPLIED:
            compute(cmd, book, effect, cctx)
        return book.to_event_book()

    # --- shared guards ---

    @staticmethod
    def _guard_exists(state: TableState) -> None:
        if state.phase == Phase.PHASE_UNSPECIFIED:
            raise precondition("TABLE_NOT_FOUND", "the table does not exist")

    @staticmethod
    def _guard_between_rounds(state: TableState) -> None:
        TableAggregate._guard_exists(state)
        if state.phase == Phase.PHASE_PLAYER_TURNS:
            raise precondition("ROUND_IN_PROGRESS", "a round is in progress")

    @staticmethod
    def _guard_round_in_progress(state: TableState) -> None:
        TableAggregate._guard_exists(state)
        if state.phase != Phase.PHASE_PLAYER_TURNS:
            raise precondition("NO_ROUND_IN_PROGRESS", "no round is in progress")

    @staticmethod
    def _validate_seat_number(seat: int, state: TableState) -> None:
        if not 0 <= seat < state.seats:
            raise invalid("SEAT_OUT_OF_RANGE", f"seat {seat} does not exist")

    @staticmethod
    def _validate_occupied(seat: int, state: TableState) -> _table.TableSeat:
        TableAggregate._validate_seat_number(seat, state)
        if seat not in state.seated:
            raise precondition("NOT_SEATED", f"seat {seat} is not occupied")
        return state.seated[seat]

    @staticmethod
    def _validate_no_wager(seat: _table.TableSeat) -> None:
        if seat.wager > 0:
            raise precondition("WAGER_IN_PLAY", "the seat has a wager in play")

    # --- creating the table ---

    def create_table(
        self, cmd: _table.CreateTable, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_new, self._validate_config, self._compute_create, cmd, state
        )

    @staticmethod
    def _guard_new(state: TableState) -> None:
        if state.phase != Phase.PHASE_UNSPECIFIED:
            raise precondition("TABLE_ALREADY_EXISTS", "the table already exists")

    @staticmethod
    def _validate_config(cmd: _table.CreateTable, state: TableState) -> Effect:
        if not rules.config_is_valid(
            cmd.seats,
            cmd.decks,
            cmd.min_bet,
            cmd.max_bet,
            cmd.min_buy_in,
            cmd.max_buy_in,
        ):
            raise invalid(
                "INVALID_TABLE_CONFIG", "the table configuration breaks the house rules"
            )
        return Effect.APPLY

    @staticmethod
    def _compute_create(cmd: _table.CreateTable, book: _Book, effect, cctx) -> None:
        book.emit(
            _table.TableCreated(
                name=cmd.name,
                min_bet=cmd.min_bet,
                max_bet=cmd.max_bet,
                min_buy_in=cmd.min_buy_in,
                max_buy_in=cmd.max_buy_in,
                seats=cmd.seats,
                decks=cmd.decks,
            )
        )
        book.emit(
            _table.ShoeShuffled(
                shoe_number=1,
                seed=cmd.shoe_seed,
                decks=cmd.decks,
                cards=shuffle(cmd.shoe_seed, cmd.decks),
            )
        )
        book.lasting_snapshot = True

    # --- seats (held for a buy-in, then confirmed or released) ---

    def request_seat(
        self, cmd: _table.RequestSeat, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_exists,
            self._validate_request_seat,
            self._compute_request_seat,
            cmd,
            state,
        )

    @classmethod
    def _validate_request_seat(
        cls, cmd: _table.RequestSeat, state: TableState
    ) -> Effect:
        key = cmd.request_id.hex()
        hold = state.seat_holds.get(key)
        if hold is not None and (hold.player_root, hold.seat, hold.amount) == (
            cmd.player_root,
            cmd.seat,
            cmd.amount,
        ):
            return Effect.ALREADY_APPLIED
        if key in state.confirmed_buy_ins:
            return Effect.ALREADY_APPLIED
        cls._validate_seat_number(cmd.seat, state)
        if not state.min_buy_in <= cmd.amount <= state.max_buy_in:
            raise invalid(
                "BUY_IN_OUT_OF_RANGE",
                f"the buy-in must be within {state.min_buy_in} to {state.max_buy_in}",
            )
        held = {h.seat for h in state.seat_holds.values()}
        if cmd.seat in state.seated or cmd.seat in held or hold is not None:
            raise precondition("SEAT_TAKEN", f"seat {cmd.seat} is taken")
        if seat_of(state, cmd.player_root) is not None:
            raise precondition("PLAYER_ALREADY_SEATED", "the player is already seated")
        return Effect.APPLY

    @staticmethod
    def _compute_request_seat(
        cmd: _table.RequestSeat, book: _Book, effect, cctx
    ) -> None:
        book.emit(
            _table.SeatHeld(
                buy_in_id=cmd.request_id,
                player_root=cmd.player_root,
                seat=cmd.seat,
                amount=cmd.amount,
            )
        )

    def confirm_seat(
        self, cmd: _table.ConfirmSeat, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_exists,
            self._validate_confirm,
            self._compute_confirm,
            cmd,
            state,
        )

    @staticmethod
    def _validate_confirm(cmd: _table.ConfirmSeat, state: TableState) -> Effect:
        key = cmd.buy_in_id.hex()
        if key in state.confirmed_buy_ins:
            return Effect.ALREADY_APPLIED
        hold = state.seat_holds.get(key)
        if hold is None:
            raise precondition("SEAT_HOLD_NOT_FOUND", f"buy-in {key} holds no seat")
        if seat_of(state, hold.player_root) is not None:
            raise precondition("PLAYER_ALREADY_SEATED", "the player is already seated")
        return Effect.APPLY

    @staticmethod
    def _compute_confirm(cmd: _table.ConfirmSeat, book: _Book, effect, cctx) -> None:
        hold = book.state.seat_holds[cmd.buy_in_id.hex()]
        book.emit(
            _table.PlayerSeated(
                buy_in_id=cmd.buy_in_id,
                player_root=hold.player_root,
                seat=hold.seat,
                stack=hold.amount,
            )
        )

    def release_seat(
        self, cmd: _table.ReleaseSeat, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_exists,
            self._validate_release,
            self._compute_release,
            cmd,
            state,
        )

    @staticmethod
    def _validate_release(cmd: _table.ReleaseSeat, state: TableState) -> Effect:
        if cmd.buy_in_id.hex() not in state.seat_holds:
            return Effect.ALREADY_APPLIED
        return Effect.APPLY

    @staticmethod
    def _compute_release(cmd: _table.ReleaseSeat, book: _Book, effect, cctx) -> None:
        hold = book.state.seat_holds[cmd.buy_in_id.hex()]
        book.emit(
            _table.SeatReleased(
                buy_in_id=cmd.buy_in_id,
                player_root=hold.player_root,
                seat=hold.seat,
                reason=cmd.reason,
            )
        )

    # --- chips in and out ---

    def add_chips(
        self, cmd: _table.AddChips, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_exists,
            self._validate_add_chips,
            self._compute_add_chips,
            cmd,
            state,
        )

    @classmethod
    def _validate_add_chips(cls, cmd: _table.AddChips, state: TableState) -> Effect:
        if cmd.hold_id.hex() in state.added_holds:
            return Effect.ALREADY_APPLIED
        number = seat_of(state, cmd.player_root)
        if number is None:
            raise precondition("NOT_SEATED", "the player has no seat at this table")
        seat = state.seated[number]
        cls._validate_no_wager(seat)
        if seat.stack + cmd.amount > state.max_buy_in:
            raise invalid(
                "TOP_UP_EXCEEDS_MAX",
                f"the stack would exceed the maximum buy-in {state.max_buy_in}",
            )
        return Effect.APPLY

    @staticmethod
    def _compute_add_chips(cmd: _table.AddChips, book: _Book, effect, cctx) -> None:
        number = seat_of(book.state, cmd.player_root)
        book.emit(
            _table.ChipsAdded(
                hold_id=cmd.hold_id,
                player_root=cmd.player_root,
                seat=number,
                amount=cmd.amount,
                stack_after=book.state.seated[number].stack + cmd.amount,
            )
        )

    def leave_table(
        self, cmd: _table.LeaveTable, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_exists,
            self._validate_leave,
            self._compute_leave,
            cmd,
            state,
            cctx,
        )

    @classmethod
    def _validate_leave(cls, cmd: _table.LeaveTable, state: TableState) -> Effect:
        cls._validate_no_wager(cls._validate_occupied(cmd.seat, state))
        return Effect.APPLY

    @staticmethod
    def _compute_leave(cmd: _table.LeaveTable, book: _Book, effect, cctx) -> None:
        seat = book.state.seated[cmd.seat]
        book.emit(
            _table.PlayerCashedOut(
                cashout_id=cashout_id(cctx.cover.root.value, cctx.next_sequence),
                player_root=seat.player_root,
                seat=cmd.seat,
                amount=seat.stack,
            )
        )

    # --- the round ---

    # region handlers
    def place_bet(
        self, cmd: _table.PlaceBet, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_between_rounds,
            self._validate_bet,
            self._compute_bet,
            cmd,
            state,
        )

    @classmethod
    def _validate_bet(cls, cmd: _table.PlaceBet, state: TableState) -> Effect:
        seat = cls._validate_occupied(cmd.seat, state)
        if seat.wager > 0:
            raise precondition(
                "ALREADY_BET", f"seat {cmd.seat} has already bet this round"
            )
        if not state.min_bet <= cmd.amount <= state.max_bet:
            raise invalid(
                "BET_OUT_OF_RANGE",
                f"the bet must be within {state.min_bet} to {state.max_bet}",
            )
        if cmd.amount % 2:
            raise invalid("BET_NOT_EVEN", "the bet must be an even amount")
        if cmd.amount > seat.stack:
            raise precondition("INSUFFICIENT_STACK", "the stack is too small")
        return Effect.APPLY

    @staticmethod
    def _compute_bet(cmd: _table.PlaceBet, book: _Book, effect, cctx) -> None:
        seat = book.state.seated[cmd.seat]
        book.emit(
            _table.BetPlaced(
                round=book.state.round + 1,
                seat=cmd.seat,
                player_root=seat.player_root,
                amount=cmd.amount,
                stack_after=seat.stack - cmd.amount,
            )
        )

    def deal_round(
        self, cmd: _table.DealRound, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_between_rounds,
            self._validate_deal,
            self._compute_deal,
            cmd,
            state,
        )

    @staticmethod
    def _validate_deal(cmd: _table.DealRound, state: TableState) -> Effect:
        if not wagered_seats(state):
            raise precondition("NO_BETS", "nobody has bet")
        return Effect.APPLY

    def _compute_deal(self, cmd: _table.DealRound, book: _Book, effect, cctx) -> None:
        seats = wagered_seats(book.state)
        if rules.needs_reshuffle(len(book.state.shoe), len(seats)):
            seed = next_seed(book.state.shoe_seed)
            book.emit(
                _table.ShoeShuffled(
                    shoe_number=book.state.shoe_number + 1,
                    seed=seed,
                    decks=book.state.decks,
                    cards=shuffle(seed, book.state.decks),
                )
            )
            book.lasting_snapshot = True
        shoe = list(book.state.shoe)
        first, dealer_up = shoe[: len(seats)], shoe[len(seats)]
        second, dealer_hole = (
            shoe[len(seats) + 1 : 2 * len(seats) + 1],
            shoe[2 * len(seats) + 1],
        )
        hands = []
        for seat, card_1, card_2 in zip(seats, first, second):
            total, soft = hand_value([card_1, card_2])
            hands.append(
                _table.SeatHand(
                    seat=seat,
                    cards=[card_1, card_2],
                    total=total,
                    soft=soft,
                    blackjack=is_blackjack([card_1, card_2]),
                )
            )
        dealer_blackjack = is_blackjack([dealer_up, dealer_hole])
        finished = {hand.seat: hand.blackjack for hand in hands}
        turn = rules.NO_TURN if dealer_blackjack else rules.next_turn(seats, finished)
        book.emit(
            _table.RoundDealt(
                round=book.state.round + 1,
                hands=hands,
                dealer_up=dealer_up,
                dealer_hole=dealer_hole,
                turn=turn,
            )
        )
        if turn == rules.NO_TURN:
            self._finish_round(book)

    def hit(self, cmd: _table.Hit, state: TableState, cctx: _az.CommandContext):
        return self._run(
            self._guard_round_in_progress,
            self._validate_on_turn,
            self._compute_hit,
            cmd,
            state,
        )

    def stand(self, cmd: _table.Stand, state: TableState, cctx: _az.CommandContext):
        return self._run(
            self._guard_round_in_progress,
            self._validate_on_turn,
            self._compute_stand,
            cmd,
            state,
        )

    def double_down(
        self, cmd: _table.DoubleDown, state: TableState, cctx: _az.CommandContext
    ):
        return self._run(
            self._guard_round_in_progress,
            self._validate_double,
            self._compute_double,
            cmd,
            state,
        )

    @staticmethod
    def _validate_on_turn(cmd, state: TableState) -> Effect:
        if cmd.seat != state.turn:
            raise precondition("NOT_YOUR_TURN", f"it is not seat {cmd.seat}'s turn")
        return Effect.APPLY

    @classmethod
    def _validate_double(cls, cmd: _table.DoubleDown, state: TableState) -> Effect:
        cls._validate_on_turn(cmd, state)
        seat = state.seated[cmd.seat]
        if len(seat.hand.cards) != 2:
            raise precondition(
                "DOUBLE_NOT_ALLOWED", "doubling is only allowed on the first two cards"
            )
        if seat.stack < seat.wager:
            raise precondition("INSUFFICIENT_STACK", "the stack is too small to double")
        return Effect.APPLY

    def _compute_hit(self, cmd: _table.Hit, book: _Book, effect, cctx) -> None:
        state = book.state
        card = state.shoe[0]
        total, soft = hand_value([*state.seated[cmd.seat].hand.cards, card])
        busted = total > 21
        if busted:
            next_turn = self._turn_after(state, cmd.seat)
        else:
            next_turn = cmd.seat
        book.emit(
            _table.CardDealt(
                seat=cmd.seat,
                card=card,
                total=total,
                soft=soft,
                busted=busted,
                next_turn=next_turn,
            )
        )
        if next_turn == rules.NO_TURN:
            self._finish_round(book)

    def _compute_stand(self, cmd: _table.Stand, book: _Book, effect, cctx) -> None:
        state = book.state
        next_turn = self._turn_after(state, cmd.seat)
        book.emit(
            _table.HandStood(
                seat=cmd.seat,
                total=state.seated[cmd.seat].hand.total,
                next_turn=next_turn,
            )
        )
        if next_turn == rules.NO_TURN:
            self._finish_round(book)

    def _compute_double(
        self, cmd: _table.DoubleDown, book: _Book, effect, cctx
    ) -> None:
        state = book.state
        seat = state.seated[cmd.seat]
        card = state.shoe[0]
        total, _ = hand_value([*seat.hand.cards, card])
        next_turn = self._turn_after(state, cmd.seat)
        book.emit(
            _table.HandDoubled(
                seat=cmd.seat,
                added=seat.wager,
                card=card,
                total=total,
                busted=total > 21,
                next_turn=next_turn,
                stack_after=seat.stack - seat.wager,
            )
        )
        if next_turn == rules.NO_TURN:
            self._finish_round(book)

    @staticmethod
    def _turn_after(state: TableState, seat: int) -> int:
        finished = finished_hands(state)
        finished[seat] = True
        return rules.next_turn(wagered_seats(state), finished, after=seat)

    @staticmethod
    def _finish_round(book: _Book) -> None:
        """The dealer plays (AHR-11) and every wager is settled (AHR-12)."""
        state = book.state
        seats = wagered_seats(state)
        dealer = list(state.dealer_cards)
        live = any(
            not rules.is_busted(state.seated[s].hand.cards)
            and not is_blackjack(state.seated[s].hand.cards)
            for s in seats
        )
        drawn = rules.dealer_draws(
            dealer, state.shoe, live and not is_blackjack(dealer)
        )
        final = dealer + drawn
        total, soft = hand_value(final)
        book.emit(
            _table.DealerPlayed(
                round=state.round,
                hole=dealer[1],
                drawn=drawn,
                total=total,
                soft=soft,
                busted=total > 21,
                blackjack=is_blackjack(dealer),
            )
        )
        outcomes = []
        for number in seats:
            seat = book.state.seated[number]
            result = rules.outcome(seat.hand.cards, final)
            paid = rules.returned(result, seat.wager)
            outcomes.append(
                _table.SeatOutcome(
                    seat=number,
                    player_root=seat.player_root,
                    wager=seat.wager,
                    outcome=result,
                    returned=paid,
                    net=paid - seat.wager,
                    stack_after=seat.stack + paid,
                )
            )
        house_delta = sum(o.wager for o in outcomes) - sum(o.returned for o in outcomes)
        book.emit(
            _table.RoundSettled(
                round=book.state.round,
                outcomes=outcomes,
                house_delta=house_delta,
                house_result_after=book.state.house_result + house_delta,
            )
        )

    # endregion handlers

    # --- appliers ---

    def apply_table_created(
        self, state: TableState, event: _table.TableCreated
    ) -> None:
        state.name = event.name
        state.min_bet = event.min_bet
        state.max_bet = event.max_bet
        state.min_buy_in = event.min_buy_in
        state.max_buy_in = event.max_buy_in
        state.seats = event.seats
        state.decks = event.decks
        state.phase = Phase.PHASE_IDLE
        state.turn = rules.NO_TURN

    def apply_shoe_shuffled(
        self, state: TableState, event: _table.ShoeShuffled
    ) -> None:
        state.shoe_number = event.shoe_number
        state.shoe_seed = event.seed
        state.decks = event.decks
        del state.shoe[:]
        state.shoe.extend(event.cards)

    def apply_seat_held(self, state: TableState, event: _table.SeatHeld) -> None:
        state.seat_holds[event.buy_in_id.hex()].CopyFrom(
            _table.TableSeatHold(
                player_root=event.player_root, seat=event.seat, amount=event.amount
            )
        )

    def apply_seat_released(
        self, state: TableState, event: _table.SeatReleased
    ) -> None:
        state.seat_holds.pop(event.buy_in_id.hex(), None)

    def apply_player_seated(
        self, state: TableState, event: _table.PlayerSeated
    ) -> None:
        state.seat_holds.pop(event.buy_in_id.hex(), None)
        state.seated[event.seat].CopyFrom(
            _table.TableSeat(player_root=event.player_root, stack=event.stack)
        )
        state.chips_in += event.stack
        state.confirmed_buy_ins.append(event.buy_in_id.hex())

    def apply_chips_added(self, state: TableState, event: _table.ChipsAdded) -> None:
        state.seated[event.seat].stack = event.stack_after
        state.chips_in += event.amount
        state.added_holds.append(event.hold_id.hex())

    def apply_player_cashed_out(
        self, state: TableState, event: _table.PlayerCashedOut
    ) -> None:
        del state.seated[event.seat]
        state.chips_out += event.amount

    def apply_bet_placed(self, state: TableState, event: _table.BetPlaced) -> None:
        seat = state.seated[event.seat]
        seat.wager = event.amount
        seat.stack = event.stack_after
        state.phase = Phase.PHASE_BETTING

    def apply_round_dealt(self, state: TableState, event: _table.RoundDealt) -> None:
        state.round = event.round
        for hand in event.hands:
            seat = state.seated[hand.seat]
            seat.hand.CopyFrom(hand)
            seat.finished = hand.blackjack
        del state.dealer_cards[:]
        state.dealer_cards.extend([event.dealer_up, event.dealer_hole])
        del state.shoe[: 2 * len(event.hands) + 2]
        state.turn = event.turn
        state.phase = Phase.PHASE_PLAYER_TURNS

    def apply_card_dealt(self, state: TableState, event: _table.CardDealt) -> None:
        hand = state.seated[event.seat].hand
        hand.cards.append(event.card)
        hand.total = event.total
        hand.soft = event.soft
        state.seated[event.seat].finished = event.busted
        del state.shoe[:1]
        state.turn = event.next_turn

    def apply_hand_stood(self, state: TableState, event: _table.HandStood) -> None:
        state.seated[event.seat].finished = True
        state.turn = event.next_turn

    def apply_hand_doubled(self, state: TableState, event: _table.HandDoubled) -> None:
        seat = state.seated[event.seat]
        seat.wager += event.added
        seat.stack = event.stack_after
        seat.hand.cards.append(event.card)
        seat.hand.total = event.total
        seat.hand.soft = hand_value(seat.hand.cards)[1]
        seat.finished = True
        del state.shoe[:1]
        state.turn = event.next_turn

    def apply_dealer_played(
        self, state: TableState, event: _table.DealerPlayed
    ) -> None:
        state.dealer_cards.extend(event.drawn)
        del state.shoe[: len(event.drawn)]

    def apply_round_settled(
        self, state: TableState, event: _table.RoundSettled
    ) -> None:
        for result in event.outcomes:
            seat = state.seated[result.seat]
            seat.stack = result.stack_after
            seat.wager = 0
            seat.ClearField("hand")
            seat.finished = False
        state.house_result = event.house_result_after
        del state.dealer_cards[:]
        state.turn = rules.NO_TURN
        state.phase = Phase.PHASE_IDLE
