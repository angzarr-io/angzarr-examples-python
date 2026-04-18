"""Saga unit tests (unified Router API).

These tests exercise the migrated sagas by dispatching ``SagaHandleRequest``
instances through a freshly-built ``Router``. They intentionally avoid any
local saga abstraction and instead rely on the unified
``angzarr_client.Router`` machinery.
"""

from __future__ import annotations

import pytest
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Router
from angzarr_client.helpers import TYPE_URL_PREFIX, type_matches
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.angzarr import saga_pb2
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import table_pb2 as table

try:
    from sagas.hand_results_saga import HandPayoutSaga, HandResultsSaga
    from sagas.table_sync_saga import TableSyncCompleteSaga, TableSyncStartSaga

    SAGAS_AVAILABLE = True
except ImportError:
    SAGAS_AVAILABLE = False
    HandResultsSaga = None
    HandPayoutSaga = None
    TableSyncStartSaga = None
    TableSyncCompleteSaga = None

from tests.helpers import uuid_for


def make_event_book(domain: str, root: bytes, events: list) -> types.EventBook:
    """Build an EventBook with the type URL prefix expected by the unified
    Router (no domain segment in the prefix)."""
    pages = []
    for i, event in enumerate(events):
        any_pb = ProtoAny()
        any_pb.Pack(event, type_url_prefix=TYPE_URL_PREFIX)
        pages.append(
            types.EventPage(
                header=types.PageHeader(sequence=i),
                event=any_pb,
            )
        )
    return types.EventBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=pages,
        next_sequence=len(pages),
    )


pytestmark = pytest.mark.skipif(
    not SAGAS_AVAILABLE, reason="sagas package not importable"
)


def _saga_request(
    event_book: types.EventBook, dest_seqs: dict[str, int] | None = None
) -> saga_pb2.SagaHandleRequest:
    req = saga_pb2.SagaHandleRequest()
    req.source.CopyFrom(event_book)
    for k, v in (dest_seqs or {}).items():
        req.destination_sequences[k] = v
    return req


