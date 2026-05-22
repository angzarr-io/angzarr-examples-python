"""Projector: Output (OO Pattern).

Subscribes to player, table, and hand domain events; emits a formatted
human-readable log line per event.

Dual-mode surface:

* As an angzarr projector — ``@projector(name="prj-output", domains=[...])``
  plus ``@handles(EventType)`` methods — dispatched by the Router when the
  projector is deployed as a service.
* As a plain class with ``handle_event`` / ``handle_event_book`` / a
  configurable ``output_fn`` and ``show_timestamps`` — used directly by
  behave tests (features/example/unit/projector.feature).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

from renderer import format_card

from angzarr_client import (
    ProjectorGrpc,
    Router,
    handles,
    projector,
    run_server,
)
from angzarr_client.helpers import type_name_from_url
from angzarr_client.proto.angzarr.v1 import projector_pb2_grpc
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import hand_pb2 as hand
from angzarr_client.proto.examples.v1 import player_pb2 as player
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import table_pb2 as table

_ACTION_NAME = {
    poker_types.FOLD: "folds",
    poker_types.CHECK: "checks",
    poker_types.CALL: "calls",
    poker_types.BET: "bets",
    poker_types.RAISE: "raises to",
    poker_types.ALL_IN: "all-in",
}

_PHASE_NAME = {
    poker_types.FLOP: "Flop",
    poker_types.TURN: "Turn",
    poker_types.RIVER: "River",
    poker_types.DRAW: "Draw",
    poker_types.SHOWDOWN: "Showdown",
}

_GAME_VARIANT_NAME = {
    poker_types.TEXAS_HOLDEM: "TEXAS_HOLDEM",
    poker_types.OMAHA: "OMAHA",
    poker_types.FIVE_CARD_DRAW: "FIVE_CARD_DRAW",
    poker_types.SEVEN_CARD_STUD: "SEVEN_CARD_STUD",
}

_HAND_RANK_NAME = {
    poker_types.HIGH_CARD: "High Card",
    poker_types.PAIR: "Pair",
    poker_types.TWO_PAIR: "Two Pair",
    poker_types.THREE_OF_A_KIND: "Three of a Kind",
    poker_types.STRAIGHT: "Straight",
    poker_types.FLUSH: "Flush",
    poker_types.FULL_HOUSE: "Full House",
    poker_types.FOUR_OF_A_KIND: "Four of a Kind",
    poker_types.STRAIGHT_FLUSH: "Straight Flush",
    poker_types.ROYAL_FLUSH: "Royal Flush",
}


def _format_currency(amount: int) -> str:
    """Format integer chips as ``$1,234`` with thousands separators."""
    return f"${amount:,}"


def _format_cards(cards) -> str:
    return " ".join(format_card(c) for c in cards)


def _default_log_emitter() -> Callable[[str], None]:
    """Build a sink that appends timestamped lines to ``HAND_LOG_FILE``."""
    path = os.environ.get("HAND_LOG_FILE", "hand_log_oo.txt")
    handle = open(path, "a")  # noqa: SIM115 — kept open for the process lifetime

    def emit(line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        handle.write(f"[{ts}] {line}\n")
        handle.flush()

    return emit


# region projector
@projector(name="prj-output", domains=["player", "table", "hand"])
class OutputProjector:
    """Output projector using OO-style decorators with multi-domain support."""

    def __init__(
        self,
        output_fn: Callable[[str], None] | None = None,
        show_timestamps: bool = False,
    ) -> None:
        self._output_fn = output_fn if output_fn is not None else _default_log_emitter()
        self._show_timestamps = show_timestamps
        self._player_names: dict[bytes, str] = {}
        self._current_event_time: str | None = None
        self._board: list = []

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------

    def set_player_name(self, player_root: bytes, name: str) -> None:
        self._player_names[player_root] = name

    def _resolve_name(self, player_root: bytes) -> str:
        if player_root in self._player_names:
            return self._player_names[player_root]
        raw = player_root.decode("utf-8", errors="replace")
        if raw.startswith("player-"):
            raw = raw[len("player-") :]
        return f"Player_{raw}"

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _emit(self, line: str) -> None:
        if self._show_timestamps and self._current_event_time:
            line = f"[{self._current_event_time}] {line}"
        self._output_fn(line)

    # ------------------------------------------------------------------
    # Plain dispatch (used directly by tests)
    # ------------------------------------------------------------------

    def handle_event(self, event_page: types.EventPage) -> None:
        """Dispatch a single packed EventPage to the matching ``@handles`` method."""
        self._current_event_time = _format_time(event_page.created_at)
        event_any = event_page.event
        type_name = type_name_from_url(event_any.type_url)
        dispatched = False
        for event_cls in _REGISTERED_EVENT_TYPES:
            if event_cls.DESCRIPTOR.full_name == type_name:
                evt = event_cls()
                event_any.Unpack(evt)
                method = _DISPATCH_TABLE[event_cls]
                method(self, evt)
                dispatched = True
                break
        if not dispatched:
            self._emit(f"[Unknown event type: {type_name}]")
        self._current_event_time = None

    def handle_event_book(self, event_book: types.EventBook) -> None:
        for page in event_book.pages:
            self.handle_event(page)

    # ------------------------------------------------------------------
    # Player domain
    # ------------------------------------------------------------------

    @handles(player.PlayerRegistered)
    def project_player_registered(self, event: player.PlayerRegistered) -> None:
        self._emit(f"{event.display_name} registered ({event.email})")

    @handles(player.FundsDeposited)
    def project_funds_deposited(self, event: player.FundsDeposited) -> None:
        amount = event.amount.amount if event.HasField("amount") else 0
        new_balance = event.new_balance.amount if event.HasField("new_balance") else 0
        self._emit(
            f"Deposited {_format_currency(amount)}, "
            f"balance: {_format_currency(new_balance)}"
        )

    @handles(player.FundsWithdrawn)
    def project_funds_withdrawn(self, event: player.FundsWithdrawn) -> None:
        amount = event.amount.amount if event.HasField("amount") else 0
        new_balance = event.new_balance.amount if event.HasField("new_balance") else 0
        self._emit(
            f"Withdrew {_format_currency(amount)}, "
            f"balance: {_format_currency(new_balance)}"
        )

    @handles(player.FundsReserved)
    def project_funds_reserved(self, event: player.FundsReserved) -> None:
        amount = event.amount.amount if event.HasField("amount") else 0
        self._emit(f"Reserved {_format_currency(amount)}")

    # ------------------------------------------------------------------
    # Table domain
    # ------------------------------------------------------------------

    @handles(table.TableCreated)
    def project_table_created(self, event: table.TableCreated) -> None:
        variant = _GAME_VARIANT_NAME.get(event.game_variant, str(event.game_variant))
        self._emit(
            f'Table "{event.table_name}" created: {variant} '
            f"{_format_currency(event.small_blind)}/"
            f"{_format_currency(event.big_blind)} "
            f"(buy-in: {_format_currency(event.min_buy_in)} - "
            f"{_format_currency(event.max_buy_in)})"
        )

    @handles(table.PlayerJoined)
    def project_player_joined(self, event: table.PlayerJoined) -> None:
        name = self._resolve_name(event.player_root)
        self._emit(
            f"{name} joined at seat {event.seat_position} "
            f"with {_format_currency(event.stack)}"
        )

    @handles(table.PlayerLeft)
    def project_player_left(self, event: table.PlayerLeft) -> None:
        name = self._resolve_name(event.player_root)
        self._emit(f"{name} left with {_format_currency(event.chips_cashed_out)}")

    @handles(table.HandStarted)
    def project_hand_started(self, event: table.HandStarted) -> None:
        names = [self._resolve_name(p.player_root) for p in event.active_players]
        player_list = ", ".join(names) if names else "no players"
        self._emit(
            f"HAND #{event.hand_number} started — "
            f"Dealer: Seat {event.dealer_position} — Players: {player_list}"
        )
        self._board = []

    @handles(table.HandEnded)
    def project_hand_ended(self, event: table.HandEnded) -> None:
        if not event.results:
            self._emit("Hand ended")
            return
        parts = []
        for result in event.results:
            name = self._resolve_name(result.winner_root)
            parts.append(f"{name} wins {_format_currency(result.amount)}")
        self._emit("Hand ended — " + ", ".join(parts))

    # ------------------------------------------------------------------
    # Hand domain
    # ------------------------------------------------------------------

    @handles(hand.CardsDealt)
    def project_cards_dealt(self, event: hand.CardsDealt) -> None:
        if not event.player_cards:
            self._emit("Cards dealt")
            return
        lines = []
        for hole in event.player_cards:
            name = self._resolve_name(hole.player_root)
            lines.append(f"{name}: [{_format_cards(hole.cards)}]")
        self._emit(" | ".join(lines))

    @handles(hand.BlindPosted)
    def project_blind_posted(self, event: hand.BlindPosted) -> None:
        name = self._resolve_name(event.player_root)
        blind_type = event.blind_type.upper() if event.blind_type else "BLIND"
        self._emit(f"{name} posts {blind_type} {_format_currency(event.amount)}")

    @handles(hand.ActionTaken)
    def project_action_taken(self, event: hand.ActionTaken) -> None:
        name = self._resolve_name(event.player_root)
        verb = _ACTION_NAME.get(event.action, "acts")
        if event.action in (poker_types.CALL, poker_types.BET, poker_types.RAISE):
            msg = f"{name} {verb} {_format_currency(event.amount)}"
        elif event.action == poker_types.ALL_IN:
            msg = f"{name} {verb} {_format_currency(event.amount)}"
        else:
            msg = f"{name} {verb}"
        if event.pot_total > 0:
            msg += f" (pot: {_format_currency(event.pot_total)})"
        self._emit(msg)

    @handles(hand.CommunityCardsDealt)
    def project_community_cards_dealt(self, event: hand.CommunityCardsDealt) -> None:
        phase_name = _PHASE_NAME.get(event.phase, "Street")
        self._board.extend(event.cards)
        cards_str = _format_cards(event.cards)
        board_str = _format_cards(self._board) if self._board else cards_str
        self._emit(f"{phase_name}: [{cards_str}] — Board: [{board_str}]")

    @handles(hand.ShowdownStarted)
    def project_showdown_started(self, event: hand.ShowdownStarted) -> None:
        self._emit("SHOWDOWN")

    @handles(hand.CardsRevealed)
    def project_cards_revealed(self, event: hand.CardsRevealed) -> None:
        name = self._resolve_name(event.player_root)
        cards_str = _format_cards(event.cards)
        ranking_name = _HAND_RANK_NAME.get(
            event.ranking.rank_type if event.HasField("ranking") else 0,
            "",
        )
        if ranking_name:
            self._emit(f"{name} shows [{cards_str}] — {ranking_name}")
        else:
            self._emit(f"{name} shows [{cards_str}]")

    @handles(hand.CardsMucked)
    def project_cards_mucked(self, event: hand.CardsMucked) -> None:
        name = self._resolve_name(event.player_root)
        self._emit(f"{name} mucks")

    @handles(hand.PotAwarded)
    def project_pot_awarded(self, event: hand.PotAwarded) -> None:
        parts = [
            f"{self._resolve_name(w.player_root)} wins {_format_currency(w.amount)}"
            for w in event.winners
        ]
        self._emit("Pot awarded — " + ", ".join(parts) if parts else "Pot awarded")

    @handles(hand.HandComplete)
    def project_hand_complete(self, event: hand.HandComplete) -> None:
        if not event.final_stacks:
            self._emit(f"HAND #{event.hand_number} complete")
            return
        parts = []
        for snap in event.final_stacks:
            name = self._resolve_name(snap.player_root)
            entry = f"{name}: {_format_currency(snap.stack)}"
            if snap.has_folded:
                entry += " (folded)"
            parts.append(entry)
        self._emit("Final stacks — " + ", ".join(parts))

    @handles(hand.PlayerTimedOut)
    def project_player_timed_out(self, event: hand.PlayerTimedOut) -> None:
        name = self._resolve_name(event.player_root)
        verb = _ACTION_NAME.get(event.default_action, "acts").split(" ")[0]
        self._emit(f"{name} timed out — auto {verb}")


# endregion


def _format_time(ts) -> str | None:
    """Render a protobuf Timestamp as ``HH:MM:SS`` in UTC."""
    if ts is None or (ts.seconds == 0 and ts.nanos == 0):
        return None
    dt = datetime.fromtimestamp(ts.seconds + ts.nanos / 1e9, tz=timezone.utc)
    return dt.strftime("%H:%M:%S")


# Build the dispatch table once class is defined — walks @handles-decorated
# methods on OutputProjector.
_DISPATCH_TABLE: dict[type, Callable] = {}
_REGISTERED_EVENT_TYPES: list[type] = []
for _name, _method in vars(OutputProjector).items():
    _msg = getattr(_method, "__angzarr_handles__", None)
    if _msg is not None:
        _DISPATCH_TABLE[_msg] = _method
        _REGISTERED_EVENT_TYPES.append(_msg)


def main() -> None:
    """Run the output projector server."""
    path = os.environ.get("HAND_LOG_FILE", "hand_log_oo.txt")
    if os.path.exists(path):
        os.remove(path)

    print("Starting Output projector (OO pattern)")

    router = (
        Router("prj-output")
        .with_handler(OutputProjector, lambda: OutputProjector())
        .build()
    )
    servicer = ProjectorGrpc(router)
    run_server(
        projector_pb2_grpc.add_ProjectorServiceServicer_to_server,
        servicer,
        service_name="prj-output",
        domain="player",
        default_port="50391",
    )


if __name__ == "__main__":
    main()
