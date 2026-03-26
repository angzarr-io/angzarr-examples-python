"""Rebuy PM handlers.

Coordinates rebuy flows across Player <-> Tournament <-> Table:
1. Player emits RebuyRequested
2. PM emits ProcessRebuy to Tournament (aggregate validates rebuy eligibility)
3. Tournament emits RebuyProcessed or RebuyDenied
4. PM emits AddRebuyChips to Table (on success, aggregate validates)
5. Table emits RebuyChipsAdded
6. PM emits ConfirmRebuyFee to Player

Design Philosophy:
    PMs are coordinators, NOT decision makers. Business validation (rebuy
    eligibility, level cutoffs, stack thresholds) belongs in aggregates.
    PM just translates events to commands and handles rejection.

    Don't rebuild destination state - use destinations.stamp_command() for
    sequence stamping. Let aggregates decide.
"""

from angzarr_client import now
from angzarr_client.destinations import Destinations
from angzarr_client.process_manager import (
    ProcessManager,
    applies,
    handles,
    output_domain,
    prepares,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import RebuyState


class RebuyPM(ProcessManager[RebuyState]):
    """Rebuy process manager.

    Coordinates the rebuy flow between Player, Tournament, and Table aggregates.

    Design Philosophy:
        PM sends commands, aggregates decide. Tournament validates rebuy
        eligibility, Table validates seating. PM handles rejections.
    """

    name = "pmg-rebuy"

    def _create_empty_state(self) -> RebuyState:
        return RebuyState()

    # --- State appliers ---

    @applies(rebuy.RebuyInitiated)
    def apply_initiated(self, state: RebuyState, event: rebuy.RebuyInitiated) -> None:
        state.phase = event.phase
        state.fee = event.fee.amount if event.HasField("fee") else 0
        state.chips_to_add = event.chips_to_add
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.tournament_root = event.tournament_root
        state.table_root = event.table_root
        state.seat = event.seat

    @applies(rebuy.RebuyPhaseChanged)
    def apply_phase_changed(
        self, state: RebuyState, event: rebuy.RebuyPhaseChanged
    ) -> None:
        state.phase = event.to_phase

    @applies(rebuy.RebuyCompleted)
    def apply_completed(self, state: RebuyState, _event: rebuy.RebuyCompleted) -> None:
        state.phase = orch.RebuyPhase.REBUY_COMPLETED

    @applies(rebuy.RebuyFailed)
    def apply_failed(self, state: RebuyState, _event: rebuy.RebuyFailed) -> None:
        state.phase = orch.RebuyPhase.REBUY_FAILED

    # --- Prepare handlers ---

    @prepares(rebuy.RebuyRequested)
    def prepare_rebuy_requested(
        self, event: rebuy.RebuyRequested
    ) -> list[types.Cover]:
        """RebuyRequested from Player -> need Tournament + Table sequences."""
        return [
            types.Cover(
                domain="tournament",
                root=types.UUID(value=event.tournament_root),
            ),
            types.Cover(
                domain="table",
                root=types.UUID(value=event.table_root),
            ),
        ]

    @prepares(tournament.RebuyProcessed)
    def prepare_rebuy_processed(
        self, event: tournament.RebuyProcessed
    ) -> list[types.Cover]:
        """RebuyProcessed from Tournament -> need Table sequence."""
        return [
            types.Cover(
                domain="table",
                root=types.UUID(value=self.state.table_root if self.state else b""),
            ),
        ]

    @prepares(tournament.RebuyDenied)
    def prepare_rebuy_denied(
        self, event: tournament.RebuyDenied
    ) -> list[types.Cover]:
        """RebuyDenied from Tournament -> need Player sequence."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            ),
        ]

    @prepares(rebuy.RebuyChipsAdded)
    def prepare_chips_added(
        self, event: rebuy.RebuyChipsAdded
    ) -> list[types.Cover]:
        """RebuyChipsAdded from Table -> need Player sequence."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            ),
        ]

    # --- Event handlers ---

    @output_domain("tournament")
    @handles(rebuy.RebuyRequested, input_domain="player")
    def handle_rebuy_requested(
        self,
        event: rebuy.RebuyRequested,
        destinations: Destinations,
        root: bytes,
    ) -> tournament.ProcessRebuy:
        """Handle RebuyRequested from Player domain.

        Emits ProcessRebuy to Tournament - aggregate validates rebuy eligibility.
        PM handles RebuyDenied if Tournament rejects.
        """
        player_root = root
        fee = event.fee.amount if event.HasField("fee") else 0

        # Emit PM event for tracking - Tournament will validate
        self._apply_and_record(
            rebuy.RebuyInitiated(
                player_root=player_root,
                tournament_root=event.tournament_root,
                table_root=event.table_root,
                reservation_id=event.reservation_id,
                seat=event.seat,
                fee=poker.Currency(amount=fee, currency_code="USD"),
                chips_to_add=0,  # Tournament will determine chips
                phase=orch.RebuyPhase.REBUY_APPROVING,
                initiated_at=now(),
            )
        )

        # Return ProcessRebuy command to Tournament
        # Tournament aggregate validates rebuy eligibility, level cutoffs, etc.
        return tournament.ProcessRebuy(
            player_root=player_root,
            reservation_id=event.reservation_id,
        )

    @output_domain("table")
    @handles(tournament.RebuyProcessed, input_domain="tournament")
    def handle_rebuy_processed(
        self,
        event: tournament.RebuyProcessed,
        destinations: Destinations,
    ) -> rebuy.AddRebuyChips:
        """Handle RebuyProcessed from Tournament domain.

        Emits AddRebuyChips to Table - aggregate validates seating.
        """
        # Use PM state for table_root and seat
        return rebuy.AddRebuyChips(
            player_root=event.player_root,
            reservation_id=event.reservation_id,
            seat=self.state.seat,
            amount=event.chips_added,
        )

    @output_domain("player")
    @handles(tournament.RebuyDenied, input_domain="tournament")
    def handle_rebuy_denied(
        self,
        event: tournament.RebuyDenied,
        destinations: Destinations,
    ) -> rebuy.ReleaseRebuyFee:
        """Handle RebuyDenied from Tournament domain.

        Emits ReleaseRebuyFee to Player.
        """
        # Emit PM failure event
        self._apply_and_record(
            rebuy.RebuyFailed(
                player_root=event.player_root,
                tournament_root=self.state.tournament_root,
                reservation_id=event.reservation_id,
                failure=orch.OrchestrationFailure(
                    code="REBUY_DENIED",
                    message=event.reason,
                    failed_at_phase="APPROVING",
                    failed_at=now(),
                ),
            )
        )

        return rebuy.ReleaseRebuyFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

    @output_domain("player")
    @handles(rebuy.RebuyChipsAdded, input_domain="table")
    def handle_chips_added(
        self,
        event: rebuy.RebuyChipsAdded,
        destinations: Destinations,
    ) -> rebuy.ConfirmRebuyFee:
        """Handle RebuyChipsAdded from Table domain.

        Emits ConfirmRebuyFee to Player.
        """
        # Emit PM completion event
        self._apply_and_record(
            rebuy.RebuyCompleted(
                player_root=event.player_root,
                tournament_root=self.state.tournament_root,
                table_root=self.state.table_root,
                reservation_id=event.reservation_id,
                fee=poker.Currency(amount=self.state.fee, currency_code="USD"),
                chips_added=event.amount,
                completed_at=now(),
            )
        )

        return rebuy.ConfirmRebuyFee(reservation_id=event.reservation_id)
