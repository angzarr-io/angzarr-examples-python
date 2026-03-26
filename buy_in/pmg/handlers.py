"""Buy-in PM handlers.

Coordinates buy-in flows across Player <-> Table:
1. Player emits BuyInRequested
2. PM emits SeatPlayer command to Table (aggregate validates)
3. Table emits PlayerSeated or SeatingRejected
4. PM emits ConfirmBuyIn or ReleaseBuyIn to Player

Design Philosophy:
    PMs are coordinators, NOT decision makers. Business logic (seat validation,
    buy-in range checks) belongs in the Table aggregate. PM just translates
    events to commands and handles rejection via @rejected decorators.

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
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker

from state import BuyInState


class BuyInPM(ProcessManager[BuyInState]):
    """Buy-in process manager.

    Coordinates the buy-in flow between Player and Table aggregates.

    Design Philosophy:
        PM sends commands, aggregates decide. The Table aggregate validates
        seat availability, buy-in range, etc. PM handles rejection via
        @rejected decorators and emits compensation commands.
    """

    name = "pmg-buy-in"

    def _create_empty_state(self) -> BuyInState:
        return BuyInState()

    # --- State appliers ---

    @applies(buy_in.BuyInInitiated)
    def apply_initiated(self, state: BuyInState, event: buy_in.BuyInInitiated) -> None:
        state.phase = event.phase
        state.amount = event.amount.amount if event.HasField("amount") else 0
        state.reservation_id = event.reservation_id
        state.player_root = event.player_root
        state.table_root = event.table_root
        state.seat = event.seat

    @applies(buy_in.BuyInPhaseChanged)
    def apply_phase_changed(
        self, state: BuyInState, event: buy_in.BuyInPhaseChanged
    ) -> None:
        state.phase = event.to_phase

    @applies(buy_in.BuyInCompleted)
    def apply_completed(
        self, state: BuyInState, _event: buy_in.BuyInCompleted
    ) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_COMPLETED

    @applies(buy_in.BuyInFailed)
    def apply_failed(self, state: BuyInState, _event: buy_in.BuyInFailed) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_FAILED

    # --- Prepare handlers ---

    @prepares(buy_in.BuyInRequested)
    def prepare_buy_in_requested(
        self, event: buy_in.BuyInRequested
    ) -> list[types.Cover]:
        """BuyInRequested from Player -> need Table state."""
        return [
            types.Cover(
                domain="table",
                root=types.UUID(value=event.table_root),
            )
        ]

    @prepares(buy_in.PlayerSeated)
    def prepare_player_seated(self, event: buy_in.PlayerSeated) -> list[types.Cover]:
        """PlayerSeated from Table -> need Player state."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            )
        ]

    @prepares(buy_in.SeatingRejected)
    def prepare_seating_rejected(
        self, event: buy_in.SeatingRejected
    ) -> list[types.Cover]:
        """SeatingRejected from Table -> need Player state."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            )
        ]

    # --- Event handlers ---

    @output_domain("table")
    @handles(buy_in.BuyInRequested, input_domain="player")
    def handle_buy_in_requested(
        self,
        event: buy_in.BuyInRequested,
        destinations: Destinations,
        root: bytes,
    ) -> buy_in.SeatPlayer:
        """Handle BuyInRequested from Player domain.

        Emits SeatPlayer command to Table - Table aggregate validates seat
        availability, buy-in range, etc. PM handles rejection via @rejected.

        Args:
            event: The BuyInRequested event
            destinations: Destinations context for sequence stamping
            root: The player_root from the trigger's Cover
        """
        # player_root comes from trigger's Cover
        player_root = root
        amount = event.amount.amount if event.HasField("amount") else 0

        # Emit PM event for tracking - Table will validate
        self._apply_and_record(
            buy_in.BuyInInitiated(
                player_root=player_root,
                table_root=event.table_root,
                reservation_id=event.reservation_id,
                seat=event.seat,
                amount=poker.Currency(amount=amount, currency_code="USD"),
                phase=orch.BuyInPhase.BUY_IN_SEATING,
                initiated_at=now(),
            )
        )

        # Return SeatPlayer command to Table
        # Table aggregate validates seat availability, buy-in range, etc.
        # PM handles rejection via @rejected decorator
        return buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=event.reservation_id,
            seat=event.seat,
            amount=amount,
        )

    @output_domain("player")
    @handles(buy_in.PlayerSeated, input_domain="table")
    def handle_player_seated(
        self, event: buy_in.PlayerSeated, destinations: Destinations
    ) -> buy_in.ConfirmBuyIn:
        """Handle PlayerSeated from Table domain.

        Emits ConfirmBuyIn to Player to complete the buy-in flow.
        """
        # Emit PM completion event
        self._apply_and_record(
            buy_in.BuyInCompleted(
                player_root=event.player_root,
                table_root=b"",  # Not available in PlayerSeated
                reservation_id=event.reservation_id,
                seat=event.seat_position,
                amount=poker.Currency(amount=event.stack, currency_code="USD"),
                completed_at=now(),
            )
        )

        return buy_in.ConfirmBuyIn(reservation_id=event.reservation_id)

    @output_domain("player")
    @handles(buy_in.SeatingRejected, input_domain="table")
    def handle_seating_rejected(
        self, event: buy_in.SeatingRejected, destinations: Destinations
    ) -> buy_in.ReleaseBuyIn:
        """Handle SeatingRejected from Table domain.

        Emits ReleaseBuyIn to Player to release reserved funds.
        Table aggregate rejected the SeatPlayer command with a reason.
        """
        # Emit PM failure event
        self._apply_and_record(
            buy_in.BuyInFailed(
                player_root=event.player_root,
                table_root=b"",
                reservation_id=event.reservation_id,
                failure=orch.OrchestrationFailure(
                    code="SEATING_REJECTED",
                    message=event.reason,
                    failed_at_phase="SEATING",
                    failed_at=now(),
                ),
            )
        )

        return buy_in.ReleaseBuyIn(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

