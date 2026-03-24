"""Buy-in PM handlers.

Coordinates buy-in flows across Player <-> Table:
1. Player emits BuyInRequested
2. PM checks Table state (seat availability, buy-in range)
3. PM emits SeatPlayer command to Table
4. Table emits PlayerSeated or SeatingRejected
5. PM emits ConfirmBuyIn or ReleaseBuyIn to Player
"""

from dataclasses import dataclass

from angzarr_client import now
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
from angzarr_client.proto.examples import table_pb2 as table

from state import BuyInState


@dataclass
class TableStateHelper:
    """Minimal table state for PM validation."""

    table_id: str = ""
    table_name: str = ""
    min_buy_in: int = 0
    max_buy_in: int = 0
    max_players: int = 0
    seats: dict[int, bytes] = None  # position -> player_root

    def __post_init__(self):
        if self.seats is None:
            self.seats = {}

    def find_seat_by_player(self, player_root: bytes) -> int | None:
        """Find seat position for a player."""
        for pos, root in self.seats.items():
            if root == player_root:
                return pos
        return None

    def next_available_seat(self) -> int | None:
        """Find next available seat."""
        for i in range(self.max_players):
            if i not in self.seats:
                return i
        return None


def rebuild_table_state(event_book: types.EventBook) -> TableStateHelper:
    """Rebuild table state from EventBook."""
    state = TableStateHelper()

    # Check for snapshot first
    if event_book.HasField("snapshot") and event_book.snapshot.HasField("state"):
        state_any = event_book.snapshot.state
        if state_any.type_url.endswith("TableState"):
            proto_state = table.TableState()
            state_any.Unpack(proto_state)
            state.table_id = proto_state.table_id
            state.table_name = proto_state.table_name
            state.min_buy_in = proto_state.min_buy_in
            state.max_buy_in = proto_state.max_buy_in
            state.max_players = proto_state.max_players
            for seat in proto_state.seats:
                state.seats[seat.position] = seat.player_root

    # Apply events
    for page in event_book.pages:
        if not page.HasField("event"):
            continue
        event_any = page.event
        type_url = event_any.type_url

        if type_url.endswith("TableCreated"):
            evt = table.TableCreated()
            event_any.Unpack(evt)
            state.table_id = f"table_{evt.table_name}"
            state.table_name = evt.table_name
            state.min_buy_in = evt.min_buy_in
            state.max_buy_in = evt.max_buy_in
            state.max_players = evt.max_players
        elif type_url.endswith("PlayerJoined"):
            evt = table.PlayerJoined()
            event_any.Unpack(evt)
            state.seats[evt.seat_position] = evt.player_root
        elif type_url.endswith("PlayerSeated"):
            evt = buy_in.PlayerSeated()
            event_any.Unpack(evt)
            state.seats[evt.seat_position] = evt.player_root
        elif type_url.endswith("PlayerLeft"):
            evt = table.PlayerLeft()
            event_any.Unpack(evt)
            state.seats.pop(evt.seat_position, None)

    return state


class BuyInPM(ProcessManager[BuyInState]):
    """Buy-in process manager.

    Coordinates the buy-in flow between Player and Table aggregates.
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
        destinations: list[types.EventBook],
        root: bytes,
    ) -> buy_in.SeatPlayer | None:
        """Handle BuyInRequested from Player domain.

        Validates Table state and emits SeatPlayer command if valid.

        Args:
            event: The BuyInRequested event
            destinations: Fetched aggregate states (Table in this case)
            root: The player_root from the trigger's Cover
        """
        if not destinations:
            self._emit_failure(
                root,
                event.table_root,
                event.reservation_id,
                "MISSING_TABLE",
                "Table destination not found",
            )
            return None

        table_event_book = destinations[0]
        table_state = rebuild_table_state(table_event_book)

        # player_root comes from trigger's Cover
        player_root = root

        # Validate buy-in amount
        amount = event.amount.amount if event.HasField("amount") else 0
        if amount < table_state.min_buy_in:
            self._emit_failure(
                player_root,
                event.table_root,
                event.reservation_id,
                "INVALID_AMOUNT",
                f"Buy-in must be at least {table_state.min_buy_in}",
            )
            return None

        if amount > table_state.max_buy_in:
            self._emit_failure(
                player_root,
                event.table_root,
                event.reservation_id,
                "INVALID_AMOUNT",
                f"Buy-in must be at most {table_state.max_buy_in}",
            )
            return None

        # Validate seat availability
        requested_seat = event.seat
        if requested_seat >= 0:
            # Specific seat requested
            if requested_seat >= table_state.max_players:
                self._emit_failure(
                    player_root,
                    event.table_root,
                    event.reservation_id,
                    "INVALID_SEAT",
                    f"Seat {requested_seat} does not exist",
                )
                return None
            if requested_seat in table_state.seats:
                self._emit_failure(
                    player_root,
                    event.table_root,
                    event.reservation_id,
                    "SEAT_OCCUPIED",
                    f"Seat {requested_seat} is already occupied",
                )
                return None
        else:
            # Any seat - check if table has space
            if table_state.next_available_seat() is None:
                self._emit_failure(
                    player_root,
                    event.table_root,
                    event.reservation_id,
                    "TABLE_FULL",
                    "Table is full",
                )
                return None

        # Check if player already seated
        if table_state.find_seat_by_player(player_root) is not None:
            self._emit_failure(
                player_root,
                event.table_root,
                event.reservation_id,
                "ALREADY_SEATED",
                "Player is already seated at this table",
            )
            return None

        # Emit PM event for tracking
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
        return buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=event.reservation_id,
            seat=event.seat,
            amount=amount,
        )

    @output_domain("player")
    @handles(buy_in.PlayerSeated, input_domain="table")
    def handle_player_seated(
        self, event: buy_in.PlayerSeated, destinations: list[types.EventBook]
    ) -> buy_in.ConfirmBuyIn:
        """Handle PlayerSeated from Table domain.

        Emits ConfirmBuyIn to Player.
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
        self, event: buy_in.SeatingRejected, destinations: list[types.EventBook]
    ) -> buy_in.ReleaseBuyIn:
        """Handle SeatingRejected from Table domain.

        Emits ReleaseBuyIn to Player to release reserved funds.
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

    def _emit_failure(
        self,
        player_root: bytes,
        table_root: bytes,
        reservation_id: bytes,
        code: str,
        message: str,
    ) -> None:
        """Record a failure event (no commands)."""
        self._apply_and_record(
            buy_in.BuyInFailed(
                player_root=player_root,
                table_root=table_root,
                reservation_id=reservation_id,
                failure=orch.OrchestrationFailure(
                    code=code,
                    message=message,
                    failed_at_phase="VALIDATION",
                    failed_at=now(),
                ),
            )
        )
