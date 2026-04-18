"""Tests for PM-orchestrated Table handlers: SeatPlayer + AddRebuyChips.

Ported from ``examples-rust/main/table/agg/src/handlers/seat_player.rs`` and
``add_rebuy_chips.rs``.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import table_pb2 as table_proto

from .table import Table


PLAYER_ROOT = b"\x01" * 16
OTHER_PLAYER = b"\x02" * 16
RESERVATION = b"\x03" * 16


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _table_with(
    min_bi: int = 200, max_bi: int = 2000, max_players: int = 9, occupant=None
) -> Table:
    book = types.EventBook()
    book.pages.append(
        types.EventPage(
            event=_pack(
                table_proto.TableCreated(
                    table_name="Test Table",
                    small_blind=5,
                    big_blind=10,
                    min_buy_in=min_bi,
                    max_buy_in=max_bi,
                    max_players=max_players,
                )
            ),
        )
    )
    if occupant is not None:
        seat, root = occupant
        book.pages.append(
            types.EventPage(
                event=_pack(
                    table_proto.PlayerJoined(
                        player_root=root,
                        seat_position=seat,
                        buy_in_amount=500,
                        stack=500,
                    )
                ),
            )
        )
    return Table(event_book=book)


# --------------------------------------------------------------------------
# SeatPlayer
# --------------------------------------------------------------------------


class TestHandleSeatPlayer:
    def test_accept_emits_player_seated(self):
        table = _table_with()
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=0,
            amount=500,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.PlayerSeated)
        assert event.seat_position == 0
        assert event.stack == 500

    def test_reject_below_min(self):
        table = _table_with()
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=0,
            amount=100,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.SeatingRejected)
        assert "at least" in event.reason.lower()

    def test_reject_above_max(self):
        table = _table_with()
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=0,
            amount=5000,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.SeatingRejected)
        assert "above maximum" in event.reason.lower()

    def test_reject_seat_occupied(self):
        table = _table_with(occupant=(0, OTHER_PLAYER))
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=0,
            amount=500,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.SeatingRejected)
        assert "occupied" in event.reason.lower()

    def test_reject_player_already_seated(self):
        table = _table_with(occupant=(1, PLAYER_ROOT))
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=2,
            amount=500,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.SeatingRejected)
        assert "already seated" in event.reason.lower()

    def test_any_seat_picks_available(self):
        table = _table_with(occupant=(0, OTHER_PLAYER))
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=-1,
            amount=500,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.PlayerSeated)
        assert event.seat_position == 1  # first available

    def test_any_seat_full_table(self):
        # Build a table with every seat occupied.
        book = types.EventBook()
        book.pages.append(
            types.EventPage(
                event=_pack(
                    table_proto.TableCreated(
                        table_name="Full",
                        small_blind=5,
                        big_blind=10,
                        min_buy_in=200,
                        max_buy_in=2000,
                        max_players=2,
                    )
                ),
            )
        )
        for i in range(2):
            book.pages.append(
                types.EventPage(
                    event=_pack(
                        table_proto.PlayerJoined(
                            player_root=bytes([0x30 + i]) * 16,
                            seat_position=i,
                            buy_in_amount=500,
                            stack=500,
                        )
                    ),
                )
            )
        table = Table(event_book=book)
        cmd = buy_in.SeatPlayer(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=-1,
            amount=500,
        )
        event = table.handle_seat_player(cmd)
        assert isinstance(event, buy_in.SeatingRejected)
        assert "full" in event.reason.lower()


# --------------------------------------------------------------------------
# AddRebuyChips
# --------------------------------------------------------------------------


class TestHandleAddRebuyChips:
    def test_add_chips_emits_rebuy_chips_added(self):
        table = _table_with(occupant=(2, PLAYER_ROOT))
        cmd = rebuy.AddRebuyChips(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=2,
            amount=1000,
        )
        event = table.handle_add_rebuy_chips(cmd)
        assert isinstance(event, rebuy.RebuyChipsAdded)
        assert event.amount == 1000
        assert event.new_stack == 500 + 1000
        assert event.seat == 2

    def test_rejects_not_seated(self):
        table = _table_with()  # no occupants
        cmd = rebuy.AddRebuyChips(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=2,
            amount=1000,
        )
        try:
            table.handle_add_rebuy_chips(cmd)
            assert False, "expected CommandRejectedError"
        except CommandRejectedError as e:
            assert "not seated" in str(e).lower()

    def test_rejects_seat_mismatch(self):
        table = _table_with(occupant=(2, PLAYER_ROOT))
        cmd = rebuy.AddRebuyChips(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=3,  # different from actual seat
            amount=1000,
        )
        try:
            table.handle_add_rebuy_chips(cmd)
            assert False, "expected CommandRejectedError"
        except CommandRejectedError as e:
            assert "mismatch" in str(e).lower()

    def test_rejects_nonpositive_amount(self):
        table = _table_with(occupant=(2, PLAYER_ROOT))
        cmd = rebuy.AddRebuyChips(
            player_root=PLAYER_ROOT,
            reservation_id=RESERVATION,
            seat=2,
            amount=0,
        )
        try:
            table.handle_add_rebuy_chips(cmd)
            assert False, "expected CommandRejectedError"
        except CommandRejectedError as e:
            assert "positive" in str(e).lower()