class TestTableSyncStartSaga:
    """TableSyncStartSaga: HandStarted -> DealCards."""

    def test_routes_hand_started_to_deal_cards(self) -> None:
        router = Router("sagas").with_handler(TableSyncStartSaga()).build()

        event = table.HandStarted(
            hand_root=uuid_for("hand-1"),
            hand_number=1,
            game_variant=poker_types.TEXAS_HOLDEM,
            dealer_position=0,
            small_blind=100,
            big_blind=200,
        )
        event.active_players.append(
            table.SeatSnapshot(player_root=uuid_for("player-1"), position=0, stack=500)
        )
        event.active_players.append(
            table.SeatSnapshot(player_root=uuid_for("player-2"), position=1, stack=500)
        )

        event_book = make_event_book("table", uuid_for("table-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"hand": 0}))

        assert len(response.commands) == 1
        assert response.commands[0].cover.domain == "hand"
        assert type_matches(response.commands[0].pages[0].command, hand.DealCards)

        cmd = hand.DealCards()
        response.commands[0].pages[0].command.Unpack(cmd)
        assert cmd.game_variant == poker_types.TEXAS_HOLDEM
        assert len(cmd.players) == 2
        assert cmd.hand_number == 1


class TestTableSyncCompleteSaga:
    """TableSyncCompleteSaga: HandComplete -> EndHand."""

    def test_routes_hand_complete_to_end_hand(self) -> None:
        router = Router("sagas").with_handler(TableSyncCompleteSaga()).build()

        event = hand.HandComplete(
            table_root=uuid_for("table-1"),
            hand_number=1,
        )
        event.winners.append(
            hand.PotWinner(player_root=uuid_for("player-1"), amount=100)
        )

        event_book = make_event_book("hand", uuid_for("hand-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"table": 0}))

        assert len(response.commands) == 1
        assert response.commands[0].cover.domain == "table"
        assert type_matches(response.commands[0].pages[0].command, table.EndHand)

        cmd = table.EndHand()
        response.commands[0].pages[0].command.Unpack(cmd)
        assert len(cmd.results) == 1
        assert cmd.results[0].winner_root == uuid_for("player-1")
        assert cmd.results[0].amount == 100


class TestHandResultsSaga:
    """HandResultsSaga: HandEnded (table) -> ReleaseFunds per player."""

    def test_routes_hand_ended_to_release_funds(self) -> None:
        router = Router("sagas").with_handler(HandResultsSaga()).build()

        event = table.HandEnded(hand_root=uuid_for("hand-1"))
        event.stack_changes[uuid_for("player-1").hex()] = 50
        event.stack_changes[uuid_for("player-2").hex()] = -50

        event_book = make_event_book("table", uuid_for("table-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"player": 0}))

        assert len(response.commands) == 2
        for cmd_book in response.commands:
            assert cmd_book.cover.domain == "player"
            assert type_matches(cmd_book.pages[0].command, player.ReleaseFunds)


class TestHandPayoutSaga:
    """HandPayoutSaga: PotAwarded (hand) -> DepositFunds per winner."""

    def test_routes_pot_awarded_to_deposit_funds(self) -> None:
        router = Router("sagas").with_handler(HandPayoutSaga()).build()

        event = hand.PotAwarded()
        event.winners.append(
            hand.PotWinner(player_root=uuid_for("player-1"), amount=60)
        )
        event.winners.append(
            hand.PotWinner(player_root=uuid_for("player-2"), amount=40)
        )

        event_book = make_event_book("hand", uuid_for("hand-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"player": 0}))

        assert len(response.commands) == 2
        for cmd_book in response.commands:
            assert cmd_book.cover.domain == "player"
            assert type_matches(cmd_book.pages[0].command, player.DepositFunds)

        cmd1 = player.DepositFunds()
        response.commands[0].pages[0].command.Unpack(cmd1)
        assert cmd1.amount.amount == 60
        assert response.commands[0].cover.root.value == uuid_for("player-1")

        cmd2 = player.DepositFunds()
        response.commands[1].pages[0].command.Unpack(cmd2)
        assert cmd2.amount.amount == 40
        assert response.commands[1].cover.root.value == uuid_for("player-2")


class TestMultiSagaRouter:
    """Router routes events only to sagas whose source domain matches."""

    def test_dispatches_to_matching_saga_only(self) -> None:
        router = (
            Router("sagas")
            .with_handler(TableSyncStartSaga())
            .with_handler(HandResultsSaga())
            .with_handler(HandPayoutSaga())
            .build()
        )

        event = table.HandStarted(
            hand_root=uuid_for("hand-1"),
            hand_number=1,
            game_variant=poker_types.TEXAS_HOLDEM,
        )
        event.active_players.append(
            table.SeatSnapshot(player_root=uuid_for("player-1"), position=0, stack=500)
        )

        event_book = make_event_book("table", uuid_for("table-1"), [event])
        response = router.dispatch(
            _saga_request(event_book, {"hand": 0, "table": 0, "player": 0})
        )

        # Only TableSyncStartSaga (source=table) emits DealCards.
        assert len(response.commands) == 1
        assert type_matches(response.commands[0].pages[0].command, hand.DealCards)


class TestHandResultsSagaEdgeCases:
    """Edge cases for HandResultsSaga."""

    def test_empty_stack_changes_yields_no_commands(self) -> None:
        router = Router("sagas").with_handler(HandResultsSaga()).build()

        event = table.HandEnded(hand_root=uuid_for("hand-1"))
        event_book = make_event_book("table", uuid_for("table-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"player": 0}))

        assert len(response.commands) == 0

    def test_emits_for_all_players_including_zero_change(self) -> None:
        router = Router("sagas").with_handler(HandResultsSaga()).build()

        event = table.HandEnded(hand_root=uuid_for("hand-1"))
        event.stack_changes[uuid_for("player-1").hex()] = 100
        event.stack_changes[uuid_for("player-2").hex()] = 0

        event_book = make_event_book("table", uuid_for("table-1"), [event])
        response = router.dispatch(_saga_request(event_book, {"player": 0}))

        assert len(response.commands) == 2
        for cmd_book in response.commands:
            assert cmd_book.cover.domain == "player"
            assert type_matches(cmd_book.pages[0].command, player.ReleaseFunds)
