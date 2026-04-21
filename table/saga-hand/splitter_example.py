"""Saga splitter pattern example for documentation.

Demonstrates the splitter pattern where one event triggers commands to
multiple different aggregates. Uses the unified Router's ``@saga`` decorator.

``table.TableSettled`` is an example proto that is not part of the current
generated protos. The saga class below is only constructed if the proto is
available, otherwise the module loads with ``TableSettledSplitterSaga = None``
so the example remains importable.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Destinations, handles, saga
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import table_pb2 as table


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


_TableSettled = getattr(table, "TableSettled", None)
_TransferFunds = getattr(player, "TransferFunds", None)

if _TableSettled is not None and _TransferFunds is not None:

    # region saga_splitter
    @saga(name="saga-table-player-splitter", source="table", target="player")
    class TableSettledSplitterSaga:
        """Splits one TableSettled event into multiple TransferFunds commands."""

        @handles(_TableSettled)
        def handle_table_settled(
            self, event, destinations: Destinations
        ) -> list[types.CommandBook]:
            target_seq = destinations.sequence_for("player") if destinations else 0
            target_seq = target_seq if target_seq is not None else 0

            commands: list[types.CommandBook] = []
            for payout in event.payouts:
                cmd = _TransferFunds(
                    table_root=event.table_root,
                    amount=payout.amount,
                )
                commands.append(
                    types.CommandBook(
                        cover=types.Cover(
                            domain="player",
                            root=types.UUID(value=payout.player_root),
                        ),
                        pages=[
                            types.CommandPage(
                                header=types.PageHeader(sequence=target_seq),
                                command=_pack(cmd),
                            )
                        ],
                    )
                )
            return commands

    # endregion

else:
    TableSettledSplitterSaga = None
