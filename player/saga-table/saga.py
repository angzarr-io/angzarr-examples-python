"""Player-to-Table saga: propagates player intent as table facts.

Flow:
- Player receives SitOut command → emits PlayerSittingOut event
- This saga receives PlayerSittingOut → would emit a PlayerSatOut fact to table
- Table aggregate accepts the fact (no validation)

Same pattern for SitIn/PlayerReturningToPlay → PlayerSatIn.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Destinations, handles, now, saga
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import table_pb2 as table


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
    ):
        """Propagate PlayerSittingOut as PlayerSatOut fact to table."""
        # TODO(saga-source-context): needs proto or library extension to access
        # source root. PlayerSittingOut does not carry player_root; the old
        # implementation captured it from ``self._current_root`` set by
        # overriding Saga.dispatch. That override is not supported in the new
        # router, and player_root is not available in the event payload.
        return None

    @handles(player.PlayerReturningToPlay)
    def handle_player_returning_to_play(
        self,
        event: player.PlayerReturningToPlay,
        destinations: Destinations,
    ):
        """Propagate PlayerReturningToPlay as PlayerSatIn fact to table."""
        # TODO(saga-source-context): needs proto or library extension to access
        # source root. PlayerReturningToPlay does not carry player_root.
        return None
