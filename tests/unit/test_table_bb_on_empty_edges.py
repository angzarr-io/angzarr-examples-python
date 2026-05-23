"""TDA Rule 11D edge emission: false→true and true→false transitions.

Drives each of the four instrumented handlers and asserts that the
right edge event was emitted (or not, for non-edge calls)."""

from __future__ import annotations

import uuid as _uuid

import pytest
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in_proto
from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
from table.agg.handlers import Table


def _pack(event) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(event, type_url_prefix="type.googleapis.com/")
    return any_msg


def _page(event, sequence: int) -> types.EventPage:
    return types.EventPage(
        header=types.PageHeader(sequence=sequence),
        event=_pack(event),
    )


def _seed_book(*events) -> types.EventBook:
    return types.EventBook(pages=[_page(e, i) for i, e in enumerate(events)])


def _player_root(seed: str) -> bytes:
    return _uuid.uuid5(_uuid.NAMESPACE_OID, seed).bytes


def _aggregate_with_three_players_at_bb_seat_2() -> Table:
    """3 players seated at 0/1/2; BB landed on seat 2 on the first
    hand. Predicate is False because seat 2 is still active."""
    events = [
        table_proto.TableCreated(
            table_name="T-edge",
            small_blind=5,
            big_blind=10,
            min_buy_in=100,
            max_buy_in=500,
            max_players=9,
        ),
        table_proto.PlayerJoined(
            player_root=_player_root("p-0"),
            seat_position=0,
            buy_in_amount=100,
            stack=100,
        ),
        table_proto.PlayerJoined(
            player_root=_player_root("p-1"),
            seat_position=1,
            buy_in_amount=100,
            stack=100,
        ),
        table_proto.PlayerJoined(
            player_root=_player_root("p-2"),
            seat_position=2,
            buy_in_amount=100,
            stack=100,
        ),
        table_proto.HandStarted(
            hand_root=b"h-1",
            hand_number=1,
            dealer_position=0,
            small_blind_position=1,
            big_blind_position=2,
        ),
        table_proto.HandEnded(
            hand_root=b"h-1",
        ),
    ]
    return Table(_seed_book(*events))


def _emitted_event_types(agg: Table) -> list[str]:
    """Return the proto full_name of each event in the aggregate's
    event_book, in order."""
    names: list[str] = []
    for page in agg.event_book().pages:
        names.append(page.event.type_url.rsplit("/", 1)[-1])
    return names


# -----------------------------------------------------------------------------
# handle_leave_table — emits TableBBOnEmptyPredicted when the leaving
# seat was the prior BB
# -----------------------------------------------------------------------------


def test_leave_table_emits_predicted_when_bb_seat_vacated() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    assert agg._state.bb_on_empty_flagged is False

    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TableBBOnEmptyPredicted" in emitted
    assert agg._state.bb_on_empty_flagged is True


def test_leave_table_does_not_emit_when_non_bb_seat_vacated() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()

    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-0")))

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TableBBOnEmptyPredicted" not in emitted
    assert agg._state.bb_on_empty_flagged is False


# -----------------------------------------------------------------------------
# handle_seat_player (buy_in) — emits TableBBOnEmptyResolved when the
# seat being filled is the prior BB
# -----------------------------------------------------------------------------


def test_seat_player_emits_resolved_when_bb_seat_filled() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    # Vacate seat 2 first to set the flag.
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))
    assert agg._state.bb_on_empty_flagged is True

    # Seat a new player at seat 2 via buy_in path.
    agg.handle_seat_player(
        buy_in_proto.SeatPlayer(
            player_root=_player_root("p-fill"),
            reservation_id=b"r1",
            seat=2,
            amount=100,
        )
    )

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TableBBOnEmptyResolved" in emitted
    assert agg._state.bb_on_empty_flagged is False


def test_seat_player_does_not_emit_when_filling_unrelated_seat() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))
    # Seat at 4, leaving the BB-seat-2 still empty.
    agg.handle_seat_player(
        buy_in_proto.SeatPlayer(
            player_root=_player_root("p-fill"),
            reservation_id=b"r1",
            seat=4,
            amount=100,
        )
    )

    # The seat_player call's emit emitted a PlayerSeated. There should be
    # NO TableBBOnEmptyResolved because seat 2 is still empty.
    emitted = _emitted_event_types(agg)
    # The original Predicted from leave is still there.
    predicted_count = emitted.count(
        "angzarr_client.proto.examples.v1.TableBBOnEmptyPredicted"
    )
    resolved_count = emitted.count(
        "angzarr_client.proto.examples.v1.TableBBOnEmptyResolved"
    )
    assert predicted_count == 1
    assert resolved_count == 0
    assert agg._state.bb_on_empty_flagged is True


# -----------------------------------------------------------------------------
# handle_join_table — same as seat_player, the legacy/test path
# -----------------------------------------------------------------------------


def test_join_table_resolves_when_filling_bb_seat() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))

    # join_table picks the seat or honors preferred_seat. Use preferred=2.
    agg.handle_join_table(
        table_proto.JoinTable(
            player_root=_player_root("p-rejoin"),
            preferred_seat=2,
            buy_in_amount=100,
        )
    )

    assert agg._state.bb_on_empty_flagged is False


# -----------------------------------------------------------------------------
# Idempotency: edge emit only on transitions, not on every state-change
# -----------------------------------------------------------------------------


def test_consecutive_eliminations_emit_predicted_only_once() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    # 1st elimination: BB seat 2 — flag flips False→True (edge emitted)
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))
    # 2nd elimination: seat 0 — predicate still True (BB seat still empty),
    # no new edge.
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-0")))

    emitted = _emitted_event_types(agg)
    predicted_count = emitted.count(
        "angzarr_client.proto.examples.v1.TableBBOnEmptyPredicted"
    )
    assert predicted_count == 1


# -----------------------------------------------------------------------------
# Sanity: emitted event carries the table_root
# -----------------------------------------------------------------------------


def test_predicted_event_carries_table_root() -> None:
    agg = _aggregate_with_three_players_at_bb_seat_2()
    agg.handle_leave_table(table_proto.LeaveTable(player_root=_player_root("p-2")))

    # Find the predicted event and unpack
    for page in agg.event_book().pages:
        if page.event.type_url.endswith("TableBBOnEmptyPredicted"):
            evt = table_proto.TableBBOnEmptyPredicted()
            page.event.Unpack(evt)
            expected_root = _uuid.uuid5(_uuid.NAMESPACE_OID, "T-edge").bytes
            assert evt.table_root == expected_root
            return
    pytest.fail("No TableBBOnEmptyPredicted in event_book")
