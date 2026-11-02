from angzarr_player._gen.io.angzarr.examples.v1 import cards_pb2 as _cards_pb2
from angzarr_client.proto.io.angzarr.v1 import options_pb2 as _options_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CreateTable(_message.Message):
    __slots__ = ("name", "min_bet", "max_bet", "min_buy_in", "max_buy_in", "seats", "decks", "shoe_seed")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MIN_BET_FIELD_NUMBER: _ClassVar[int]
    MAX_BET_FIELD_NUMBER: _ClassVar[int]
    MIN_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    MAX_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    SEATS_FIELD_NUMBER: _ClassVar[int]
    DECKS_FIELD_NUMBER: _ClassVar[int]
    SHOE_SEED_FIELD_NUMBER: _ClassVar[int]
    name: str
    min_bet: int
    max_bet: int
    min_buy_in: int
    max_buy_in: int
    seats: int
    decks: int
    shoe_seed: int
    def __init__(self, name: _Optional[str] = ..., min_bet: _Optional[int] = ..., max_bet: _Optional[int] = ..., min_buy_in: _Optional[int] = ..., max_buy_in: _Optional[int] = ..., seats: _Optional[int] = ..., decks: _Optional[int] = ..., shoe_seed: _Optional[int] = ...) -> None: ...

class RequestSeat(_message.Message):
    __slots__ = ("player_root", "seat", "amount", "request_id")
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    player_root: bytes
    seat: int
    amount: int
    request_id: bytes
    def __init__(self, player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., amount: _Optional[int] = ..., request_id: _Optional[bytes] = ...) -> None: ...

class LeaveTable(_message.Message):
    __slots__ = ("seat",)
    SEAT_FIELD_NUMBER: _ClassVar[int]
    seat: int
    def __init__(self, seat: _Optional[int] = ...) -> None: ...

class PlaceBet(_message.Message):
    __slots__ = ("seat", "amount")
    SEAT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    seat: int
    amount: int
    def __init__(self, seat: _Optional[int] = ..., amount: _Optional[int] = ...) -> None: ...

