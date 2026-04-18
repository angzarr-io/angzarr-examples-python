"""Table Sync Saga - bridges Table and Hand domains.

Two sagas:
- ``TableSyncStartSaga``: HandStarted (table) -> DealCards (hand)
- ``TableSyncCompleteSaga``: HandComplete (hand) -> EndHand (table)
"""

from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.message import Message

from angzarr_client import Destinations, handles, saga
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import table_pb2 as table


def _pack_command(cmd: Message) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(cmd, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(
    domain: str, root: bytes, command: Message, sequence: int = 0
) -> types.CommandBook:
    return types.CommandBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.CommandPage(
                header=types.PageHeader(sequence=sequence),
                command=_pack_command(command),
            )
        ],
    )


@saga(name="table-sync-start", source="table", target="hand")
class TableSyncStartSaga:
    """Saga: HandStarted -> DealCards."""

    @handles(table.HandStarted)
    def handle_hand_started(
        self, event: table.HandStarted, destinations: Destinations
    ) -> types.CommandBook:
        players = [
            hand.PlayerInHand(
                player_root=seat.player_root,
                position=seat.position,
                stack=seat.stack,
            )
            for seat in event.active_players
        ]

        deal_cards = hand.DealCards(
            table_root=event.hand_root,
            hand_number=event.hand_number,
            game_variant=event.game_variant,
            players=players,
            dealer_position=event.dealer_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
            deck_seed=b"",
        )

        dest_seq = destinations.sequence_for("hand") if destinations else 0
        dest_seq = dest_seq if dest_seq is not None else 0
        return _command_book("hand", event.hand_root, deal_cards, dest_seq)


# Kept as an alias so existing import paths (``TableSyncSaga``) continue to work
# where code expected the pre-split class.
TableSyncSaga = TableSyncStartSaga


@saga(name="table-sync-complete", source="hand", target="table")
class TableSyncCompleteSaga:
    """Saga: HandComplete -> EndHand."""

    @handles(hand.HandComplete)
    def handle_hand_complete(
        self, event: hand.HandComplete, destinations: Destinations
    ) -> types.CommandBook:
        results = [
            table.PotResult(
                winner_root=winner.player_root,
                amount=winner.amount,
            )
            for winner in event.winners
        ]

        end_hand = table.EndHand(
            hand_root=event.table_root,
            results=results,
        )

        dest_seq = destinations.sequence_for("table") if destinations else 0
        dest_seq = dest_seq if dest_seq is not None else 0
        return _command_book("table", event.table_root, end_hand, dest_seq)
