"""Player-to-Table saga: propagates player intent as table facts.

Flow:
- Player receives SitOut command → emits PlayerSittingOut event
- This saga receives PlayerSittingOut → emits PlayerSatOut fact to table
- Table aggregate accepts the fact (no validation)

Same pattern for SitIn/PlayerReturningToPlay → PlayerSatIn.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Destinations, handles, now, saga
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import table_pb2 as table


def _pack_fact(fact, table_root: bytes, external_id: str) -> types.EventBook:
    cover = types.Cover(
        domain="table",
        root=types.UUID(value=table_root),
    )
    fact_any = ProtoAny()
    fact_any.Pack(fact, type_url_prefix="type.googleapis.com/")
    return types.EventBook(
        cover=cover,
        pages=[
            types.EventPage(
                header=types.PageHeader(
                    external_deferred=types.ExternalDeferredSequence(
                        external_id=external_id,
                    )
                ),
                event=fact_any,
            )
        ],
    )


@saga(name="saga-player-table", source="player", target="table")
class PlayerTableSaga:
    """Saga that propagates player sit-out intent to table as facts.

    Player owns the intent to sit out/in. The table aggregate must accept
    these as facts (no validation) because player has authority over their
    own participation state.
    """

    @handles(player.PlayerSittingOut)
    def handle_player_sitting_out(
        self,
        event: player.PlayerSittingOut,
        destinations: Destinations,
        source_cover: types.Cover = None,
    ) -> types.EventBook:
        """Propagate PlayerSittingOut as PlayerSatOut fact to table."""
        player_root = source_cover.root.value if source_cover is not None else b""
        fact = table.PlayerSatOut(
            player_root=player_root,
            sat_out_at=event.sat_out_at or now(),
        )
        return _pack_fact(
            fact,
            event.table_root,
            f"sitout-{player_root.hex()}",
        )

    @handles(player.PlayerReturningToPlay)
    def handle_player_returning_to_play(
        self,
        event: player.PlayerReturningToPlay,
        destinations: Destinations,
        source_cover: types.Cover = None,
    ) -> types.EventBook:
        """Propagate PlayerReturningToPlay as PlayerSatIn fact to table."""
        player_root = source_cover.root.value if source_cover is not None else b""
        fact = table.PlayerSatIn(
            player_root=player_root,
            sat_in_at=event.sat_in_at or now(),
        )
        return _pack_fact(
            fact,
            event.table_root,
            f"sitin-{player_root.hex()}",
        )
