"""TDA Rule 11D local predicate: ``_predicate_bb_on_empty``.

The predicate captures the "blinds are impacted" half of Rule 11D —
the seat that previously held the BB no longer has an active player.
Pure function on table state; no command dispatch.
"""

from __future__ import annotations

import uuid as _uuid

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr.v1 import types_pb2 as types
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


def _basic_table_with_three_players_and_hand() -> Table:
    """TableCreated + 3 PlayerJoined + HandStarted (sets BB position)."""
    events = [
        table_proto.TableCreated(
            table_name="T-pred",
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
    ]
    return Table(_seed_book(*events))


# -----------------------------------------------------------------------------
# Predicate cases
# -----------------------------------------------------------------------------


def test_predicate_false_when_no_hand_played_yet() -> None:
    # last_big_blind_position is -1 until HandStarted applies.
    events = [
        table_proto.TableCreated(
            table_name="T",
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
    ]
    agg = Table(_seed_book(*events))
    assert agg._state.last_big_blind_position == -1
    assert agg._predicate_bb_on_empty() is False


def test_predicate_false_when_bb_seat_still_active() -> None:
    agg = _basic_table_with_three_players_and_hand()
    # BB was at seat 2; seat 2 still has an active player.
    assert agg._predicate_bb_on_empty() is False


def test_predicate_true_when_bb_seat_vacated_by_elimination() -> None:
    agg = _basic_table_with_three_players_and_hand()
    # Drop the seat-2 player (the prior BB).
    del agg._state.seats[2]
    assert agg._predicate_bb_on_empty() is True


def test_predicate_true_when_bb_seat_player_sat_out() -> None:
    agg = _basic_table_with_three_players_and_hand()
    # Mark seat 2 as sitting-out (predicate uses the same 'active'
    # subset as the dead-button rule, which excludes sat-out).
    agg._state.seats[2].is_sitting_out = True
    assert agg._predicate_bb_on_empty() is True


def test_predicate_false_when_a_different_seat_is_vacated() -> None:
    agg = _basic_table_with_three_players_and_hand()
    # Drop seat 0 (the dealer); BB seat 2 is still active.
    del agg._state.seats[0]
    assert agg._predicate_bb_on_empty() is False


def test_predicate_false_for_table_with_no_seats() -> None:
    # Degenerate case: TableCreated but no joins.
    agg = Table(
        _seed_book(
            table_proto.TableCreated(
                table_name="T-empty",
                small_blind=5,
                big_blind=10,
                min_buy_in=100,
                max_buy_in=500,
                max_players=9,
            )
        )
    )
    assert agg._predicate_bb_on_empty() is False
