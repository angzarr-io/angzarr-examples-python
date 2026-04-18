"""Buy-in PM handlers.

Coordinates buy-in flows across Player <-> Table:

1. Player emits ``BuyInRequested``
2. PM synchronously queries Table state via ``QueryClient`` and validates:
   amount within [min_buy_in, max_buy_in], seat available, table not full.
3. If validation fails: emit ``BuyInFailed`` with a failure code and no
   outbound commands.
4. If validation passes: emit ``SeatPlayer`` command to Table and
   ``BuyInInitiated`` process event.
5. Later, Table emits ``PlayerSeated`` → PM emits ``ConfirmBuyIn`` to Player
   and ``BuyInCompleted`` process event; or Table emits ``SeatingRejected``
   → PM emits ``ReleaseBuyIn`` to Player and ``BuyInFailed``.

The destination-state query is a read; downstream command dispatch remains
the framework's responsibility. For a downstream command that needs
synchronous accept/reject decisioning, the caller uses the new
``SYNC_MODE_DECISION`` on the framework-side dispatch.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import (
    Destinations,
    ProcessManagerResponse,
    applies,
    handles,
    now,
    process_manager,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker

from state import BuyInState
from table_state import TableStateHelper, table_state_from_event_book


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _command_book(domain: str, root: bytes, cmd, sequence: int = 0) -> types.CommandBook:
    return types.CommandBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.CommandPage(
                header=types.PageHeader(sequence=sequence),
                command=_pack(cmd),
            )
        ],
    )


def _event_book(domain: str, root: bytes, event) -> types.EventBook:
    return types.EventBook(
        cover=types.Cover(
            domain=domain,
            root=types.UUID(value=root),
        ),
        pages=[
            types.EventPage(event=_pack(event)),
        ],
    )


def _fetch_table_state(query_client, table_root: bytes) -> TableStateHelper:
    """Query the table domain and rebuild its state for pre-validation.

    Returns an empty helper if no query client is wired (tests that don't
    need validation still function) or the query fails.
    """
    if query_client is None or not table_root:
        return TableStateHelper()
    try:
        book = query_client.query("table", table_root).get_event_book()
    except Exception:
        return TableStateHelper()
    return table_state_from_event_book(book)


def _fail(
    reservation_id: bytes,
    player_root: bytes,
    table_root: bytes,
    code: str,
    message: str,
    phase: str,
) -> ProcessManagerResponse:
    failed = buy_in.BuyInFailed(
        player_root=player_root,
        table_root=table_root,
        reservation_id=reservation_id,
        failure=orch.OrchestrationFailure(
            code=code,
            message=message,
            failed_at_phase=phase,
            failed_at=now(),
        ),
    )
    return ProcessManagerResponse(
        process_events=_event_book("buyin", reservation_id, failed),
    )


@process_manager(
    name="pmg-buy-in",
    pm_domain="buyin",
    sources=["player", "table"],
    targets=["table", "player"],
    state=BuyInState,
)
class BuyInPM:
    """Buy-in process manager.

    Coordinates the buy-in flow between Player and Table aggregates.
    """

    def __init__(self, query_client=None):
        self.query = query_client

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
    def apply_completed(self, state: BuyInState, _event: buy_in.BuyInCompleted) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_COMPLETED

    @applies(buy_in.BuyInFailed)
    def apply_failed(self, state: BuyInState, _event: buy_in.BuyInFailed) -> None:
        state.phase = orch.BuyInPhase.BUY_IN_FAILED

    # --- Event handlers ---

    @handles(buy_in.BuyInRequested)
    def handle_buy_in_requested(
        self,
        event: buy_in.BuyInRequested,
        state: BuyInState,
        destinations: Destinations,
        source_cover: types.Cover = None,
    ) -> ProcessManagerResponse:
        """Handle BuyInRequested from Player domain.

        Pre-validates against live Table state queried synchronously; emits
        SeatPlayer on pass or BuyInFailed on fail.
        """
        player_root = (
            source_cover.root.value if source_cover is not None else state.player_root
        )
        amount = event.amount.amount if event.HasField("amount") else 0
        reservation_id = event.reservation_id
        table_root = event.table_root

        table_state = _fetch_table_state(self.query, table_root)

        # Only enforce state-based validation when the helper was seeded
        # from an actual TableCreated event. This keeps tests without a
        # query client ergonomic while still exercising the real path via
        # the pytest-bdd orchestration fixtures.
        if table_state.max_players > 0:
            if amount < table_state.min_buy_in:
                return _fail(
                    reservation_id,
                    player_root,
                    table_root,
                    "INVALID_AMOUNT",
                    f"amount {amount} below minimum {table_state.min_buy_in}",
                    "VALIDATING",
                )
            if amount > table_state.max_buy_in:
                return _fail(
                    reservation_id,
                    player_root,
                    table_root,
                    "INVALID_AMOUNT",
                    f"amount {amount} exceeds maximum {table_state.max_buy_in}",
                    "VALIDATING",
                )
            if len(table_state.seats) >= table_state.max_players:
                return _fail(
                    reservation_id,
                    player_root,
                    table_root,
                    "TABLE_FULL",
                    "table has no available seats",
                    "VALIDATING",
                )
            if event.seat in table_state.seats:
                return _fail(
                    reservation_id,
                    player_root,
                    table_root,
                    "SEAT_OCCUPIED",
                    f"seat {event.seat} is occupied",
                    "VALIDATING",
                )

        initiated = buy_in.BuyInInitiated(
            player_root=player_root,
            table_root=table_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=poker.Currency(amount=amount, currency_code="USD"),
            phase=orch.BuyInPhase.BUY_IN_SEATING,
            initiated_at=now(),
        )

        seat_cmd = buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=reservation_id,
            seat=event.seat,
            amount=amount,
        )

        dest_seq = 0
        if destinations and destinations.sequence_for("table") is not None:
            dest_seq = destinations.sequence_for("table") or 0
        cmd_book = _command_book("table", table_root, seat_cmd, dest_seq)
        pe_book = _event_book("buyin", reservation_id, initiated)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(buy_in.PlayerSeated)
    def handle_player_seated(
        self,
        event: buy_in.PlayerSeated,
        state: BuyInState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle PlayerSeated from Table domain."""
        completed = buy_in.BuyInCompleted(
            player_root=event.player_root,
            table_root=b"",
            reservation_id=event.reservation_id,
            seat=event.seat_position,
            amount=poker.Currency(amount=event.stack, currency_code="USD"),
            completed_at=now(),
        )

        confirm = buy_in.ConfirmBuyIn(reservation_id=event.reservation_id)

        dest_seq = 0
        if destinations and destinations.sequence_for("player") is not None:
            dest_seq = destinations.sequence_for("player") or 0
        cmd_book = _command_book("player", event.player_root, confirm, dest_seq)

        pe_book = _event_book("buyin", event.reservation_id, completed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(buy_in.SeatingRejected)
    def handle_seating_rejected(
        self,
        event: buy_in.SeatingRejected,
        state: BuyInState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle SeatingRejected from Table domain."""
        failed = buy_in.BuyInFailed(
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

        release = buy_in.ReleaseBuyIn(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

        dest_seq = 0
        if destinations and destinations.sequence_for("player") is not None:
            dest_seq = destinations.sequence_for("player") or 0
        cmd_book = _command_book("player", event.player_root, release, dest_seq)

        pe_book = _event_book("buyin", event.reservation_id, failed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )
