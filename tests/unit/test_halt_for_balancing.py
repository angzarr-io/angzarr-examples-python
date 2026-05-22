"""TDA Rule 11D — table halts for balancing.

Exercises the table aggregate's ``handle_halt_for_balancing`` and
``handle_resume_play_at_table`` paths plus the ``StartHand`` guard that
the halt installs. Detection (cross-table comparison + next-BB-on-empty
check) lives in the tournament-coordinator saga and is out of scope
here — these tests seed the table with enough state to be StartHand-able
and drive the halt/resume cycle directly."""

from __future__ import annotations

import uuid as _uuid

import pytest
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
from table.agg.handlers import Table
from table.agg.handlers.table import MIN_HALT_FOR_BALANCING_DEFICIT
from table.agg.errors import (
    HaltDeficitBelowMin,
    TableAlreadyHalted,
    TableHaltedAwaitingRebalance,
    TableNotFound,
    TableNotHalted,
)


TABLE_NAME = "Table-A"


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
    return types.EventBook(
        cover=types.Cover(
            root=types.UUID(
                value=_uuid.uuid5(_uuid.NAMESPACE_OID, TABLE_NAME).bytes
            ),
            domain="table",
        ),
        pages=[_page(evt, i) for i, evt in enumerate(events)],
    )


def _player_root(seed: str) -> bytes:
    return _uuid.uuid5(_uuid.NAMESPACE_OID, seed).bytes


def _make_seated_table(*, players: int = 2) -> Table:
    """Aggregate with TableCreated + N PlayerJoined events applied —
    enough state for StartHand to be eligible (>= 2 active players).
    """
    events = [
        table_proto.TableCreated(
            table_name=TABLE_NAME,
            small_blind=5,
            big_blind=10,
            min_buy_in=100,
            max_buy_in=500,
            max_players=9,
            action_timeout_seconds=30,
        )
    ]
    for i in range(players):
        events.append(
            table_proto.PlayerJoined(
                player_root=_player_root(f"player-{i}"),
                seat_position=i + 1,
                buy_in_amount=100,
                stack=100,
            )
        )
    return Table(_seed_book(*events))


# -----------------------------------------------------------------------------
# Halt
# -----------------------------------------------------------------------------


def test_handle_halt_emits_event_with_deficit_and_table_root() -> None:
    agg = _make_seated_table()
    deficit = MIN_HALT_FOR_BALANCING_DEFICIT  # 3, the minimum that issues

    event = agg.handle_halt_for_balancing(
        table_proto.HaltForBalancing(deficit=deficit)
    )

    assert isinstance(event, table_proto.TableHaltedForBalancing)
    assert event.deficit == deficit
    assert event.table_root == _uuid.uuid5(_uuid.NAMESPACE_OID, TABLE_NAME).bytes
    assert event.halted_at.seconds > 0


def test_apply_halt_flips_state() -> None:
    agg = _make_seated_table()

    agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=4))

    assert agg._state.halted_for_balancing is True
    assert agg._state.halted_deficit == 4


def test_halt_below_threshold_rejected() -> None:
    agg = _make_seated_table()

    with pytest.raises(HaltDeficitBelowMin) as exc_info:
        agg.handle_halt_for_balancing(
            table_proto.HaltForBalancing(
                deficit=MIN_HALT_FOR_BALANCING_DEFICIT - 1
            )
        )

    assert exc_info.value.code == "HALT_DEFICIT_BELOW_MIN"
    assert agg._state.halted_for_balancing is False


def test_double_halt_rejected() -> None:
    agg = _make_seated_table()
    agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=3))

    with pytest.raises(TableAlreadyHalted):
        agg.handle_halt_for_balancing(
            table_proto.HaltForBalancing(deficit=4)
        )

    # State unchanged from the original halt.
    assert agg._state.halted_deficit == 3


def test_halt_on_nonexistent_table_rejected() -> None:
    # No TableCreated in the event book — aggregate exists() returns False.
    agg = Table(types.EventBook())

    with pytest.raises(TableNotFound):
        agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=3))


# -----------------------------------------------------------------------------
# StartHand guard
# -----------------------------------------------------------------------------


def test_start_hand_rejected_while_halted() -> None:
    agg = _make_seated_table()
    agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=5))

    with pytest.raises(TableHaltedAwaitingRebalance) as exc_info:
        agg.handle_start_hand(table_proto.StartHand())

    # Rule-faithful surfacing — the deficit is reported back so operators
    # can see why play is paused without rebuilding state.
    assert exc_info.value.deficit == 5


# -----------------------------------------------------------------------------
# Resume
# -----------------------------------------------------------------------------


def test_resume_clears_halt_state() -> None:
    agg = _make_seated_table()
    agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=3))

    event = agg.handle_resume_play_at_table(table_proto.ResumePlayAtTable())

    assert isinstance(event, table_proto.TableResumedForBalancing)
    assert event.table_root == _uuid.uuid5(_uuid.NAMESPACE_OID, TABLE_NAME).bytes
    assert agg._state.halted_for_balancing is False
    assert agg._state.halted_deficit == 0


def test_resume_when_not_halted_rejected() -> None:
    agg = _make_seated_table()

    with pytest.raises(TableNotHalted):
        agg.handle_resume_play_at_table(table_proto.ResumePlayAtTable())


def test_start_hand_works_again_after_resume() -> None:
    agg = _make_seated_table()
    agg.handle_halt_for_balancing(table_proto.HaltForBalancing(deficit=3))
    agg.handle_resume_play_at_table(table_proto.ResumePlayAtTable())

    # Should NOT raise — halt cleared by the resume.
    try:
        agg.handle_start_hand(table_proto.StartHand())
    except CommandRejectedError as exc:  # pragma: no cover - diagnostic only
        pytest.fail(f"StartHand rejected after resume: {exc}")
