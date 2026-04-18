"""Rebuy PM handlers.

Coordinates rebuy flows across Player <-> Tournament <-> Table.
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
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import tournament_pb2 as tournament

from state import RebuyState


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


def _seq(destinations: Destinations | None, domain: str) -> int:
    if destinations is None:
        return 0
    seq = destinations.sequence_for(domain)
    return seq if seq is not None else 0


@process_manager(
    name="pmg-rebuy",
    pm_domain="rebuy",
    sources=["player", "tournament", "table"],
    targets=["tournament", "table", "player"],
    state=RebuyState,
)
class RebuyPM:
    """Rebuy process manager.

    Coordinates the rebuy flow between Player, Tournament, and Table aggregates.
    """

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

    # --- Event handlers ---

    # TODO(pm-source-context): new Router API doesn't expose source cover root
    # to handlers. Callers must seed state.player_root (or include player_root
    # in the event payload) when testing handle_rebuy_requested.
    @handles(rebuy.RebuyRequested)
    def handle_rebuy_requested(
        self,
        event: rebuy.RebuyRequested,
        state: RebuyState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle RebuyRequested from Player domain."""
        player_root = state.player_root
        fee = event.fee.amount if event.HasField("fee") else 0

        initiated = rebuy.RebuyInitiated(
            player_root=player_root,
            tournament_root=event.tournament_root,
            table_root=event.table_root,
            reservation_id=event.reservation_id,
            seat=event.seat,
            fee=poker.Currency(amount=fee, currency_code="USD"),
            chips_to_add=0,
            phase=orch.RebuyPhase.REBUY_APPROVING,
            initiated_at=now(),
        )

        process_rebuy = tournament.ProcessRebuy(
            player_root=player_root,
            reservation_id=event.reservation_id,
        )

        cmd_book = _command_book(
            "tournament",
            event.tournament_root,
            process_rebuy,
            _seq(destinations, "tournament"),
        )

        pe_book = _event_book("rebuy", event.reservation_id, initiated)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(tournament.RebuyProcessed)
    def handle_rebuy_processed(
        self,
        event: tournament.RebuyProcessed,
        state: RebuyState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle RebuyProcessed from Tournament domain."""
        add_chips = rebuy.AddRebuyChips(
            player_root=event.player_root,
            reservation_id=event.reservation_id,
            seat=state.seat,
            amount=event.chips_added,
        )

        cmd_book = _command_book(
            "table", state.table_root, add_chips, _seq(destinations, "table")
        )

        return ProcessManagerResponse(commands=[cmd_book])

    @handles(tournament.RebuyDenied)
    def handle_rebuy_denied(
        self,
        event: tournament.RebuyDenied,
        state: RebuyState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle RebuyDenied from Tournament domain."""
        failed = rebuy.RebuyFailed(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            reservation_id=event.reservation_id,
            failure=orch.OrchestrationFailure(
                code="REBUY_DENIED",
                message=event.reason,
                failed_at_phase="APPROVING",
                failed_at=now(),
            ),
        )

        release = rebuy.ReleaseRebuyFee(
            reservation_id=event.reservation_id,
            reason=event.reason,
        )

        cmd_book = _command_book(
            "player", event.player_root, release, _seq(destinations, "player")
        )

        pe_book = _event_book("rebuy", event.reservation_id, failed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )

    @handles(rebuy.RebuyChipsAdded)
    def handle_chips_added(
        self,
        event: rebuy.RebuyChipsAdded,
        state: RebuyState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """Handle RebuyChipsAdded from Table domain."""
        completed = rebuy.RebuyCompleted(
            player_root=event.player_root,
            tournament_root=state.tournament_root,
            table_root=state.table_root,
            reservation_id=event.reservation_id,
            fee=poker.Currency(amount=state.fee, currency_code="USD"),
            chips_added=event.amount,
            completed_at=now(),
        )

        confirm = rebuy.ConfirmRebuyFee(reservation_id=event.reservation_id)

        cmd_book = _command_book(
            "player", event.player_root, confirm, _seq(destinations, "player")
        )

        pe_book = _event_book("rebuy", event.reservation_id, completed)

        return ProcessManagerResponse(
            commands=[cmd_book],
            process_events=pe_book,
        )
