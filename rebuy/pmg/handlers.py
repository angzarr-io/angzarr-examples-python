"""Rebuy PM handlers.

Coordinates rebuy flows across Player <-> Tournament <-> Table:
1. Player emits RebuyRequested
2. PM validates Tournament state (rebuy enabled, level cutoff, max rebuys)
3. PM validates Table state (player seated, stack threshold)
4. PM emits ProcessRebuy to Tournament
5. Tournament emits RebuyProcessed or RebuyDenied
6. PM emits AddRebuyChips to Table (on success)
7. Table emits RebuyChipsAdded
8. PM emits ConfirmRebuyFee to Player
"""

from dataclasses import dataclass, field

from angzarr_client import now
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
from angzarr_client.proto.examples import table_pb2 as table
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import RebuyState


@dataclass
class TournamentStateHelper:
    """Minimal tournament state for PM validation."""

    status: int = tournament.TournamentStatus.TOURNAMENT_STATUS_UNSPECIFIED
    rebuy_enabled: bool = False
    max_rebuys: int = 0
    rebuy_level_cutoff: int = 0
    stack_threshold: int = 0
    rebuy_chips: int = 0
    rebuy_cost: int = 0
    current_level: int = 1
    registered_players: dict[str, int] = field(default_factory=dict)  # hex -> rebuys_used


@dataclass
class TableStateHelper:
    """Minimal table state for PM validation."""

    seats: dict[int, tuple[bytes, int]] = field(
        default_factory=dict
    )  # position -> (player_root, stack)

    def find_seat_by_player(self, player_root: bytes) -> int | None:
        """Find seat position for a player."""
        for pos, (root, _) in self.seats.items():
            if root == player_root:
                return pos
        return None

    def get_stack(self, player_root: bytes) -> int | None:
        """Get player's current stack."""
        for root, stack in self.seats.values():
            if root == player_root:
                return stack
        return None


def rebuild_tournament_state(event_book: types.EventBook) -> TournamentStateHelper:
    """Rebuild tournament state from EventBook."""
    state = TournamentStateHelper()

    # Check for snapshot first
    if event_book.HasField("snapshot") and event_book.snapshot.HasField("state"):
        state_any = event_book.snapshot.state
        if state_any.type_url.endswith("TournamentState"):
            proto_state = tournament.TournamentState()
            state_any.Unpack(proto_state)
            state.status = proto_state.status
            state.current_level = proto_state.current_level
            if proto_state.HasField("rebuy_config"):
                rc = proto_state.rebuy_config
                state.rebuy_enabled = rc.enabled
                state.max_rebuys = rc.max_rebuys
                state.rebuy_level_cutoff = rc.rebuy_level_cutoff
                state.stack_threshold = rc.stack_threshold
                state.rebuy_chips = rc.rebuy_chips
                state.rebuy_cost = rc.rebuy_cost
            for player in proto_state.registered_players:
                state.registered_players[player.player_root.hex()] = player.rebuys_used

    # Apply events
    for page in event_book.pages:
        if not page.HasField("event"):
            continue
        event_any = page.event
        type_url = event_any.type_url

        if type_url.endswith("TournamentCreated"):
            evt = tournament.TournamentCreated()
            event_any.Unpack(evt)
            state.status = tournament.TournamentStatus.TOURNAMENT_CREATED
            if evt.HasField("rebuy_config"):
                rc = evt.rebuy_config
                state.rebuy_enabled = rc.enabled
                state.max_rebuys = rc.max_rebuys
                state.rebuy_level_cutoff = rc.rebuy_level_cutoff
                state.stack_threshold = rc.stack_threshold
                state.rebuy_chips = rc.rebuy_chips
                state.rebuy_cost = rc.rebuy_cost
        elif type_url.endswith("TournamentStarted"):
            state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING
        elif type_url.endswith("TournamentPlayerEnrolled"):
            evt = tournament.TournamentPlayerEnrolled()
            event_any.Unpack(evt)
            state.registered_players[evt.player_root.hex()] = 0
        elif type_url.endswith("RebuyProcessed"):
            evt = tournament.RebuyProcessed()
            event_any.Unpack(evt)
            player_hex = evt.player_root.hex()
            state.registered_players[player_hex] = evt.rebuy_count
        elif type_url.endswith("BlindLevelAdvanced"):
            evt = tournament.BlindLevelAdvanced()
            event_any.Unpack(evt)
            state.current_level = evt.level

    return state


def rebuild_table_state(event_book: types.EventBook) -> TableStateHelper:
    """Rebuild table state from EventBook."""
    state = TableStateHelper()

    for page in event_book.pages:
        if not page.HasField("event"):
            continue
        event_any = page.event
        type_url = event_any.type_url

        if type_url.endswith("PlayerJoined"):
            evt = table.PlayerJoined()
            event_any.Unpack(evt)
            state.seats[evt.seat_position] = (evt.player_root, evt.stack)
        elif type_url.endswith("PlayerSeated"):
            from angzarr_client.proto.examples import buy_in_pb2

            evt = buy_in_pb2.PlayerSeated()
            event_any.Unpack(evt)
            state.seats[evt.seat_position] = (evt.player_root, evt.stack)
        elif type_url.endswith("PlayerLeft"):
            evt = table.PlayerLeft()
            event_any.Unpack(evt)
            state.seats.pop(evt.seat_position, None)
        elif type_url.endswith("RebuyChipsAdded"):
            evt = rebuy.RebuyChipsAdded()
            event_any.Unpack(evt)
            if evt.seat in state.seats:
                player_root, _ = state.seats[evt.seat]
                state.seats[evt.seat] = (player_root, evt.new_stack)

    return state


