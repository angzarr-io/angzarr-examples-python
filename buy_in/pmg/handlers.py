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
        """Handle BuyInRequested from Player domain."""
        player_root = (
            source_cover.root.value if source_cover is not None else state.player_root
        )
        amount = event.amount.amount if event.HasField("amount") else 0

        initiated = buy_in.BuyInInitiated(
            player_root=player_root,
            table_root=event.table_root,
            reservation_id=event.reservation_id,
            seat=event.seat,
            amount=poker.Currency(amount=amount, currency_code="USD"),
            phase=orch.BuyInPhase.BUY_IN_SEATING,
            initiated_at=now(),
        )

        seat_cmd = buy_in.SeatPlayer(
            player_root=player_root,
            reservation_id=event.reservation_id,
            seat=event.seat,
            amount=amount,
        )

        dest_seq = 0
        if destinations and destinations.sequence_for("table") is not None:
            dest_seq = destinations.sequence_for("table") or 0
        cmd_book = _command_book("table", event.table_root, seat_cmd, dest_seq)

        pe_book = _event_book("buyin", event.reservation_id, initiated)

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
