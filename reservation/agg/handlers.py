"""Reservation aggregate — owns the lifecycle records for buy-in / rebuy /
tournament-registration flows.

Three command shapes per flavor: ``Initiate*`` opens a pending record and
emits a ``*Requested`` event; ``Confirm*`` closes the pending record on
success and emits a ``*Confirmed`` event; ``Release*`` closes on failure
and emits a ``*Released`` event. The downstream PM (``reservation/pmg``)
translates each event into the matching player primitive (ReserveFunds /
DeductReservedFunds / ReleaseFunds).

Sync DECISION on financials: ``Initiate*`` handlers call into the player
aggregate via ``QueryClient`` to check ``available_balance`` *before*
emitting the request event. The check is best-effort (race against
concurrent player commands is possible); the player primitive will
re-validate on its own command. This honors the user-facing semantic
that an ``Initiate*`` that fails immediately means "you can't afford
this", same as today.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import (
    QueryClient,
    applies,
    command_handler,
    handles,
    now,
)
from angzarr_client.errors import CommandRejectedError
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration

# Reuse the player aggregate's state model + appliers to compute
# available_balance from a player event book during sync DECISION.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from player.agg.state import PlayerState, build_state  # noqa: E402

from .state import (  # noqa: E402
    PendingBuyIn,
    PendingRebuy,
    PendingRegistration,
    ReservationState,
)


def _new_reservation_id() -> bytes:
    return uuid.uuid4().bytes


def _amount(currency) -> int:
    """Extract the amount from a Currency message; 0 if unset."""
    return currency.amount if currency is not None else 0


def _player_state(query_client: QueryClient | None, player_root: bytes) -> PlayerState:
    """Sync DECISION: fetch the player's event book and rebuild state.

    Returns a fresh empty PlayerState if no client is wired (test paths)
    so handler logic stays exercisable without a live coordinator.
    """
    state = PlayerState()
    if query_client is None or not player_root:
        return state
    try:
        cover = types.Cover(domain="player", root=types.UUID(value=player_root))
        book = query_client.get_event_book(types.Query(cover=cover))
    except Exception:
        return state
    events = [page.event for page in book.pages if page.HasField("event")]
    return build_state(state, events)


_APPLIER_REGISTRY: list[tuple[type, str]] = []


@command_handler(domain="reservation", state=ReservationState)
class Reservation:
    """Reservation aggregate. Pending records for the three lifecycle flavors."""

    def __init__(
        self,
        query_client: QueryClient | None = None,
        event_book: types.EventBook | None = None,
    ) -> None:
        self._state = ReservationState()
        self._events = types.EventBook()
        self._query_client = query_client
        if event_book is not None:
            for page in event_book.pages:
                new_page = types.EventPage()
                new_page.CopyFrom(page)
                self._events.pages.append(new_page)
                if page.HasField("event"):
                    self._apply_any(page.event, self._state)

    # --- Internal plumbing (test-path replay) ---

    def _get_state(self) -> ReservationState:
        return self._state

    def event_book(self) -> types.EventBook:
        return self._events

    def _apply_any(self, event_any: ProtoAny, state: ReservationState) -> None:
        for event_type, method_name in _APPLIER_REGISTRY:
            expected = f"type.googleapis.com/{event_type.DESCRIPTOR.full_name}"
            if event_any.type_url == expected:
                evt = event_type()
                event_any.Unpack(evt)
                getattr(self, method_name)(state, evt)
                return

    # =========================================================================
    # Buy-in
    # =========================================================================

    @handles(buy_in.InitiateBuyIn)
    def on_initiate_buy_in(
        self, cmd: buy_in.InitiateBuyIn, state: ReservationState
    ) -> buy_in.BuyInRequested:
        """Open a buy-in pending record after sync DECISION on player funds."""
        if not cmd.player_root:
            raise CommandRejectedError("player_root is required")
        if not cmd.table_root:
            raise CommandRejectedError("table_root is required")
        amount = _amount(cmd.amount) if cmd.HasField("amount") else 0
        if amount <= 0:
            raise CommandRejectedError.invalid_argument("amount must be positive")

        # Sync DECISION against player aggregate
        player_state = _player_state(self._query_client, cmd.player_root)
        if not player_state.exists:
            raise CommandRejectedError("Player does not exist")
        if amount > player_state.available_balance:
            raise CommandRejectedError("Insufficient funds")

        return buy_in.BuyInRequested(
            reservation_id=_new_reservation_id(),
            player_root=cmd.player_root,
            table_root=cmd.table_root,
            seat=cmd.seat,
            amount=cmd.amount,
            requested_at=now(),
        )

    @handles(buy_in.ConfirmBuyIn)
    def on_confirm_buy_in(
        self, cmd: buy_in.ConfirmBuyIn, state: ReservationState
    ) -> buy_in.BuyInConfirmed:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_buy_ins.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError("No pending buy-in with this reservation_id")
        return buy_in.BuyInConfirmed(
            reservation_id=cmd.reservation_id,
            player_root=pending.player_root,
            table_root=pending.table_root,
            seat=pending.seat,
            amount=poker_types.Currency(amount=pending.amount, currency_code="CHIPS"),
            confirmed_at=now(),
        )

    @handles(buy_in.ReleaseBuyIn)
    def on_release_buy_in(
        self, cmd: buy_in.ReleaseBuyIn, state: ReservationState
    ) -> buy_in.BuyInReservationReleased:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_buy_ins.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError("No pending buy-in with this reservation_id")
        return buy_in.BuyInReservationReleased(
            reservation_id=cmd.reservation_id,
            reason=cmd.reason,
            released_at=now(),
            player_root=pending.player_root,
            table_root=pending.table_root,
            amount=poker_types.Currency(amount=pending.amount, currency_code="CHIPS"),
        )

    @applies(buy_in.BuyInRequested)
    def apply_buy_in_requested(
        self, state: ReservationState, event: buy_in.BuyInRequested
    ) -> None:
        state.pending_buy_ins[event.reservation_id.hex()] = PendingBuyIn(
            player_root=event.player_root,
            table_root=event.table_root,
            seat=event.seat,
            amount=_amount(event.amount) if event.HasField("amount") else 0,
        )

    @applies(buy_in.BuyInConfirmed)
    def apply_buy_in_confirmed(
        self, state: ReservationState, event: buy_in.BuyInConfirmed
    ) -> None:
        state.pending_buy_ins.pop(event.reservation_id.hex(), None)

    @applies(buy_in.BuyInReservationReleased)
    def apply_buy_in_released(
        self, state: ReservationState, event: buy_in.BuyInReservationReleased
    ) -> None:
        state.pending_buy_ins.pop(event.reservation_id.hex(), None)

    # =========================================================================
    # Tournament registration
    # =========================================================================

    @handles(registration.InitiateTournamentRegistration)
    def on_initiate_registration(
        self,
        cmd: registration.InitiateTournamentRegistration,
        state: ReservationState,
    ) -> registration.RegistrationRequested:
        """Fee comes from Tournament state via the PM later. We can't sync
        DECISION on funds here because the fee isn't known yet."""
        if not cmd.player_root:
            raise CommandRejectedError("player_root is required")
        if not cmd.tournament_root:
            raise CommandRejectedError("tournament_root is required")

        player_state = _player_state(self._query_client, cmd.player_root)
        if not player_state.exists:
            raise CommandRejectedError("Player does not exist")

        return registration.RegistrationRequested(
            reservation_id=_new_reservation_id(),
            player_root=cmd.player_root,
            tournament_root=cmd.tournament_root,
            requested_at=now(),
        )

    @handles(registration.ConfirmRegistrationFee)
    def on_confirm_registration(
        self,
        cmd: registration.ConfirmRegistrationFee,
        state: ReservationState,
    ) -> registration.RegistrationFeeConfirmed:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_registrations.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError(
                "No pending registration with this reservation_id"
            )
        return registration.RegistrationFeeConfirmed(
            reservation_id=cmd.reservation_id,
            player_root=pending.player_root,
            tournament_root=pending.tournament_root,
            fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
            confirmed_at=now(),
        )

    @handles(registration.ReleaseRegistrationFee)
    def on_release_registration(
        self,
        cmd: registration.ReleaseRegistrationFee,
        state: ReservationState,
    ) -> registration.RegistrationFeeReleased:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_registrations.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError(
                "No pending registration with this reservation_id"
            )
        return registration.RegistrationFeeReleased(
            reservation_id=cmd.reservation_id,
            reason=cmd.reason,
            released_at=now(),
            player_root=pending.player_root,
            tournament_root=pending.tournament_root,
            fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
        )

    @applies(registration.RegistrationRequested)
    def apply_registration_requested(
        self,
        state: ReservationState,
        event: registration.RegistrationRequested,
    ) -> None:
        state.pending_registrations[event.reservation_id.hex()] = PendingRegistration(
            player_root=event.player_root,
            tournament_root=event.tournament_root,
            fee=_amount(event.fee) if event.HasField("fee") else 0,
        )

    @applies(registration.RegistrationFeeConfirmed)
    def apply_registration_confirmed(
        self,
        state: ReservationState,
        event: registration.RegistrationFeeConfirmed,
    ) -> None:
        state.pending_registrations.pop(event.reservation_id.hex(), None)

    @applies(registration.RegistrationFeeReleased)
    def apply_registration_released(
        self,
        state: ReservationState,
        event: registration.RegistrationFeeReleased,
    ) -> None:
        state.pending_registrations.pop(event.reservation_id.hex(), None)

    # =========================================================================
    # Rebuy
    # =========================================================================

    @handles(rebuy.InitiateRebuy)
    def on_initiate_rebuy(
        self, cmd: rebuy.InitiateRebuy, state: ReservationState
    ) -> rebuy.RebuyRequested:
        """Fee comes from Tournament state via the PM later."""
        if not cmd.player_root:
            raise CommandRejectedError("player_root is required")
        if not cmd.tournament_root:
            raise CommandRejectedError("tournament_root is required")
        if not cmd.table_root:
            raise CommandRejectedError("table_root is required")

        player_state = _player_state(self._query_client, cmd.player_root)
        if not player_state.exists:
            raise CommandRejectedError("Player does not exist")

        return rebuy.RebuyRequested(
            reservation_id=_new_reservation_id(),
            player_root=cmd.player_root,
            tournament_root=cmd.tournament_root,
            table_root=cmd.table_root,
            seat=cmd.seat,
            requested_at=now(),
        )

    @handles(rebuy.ConfirmRebuyFee)
    def on_confirm_rebuy(
        self, cmd: rebuy.ConfirmRebuyFee, state: ReservationState
    ) -> rebuy.RebuyFeeConfirmed:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_rebuys.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError("No pending rebuy with this reservation_id")
        return rebuy.RebuyFeeConfirmed(
            reservation_id=cmd.reservation_id,
            player_root=pending.player_root,
            tournament_root=pending.tournament_root,
            table_root=pending.table_root,
            fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
            chips_added=0,  # Set by PM after Tournament processes the rebuy
            confirmed_at=now(),
        )

    @handles(rebuy.ReleaseRebuyFee)
    def on_release_rebuy(
        self, cmd: rebuy.ReleaseRebuyFee, state: ReservationState
    ) -> rebuy.RebuyFeeReleased:
        if not cmd.reservation_id:
            raise CommandRejectedError("reservation_id is required")
        pending = state.pending_rebuys.get(cmd.reservation_id.hex())
        if pending is None:
            raise CommandRejectedError("No pending rebuy with this reservation_id")
        return rebuy.RebuyFeeReleased(
            reservation_id=cmd.reservation_id,
            reason=cmd.reason,
            released_at=now(),
            player_root=pending.player_root,
            table_root=pending.table_root,
            fee=poker_types.Currency(amount=pending.fee, currency_code="CHIPS"),
        )

    @applies(rebuy.RebuyRequested)
    def apply_rebuy_requested(
        self, state: ReservationState, event: rebuy.RebuyRequested
    ) -> None:
        state.pending_rebuys[event.reservation_id.hex()] = PendingRebuy(
            player_root=event.player_root,
            tournament_root=event.tournament_root,
            table_root=event.table_root,
            seat=event.seat,
            fee=_amount(event.fee) if event.HasField("fee") else 0,
        )

    @applies(rebuy.RebuyFeeConfirmed)
    def apply_rebuy_confirmed(
        self, state: ReservationState, event: rebuy.RebuyFeeConfirmed
    ) -> None:
        state.pending_rebuys.pop(event.reservation_id.hex(), None)

    @applies(rebuy.RebuyFeeReleased)
    def apply_rebuy_released(
        self, state: ReservationState, event: rebuy.RebuyFeeReleased
    ) -> None:
        state.pending_rebuys.pop(event.reservation_id.hex(), None)
