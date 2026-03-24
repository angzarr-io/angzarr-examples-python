"""Fluent builders for test state and events.

Provides builder patterns for creating test fixtures with sensible defaults
and easy customization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google.protobuf.message import Message

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

from .proto_helpers import make_cover, make_event_page, pack_event, uuid_for


class PlayerStateBuilder:
    """Fluent builder for PlayerState."""

    def __init__(self):
        self._player_id = ""
        self._display_name = ""
        self._email = ""
        self._player_type = player.PlayerType.HUMAN
        self._ai_model_id = ""
        self._bankroll = 0
        self._reserved_funds = 0
        self._table_reservations: dict[str, int] = {}
        self._status = ""

    def registered(self, name: str = "TestPlayer", email: str = "test@example.com") -> PlayerStateBuilder:
        """Set player as registered with default values."""
        self._player_id = f"player_{email}"
        self._display_name = name
        self._email = email
        self._status = "active"
        return self

    def with_bankroll(self, amount: int) -> PlayerStateBuilder:
        """Set bankroll amount."""
        self._bankroll = amount
        return self

    def with_reserved(self, amount: int, table_root: bytes) -> PlayerStateBuilder:
        """Add a table reservation."""
        self._reserved_funds += amount
        self._table_reservations[table_root.hex()] = amount
        return self

    def as_ai(self, model_id: str = "gpt-4") -> PlayerStateBuilder:
        """Set player type to AI."""
        self._player_type = player.PlayerType.AI
        self._ai_model_id = model_id
        return self

    def build(self) -> Any:
        """Build the PlayerState.

        Note: Returns dict-like object to avoid import cycles.
        The actual PlayerState should be constructed by the test.
        """
        return {
            "player_id": self._player_id,
            "display_name": self._display_name,
            "email": self._email,
            "player_type": self._player_type,
            "ai_model_id": self._ai_model_id,
            "bankroll": self._bankroll,
            "reserved_funds": self._reserved_funds,
            "table_reservations": self._table_reservations.copy(),
            "status": self._status,
        }


class TableStateBuilder:
    """Fluent builder for TableState."""

    def __init__(self):
        self._table_root = uuid_for("test-table")
        self._name = "Test Table"
        self._max_players = 9
        self._min_buy_in = 100
        self._max_buy_in = 1000
        self._small_blind = 5
        self._big_blind = 10
        self._seats: dict[int, tuple[bytes, int]] = {}  # position -> (player_root, stack)
        self._status = "waiting"
        self._hand_count = 0

    def with_name(self, name: str) -> TableStateBuilder:
        """Set table name."""
        self._name = name
        return self

    def with_buy_in_range(self, min_buy: int, max_buy: int) -> TableStateBuilder:
        """Set buy-in range."""
        self._min_buy_in = min_buy
        self._max_buy_in = max_buy
        return self

    def with_blinds(self, small: int, big: int) -> TableStateBuilder:
        """Set blind levels."""
        self._small_blind = small
        self._big_blind = big
        return self

    def with_player(self, position: int, player_root: bytes, stack: int) -> TableStateBuilder:
        """Add a seated player."""
        self._seats[position] = (player_root, stack)
        return self

    def with_max_players(self, max_players: int) -> TableStateBuilder:
        """Set max players."""
        self._max_players = max_players
        return self

    def in_hand(self) -> TableStateBuilder:
        """Set table status to in_hand."""
        self._status = "in_hand"
        return self

    def build(self) -> dict:
        """Build the TableState as a dict."""
        return {
            "table_root": self._table_root,
            "name": self._name,
            "max_players": self._max_players,
            "min_buy_in": self._min_buy_in,
            "max_buy_in": self._max_buy_in,
            "small_blind": self._small_blind,
            "big_blind": self._big_blind,
            "seats": self._seats.copy(),
            "status": self._status,
            "hand_count": self._hand_count,
        }


class HandStateBuilder:
    """Fluent builder for HandState."""

    def __init__(self):
        self._hand_root = uuid_for("test-hand")
        self._game_variant = poker_types.GameVariant.TEXAS_HOLDEM
        self._players: list[dict] = []
        self._community_cards: list = []
        self._pot = 0
        self._phase = "preflop"
        self._current_bet = 0
        self._dealer_position = 0

    def with_variant(self, variant: int) -> HandStateBuilder:
        """Set game variant."""
        self._game_variant = variant
        return self

    def with_player(
        self,
        player_root: bytes,
        position: int,
        stack: int,
        hole_cards: list | None = None,
    ) -> HandStateBuilder:
        """Add a player to the hand."""
        self._players.append({
            "player_root": player_root,
            "position": position,
            "stack": stack,
            "hole_cards": hole_cards or [],
            "has_folded": False,
            "is_all_in": False,
            "current_bet": 0,
        })
        return self

    def with_pot(self, amount: int) -> HandStateBuilder:
        """Set pot size."""
        self._pot = amount
        return self

    def in_phase(self, phase: str) -> HandStateBuilder:
        """Set hand phase."""
        self._phase = phase
        return self

    def with_community(self, cards: list) -> HandStateBuilder:
        """Set community cards."""
        self._community_cards = cards
        return self

    def build(self) -> dict:
        """Build the HandState as a dict."""
        return {
            "hand_root": self._hand_root,
            "game_variant": self._game_variant,
            "players": self._players.copy(),
            "community_cards": self._community_cards.copy(),
            "pot": self._pot,
            "phase": self._phase,
            "current_bet": self._current_bet,
            "dealer_position": self._dealer_position,
        }


class EventBookBuilder:
    """Fluent builder for EventBook."""

    def __init__(self):
        self._domain = "test"
        self._root = uuid_for("test-root")
        self._events: list[Message] = []

    def with_domain(self, domain: str) -> EventBookBuilder:
        """Set domain."""
        self._domain = domain
        return self

    def with_root(self, root: bytes) -> EventBookBuilder:
        """Set root."""
        self._root = root
        return self

    def with_event(self, event: Message) -> EventBookBuilder:
        """Add an event."""
        self._events.append(event)
        return self

    def with_events(self, events: list[Message]) -> EventBookBuilder:
        """Add multiple events."""
        self._events.extend(events)
        return self

    def build(self) -> types.EventBook:
        """Build the EventBook."""
        pages = [
            make_event_page(event, sequence=i)
            for i, event in enumerate(self._events)
        ]
        return types.EventBook(
            cover=make_cover(self._domain, self._root),
            pages=pages,
            next_sequence=len(pages),
        )
