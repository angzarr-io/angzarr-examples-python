from angzarr_player._gen.io.angzarr.examples.v1 import cards_pb2 as _cards_pb2
from angzarr_client.proto.io.angzarr.v1 import options_pb2 as _options_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class MoveAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MOVE_ACTION_UNSPECIFIED: _ClassVar[MoveAction]
    MOVE_ACTION_HIT: _ClassVar[MoveAction]
    MOVE_ACTION_STAND: _ClassVar[MoveAction]
    MOVE_ACTION_DOUBLE_DOWN: _ClassVar[MoveAction]
MOVE_ACTION_UNSPECIFIED: MoveAction
MOVE_ACTION_HIT: MoveAction
MOVE_ACTION_STAND: MoveAction
MOVE_ACTION_DOUBLE_DOWN: MoveAction

class DecideMove(_message.Message):
    __slots__ = ("table_root", "round", "seat", "cards", "total", "soft", "dealer_up", "can_double", "stack", "wager")
    TABLE_ROOT_FIELD_NUMBER: _ClassVar[int]
    ROUND_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    CARDS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    SOFT_FIELD_NUMBER: _ClassVar[int]
    DEALER_UP_FIELD_NUMBER: _ClassVar[int]
    CAN_DOUBLE_FIELD_NUMBER: _ClassVar[int]
    STACK_FIELD_NUMBER: _ClassVar[int]
    WAGER_FIELD_NUMBER: _ClassVar[int]
    table_root: bytes
    round: int
    seat: int
    cards: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    total: int
    soft: bool
    dealer_up: _cards_pb2.Card
    can_double: bool
    stack: int
    wager: int
    def __init__(self, table_root: _Optional[bytes] = ..., round: _Optional[int] = ..., seat: _Optional[int] = ..., cards: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., total: _Optional[int] = ..., soft: _Optional[bool] = ..., dealer_up: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ..., can_double: _Optional[bool] = ..., stack: _Optional[int] = ..., wager: _Optional[int] = ...) -> None: ...

class MoveDecided(_message.Message):
    __slots__ = ("table_root", "round", "seat", "action", "cards", "total", "soft", "dealer_up")
    TABLE_ROOT_FIELD_NUMBER: _ClassVar[int]
    ROUND_FIELD_NUMBER: _ClassVar[int]
    SEAT_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    CARDS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    SOFT_FIELD_NUMBER: _ClassVar[int]
    DEALER_UP_FIELD_NUMBER: _ClassVar[int]
    table_root: bytes
    round: int
    seat: int
    action: MoveAction
    cards: _containers.RepeatedCompositeFieldContainer[_cards_pb2.Card]
    total: int
    soft: bool
    dealer_up: _cards_pb2.Card
    def __init__(self, table_root: _Optional[bytes] = ..., round: _Optional[int] = ..., seat: _Optional[int] = ..., action: _Optional[_Union[MoveAction, str]] = ..., cards: _Optional[_Iterable[_Union[_cards_pb2.Card, _Mapping]]] = ..., total: _Optional[int] = ..., soft: _Optional[bool] = ..., dealer_up: _Optional[_Union[_cards_pb2.Card, _Mapping]] = ...) -> None: ...

class PlayerState(_message.Message):
    __slots__ = ("decisions", "hands_seen")
    DECISIONS_FIELD_NUMBER: _ClassVar[int]
    HANDS_SEEN_FIELD_NUMBER: _ClassVar[int]
    decisions: int
    hands_seen: int
    def __init__(self, decisions: _Optional[int] = ..., hands_seen: _Optional[int] = ...) -> None: ...