class RebuyPM(ProcessManager[RebuyState]):
    """Rebuy process manager.

    Coordinates the rebuy flow between Player, Tournament, and Table aggregates.
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
        """RebuyRequested from Player -> need Tournament + Table state."""
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
        """RebuyProcessed from Tournament -> need Player state."""
        return [
            types.Cover(
                domain="player",
                root=types.UUID(value=event.player_root),
            ),
        ]

    @prepares(tournament.RebuyDenied)
    def prepare_rebuy_denied(
        self, event: tournament.RebuyDenied
    ) -> list[types.Cover]:
        """RebuyDenied from Tournament -> need Player state."""
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
        """RebuyChipsAdded from Table -> need Player state."""
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
        destinations: list[types.EventBook],
        root: bytes,
    ) -> tournament.ProcessRebuy | None:
        """Handle RebuyRequested from Player domain.

        Validates Tournament + Table state and emits ProcessRebuy if valid.
        """
        if len(destinations) < 2:
            self._emit_failure(
                root,
                event.tournament_root,
                event.reservation_id,
                "MISSING_DESTINATIONS",
                "Missing tournament or table destination",
            )
            return None

        player_root = root
        tournament_eb = destinations[0]
        table_eb = destinations[1]

        tournament_state = rebuild_tournament_state(tournament_eb)
        table_state = rebuild_table_state(table_eb)

        # Validate tournament is running
        if tournament_state.status != tournament.TournamentStatus.TOURNAMENT_RUNNING:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "TOURNAMENT_NOT_RUNNING",
                "Tournament is not in progress",
            )
            return None

        # Validate rebuy is enabled
        if not tournament_state.rebuy_enabled:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "REBUY_NOT_ENABLED",
                "Rebuys are not enabled for this tournament",
            )
            return None

        # Validate rebuy window (level cutoff)
        if (
            tournament_state.rebuy_level_cutoff > 0
            and tournament_state.current_level > tournament_state.rebuy_level_cutoff
        ):
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "REBUY_WINDOW_CLOSED",
                f"Rebuy window closed after level {tournament_state.rebuy_level_cutoff}",
            )
            return None

        # Validate player is registered
        player_hex = player_root.hex()
        if player_hex not in tournament_state.registered_players:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "NOT_REGISTERED",
                "Player is not registered for this tournament",
            )
            return None

        rebuys_used = tournament_state.registered_players[player_hex]

        # Validate rebuy count
        if (
            tournament_state.max_rebuys > 0
            and rebuys_used >= tournament_state.max_rebuys
        ):
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "MAX_REBUYS_REACHED",
                f"Maximum rebuys ({tournament_state.max_rebuys}) already used",
            )
            return None

        # Validate player is seated at table
        seat_pos = table_state.find_seat_by_player(player_root)
        if seat_pos is None:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "NOT_SEATED",
                "Player is not seated at the table",
            )
            return None

        if seat_pos != event.seat:
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "SEAT_MISMATCH",
                "Seat position does not match",
            )
            return None

        # Validate stack threshold
        current_stack = table_state.get_stack(player_root) or 0
        if (
            tournament_state.stack_threshold > 0
            and current_stack > tournament_state.stack_threshold
        ):
            self._emit_failure(
                player_root,
                event.tournament_root,
                event.reservation_id,
                "STACK_TOO_HIGH",
                f"Stack {current_stack} exceeds rebuy threshold {tournament_state.stack_threshold}",
            )
            return None

        # Emit PM event for tracking
        fee = event.fee.amount if event.HasField("fee") else 0
        self._apply_and_record(
            rebuy.RebuyInitiated(
                player_root=player_root,
                tournament_root=event.tournament_root,
                table_root=event.table_root,
                reservation_id=event.reservation_id,
                seat=event.seat,
                fee=poker.Currency(amount=fee, currency_code="USD"),
                chips_to_add=tournament_state.rebuy_chips,
                phase=orch.RebuyPhase.REBUY_APPROVING,
                initiated_at=now(),
            )
        )

        # Return ProcessRebuy command to Tournament
        return tournament.ProcessRebuy(
            player_root=player_root,
            reservation_id=event.reservation_id,
        )

    @output_domain("table")
    @handles(tournament.RebuyProcessed, input_domain="tournament")
    def handle_rebuy_processed(
        self,
        event: tournament.RebuyProcessed,
        destinations: list[types.EventBook],
    ) -> rebuy.AddRebuyChips:
        """Handle RebuyProcessed from Tournament domain.

        Emits AddRebuyChips to Table.
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
        destinations: list[types.EventBook],
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
        destinations: list[types.EventBook],
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

    def _emit_failure(
        self,
        player_root: bytes,
        tournament_root: bytes,
        reservation_id: bytes,
        code: str,
        message: str,
    ) -> None:
        """Record a failure event (no commands)."""
        self._apply_and_record(
            rebuy.RebuyFailed(
                player_root=player_root,
                tournament_root=tournament_root,
                reservation_id=reservation_id,
                failure=orch.OrchestrationFailure(
                    code=code,
                    message=message,
                    failed_at_phase="VALIDATION",
                    failed_at=now(),
                ),
            )
        )
