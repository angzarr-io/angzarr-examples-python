"""Hand Results Saga - bridges Hand/Table and Player domains.

Two sagas are defined here:

- ``HandResultsSaga``: HandEnded (table) -> ReleaseFunds commands (player)
- ``HandPayoutSaga``: PotAwarded (hand) -> DepositFunds commands (player)

Each saga is a single source -> single target (the unified Router restricts
a saga to one ``source`` / ``target`` pair). The original monolithic
``HandResultsSaga`` class has been split into two classes that together
cover the same behaviour.
"""

from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.message import Message

from angzarr_client import Destinations, handles, saga
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
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


@saga(name="hand-results-release", source="table", target="player")
class HandResultsSaga:
    """Saga: HandEnded -> ReleaseFunds for each player in stack_changes."""

    @handles(table.HandEnded)
    def handle_hand_ended(
        self, event: table.HandEnded, destinations: Destinations
    ) -> list[types.CommandBook]:
        dest_seq = destinations.sequence_for("player") if destinations else 0
        dest_seq = dest_seq if dest_seq is not None else 0
        commands: list[types.CommandBook] = []
        for player_hex in event.stack_changes:
            player_root = bytes.fromhex(player_hex)
            release = player.ReleaseFunds(
                key=event.hand_root,
            )
            commands.append(_command_book("player", player_root, release, dest_seq))
        return commands


@saga(name="hand-results-payout", source="hand", target="player")
class HandPayoutSaga:
    """Saga: PotAwarded -> DepositFunds for each winner."""

    @handles(hand.PotAwarded)
    def handle_pot_awarded(
        self, event: hand.PotAwarded, destinations: Destinations
    ) -> list[types.CommandBook]:
        dest_seq = destinations.sequence_for("player") if destinations else 0
        dest_seq = dest_seq if dest_seq is not None else 0
        commands: list[types.CommandBook] = []
        for winner in event.winners:
            deposit = player.DepositFunds(
                amount=poker_types.Currency(
                    amount=winner.amount,
                    currency_code="CHIPS",
                ),
            )
            commands.append(
                _command_book("player", winner.player_root, deposit, dest_seq)
            )
        return commands
