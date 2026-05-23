"""TDA Rule 11D tournament-side: cross-table state + auto-detection.

Drives the tournament aggregate's saga-fed handlers (RecordTable*) and
asserts:
- per-table count + flag state updates correctly
- BB-on-empty + deficit ≥ 3 emits TableHaltOrdered
- BB-on-empty cleared on a halted table emits TableResumeOrdered
- operator-issued HaltShortTable / ResumeShortTable paths still work
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import tournament_pb2 as tournament
from tournament.agg.handlers import Tournament


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


def _table_root(seed: str) -> bytes:
    return _uuid.uuid5(_uuid.NAMESPACE_OID, seed).bytes


def _running_tournament() -> Tournament:
    """Tournament aggregate in RUNNING state — enough to accept the
    new commands."""
    events = [
        tournament.TournamentCreated(
            name="T-x",
            game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
            buy_in=100,
            starting_stack=1500,
            max_players=200,
            min_players=2,
        ),
        tournament.RegistrationOpened(),
        tournament.RegistrationClosed(),
        tournament.TournamentStarted(),
    ]
    return Tournament(_seed_book(*events))


def _emitted_event_types(agg: Tournament) -> list[str]:
    return [p.event.type_url.rsplit("/", 1)[-1] for p in agg.event_book().pages]


# -----------------------------------------------------------------------------
# Count tracking
# -----------------------------------------------------------------------------


def test_record_player_joined_emits_and_increments() -> None:
    agg = _running_tournament()
    t_a = _table_root("Table-A")

    agg.handle_record_table_player_joined(
        tournament.RecordTablePlayerJoined(
            table_root=t_a,
            player_root=b"p1",
        )
    )

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TournamentTablePlayerJoined" in emitted
    assert agg._state.table_player_counts[t_a] == 1


def test_record_player_left_decrements_and_clamps_at_zero() -> None:
    agg = _running_tournament()
    t_a = _table_root("Table-A")

    agg.handle_record_table_player_joined(
        tournament.RecordTablePlayerJoined(table_root=t_a, player_root=b"p1")
    )
    agg.handle_record_table_player_left(
        tournament.RecordTablePlayerLeft(table_root=t_a, player_root=b"p1")
    )
    assert agg._state.table_player_counts[t_a] == 0

    # Double-leave (saga retry) — clamps to 0, no underflow
    agg.handle_record_table_player_left(
        tournament.RecordTablePlayerLeft(table_root=t_a, player_root=b"p1")
    )
    assert agg._state.table_player_counts[t_a] == 0


# -----------------------------------------------------------------------------
# Rule evaluation on BB-on-empty
# -----------------------------------------------------------------------------


def _seed_two_table_state(agg: Tournament, a_count: int, b_count: int) -> None:
    t_a = _table_root("Table-A")
    t_b = _table_root("Table-B")
    for i in range(a_count):
        agg.handle_record_table_player_joined(
            tournament.RecordTablePlayerJoined(
                table_root=t_a,
                player_root=f"a{i}".encode(),
            )
        )
    for i in range(b_count):
        agg.handle_record_table_player_joined(
            tournament.RecordTablePlayerJoined(
                table_root=t_b,
                player_root=f"b{i}".encode(),
            )
        )


def test_bb_on_empty_with_deficit_3_emits_halt_ordered() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=8, b_count=5)
    t_b = _table_root("Table-B")

    agg.handle_record_table_bb_on_empty(tournament.RecordTableBBOnEmpty(table_root=t_b))

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TournamentTableBBOnEmpty" in emitted
    assert "angzarr_client.proto.examples.v1.TableHaltOrdered" in emitted
    # The halt event carries deficit=3 (8 - 5).
    halt_event = None
    for page in agg.event_book().pages:
        if page.event.type_url.endswith("TableHaltOrdered"):
            halt_event = tournament.TableHaltOrdered()
            page.event.Unpack(halt_event)
            break
    assert halt_event is not None
    assert halt_event.target_table_root == t_b
    assert halt_event.deficit == 3
    # The applier added t_b to pending_halt_orders.
    assert t_b in agg._state.pending_halt_orders


def test_bb_on_empty_with_deficit_2_does_not_halt() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=7, b_count=5)
    t_b = _table_root("Table-B")

    agg.handle_record_table_bb_on_empty(tournament.RecordTableBBOnEmpty(table_root=t_b))

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TournamentTableBBOnEmpty" in emitted
    assert "angzarr_client.proto.examples.v1.TableHaltOrdered" not in emitted
    assert t_b not in agg._state.pending_halt_orders


def test_bb_on_empty_idempotent_on_already_halted_table() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=8, b_count=5)
    t_b = _table_root("Table-B")

    agg.handle_record_table_bb_on_empty(tournament.RecordTableBBOnEmpty(table_root=t_b))
    # Second call — flag is still on, but no NEW halt should fire.
    agg.handle_record_table_bb_on_empty(tournament.RecordTableBBOnEmpty(table_root=t_b))

    halt_count = sum(
        1
        for p in agg.event_book().pages
        if p.event.type_url.endswith("TableHaltOrdered")
    )
    assert halt_count == 1


# -----------------------------------------------------------------------------
# Resume on bb-on-empty-cleared
# -----------------------------------------------------------------------------


def test_bb_on_empty_cleared_resumes_halted_table() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=8, b_count=5)
    t_b = _table_root("Table-B")

    # First halt
    agg.handle_record_table_bb_on_empty(tournament.RecordTableBBOnEmpty(table_root=t_b))
    assert t_b in agg._state.pending_halt_orders

    # Now clear
    agg.handle_record_table_bb_on_empty_cleared(
        tournament.RecordTableBBOnEmptyCleared(table_root=t_b)
    )

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TournamentTableBBOnEmptyCleared" in emitted
    assert "angzarr_client.proto.examples.v1.TableResumeOrdered" in emitted
    assert t_b not in agg._state.pending_halt_orders


def test_bb_on_empty_cleared_on_unhalted_table_does_not_emit_resume() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=7, b_count=5)
    t_b = _table_root("Table-B")

    agg.handle_record_table_bb_on_empty_cleared(
        tournament.RecordTableBBOnEmptyCleared(table_root=t_b)
    )

    emitted = _emitted_event_types(agg)
    assert "angzarr_client.proto.examples.v1.TableResumeOrdered" not in emitted


# -----------------------------------------------------------------------------
# Operator-issued path
# -----------------------------------------------------------------------------


def test_halt_short_table_emits_halt_ordered() -> None:
    agg = _running_tournament()
    t_b = _table_root("Table-B")

    event = agg.handle_halt_short_table(
        tournament.HaltShortTable(target_table_root=t_b, deficit=4)
    )

    assert isinstance(event, tournament.TableHaltOrdered)
    assert event.target_table_root == t_b
    assert event.deficit == 4
    assert t_b in agg._state.pending_halt_orders


def test_resume_short_table_emits_resume_ordered() -> None:
    agg = _running_tournament()
    t_b = _table_root("Table-B")

    # Halt first
    agg.handle_halt_short_table(
        tournament.HaltShortTable(target_table_root=t_b, deficit=4)
    )
    # Now resume
    event = agg.handle_resume_short_table(
        tournament.ResumeShortTable(target_table_root=t_b)
    )

    assert isinstance(event, tournament.TableResumeOrdered)
    assert event.target_table_root == t_b
    assert t_b not in agg._state.pending_halt_orders


def test_halt_short_table_rejects_when_tournament_not_running() -> None:
    from angzarr_client.errors import CommandRejectedError

    # No TournamentStarted in history → state is "Created".
    events = [
        tournament.TournamentCreated(
            name="T-x",
            game_variant=poker_types.GameVariant.TEXAS_HOLDEM,
            buy_in=100,
            starting_stack=1500,
            max_players=200,
            min_players=2,
        ),
    ]
    agg = Tournament(_seed_book(*events))

    with pytest.raises(CommandRejectedError):
        agg.handle_halt_short_table(
            tournament.HaltShortTable(target_table_root=_table_root("T"), deficit=4)
        )


# -----------------------------------------------------------------------------
# _compute_table_deficit edge cases
# -----------------------------------------------------------------------------


def test_compute_deficit_returns_zero_when_no_other_tables() -> None:
    agg = _running_tournament()
    t_a = _table_root("Table-A")
    agg.handle_record_table_player_joined(
        tournament.RecordTablePlayerJoined(table_root=t_a, player_root=b"p")
    )

    assert agg._compute_table_deficit(t_a) == 0


def test_compute_deficit_returns_positive_when_other_table_larger() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=8, b_count=5)
    t_b = _table_root("Table-B")
    assert agg._compute_table_deficit(t_b) == 3


def test_compute_deficit_returns_zero_for_largest_table() -> None:
    agg = _running_tournament()
    _seed_two_table_state(agg, a_count=8, b_count=5)
    t_a = _table_root("Table-A")
    # A IS the largest; the next-largest other is B at 5; deficit = 5-8 = -3.
    # _compute_table_deficit returns `other_max - this_count`, which can be negative.
    assert agg._compute_table_deficit(t_a) == -3
