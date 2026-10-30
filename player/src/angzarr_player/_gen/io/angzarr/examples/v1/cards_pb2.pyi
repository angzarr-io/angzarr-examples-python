from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Suit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SUIT_UNSPECIFIED: _ClassVar[Suit]
    CLUBS: _ClassVar[Suit]
    DIAMONDS: _ClassVar[Suit]
    HEARTS: _ClassVar[Suit]
    SPADES: _ClassVar[Suit]
SUIT_UNSPECIFIED: Suit
CLUBS: Suit
DIAMONDS: Suit
HEARTS: Suit
SPADES: Suit

class Card(_message.Message):
    __slots__ = ("rank", "suit")
    RANK_FIELD_NUMBER: _ClassVar[int]
    SUIT_FIELD_NUMBER: _ClassVar[int]
    rank: int
    suit: Suit
    def __init__(self, rank: _Optional[int] = ..., suit: _Optional[_Union[Suit, str]] = ...) -> None: ...