class DealRound(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Hit(_message.Message):
    __slots__ = ("seat",)
    SEAT_FIELD_NUMBER: _ClassVar[int]
    seat: int
    def __init__(self, seat: _Optional[int] = ...) -> None: ...

class Stand(_message.Message):
    __slots__ = ("seat",)
    SEAT_FIELD_NUMBER: _ClassVar[int]
    seat: int
    def __init__(self, seat: _Optional[int] = ...) -> None: ...

class DoubleDown(_message.Message):
    __slots__ = ("seat",)
    SEAT_FIELD_NUMBER: _ClassVar[int]
    seat: int
    def __init__(self, seat: _Optional[int] = ...) -> None: ...

class ConfirmSeat(_message.Message):
    __slots__ = ("buy_in_id",)
    BUY_IN_ID_FIELD_NUMBER: _ClassVar[int]
    buy_in_id: bytes
    def __init__(self, buy_in_id: _Optional[bytes] = ...) -> None: ...

class SeatNotConfirmable(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class ReleaseSeat(_message.Message):
    __slots__ = ("buy_in_id", "reason")
    BUY_IN_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    buy_in_id: bytes
    reason: str
    def __init__(self, buy_in_id: _Optional[bytes] = ..., reason: _Optional[str] = ...) -> None: ...

class TableRefused(_message.Message):
    __slots__ = ("reason", "name", "rule", "seat", "min_buy_in", "max_buy_in", "min_bet", "max_bet")
    class Reason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        REASON_UNSPECIFIED: _ClassVar[TableRefused.Reason]
        REASON_TABLE_ALREADY_EXISTS: _ClassVar[TableRefused.Reason]
        REASON_INVALID_TABLE_CONFIG: _ClassVar[TableRefused.Reason]
        REASON_TABLE_NOT_FOUND: _ClassVar[TableRefused.Reason]
        REASON_SEAT_TAKEN: _ClassVar[TableRefused.Reason]
        REASON_PLAYER_ALREADY_SEATED: _ClassVar[TableRefused.Reason]
        REASON_NOT_SEATED: _ClassVar[TableRefused.Reason]
        REASON_ROUND_IN_PROGRESS: _ClassVar[TableRefused.Reason]
        REASON_ALREADY_BET: _ClassVar[TableRefused.Reason]
        REASON_INSUFFICIENT_STACK: _ClassVar[TableRefused.Reason]
        REASON_NO_BETS: _ClassVar[TableRefused.Reason]
        REASON_NO_ROUND_IN_PROGRESS: _ClassVar[TableRefused.Reason]
        REASON_NOT_YOUR_TURN: _ClassVar[TableRefused.Reason]
        REASON_DOUBLE_NOT_ALLOWED: _ClassVar[TableRefused.Reason]
        REASON_SEAT_OUT_OF_RANGE: _ClassVar[TableRefused.Reason]
        REASON_BUY_IN_OUT_OF_RANGE: _ClassVar[TableRefused.Reason]
        REASON_BET_OUT_OF_RANGE: _ClassVar[TableRefused.Reason]
        REASON_BET_NOT_EVEN: _ClassVar[TableRefused.Reason]
        REASON_WAGER_IN_PLAY: _ClassVar[TableRefused.Reason]
    REASON_UNSPECIFIED: TableRefused.Reason
    REASON_TABLE_ALREADY_EXISTS: TableRefused.Reason
    REASON_INVALID_TABLE_CONFIG: TableRefused.Reason
    REASON_TABLE_NOT_FOUND: TableRefused.Reason
    REASON_SEAT_TAKEN: TableRefused.Reason
    REASON_PLAYER_ALREADY_SEATED: TableRefused.Reason
    REASON_NOT_SEATED: TableRefused.Reason
    REASON_ROUND_IN_PROGRESS: TableRefused.Reason
    REASON_ALREADY_BET: TableRefused.Reason
    REASON_INSUFFICIENT_STACK: TableRefused.Reason
    REASON_NO_BETS: TableRefused.Reason
    REASON_NO_ROUND_IN_PROGRESS: TableRefused.Reason
    REASON_NOT_YOUR_TURN: TableRefused.Reason
    REASON_DOUBLE_NOT_ALLOWED: TableRefused.Reason
    REASON_SEAT_OUT_OF_RANGE: TableRefused.Reason
    REASON_BUY_IN_OUT_OF_RANGE: TableRefused.Reason
    REASON_BET_OUT_OF_RANGE: TableRefused.Reason
    REASON_BET_NOT_EVEN: TableRefused.Reason
    REASON_WAGER_IN_PLAY: TableRefused.Reason
    REASON_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    RULE_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    MIN_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    MAX_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    MIN_BET_FIELD_NUMBER: _ClassVar[int]
    MAX_BET_FIELD_NUMBER: _ClassVar[int]
    reason: TableRefused.Reason
    name: str
    rule: str
    seat: int
    min_buy_in: int
    max_buy_in: int
    min_bet: int
    max_bet: int
    def __init__(self, reason: _Optional[_Union[TableRefused.Reason, str]] = ..., name: _Optional[str] = ..., rule: _Optional[str] = ..., seat: _Optional[int] = ..., min_buy_in: _Optional[int] = ..., max_buy_in: _Optional[int] = ..., min_bet: _Optional[int] = ..., max_bet: _Optional[int] = ...) -> None: ...

class TableCreated(_message.Message):
    __slots__ = ("name", "min_bet", "max_bet", "min_buy_in", "max_buy_in", "seats", "decks")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MIN_BET_FIELD_NUMBER: _ClassVar[int]
    MAX_BET_FIELD_NUMBER: _ClassVar[int]
    MIN_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    MAX_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    SEATS_FIELD_NUMBER: _ClassVar[int]
    DECKS_FIELD_NUMBER: _ClassVar[int]
    name: str
    min_bet: int
    max_bet: int
    min_buy_in: int
    max_buy_in: int
    seats: int
    decks: int
    def __init__(self, name: _Optional[str] = ..., min_bet: _Optional[int] = ..., max_bet: _Optional[int] = ..., min_buy_in: _Optional[int] = ..., max_buy_in: _Optional[int] = ..., seats: _Optional[int] = ..., decks: _Optional[int] = ...) -> None: ...

class ShoeShuffled(_message.Message):
    __slots__ = ("shoe_number", "seed", "decks", "cards")
    SHOE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    DECKS_FIELD_NUMBER: _ClassVar[int]
    CARDS_FIELD_NUMBER: _ClassVar[int]
    shoe_number: int
    seed: int
    decks: int
    cards: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    def __init__(self, shoe_number: _Optional[int] = ..., seed: _Optional[int] = ..., decks: _Optional[int] = ..., cards: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ...) -> None: ...

class SeatHeld(_message.Message):
    __slots__ = ("buy_in_id", "player_root", "seat", "amount")
    BUY_IN_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    buy_in_id: bytes
    player_root: bytes
    seat: int
    amount: int
    def __init__(self, buy_in_id: _Optional[bytes] = ..., player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., amount: _Optional[int] = ...) -> None: ...

class SeatReleased(_message.Message):
    __slots__ = ("buy_in_id", "player_root", "seat", "reason")
    BUY_IN_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    buy_in_id: bytes
    player_root: bytes
    seat: int
    reason: str
    def __init__(self, buy_in_id: _Optional[bytes] = ..., player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., reason: _Optional[str] = ...) -> None: ...

class PlayerSeated(_message.Message):
    __slots__ = ("buy_in_id", "player_root", "seat", "stack")
    BUY_IN_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    STACK_FIELD_NUMBER: _ClassVar[int]
    buy_in_id: bytes
    player_root: bytes
    seat: int
    stack: int
    def __init__(self, buy_in_id: _Optional[bytes] = ..., player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., stack: _Optional[int] = ...) -> None: ...

class PlayerCashedOut(_message.Message):
    __slots__ = ("cashout_id", "player_root", "seat", "amount")
    CASHOUT_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    cashout_id: bytes
    player_root: bytes
    seat: int
    amount: int
    def __init__(self, cashout_id: _Optional[bytes] = ..., player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., amount: _Optional[int] = ...) -> None: ...

class BetPlaced(_message.Message):
    __slots__ = ("round", "seat", "player_root", "amount", "stack_after")
    ROUND_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    STACK_AFTER_FIELD_NUMBER: _ClassVar[int]
    round: int
    seat: int
    player_root: bytes
    amount: int
    stack_after: int
    def __init__(self, round: _Optional[int] = ..., seat: _Optional[int] = ..., player_root: _Optional[bytes] = ..., amount: _Optional[int] = ..., stack_after: _Optional[int] = ...) -> None: ...

class SeatHand(_message.Message):
    __slots__ = ("seat", "cards", "total", "soft", "blackjack")
    SEAT_FIELD_NUMBER: _ClassVar[int]
    CARDS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    SOFT_FIELD_NUMBER: _ClassVar[int]
    BLACKJACK_FIELD_NUMBER: _ClassVar[int]
    seat: int
    cards: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    total: int
    soft: bool
    blackjack: bool
    def __init__(self, seat: _Optional[int] = ..., cards: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., total: _Optional[int] = ..., soft: _Optional[bool] = ..., blackjack: _Optional[bool] = ...) -> None: ...

class RoundDealt(_message.Message):
    __slots__ = ("round", "hands", "dealer_up", "dealer_hole", "turn")
    ROUND_FIELD_NUMBER: _ClassVar[int]
    HANDS_FIELD_NUMBER: _ClassVar[int]
    DEALER_UP_FIELD_NUMBER: _ClassVar[int]
    DEALER_HOLE_FIELD_NUMBER: _ClassVar[int]
    TURN_FIELD_NUMBER: _ClassVar[int]
    round: int
    hands: _containers.RepeatedCompositeFieldContainer[SeatHand]
    dealer_up: _cards_pb2.Card
    dealer_hole: _cards_pb2.Card
    turn: int
    def __init__(self, round: _Optional[int] = ..., hands: _Optional[_Iterable[_Union[SeatHand, _Mapping]]] = ..., dealer_up: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., dealer_hole: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., turn: _Optional[int] = ...) -> None: ...

class TurnStarted(_message.Message):
    __slots__ = ("round", "seat", "player_root", "hand", "dealer_up", "can_double", "stack", "wager")
    ROUND_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    HAND_FIELD_NUMBER: _ClassVar[int]
    DEALER_UP_FIELD_NUMBER: _ClassVar[int]
    CAN_DOUBLE_FIELD_NUMBER: _ClassVar[int]
    STACK_FIELD_NUMBER: _ClassVar[int]
    WAGER_FIELD_NUMBER: _ClassVar[int]
    round: int
    seat: int
    player_root: bytes
    hand: SeatHand
    dealer_up: _cards_pb2.Card
    can_double: bool
    stack: int
    wager: int
    def __init__(self, round: _Optional[int] = ..., seat: _Optional[int] = ..., player_root: _Optional[bytes] = ..., hand: _Optional[_Union[SeatHand, _Mapping]] = ..., dealer_up: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., can_double: _Optional[bool] = ..., stack: _Optional[int] = ..., wager: _Optional[int] = ...) -> None: ...

class CardDealt(_message.Message):
    __slots__ = ("seat", "card", "total", "soft", "busted", "next_turn")
    SEAT_FIELD_NUMBER: _ClassVar[int]
    CARD_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    SOFT_FIELD_NUMBER: _ClassVar[int]
    BUSTED_FIELD_NUMBER: _ClassVar[int]
    NEXT_TURN_FIELD_NUMBER: _ClassVar[int]
    seat: int
    card: _cards_pb2.Card
    total: int
    soft: bool
    busted: bool
    next_turn: int
    def __init__(self, seat: _Optional[int] = ..., card: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., total: _Optional[int] = ..., soft: _Optional[bool] = ..., busted: _Optional[bool] = ..., next_turn: _Optional[int] = ...) -> None: ...

class HandStood(_message.Message):
    __slots__ = ("seat", "total", "next_turn")
    SEAT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    NEXT_TURN_FIELD_NUMBER: _ClassVar[int]
    seat: int
    total: int
    next_turn: int
    def __init__(self, seat: _Optional[int] = ..., total: _Optional[int] = ..., next_turn: _Optional[int] = ...) -> None: ...

class HandDoubled(_message.Message):
    __slots__ = ("seat", "added", "card", "total", "busted", "next_turn", "stack_after")
    SEAT_FIELD_NUMBER: _ClassVar[int]
    ADDED_FIELD_NUMBER: _ClassVar[int]
    CARD_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    BUSTED_FIELD_NUMBER: _ClassVar[int]
    NEXT_TURN_FIELD_NUMBER: _ClassVar[int]
    STACK_AFTER_FIELD_NUMBER: _ClassVar[int]
    seat: int
    added: int
    card: _cards_pb2.Card
    total: int
    busted: bool
    next_turn: int
    stack_after: int
    def __init__(self, seat: _Optional[int] = ..., added: _Optional[int] = ..., card: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., total: _Optional[int] = ..., busted: _Optional[bool] = ..., next_turn: _Optional[int] = ..., stack_after: _Optional[int] = ...) -> None: ...

class DealerPlayed(_message.Message):
    __slots__ = ("round", "hole", "drawn", "total", "soft", "busted", "blackjack")
    ROUND_FIELD_NUMBER: _ClassVar[int]
    HOLE_FIELD_NUMBER: _ClassVar[int]
    DRAWN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    SOFT_FIELD_NUMBER: _ClassVar[int]
    BUSTED_FIELD_NUMBER: _ClassVar[int]
    BLACKJACK_FIELD_NUMBER: _ClassVar[int]
    round: int
    hole: _cards_pb2.Card
    drawn: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    total: int
    soft: bool
    busted: bool
    blackjack: bool
    def __init__(self, round: _Optional[int] = ..., hole: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., drawn: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., total: _Optional[int] = ..., soft: _Optional[bool] = ..., busted: _Optional[bool] = ..., blackjack: _Optional[bool] = ...) -> None: ...

class SeatOutcome(_message.Message):
    __slots__ = ("seat", "player_root", "wager", "outcome", "returned", "net", "stack_after")
    class Outcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OUTCOME_UNSPECIFIED: _ClassVar[SeatOutcome.Outcome]
        OUTCOME_LOSE: _ClassVar[SeatOutcome.Outcome]
        OUTCOME_PUSH: _ClassVar[SeatOutcome.Outcome]
        OUTCOME_WIN: _ClassVar[SeatOutcome.Outcome]
        OUTCOME_BLACKJACK: _ClassVar[SeatOutcome.Outcome]
    OUTCOME_UNSPECIFIED: SeatOutcome.Outcome
    OUTCOME_LOSE: SeatOutcome.Outcome
    OUTCOME_PUSH: SeatOutcome.Outcome
    OUTCOME_WIN: SeatOutcome.Outcome
    OUTCOME_BLACKJACK: SeatOutcome.Outcome
    SEAT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    WAGER_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    RETURNED_FIELD_NUMBER: _ClassVar[int]
    NET_FIELD_NUMBER: _ClassVar[int]
    STACK_AFTER_FIELD_NUMBER: _ClassVar[int]
    seat: int
    player_root: bytes
    wager: int
    outcome: SeatOutcome.Outcome
    returned: int
    net: int
    stack_after: int
    def __init__(self, seat: _Optional[int] = ..., player_root: _Optional[bytes] = ..., wager: _Optional[int] = ..., outcome: _Optional[_Union[SeatOutcome.Outcome, str]] = ..., returned: _Optional[int] = ..., net: _Optional[int] = ..., stack_after: _Optional[int] = ...) -> None: ...

class RoundSettled(_message.Message):
    __slots__ = ("round", "outcomes", "house_delta", "house_result_after")
    ROUND_FIELD_NUMBER: _ClassVar[int]
    OUTCOMES_FIELD_NUMBER: _ClassVar[int]
    HOUSE_DELTA_FIELD_NUMBER: _ClassVar[int]
    HOUSE_RESULT_AFTER_FIELD_NUMBER: _ClassVar[int]
    round: int
    outcomes: _containers.RepeatedCompositeFieldContainer[SeatOutcome]
    house_delta: int
    house_result_after: int
    def __init__(self, round: _Optional[int] = ..., outcomes: _Optional[_Iterable[_Union[SeatOutcome, _Mapping]]] = ..., house_delta: _Optional[int] = ..., house_result_after: _Optional[int] = ...) -> None: ...

class TableSeat(_message.Message):
    __slots__ = ("player_root", "stack", "wager", "hand", "finished")
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    STACK_FIELD_NUMBER: _ClassVar[int]
    WAGER_FIELD_NUMBER: _ClassVar[int]
    HAND_FIELD_NUMBER: _ClassVar[int]
    FINISHED_FIELD_NUMBER: _ClassVar[int]
    player_root: bytes
    stack: int
    wager: int
    hand: SeatHand
    finished: bool
    def __init__(self, player_root: _Optional[bytes] = ..., stack: _Optional[int] = ..., wager: _Optional[int] = ..., hand: _Optional[_Union[SeatHand, _Mapping]] = ..., finished: _Optional[bool] = ...) -> None: ...

class TableSeatHold(_message.Message):
    __slots__ = ("player_root", "seat", "amount")
    PLAYER_ROOT_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    player_root: bytes
    seat: int
    amount: int
    def __init__(self, player_root: _Optional[bytes] = ..., seat: _Optional[int] = ..., amount: _Optional[int] = ...) -> None: ...

class TableState(_message.Message):
    __slots__ = ("name", "min_bet", "max_bet", "min_buy_in", "max_buy_in", "seats", "decks", "phase", "shoe_number", "shoe_seed", "shoe", "seated", "seat_holds", "round", "dealer_cards", "turn", "house_result", "chips_in", "chips_out", "confirmed_buy_ins")
    class Phase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PHASE_UNSPECIFIED: _ClassVar[TableState.Phase]
        PHASE_IDLE: _ClassVar[TableState.Phase]
        PHASE_BETTING: _ClassVar[TableState.Phase]
        PHASE_PLAYER_TURNS: _ClassVar[TableState.Phase]
    PHASE_UNSPECIFIED: TableState.Phase
    PHASE_IDLE: TableState.Phase
    PHASE_BETTING: TableState.Phase
    PHASE_PLAYER_TURNS: TableState.Phase
    class SeatedEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: int
        value: TableSeat
        def __init__(self, key: _Optional[int] = ..., value: _Optional[_Union[TableSeat, _Mapping]] = ...) -> None: ...
    class SeatHoldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: TableSeatHold
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[TableSeatHold, _Mapping]] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    MIN_BET_FIELD_NUMBER: _ClassVar[int]
    MAX_BET_FIELD_NUMBER: _ClassVar[int]
    MIN_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    MAX_BUY_IN_FIELD_NUMBER: _ClassVar[int]
    SEATS_FIELD_NUMBER: _ClassVar[int]
    DECKS_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    SHOE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SHOE_SEED_FIELD_NUMBER: _ClassVar[int]
    SHOE_FIELD_NUMBER: _ClassVar[int]
    SEATED_FIELD_NUMBER: _ClassVar[int]
    SEAT_HOLDS_FIELD_NUMBER: _ClassVar[int]
    ROUND_FIELD_NUMBER: _ClassVar[int]
    DEALER_CARDS_FIELD_NUMBER: _ClassVar[int]
    TURN_FIELD_NUMBER: _ClassVar[int]
    HOUSE_RESULT_FIELD_NUMBER: _ClassVar[int]
    CHIPS_IN_FIELD_NUMBER: _ClassVar[int]
    CHIPS_OUT_FIELD_NUMBER: _ClassVar[int]
    CONFIRMED_BUY_INS_FIELD_NUMBER: _ClassVar[int]
    name: str
    min_bet: int
    max_bet: int
    min_buy_in: int
    max_buy_in: int
    seats: int
    decks: int
    phase: TableState.Phase
    shoe_number: int
    shoe_seed: int
    shoe: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    seated: _containers.MessageMap[int, TableSeat]
    seat_holds: _containers.MessageMap[str, TableSeatHold]
    round: int
    dealer_cards: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    turn: int
    house_result: int
    chips_in: int
    chips_out: int
    confirmed_buy_ins: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., min_bet: _Optional[int] = ..., max_bet: _Optional[int] = ..., min_buy_in: _Optional[int] = ..., max_buy_in: _Optional[int] = ..., seats: _Optional[int] = ..., decks: _Optional[int] = ..., phase: _Optional[_Union[TableState.Phase, str]] = ..., shoe_number: _Optional[int] = ..., shoe_seed: _Optional[int] = ..., shoe: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., seated: _Optional[_Mapping[int, TableSeat]] = ..., seat_holds: _Optional[_Mapping[str, TableSeatHold]] = ..., round: _Optional[int] = ..., dealer_cards: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., turn: _Optional[int] = ..., house_result: _Optional[int] = ..., chips_in: _Optional[int] = ..., chips_out: _Optional[int] = ..., confirmed_buy_ins: _Optional[_Iterable[str]] = ...) -> None: ...
