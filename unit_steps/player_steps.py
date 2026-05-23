"""Step definitions for player aggregate tests.

Uses functional handler pattern: handlers are standalone functions
that take (cmd, state, seq) and return events.

The step regexes are pinned to the business-language phrasing in
``features/example/unit/player.feature`` — verbs like "Alice deposits 500
chips" rather than implementation-level "I handle a DepositFunds command".
Implementations still drive the same underlying handlers; only the
matchers and a few combined business-assertion steps changed.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp
from player.agg.handlers import (
    handle_deposit_funds,
    handle_register_player,
    handle_release_funds,
    handle_reserve_funds,
    handle_transfer_funds,
    handle_withdraw_funds,
)
from player.agg.state import PlayerState, build_state
from reservation.agg.handlers import Reservation
from reservation.agg.state import (
    PendingBuyIn,
    PendingRebuy,
    PendingRegistration,
    ReservationState,
)
from tests.helpers import uuid_for

from angzarr_client.errors import CommandRejectedError
from angzarr_client.helpers import try_unpack, type_name_from_url
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in
from angzarr_client.proto.examples.v1 import player_pb2 as player
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import rebuy_pb2 as rebuy
from angzarr_client.proto.examples.v1 import registration_pb2 as registration

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, seq: int = 0) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")
    return types.EventPage(
        header=types.PageHeader(sequence=seq),
        event=event_any,
        created_at=make_timestamp(),
    )


def _make_event_book(pages):
    """Create an EventBook from a list of EventPages."""
    return types.EventBook(
        cover=types.Cover(
            root=types.UUID(value=b"player-123"),
            domain="player",
        ),
        pages=pages,
    )


# Common name token used by every player-centric step. ``\w+`` greedily
# captures Alice/Bot1/etc. without requiring per-step variant matchers.
_NAME = r"(?P<name>\w+)"


# --- Given steps ---


@given(rf"{_NAME} has not yet registered")
def step_given_player_not_registered(context, name):
    """Initialize with empty event history (no prior PlayerRegistered)."""
    context.events = []
    context.subject_name = name


@given(rf"{_NAME} is registered")
def step_given_player_registered(context, name):
    """Add a PlayerRegistered event to history."""
    if not hasattr(context, "events"):
        context.events = []
    context.subject_name = name

    event = player.PlayerRegistered(
        display_name=name,
        email=f"{name.lower()}@example.com",
        player_type=poker_types.PlayerType.HUMAN,
        registered_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(rf"{_NAME} has (?P<amount>-?\d+) chips?")
def step_given_player_has_chips(context, name, amount):
    """Seed bankroll via a FundsDeposited event (the player has N chips)."""
    if not hasattr(context, "events"):
        context.events = []
    context.subject_name = name

    # Calculate new balance from prior deposits/withdrawals/transfers
    prior_balance = 0
    for ep in context.events:
        for cls in (
            player.FundsDeposited,
            player.FundsWithdrawn,
            player.FundsTransferred,
        ):
            if evt := try_unpack(ep.event, cls):
                if evt.new_balance:
                    prior_balance = evt.new_balance.amount

    new_balance = prior_balance + int(amount)

    event = player.FundsDeposited(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        deposited_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    rf'{_NAME} has reserved (?P<amount>-?\d+) chips? for table "(?P<table_id>[^"]+)"'
)
def step_given_player_has_reserved(context, name, amount, table_id):
    """Seed a FundsReserved event for the named table."""
    if not hasattr(context, "events"):
        context.events = []
    context.subject_name = name

    # Calculate available balance
    total_deposited = 0
    total_reserved = 0
    for ep in context.events:
        if evt := try_unpack(ep.event, player.FundsDeposited):
            if evt.new_balance:
                total_deposited = evt.new_balance.amount
        elif evt := try_unpack(ep.event, player.FundsReserved):
            if evt.new_reserved_balance:
                total_reserved = evt.new_reserved_balance.amount

    new_reserved = total_reserved + int(amount)
    new_available = total_deposited - new_reserved

    event = player.FundsReserved(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        key=uuid_for(table_id),
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        reserved_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(rf"{_NAME} has withdrawn (?P<amount>-?\d+) chips?")
def step_given_player_has_withdrawn(context, name, amount):
    """Seed a FundsWithdrawn event."""
    if not hasattr(context, "events"):
        context.events = []
    context.subject_name = name

    prior_balance = 0
    for ep in context.events:
        for cls in (
            player.FundsDeposited,
            player.FundsWithdrawn,
            player.FundsTransferred,
        ):
            if evt := try_unpack(ep.event, cls):
                if evt.new_balance:
                    prior_balance = evt.new_balance.amount

    new_balance = prior_balance - int(amount)

    event = player.FundsWithdrawn(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        withdrawn_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    rf'{_NAME}\'s reservation for table "(?P<table_id>[^"]+)" has been released in full'
)
def step_given_reservation_released_in_full(context, name, table_id):
    """Seed a FundsReleased event for the full prior-reserved amount on the named
    table. ``in full`` means: release the exact prior reservation, leaving the
    reserved-for-table balance at zero."""
    if not hasattr(context, "events"):
        context.events = []
    context.subject_name = name

    total_deposited = 0
    total_reserved = 0
    # Amount reserved specifically for THIS table is the most recent
    # FundsReserved.amount for it minus any prior release.
    table_key = uuid_for(table_id)
    reserved_for_table = 0
    for ep in context.events:
        if evt := try_unpack(ep.event, player.FundsDeposited):
            if evt.new_balance:
                total_deposited = evt.new_balance.amount
        elif evt := try_unpack(ep.event, player.FundsWithdrawn):
            if evt.new_balance:
                total_deposited = evt.new_balance.amount
        elif evt := try_unpack(ep.event, player.FundsReserved):
            if evt.new_reserved_balance:
                total_reserved = evt.new_reserved_balance.amount
            if evt.key == table_key:
                reserved_for_table += evt.amount.amount
        elif evt := try_unpack(ep.event, player.FundsReleased):
            if evt.new_reserved_balance:
                total_reserved = evt.new_reserved_balance.amount
            if evt.key == table_key:
                reserved_for_table -= evt.amount.amount

    amount = reserved_for_table
    new_reserved = max(0, total_reserved - amount)
    new_available = total_deposited - new_reserved

    event = player.FundsReleased(
        amount=poker_types.Currency(amount=amount, currency_code="CHIPS"),
        key=table_key,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        released_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


# --- When steps ---

# Handler lookup by method name — player-only primitives. Lifecycle
# commands (buy-in / rebuy / registration Initiate/Confirm/Release) live
# on the reservation aggregate after the refactor; they route through
# ``_execute_reservation_handler`` below instead of ``_HANDLER_MAP``.
_HANDLER_MAP = {
    "register": handle_register_player,
    "deposit": handle_deposit_funds,
    "withdraw": handle_withdraw_funds,
    "reserve": handle_reserve_funds,
    "release": handle_release_funds,
    "transfer": handle_transfer_funds,
}


# Fixed player_root bytes used for unit-test scenarios. The value just has
# to be non-empty; a registered-player scenario that provides prior events
# means the reservation aggregate's sync DECISION finds state.exists=True
# and gates on bankroll. Scenarios with "no prior events" still fail the
# existence check because the fake query returns an empty EventBook.
_UNIT_PLAYER_ROOT = b"unit-test-player"


class _FakeQueryClient:
    """Stand-in for the real QueryClient in unit-test scenarios.

    The reservation aggregate calls into ``QueryClient.get_event_book`` on
    ``Initiate*`` to rebuild player state for a sync DECISION check. In
    unit tests we have no coordinator; instead we synthesize a player
    EventBook from the test's accumulated ``context.events`` (which
    already contains the PlayerRegistered / FundsDeposited / etc. the
    scenario's Given-steps added).
    """

    def __init__(self, event_pages: list):
        self._pages = event_pages

    def get_event_book(self, _query) -> types.EventBook:
        book = types.EventBook()
        for page in self._pages:
            new_page = types.EventPage()
            new_page.CopyFrom(page)
            book.pages.append(new_page)
        return book


# Applier table for rebuilding ReservationState from a replayed event
# stream. The production aggregate picks these up via ``@applies`` at
# router-build time; unit tests bypass the router and replay directly.
def _apply_buy_in_requested(
    state: ReservationState, event: buy_in.BuyInRequested
) -> None:
    state.pending_buy_ins[event.reservation_id.hex()] = PendingBuyIn(
        player_root=event.player_root,
        table_root=event.table_root,
        seat=event.seat,
        amount=event.amount.amount if event.HasField("amount") else 0,
    )


def _apply_buy_in_closed(state: ReservationState, event) -> None:
    state.pending_buy_ins.pop(event.reservation_id.hex(), None)


def _apply_registration_requested(
    state: ReservationState, event: registration.RegistrationRequested
) -> None:
    state.pending_registrations[event.reservation_id.hex()] = PendingRegistration(
        player_root=event.player_root,
        tournament_root=event.tournament_root,
        fee=event.fee.amount if event.HasField("fee") else 0,
    )


def _apply_registration_closed(state: ReservationState, event) -> None:
    state.pending_registrations.pop(event.reservation_id.hex(), None)


def _apply_rebuy_requested(
    state: ReservationState, event: rebuy.RebuyRequested
) -> None:
    state.pending_rebuys[event.reservation_id.hex()] = PendingRebuy(
        player_root=event.player_root,
        tournament_root=event.tournament_root,
        table_root=event.table_root,
        seat=event.seat,
        fee=event.fee.amount if event.HasField("fee") else 0,
    )


def _apply_rebuy_closed(state: ReservationState, event) -> None:
    state.pending_rebuys.pop(event.reservation_id.hex(), None)


_RESERVATION_APPLIERS: dict[str, tuple[type, callable]] = {
    "angzarr_client.proto.examples.v1.BuyInRequested": (
        buy_in.BuyInRequested,
        _apply_buy_in_requested,
    ),
    "angzarr_client.proto.examples.v1.BuyInConfirmed": (
        buy_in.BuyInConfirmed,
        _apply_buy_in_closed,
    ),
    "angzarr_client.proto.examples.v1.BuyInReservationReleased": (
        buy_in.BuyInReservationReleased,
        _apply_buy_in_closed,
    ),
    "angzarr_client.proto.examples.v1.RegistrationRequested": (
        registration.RegistrationRequested,
        _apply_registration_requested,
    ),
    "angzarr_client.proto.examples.v1.RegistrationFeeConfirmed": (
        registration.RegistrationFeeConfirmed,
        _apply_registration_closed,
    ),
    "angzarr_client.proto.examples.v1.RegistrationFeeReleased": (
        registration.RegistrationFeeReleased,
        _apply_registration_closed,
    ),
    "angzarr_client.proto.examples.v1.RebuyRequested": (
        rebuy.RebuyRequested,
        _apply_rebuy_requested,
    ),
    "angzarr_client.proto.examples.v1.RebuyFeeConfirmed": (
        rebuy.RebuyFeeConfirmed,
        _apply_rebuy_closed,
    ),
    "angzarr_client.proto.examples.v1.RebuyFeeReleased": (
        rebuy.RebuyFeeReleased,
        _apply_rebuy_closed,
    ),
}


def _build_reservation_state_from_events(events: list) -> ReservationState:
    state = ReservationState()
    for page in events:
        if not page.HasField("event"):
            continue
        type_name = type_name_from_url(page.event.type_url)
        entry = _RESERVATION_APPLIERS.get(type_name)
        if entry is None:
            continue
        proto_cls, applier = entry
        evt = proto_cls()
        page.event.Unpack(evt)
        applier(state, evt)
    return state


_RESERVATION_METHOD_MAP = {
    "initiate_buy_in": "on_initiate_buy_in",
    "confirm_buy_in": "on_confirm_buy_in",
    "release_buy_in": "on_release_buy_in",
    "initiate_registration": "on_initiate_registration",
    "confirm_registration": "on_confirm_registration",
    "release_registration": "on_release_registration",
    "initiate_rebuy": "on_initiate_rebuy",
    "confirm_rebuy": "on_confirm_rebuy",
    "release_rebuy": "on_release_rebuy",
}


def _id_bytes(label: str) -> bytes:
    """Deterministic 16-byte id derived from a label."""
    return uuid_for(label)


def _build_state_from_events(events: list) -> PlayerState:
    """Build player state from list of EventPages."""
    state = PlayerState()
    event_anys = [page.event for page in events if page.HasField("event")]
    return build_state(state, event_anys)


def _ensure_state(context) -> PlayerState:
    """Lazily rebuild ``context.state`` if no When-step has materialised it.

    The new feature dropped the explicit "I rebuild the player state" When in
    favour of state-only scenarios that go Given -> Then. Those Thens rebuild
    on demand so the assertion sees the current event history.
    """
    state = getattr(context, "state", None)
    if state is None:
        events = getattr(context, "events", [])
        state = _build_state_from_events(events)
        context.state = state
    return state


def _execute_handler(context, method_name: str, cmd):
    """Execute a command through either the player or reservation aggregate.

    Player-primitive commands (register/deposit/withdraw/reserve/release/
    transfer) use the functional handler map. Lifecycle commands
    (initiate_buy_in, confirm_rebuy, etc.) route through the reservation
    aggregate instance with a fake QueryClient so sync DECISION against
    player state works in the unit-test harness.
    """
    events = context.events if hasattr(context, "events") else []
    seq = len(events)

    if method_name in _RESERVATION_METHOD_MAP:
        return _execute_reservation(context, method_name, cmd, events, seq)

    state = _build_state_from_events(events)
    for seeder in getattr(context, "state_seeders", []):
        seeder(state)

    handler = _HANDLER_MAP.get(method_name)
    if not handler:
        raise ValueError(f"Unknown handler: {method_name}")

    try:
        result_event = handler(cmd, state)

        # Pack result into EventPage and EventBook
        event_any = ProtoAny()
        event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
        result_page = types.EventPage(
            header=types.PageHeader(sequence=seq),
            event=event_any,
            created_at=make_timestamp(),
        )
        result_book = _make_event_book([result_page])

        context.result = result_book
        context.error = None
        context.result_event_any = event_any

        # Store state for assertion steps (apply new event)
        context.state = build_state(state, [event_any])
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


def _stamp_scenario_cover(context, err):
    """Mirror the router's dispatch-boundary cover stamping in unit tests.

    Unit-tier steps call handlers directly so the production router never
    runs; this stamps any cover declared on the scenario onto the rejection
    so cucumber can assert on it.
    """
    if err is None or getattr(err, "cover", None) is not None:
        return
    cover = getattr(context, "command_cover", None)
    if cover is not None:
        err.cover = cover


def _execute_reservation(context, method_name: str, cmd, events: list, seq: int):
    """Drive a lifecycle command through the Reservation aggregate.

    Rebuilds ReservationState by replaying prior reservation events, wires
    a FakeQueryClient that returns the player events so sync DECISION
    checks work, calls the method directly, and folds the resulting event
    into both ``context.reservation_state`` (so pending assertions see it)
    and ``context.state`` (so legacy-named pending assertions still bind).
    """
    reservation_state = _build_reservation_state_from_events(events)
    for seeder in getattr(context, "state_seeders", []):
        seeder(reservation_state)

    query_client = _FakeQueryClient(events)
    aggregate = Reservation(query_client=query_client)

    method = getattr(aggregate, _RESERVATION_METHOD_MAP[method_name])

    try:
        result_event = method(cmd, reservation_state)

        event_any = ProtoAny()
        event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
        result_page = types.EventPage(
            header=types.PageHeader(sequence=seq),
            event=event_any,
            created_at=make_timestamp(),
        )
        result_book = _make_event_book([result_page])

        context.result = result_book
        context.error = None
        context.result_event_any = event_any

        type_name = type_name_from_url(event_any.type_url)
        entry = _RESERVATION_APPLIERS.get(type_name)
        if entry is not None:
            proto_cls, applier = entry
            evt = proto_cls()
            event_any.Unpack(evt)
            applier(reservation_state, evt)

        context.reservation_state = reservation_state
        # ``context.state`` still points at player state (built from the
        # same event stream, minus anything reservation-specific) so the
        # bankroll / available_balance assertions keep working. Pending
        # assertions below read from ``context.reservation_state``.
        context.state = _build_state_from_events(events)
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


# Registration: human and AI variants, plus the empty-input variants
@when(rf'{_NAME} registers with email "(?P<email>[^"]*)"')
def step_when_player_registers(context, name, email):
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.PlayerType.HUMAN,
    )
    _execute_handler(context, "register", cmd)


@when(rf'{_NAME} tries to register again with email "(?P<email>[^"]*)"')
def step_when_player_tries_register_again(context, name, email):
    """Re-register attempt; same RegisterPlayer command, different verb."""
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.PlayerType.HUMAN,
    )
    _execute_handler(context, "register", cmd)


@when(
    rf'{_NAME} registers as an AI with email "(?P<email>[^"]*)" '
    r'and model "(?P<model>[^"]*)"'
)
def step_when_player_registers_as_ai(context, name, email, model):
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.PlayerType.AI,
        ai_model_id=model,
    )
    _execute_handler(context, "register", cmd)


@when(rf'{_NAME} registers with an empty name and email "(?P<email>[^"]*)"')
def step_when_player_registers_empty_name(context, name, email):
    """Empty display_name triggers the input-validation rejection."""
    cmd = player.RegisterPlayer(
        display_name="",
        email=email,
        player_type=poker_types.PlayerType.HUMAN,
    )
    _execute_handler(context, "register", cmd)


@when(rf"{_NAME} registers with an empty email")
def step_when_player_registers_empty_email(context, name):
    """Empty email triggers the input-validation rejection."""
    cmd = player.RegisterPlayer(
        display_name=name,
        email="",
        player_type=poker_types.PlayerType.HUMAN,
    )
    _execute_handler(context, "register", cmd)


@when(rf"{_NAME} deposits (?P<amount>-?\d+) chips?")
def step_when_player_deposits(context, name, amount):
    cmd = player.DepositFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
    )
    _execute_handler(context, "deposit", cmd)


@when(rf"{_NAME} withdraws (?P<amount>-?\d+) chips?")
def step_when_player_withdraws(context, name, amount):
    cmd = player.WithdrawFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
    )
    _execute_handler(context, "withdraw", cmd)


@when(rf'{_NAME} reserves (?P<amount>-?\d+) chips? for table "(?P<table_id>[^"]*)"')
def step_when_player_reserves(context, name, amount, table_id):
    cmd = player.ReserveFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        key=uuid_for(table_id) if table_id else b"",
    )
    _execute_handler(context, "reserve", cmd)


@when(rf'{_NAME}\'s funds for table "(?P<table_id>[^"]+)" are released')
def step_when_player_funds_released(context, name, table_id):
    cmd = player.ReleaseFunds(
        key=uuid_for(table_id),
    )
    _execute_handler(context, "release", cmd)


@when(rf"{_NAME}'s funds for an empty table name are released")
def step_when_player_funds_released_empty_table(context, name):
    """ReleaseFunds with empty table_root for the input-validation check."""
    cmd = player.ReleaseFunds(key=b"")
    _execute_handler(context, "release", cmd)


@when(rf'{_NAME}\'s join attempt at table "(?P<table_id>[^"]*)" is rejected')
def step_when_join_table_rejected(context, name, table_id):
    """Invoke the rejection handler with a synthesized RejectionNotification.

    Mirrors the router path: a failed JoinTable arrives as a Notification
    wrapping a RejectionNotification whose ``rejected_command.cover.root``
    carries the target table_root.
    """
    from player.agg.rejected import handle_table_join_rejected

    events = context.events if hasattr(context, "events") else []
    state = _build_state_from_events(events)

    rejection = types.RejectionNotification()
    rejection.rejected_command.cover.domain = "table"
    rejection.rejected_command.cover.root.value = uuid_for(table_id)

    payload = ProtoAny()
    payload.Pack(rejection, type_url_prefix="type.googleapis.com/")
    notification = types.Notification(payload=payload)

    result_event = handle_table_join_rejected(notification, state)
    event_any = ProtoAny()
    event_any.Pack(result_event, type_url_prefix="type.googleapis.com/")
    result_page = types.EventPage(
        header=types.PageHeader(sequence=len(events)),
        event=event_any,
        created_at=make_timestamp(),
    )
    context.result = _make_event_book([result_page])
    context.result_event_any = event_any
    context.error = None


@when(
    r"(?P<amount>-?\d+) chips? are transferred to "
    rf'{_NAME} from "(?P<from_player>[^"]*)" '
    r'for hand "(?P<hand_id>[^"]*)" with reason "(?P<reason>[^"]*)"'
)
def step_when_chips_transferred(context, amount, name, from_player, hand_id, reason):
    cmd = player.TransferFunds(
        from_player_root=uuid_for(from_player),
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        hand_root=uuid_for(hand_id),
        reason=reason,
    )
    _execute_handler(context, "transfer", cmd)


# --- Then steps ---


def _expect_result_event(context, proto_cls, label: str):
    """Verify context.result holds an event of ``proto_cls`` and return the
    decoded instance. Centralises the no-error / right-type assertion that
    every business-outcome Then implies."""
    assert context.result is not None, (
        f"Expected {label} event but got error: {context.error}"
    )
    assert context.result.pages, "No event pages in result"
    evt = try_unpack(context.result_event_any, proto_cls)
    actual_type = type_name_from_url(context.result_event_any.type_url)
    assert evt is not None, f"Expected {label}, got {actual_type}"
    return evt


@then(rf"{_NAME} is registered as a human player")
def step_then_registered_as_human(context, name):
    """Business outcome: PlayerRegistered with HUMAN type and matching name."""
    evt = _expect_result_event(context, player.PlayerRegistered, "PlayerRegistered")
    assert evt.display_name == name, (
        f"Expected display_name={name!r}, got {evt.display_name!r}"
    )
    assert evt.player_type == poker_types.PlayerType.HUMAN, (
        f"Expected player_type=HUMAN, got {evt.player_type}"
    )
    # Human registration must not carry an ai_model_id.
    assert evt.ai_model_id == "", (
        f"Expected empty ai_model_id for HUMAN, got {evt.ai_model_id!r}"
    )


@then(rf'{_NAME} is registered as an AI player using the "(?P<model>[^"]+)" model')
def step_then_registered_as_ai(context, name, model):
    """Business outcome: PlayerRegistered with AI type and the named model."""
    evt = _expect_result_event(context, player.PlayerRegistered, "PlayerRegistered")
    assert evt.display_name == name, (
        f"Expected display_name={name!r}, got {evt.display_name!r}"
    )
    assert evt.player_type == poker_types.PlayerType.AI, (
        f"Expected player_type=AI, got {evt.player_type}"
    )
    assert evt.ai_model_id == model, (
        f"Expected ai_model_id={model!r}, got {evt.ai_model_id!r}"
    )


@then(rf"{_NAME}'s registration is timestamped")
def step_then_registration_timestamped(context, name):  # noqa: ARG001
    """PlayerRegistered.registered_at must be a non-zero protobuf Timestamp."""
    evt = try_unpack(context.result_event_any, player.PlayerRegistered)
    assert evt is not None, (
        f"Not a PlayerRegistered: {context.result_event_any.type_url}"
    )
    assert evt.HasField("registered_at"), "registered_at unset"
    assert evt.registered_at.seconds > 0, (
        f"Expected registered_at.seconds > 0, got {evt.registered_at.seconds}"
    )


def _new_balance_event(event_any):
    """Return whichever event currently sets ``new_balance`` (deposit, withdraw,
    or transfer). Used by the business-language balance assertion."""
    return (
        try_unpack(event_any, player.FundsDeposited)
        or try_unpack(event_any, player.FundsWithdrawn)
        or try_unpack(event_any, player.FundsTransferred)
    )


@then(
    r'the transfer is recorded as coming from "(?P<from_player>[^"]*)" '
    r'for hand "(?P<hand_id>[^"]*)" with reason "(?P<reason>[^"]*)"'
)
def step_then_transfer_audit_recorded(context, from_player, hand_id, reason):
    """Pin the audit fields on FundsTransferred: from_player_root, hand_root,
    and reason. The to_player_root binds to the registered player's id, which
    is exercised by the underlying handler but not asserted here (the new
    feature treats that as an internal detail)."""
    evt = _expect_result_event(context, player.FundsTransferred, "FundsTransferred")
    expected_from = uuid_for(from_player)
    expected_hand = uuid_for(hand_id)
    assert evt.from_player_root == expected_from, (
        f"Expected from_player_root for {from_player}, got {evt.from_player_root!r}"
    )
    assert evt.hand_root == expected_hand, (
        f"Expected hand_root for {hand_id}, got {evt.hand_root!r}"
    )
    assert evt.reason == reason, f"Expected reason={reason!r}, got {evt.reason!r}"


@then(rf"{_NAME}'s balance is (?P<balance>-?\d+)")
def step_then_player_balance_is(context, name, balance):  # noqa: ARG001
    """Business outcome: the most recent balance-changing event records the
    expected new_balance. Used after a deposit/withdraw/transfer."""
    evt = _new_balance_event(context.result_event_any)
    assert evt is not None, (
        f"No balance-bearing event to check: {context.result_event_any.type_url}"
    )
    assert evt.new_balance.amount == int(balance), (
        f"Expected new_balance={balance}, got {evt.new_balance.amount}"
    )
    assert evt.new_balance.currency_code == "CHIPS", (
        f"Expected currency_code=CHIPS, got {evt.new_balance.currency_code!r}"
    )


# Generic "the <event> is timestamped" assertion — covers
# deposit/withdrawal/reservation/release/confirmation/transfer/buy-in/registration/rebuy.
_TIMESTAMP_FIELDS = {
    "deposit": ("deposited_at", (player.FundsDeposited,)),
    "withdrawal": ("withdrawn_at", (player.FundsWithdrawn,)),
    "reservation": ("reserved_at", (player.FundsReserved,)),
    "release": (
        "released_at",
        (
            player.FundsReleased,
            buy_in.BuyInReservationReleased,
            registration.RegistrationFeeReleased,
            rebuy.RebuyFeeReleased,
        ),
    ),
    "confirmation": (
        "confirmed_at",
        (
            buy_in.BuyInConfirmed,
            registration.RegistrationFeeConfirmed,
            rebuy.RebuyFeeConfirmed,
        ),
    ),
    "transfer": ("transferred_at", (player.FundsTransferred,)),
    "buy-in": ("requested_at", (buy_in.BuyInRequested,)),
    "registration": ("requested_at", (registration.RegistrationRequested,)),
    "rebuy": ("requested_at", (rebuy.RebuyRequested,)),
}


@then(
    r"the (?P<kind>deposit|withdrawal|reservation|release|confirmation|transfer|buy-in|registration|rebuy) is timestamped"
)
def step_then_event_is_timestamped(context, kind):
    """The named business event must carry a non-zero protobuf Timestamp.

    Each event's timestamp field has a different name (``deposited_at``,
    ``withdrawn_at``, ...); the table above maps the business word to the
    field plus the event types that could carry it.
    """
    field, candidates = _TIMESTAMP_FIELDS[kind]
    evt = None
    for cls in candidates:
        if (evt := try_unpack(context.result_event_any, cls)) is not None:
            break
    assert evt is not None, (
        f"No {kind}-shaped event on the result: {context.result_event_any.type_url}"
    )
    assert evt.HasField(field), f"{type(evt).__name__} has no {field} set"
    ts = getattr(evt, field)
    assert ts.seconds > 0, (
        f"Expected {field}.seconds > 0, got {ts.seconds} (default Timestamp)"
    )


# --- Refusal (rejection) assertions ---
# Each business-language refusal collapses what used to be (status + code +
# field) into a single assertion. We re-verify all three so semantic
# coverage is preserved.


def _expect_error(context, status: str):
    assert context.error is not None, "Expected command to fail but it succeeded"
    assert getattr(context.error, "status_code", None) == status, (
        f"Expected status {status}, got {getattr(context.error, 'status_code', None)}"
    )


def _expect_error_message(context, text: str):
    assert context.error is not None, "Expected an error but got success"
    assert context.error_message == text, (
        f"Expected error message {text!r}, got {context.error_message!r}"
    )


def _expect_rejection_code(context, code: str):
    err = context.error
    assert err is not None, "Expected an error but got success"
    actual = getattr(err, "code", None)
    assert actual == code, f"Expected rejection code {code!r}, got {actual!r}"


def _expect_rejection_field(context, key: str, value: str):
    err = context.error
    details = getattr(err, "details", None) or {}
    assert str(details.get(key)) == value, (
        f"Expected rejection field {key}={value!r}, got {details.get(key)!r}"
    )


@then(rf"registration is refused because {_NAME} already exists")
def step_then_registration_refused_already_exists(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player already exists")


@then(r"registration is refused because a name is required")
def step_then_registration_refused_name_required(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_error_message(context, "display_name is required")


@then(r"registration is refused because an email is required")
def step_then_registration_refused_email_required(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_error_message(context, "email is required")


@then(rf"the deposit is refused because {_NAME} does not exist")
def step_then_deposit_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(r"the deposit is refused because the amount must be positive")
def step_then_deposit_refused_positive(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_rejection_code(context, "AMOUNT_MUST_BE_POSITIVE")


@then(rf"the withdrawal is refused because {_NAME} does not exist")
def step_then_withdrawal_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(
    rf"the withdrawal is refused because {_NAME} has (?P<avail>\d+) available "
    r"but requested (?P<req>\d+)"
)
def step_then_withdrawal_refused_insufficient(context, name, avail, req):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_rejection_code(context, "INSUFFICIENT_AVAILABLE_BALANCE")
    _expect_rejection_field(context, "requested", req)
    _expect_rejection_field(context, "available", avail)


@then(r"the withdrawal is refused because the amount must be positive")
def step_then_withdrawal_refused_positive(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_rejection_code(context, "AMOUNT_MUST_BE_POSITIVE")


@then(rf"the reservation is refused because {_NAME} does not exist")
def step_then_reservation_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(
    rf"the reservation is refused because {_NAME} has (?P<avail>\d+) available "
    r"but requested (?P<req>\d+)"
)
def step_then_reservation_refused_insufficient(context, name, avail, req):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_rejection_code(context, "INSUFFICIENT_FUNDS")
    _expect_rejection_field(context, "requested", req)
    _expect_rejection_field(context, "available", avail)


@then(
    rf"the reservation is refused because {_NAME} has already reserved for that table"
)
def step_then_reservation_refused_duplicate(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_rejection_code(context, "FUNDS_ALREADY_RESERVED_FOR_TABLE")


@then(r"the reservation is refused because the amount must be positive")
def step_then_reservation_refused_positive(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_rejection_code(context, "AMOUNT_MUST_BE_POSITIVE")


@then(rf"the release is refused because {_NAME} does not exist")
def step_then_release_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(rf"the release is refused because {_NAME} has no reservation for that table")
def step_then_release_refused_no_reservation(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_rejection_code(context, "NO_FUNDS_RESERVED_FOR_TABLE")


@then(r"the release is refused because a table is required")
def step_then_release_refused_table_required(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_error_message(context, "table_root is required")


@then(r"the release is refused because a reservation identifier is required")
def step_then_release_refused_resid_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "reservation_id is required")


@then(r"the release is refused because no buy-in with that reservation is pending")
def step_then_release_refused_no_pending_buy_in(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending buy-in with this reservation_id")


@then(
    r"the release is refused because no registration with that reservation is pending"
)
def step_then_release_refused_no_pending_registration(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending registration with this reservation_id")


@then(r"the release is refused because no rebuy with that reservation is pending")
def step_then_release_refused_no_pending_rebuy(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending rebuy with this reservation_id")


@then(rf"the transfer is refused because {_NAME} does not exist")
def step_then_transfer_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(r"the transfer is refused because the amount must be non-zero")
def step_then_transfer_refused_nonzero(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_rejection_code(context, "AMOUNT_MUST_BE_NON_ZERO")


@then(rf"the buy-in is refused because {_NAME} does not exist")
def step_then_buyin_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(rf"the buy-in is refused because {_NAME} has insufficient funds")
def step_then_buyin_refused_insufficient(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Insufficient funds")


@then(r"the buy-in is refused because the amount must be positive")
def step_then_buyin_refused_positive(context):
    _expect_error(context, "INVALID_ARGUMENT")
    _expect_error_message(context, "amount must be positive")


@then(r"the buy-in is refused because a table is required")
def step_then_buyin_refused_table_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "table_root is required")


@then(r"the confirmation is refused because no buy-in with that reservation is pending")
def step_then_confirmation_refused_no_pending_buy_in(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending buy-in with this reservation_id")


@then(
    r"the confirmation is refused because no registration with that reservation is pending"
)
def step_then_confirmation_refused_no_pending_registration(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending registration with this reservation_id")


@then(r"the confirmation is refused because no rebuy with that reservation is pending")
def step_then_confirmation_refused_no_pending_rebuy(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "No pending rebuy with this reservation_id")


@then(r"the confirmation is refused because a reservation identifier is required")
def step_then_confirmation_refused_resid_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "reservation_id is required")


@then(r"the registration is refused because a tournament is required")
def step_then_registration_refused_tournament_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "tournament_root is required")


@then(rf"the registration is refused because {_NAME} does not exist")
def step_then_registration_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


@then(r"the rebuy is refused because a tournament is required")
def step_then_rebuy_refused_tournament_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "tournament_root is required")


@then(r"the rebuy is refused because a table is required")
def step_then_rebuy_refused_table_required(context):
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "table_root is required")


@then(rf"the rebuy is refused because {_NAME} does not exist")
def step_then_rebuy_refused_no_player(context, name):  # noqa: ARG001
    _expect_error(context, "FAILED_PRECONDITION")
    _expect_error_message(context, "Player does not exist")


# --- Balance / reservation outcome assertions ---


@then(rf"{_NAME}'s total bankroll is (?P<amount>-?\d+)")
def step_then_total_bankroll_is(context, name, amount):  # noqa: ARG001
    state = _ensure_state(context)
    assert state.bankroll == int(amount), (
        f"Expected bankroll={amount}, got {state.bankroll}"
    )


@then(rf"{_NAME}'s reserved funds are (?P<amount>-?\d+)")
def step_then_reserved_funds_are(context, name, amount):  # noqa: ARG001
    state = _ensure_state(context)
    assert state.reserved_funds == int(amount), (
        f"Expected reserved_funds={amount}, got {state.reserved_funds}"
    )


@then(rf"{_NAME}'s available balance is (?P<amount>-?\d+)")
def step_then_available_balance_is(context, name, amount):  # noqa: ARG001
    """Check the player's available balance. Prefers the event's
    ``new_available_balance`` if a reserve/release event was just produced
    (the new feature inlines this assertion right after such commands),
    otherwise falls back to the rebuilt PlayerState."""
    if context.result is not None:
        event_any = getattr(context, "result_event_any", None)
        if event_any is not None:
            evt = try_unpack(event_any, player.FundsReserved) or try_unpack(
                event_any, player.FundsReleased
            )
            if evt is not None and evt.HasField("new_available_balance"):
                assert evt.new_available_balance.amount == int(amount), (
                    f"Expected new_available_balance={amount}, "
                    f"got {evt.new_available_balance.amount}"
                )
                return
    state = _ensure_state(context)
    assert state.available_balance == int(amount), (
        f"Expected available_balance={amount}, got {state.available_balance}"
    )


@then(rf'{_NAME} has reserved (?P<amount>\d+) chips? for table "(?P<table_id>[^"]+)"')
def step_then_player_has_reserved_now(context, name, amount, table_id):  # noqa: ARG001
    """Assert on the most recent FundsReserved event: it must carry the
    expected amount and bind to the named table."""
    evt = _expect_result_event(context, player.FundsReserved, "FundsReserved")
    assert evt.amount.amount == int(amount), (
        f"Expected amount={amount}, got {evt.amount.amount}"
    )
    assert evt.amount.currency_code == "CHIPS", (
        f"Expected currency_code=CHIPS, got {evt.amount.currency_code!r}"
    )
    expected_key = uuid_for(table_id)
    assert evt.key == expected_key, f"Expected key for {table_id}, got {evt.key!r}"


@then(rf"(?P<amount>\d+) chips? are returned to {_NAME}'s available balance")
def step_then_chips_returned(context, amount, name):  # noqa: ARG001
    """Assert a FundsReleased event with the expected ``amount`` field. This
    is the compensation-flow business assertion."""
    evt = _expect_result_event(context, player.FundsReleased, "FundsReleased")
    assert evt.amount.amount == int(amount), (
        f"Expected released amount={amount}, got {evt.amount.amount}"
    )
    assert evt.amount.currency_code == "CHIPS", (
        f"Expected currency_code=CHIPS, got {evt.amount.currency_code!r}"
    )


@then(rf"no chips are returned to {_NAME}'s available balance")
def step_then_no_chips_returned(context, name):  # noqa: ARG001
    """No-op release: FundsReleased emitted, amount must be zero."""
    evt = _expect_result_event(context, player.FundsReleased, "FundsReleased")
    assert evt.amount.amount == 0, (
        f"Expected released amount=0 for no-op, got {evt.amount.amount}"
    )


@then(rf'{_NAME} no longer has a reservation for table "(?P<table_id>[^"]+)"')
def step_then_no_reservation_for_table(context, name, table_id):  # noqa: ARG001
    """After a successful release, the player's reserved-for-table balance
    should be 0 for that table. Check on the FundsReleased event."""
    evt = try_unpack(context.result_event_any, player.FundsReleased)
    assert evt is not None, (
        f"Not a FundsReleased event: {context.result_event_any.type_url}"
    )
    expected_key = uuid_for(table_id)
    assert evt.key == expected_key, (
        f"Released reservation key did not match {table_id}: got {evt.key!r}"
    )


# =============================================================================
# Orchestration Command Step Definitions (buy-in / registration / rebuy)
# =============================================================================
# These commands live on the Reservation aggregate and emit orchestration
# events that the PMs (BuyInOrchestrator, etc.) react to. PM-level
# orchestration behaviour is in orchestration_steps.py.


# --- Helpers to seed PM-side compensating events ---


def _append_funds_reserved(context, table_root: bytes, amount: int) -> None:
    """Simulate the PM hop: a reservation request triggers ReserveFunds on the
    player aggregate, emitting FundsReserved. Without this, rebuild_player_state
    sees no change to reserved_funds / available_balance after a reservation."""
    state = _build_state_from_events(context.events)
    new_reserved = state.reserved_funds + amount
    new_available = state.bankroll - new_reserved
    event = player.FundsReserved(
        amount=poker_types.Currency(amount=amount, currency_code="CHIPS"),
        key=table_root,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        reserved_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


def _append_funds_deducted(
    context, key: bytes, reservation_id: bytes, amount: int
) -> None:
    """Simulate the PM hop: a *Confirmed event triggers DeductReservedFunds on
    the player aggregate, emitting FundsDeducted."""
    state = _build_state_from_events(context.events)
    new_reserved = state.reserved_funds - amount
    new_balance = state.bankroll - amount
    event = player.FundsDeducted(
        amount=poker_types.Currency(amount=amount, currency_code="CHIPS"),
        key=key,
        reservation_id=reservation_id,
        new_balance=poker_types.Currency(amount=new_balance, currency_code="CHIPS"),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        deducted_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


# --- Given: pending orchestration state via event replay ---


@given(
    rf'{_NAME} has a pending buy-in "(?P<res>[^"]+)" for seat (?P<seat>\d+) '
    r'at table "(?P<tbl>[^"]+)" for (?P<amt>\d+) chips?'
)
def step_given_pending_buy_in(context, name, res, seat, tbl, amt):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    event = buy_in.BuyInRequested(
        reservation_id=_id_bytes(res),
        table_root=_id_bytes(tbl),
        seat=int(seat),
        amount=poker_types.Currency(amount=int(amt), currency_code="CHIPS"),
        requested_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    _append_funds_reserved(context, _id_bytes(tbl), int(amt))


@given(
    rf'{_NAME} has a pending tournament registration "(?P<res>[^"]+)" '
    r'for tournament "(?P<trn>[^"]+)" with fee (?P<fee>\d+)'
)
def step_given_pending_registration(context, name, res, trn, fee):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    event = registration.RegistrationRequested(
        reservation_id=_id_bytes(res),
        tournament_root=_id_bytes(trn),
        fee=poker_types.Currency(amount=int(fee), currency_code="CHIPS"),
        requested_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    # Registration reserves against tournament_root (via the `key` field in the
    # PM-issued ReserveFunds). PlayerState keys by whatever bytes it sees in
    # FundsReserved.key.
    _append_funds_reserved(context, _id_bytes(trn), int(fee))


@given(
    rf'{_NAME} has a pending rebuy "(?P<res>[^"]+)" for tournament "(?P<trn>[^"]+)" '
    r'at table "(?P<tbl>[^"]+)" seat (?P<seat>\d+) with fee (?P<fee>\d+) '
    r"and (?P<chips>\d+) chips?"
)
def step_given_pending_rebuy(context, name, res, trn, tbl, seat, fee, chips):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    event = rebuy.RebuyRequested(
        reservation_id=_id_bytes(res),
        tournament_root=_id_bytes(trn),
        table_root=_id_bytes(tbl),
        seat=int(seat),
        fee=poker_types.Currency(amount=int(fee), currency_code="CHIPS"),
        requested_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    _append_funds_reserved(context, _id_bytes(tbl), int(fee))

    # PendingRebuy.chips_to_add isn't on the RebuyRequested event — seed it
    # directly on the materialized state after replay.
    hex_key = _id_bytes(res).hex()
    chips_val = int(chips)

    def _seed(state):
        pending = state.pending_rebuys.get(hex_key)
        if pending is not None:
            pending.chips_to_add = chips_val

    if not hasattr(context, "state_seeders"):
        context.state_seeders = []
    context.state_seeders.append(_seed)


def _pending_buy_in_state(context, res: str):
    state = _build_reservation_state_from_events(context.events)
    return state.pending_buy_ins.get(_id_bytes(res).hex())


def _pending_registration_state(context, res: str):
    state = _build_reservation_state_from_events(context.events)
    return state.pending_registrations.get(_id_bytes(res).hex())


def _pending_rebuy_state(context, res: str):
    state = _build_reservation_state_from_events(context.events)
    return state.pending_rebuys.get(_id_bytes(res).hex())


@given(rf'{_NAME}\'s buy-in "(?P<res>[^"]+)" has been confirmed')
def step_given_buy_in_confirmed(context, name, res):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    pending = _pending_buy_in_state(context, res)  # snapshot BEFORE appending Confirmed
    event = buy_in.BuyInConfirmed(
        reservation_id=_id_bytes(res),
        # The original step accepted a table label; the new phrasing infers it
        # from the prior pending entry. Fall back to the pending's table_root.
        table_root=pending.table_root if pending is not None else b"",
        confirmed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    if pending is not None:
        _append_funds_deducted(
            context, pending.table_root, _id_bytes(res), pending.amount
        )


@given(rf'{_NAME}\'s tournament registration "(?P<res>[^"]+)" has been confirmed')
def step_given_registration_confirmed(context, name, res):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    pending = _pending_registration_state(context, res)
    event = registration.RegistrationFeeConfirmed(
        reservation_id=_id_bytes(res),
        tournament_root=pending.tournament_root if pending is not None else b"",
        confirmed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    if pending is not None:
        _append_funds_deducted(
            context, pending.tournament_root, _id_bytes(res), pending.fee
        )


@given(rf'{_NAME}\'s rebuy "(?P<res>[^"]+)" has been confirmed')
def step_given_rebuy_confirmed(context, name, res):  # noqa: ARG001
    if not hasattr(context, "events"):
        context.events = []
    pending = _pending_rebuy_state(context, res)
    event = rebuy.RebuyFeeConfirmed(
        reservation_id=_id_bytes(res),
        confirmed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    if pending is not None:
        _append_funds_deducted(context, pending.table_root, _id_bytes(res), pending.fee)


# --- When: orchestration commands ---


@when(
    rf"{_NAME} initiates a buy-in for seat (?P<seat>-?\d+) "
    r'at table "(?P<tbl>[^"]+)" for (?P<amt>-?\d+) chips?'
)
def step_when_initiate_buy_in(context, name, seat, tbl, amt):  # noqa: ARG001
    cmd = buy_in.InitiateBuyIn(
        table_root=_id_bytes(tbl),
        seat=int(seat),
        amount=poker_types.Currency(amount=int(amt), currency_code="CHIPS"),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_buy_in", cmd)


@when(
    rf"{_NAME} initiates a buy-in for seat (?P<seat>-?\d+) "
    r"at an empty table name for (?P<amt>-?\d+) chips?"
)
def step_when_initiate_buy_in_empty_table(context, name, seat, amt):  # noqa: ARG001
    cmd = buy_in.InitiateBuyIn(
        table_root=b"",
        seat=int(seat),
        amount=poker_types.Currency(amount=int(amt), currency_code="CHIPS"),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_buy_in", cmd)


@when(rf'{_NAME}\'s buy-in "(?P<res>[^"]+)" is confirmed')
def step_when_confirm_buy_in(context, name, res):  # noqa: ARG001
    cmd = buy_in.ConfirmBuyIn(reservation_id=_id_bytes(res))
    _execute_handler(context, "confirm_buy_in", cmd)


@when(rf"{_NAME}'s buy-in with an empty reservation identifier is confirmed")
def step_when_confirm_buy_in_empty(context, name):  # noqa: ARG001
    cmd = buy_in.ConfirmBuyIn(reservation_id=b"")
    _execute_handler(context, "confirm_buy_in", cmd)


@when(rf'{_NAME}\'s buy-in "(?P<res>[^"]+)" is released because of "(?P<reason>[^"]*)"')
def step_when_release_buy_in(context, name, res, reason):  # noqa: ARG001
    cmd = buy_in.ReleaseBuyIn(reservation_id=_id_bytes(res), reason=reason)
    _execute_handler(context, "release_buy_in", cmd)


@when(
    rf"{_NAME}'s buy-in with an empty reservation identifier is released "
    r'because of "(?P<reason>[^"]*)"'
)
def step_when_release_buy_in_empty(context, name, reason):  # noqa: ARG001
    cmd = buy_in.ReleaseBuyIn(reservation_id=b"", reason=reason)
    _execute_handler(context, "release_buy_in", cmd)


@when(rf'{_NAME} initiates registration for tournament "(?P<trn>[^"]+)"')
def step_when_initiate_registration(context, name, trn):  # noqa: ARG001
    cmd = registration.InitiateTournamentRegistration(
        tournament_root=_id_bytes(trn),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_registration", cmd)


@when(rf"{_NAME} initiates registration for an empty tournament name")
def step_when_initiate_registration_empty(context, name):  # noqa: ARG001
    cmd = registration.InitiateTournamentRegistration(
        tournament_root=b"",
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_registration", cmd)


@when(rf'{_NAME}\'s tournament registration "(?P<res>[^"]+)" is confirmed')
def step_when_confirm_registration(context, name, res):  # noqa: ARG001
    cmd = registration.ConfirmRegistrationFee(reservation_id=_id_bytes(res))
    _execute_handler(context, "confirm_registration", cmd)


@when(
    rf"{_NAME}'s tournament registration with an empty reservation identifier "
    r"is confirmed"
)
def step_when_confirm_registration_empty(context, name):  # noqa: ARG001
    cmd = registration.ConfirmRegistrationFee(reservation_id=b"")
    _execute_handler(context, "confirm_registration", cmd)


@when(
    rf'{_NAME}\'s tournament registration "(?P<res>[^"]+)" '
    r'is released because of "(?P<reason>[^"]*)"'
)
def step_when_release_registration(context, name, res, reason):  # noqa: ARG001
    cmd = registration.ReleaseRegistrationFee(
        reservation_id=_id_bytes(res), reason=reason
    )
    _execute_handler(context, "release_registration", cmd)


@when(
    rf"{_NAME}'s tournament registration with an empty reservation identifier "
    r'is released because of "(?P<reason>[^"]*)"'
)
def step_when_release_registration_empty(context, name, reason):  # noqa: ARG001
    cmd = registration.ReleaseRegistrationFee(reservation_id=b"", reason=reason)
    _execute_handler(context, "release_registration", cmd)


@when(
    rf'{_NAME} initiates a rebuy for tournament "(?P<trn>[^"]+)" '
    r'at table "(?P<tbl>[^"]+)" seat (?P<seat>-?\d+)'
)
def step_when_initiate_rebuy(context, name, trn, tbl, seat):  # noqa: ARG001
    cmd = rebuy.InitiateRebuy(
        tournament_root=_id_bytes(trn),
        table_root=_id_bytes(tbl),
        seat=int(seat),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_rebuy", cmd)


@when(
    rf"{_NAME} initiates a rebuy for an empty tournament name "
    r'at table "(?P<tbl>[^"]+)" seat (?P<seat>-?\d+)'
)
def step_when_initiate_rebuy_empty_trn(context, name, tbl, seat):  # noqa: ARG001
    cmd = rebuy.InitiateRebuy(
        tournament_root=b"",
        table_root=_id_bytes(tbl),
        seat=int(seat),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_rebuy", cmd)


@when(
    rf'{_NAME} initiates a rebuy for tournament "(?P<trn>[^"]+)" '
    r"at an empty table name seat (?P<seat>-?\d+)"
)
def step_when_initiate_rebuy_empty_tbl(context, name, trn, seat):  # noqa: ARG001
    cmd = rebuy.InitiateRebuy(
        tournament_root=_id_bytes(trn),
        table_root=b"",
        seat=int(seat),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_rebuy", cmd)


@when(rf'{_NAME}\'s rebuy "(?P<res>[^"]+)" is confirmed')
def step_when_confirm_rebuy(context, name, res):  # noqa: ARG001
    cmd = rebuy.ConfirmRebuyFee(reservation_id=_id_bytes(res))
    _execute_handler(context, "confirm_rebuy", cmd)


@when(rf"{_NAME}'s rebuy with an empty reservation identifier is confirmed")
def step_when_confirm_rebuy_empty(context, name):  # noqa: ARG001
    cmd = rebuy.ConfirmRebuyFee(reservation_id=b"")
    _execute_handler(context, "confirm_rebuy", cmd)


@when(rf'{_NAME}\'s rebuy "(?P<res>[^"]+)" is released because of "(?P<reason>[^"]*)"')
def step_when_release_rebuy(context, name, res, reason):  # noqa: ARG001
    cmd = rebuy.ReleaseRebuyFee(reservation_id=_id_bytes(res), reason=reason)
    _execute_handler(context, "release_rebuy", cmd)


@when(
    rf"{_NAME}'s rebuy with an empty reservation identifier is released "
    r'because of "(?P<reason>[^"]*)"'
)
def step_when_release_rebuy_empty(context, name, reason):  # noqa: ARG001
    cmd = rebuy.ReleaseRebuyFee(reservation_id=b"", reason=reason)
    _execute_handler(context, "release_rebuy", cmd)


# --- Then: orchestration event field assertions ---


def _orch_event(event_any):
    for cls in (
        buy_in.BuyInRequested,
        buy_in.BuyInConfirmed,
        buy_in.BuyInReservationReleased,
        registration.RegistrationRequested,
        registration.RegistrationFeeConfirmed,
        registration.RegistrationFeeReleased,
        rebuy.RebuyRequested,
        rebuy.RebuyFeeConfirmed,
        rebuy.RebuyFeeReleased,
    ):
        if evt := try_unpack(event_any, cls):
            return evt
    return None


@then(
    r"a pending buy-in is recorded for seat (?P<seat>-?\d+) "
    r'at table "(?P<tbl>[^"]+)" for (?P<amt>-?\d+) chips?'
)
def step_then_pending_buy_in_recorded(context, seat, tbl, amt):
    """Business assertion on the just-emitted BuyInRequested: table, seat,
    and amount must all match what the scenario asserts."""
    evt = _expect_result_event(context, buy_in.BuyInRequested, "BuyInRequested")
    assert evt.table_root == _id_bytes(tbl), (
        f"Expected table_root for {tbl}, got {evt.table_root!r}"
    )
    assert evt.seat == int(seat), f"Expected seat={seat}, got {evt.seat}"
    assert evt.amount.amount == int(amt), (
        f"Expected amount={amt}, got {evt.amount.amount}"
    )
    assert evt.amount.currency_code == "CHIPS", (
        f"Expected currency_code=CHIPS, got {evt.amount.currency_code!r}"
    )


@then(r"the buy-in carries a generated reservation identifier")
def step_then_buyin_has_reservation_id(context):
    evt = try_unpack(context.result_event_any, buy_in.BuyInRequested)
    assert evt is not None, "Not a BuyInRequested event"
    assert evt.reservation_id, "reservation_id was empty"


@then(
    rf'{_NAME}\'s buy-in "(?P<res>[^"]+)" is confirmed for seat (?P<seat>-?\d+) '
    r'at table "(?P<tbl>[^"]+)" for (?P<amt>-?\d+) chips?'
)
def step_then_buyin_confirmed_for(context, name, res, seat, tbl, amt):  # noqa: ARG001
    """Pin every field on BuyInConfirmed: reservation_id, table, seat, amount."""
    evt = _expect_result_event(context, buy_in.BuyInConfirmed, "BuyInConfirmed")
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.table_root == _id_bytes(tbl), (
        f"Expected table_root for {tbl}, got {evt.table_root!r}"
    )
    assert evt.seat == int(seat), f"Expected seat={seat}, got {evt.seat}"
    assert evt.amount.amount == int(amt), (
        f"Expected amount={amt}, got {evt.amount.amount}"
    )


@then(
    rf'{_NAME}\'s buy-in "(?P<res>[^"]+)" is released with reason "(?P<reason>[^"]*)"'
)
def step_then_buyin_released_with_reason(context, name, res, reason):  # noqa: ARG001
    evt = _expect_result_event(
        context, buy_in.BuyInReservationReleased, "BuyInReservationReleased"
    )
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.reason == reason, f"Expected reason={reason!r}, got {evt.reason!r}"


@then(r'a pending tournament registration is recorded for tournament "(?P<trn>[^"]+)"')
def step_then_pending_registration_recorded(context, trn):
    evt = _expect_result_event(
        context, registration.RegistrationRequested, "RegistrationRequested"
    )
    assert evt.tournament_root == _id_bytes(trn), (
        f"Expected tournament_root for {trn}, got {evt.tournament_root!r}"
    )


@then(r"the registration carries a generated reservation identifier")
def step_then_registration_has_reservation_id(context):
    evt = try_unpack(context.result_event_any, registration.RegistrationRequested)
    assert evt is not None, "Not a RegistrationRequested event"
    assert evt.reservation_id, "reservation_id was empty"


@then(
    rf'{_NAME}\'s tournament registration "(?P<res>[^"]+)" is confirmed for '
    r'tournament "(?P<trn>[^"]+)" with fee (?P<fee>-?\d+)'
)
def step_then_registration_confirmed_for(context, name, res, trn, fee):  # noqa: ARG001
    evt = _expect_result_event(
        context,
        registration.RegistrationFeeConfirmed,
        "RegistrationFeeConfirmed",
    )
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.tournament_root == _id_bytes(trn), (
        f"Expected tournament_root for {trn}, got {evt.tournament_root!r}"
    )
    assert evt.fee.amount == int(fee), f"Expected fee={fee}, got {evt.fee.amount}"


@then(
    rf'{_NAME}\'s tournament registration "(?P<res>[^"]+)" '
    r'is released with reason "(?P<reason>[^"]*)"'
)
def step_then_registration_released_with_reason(context, name, res, reason):  # noqa: ARG001
    evt = _expect_result_event(
        context,
        registration.RegistrationFeeReleased,
        "RegistrationFeeReleased",
    )
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.reason == reason, f"Expected reason={reason!r}, got {evt.reason!r}"


@then(
    r'a pending rebuy is recorded for tournament "(?P<trn>[^"]+)" '
    r'at table "(?P<tbl>[^"]+)" seat (?P<seat>-?\d+)'
)
def step_then_pending_rebuy_recorded(context, trn, tbl, seat):
    evt = _expect_result_event(context, rebuy.RebuyRequested, "RebuyRequested")
    assert evt.tournament_root == _id_bytes(trn), (
        f"Expected tournament_root for {trn}, got {evt.tournament_root!r}"
    )
    assert evt.table_root == _id_bytes(tbl), (
        f"Expected table_root for {tbl}, got {evt.table_root!r}"
    )
    assert evt.seat == int(seat), f"Expected seat={seat}, got {evt.seat}"


@then(r"the rebuy carries a generated reservation identifier")
def step_then_rebuy_has_reservation_id(context):
    evt = try_unpack(context.result_event_any, rebuy.RebuyRequested)
    assert evt is not None, "Not a RebuyRequested event"
    assert evt.reservation_id, "reservation_id was empty"


@then(
    rf'{_NAME}\'s rebuy "(?P<res>[^"]+)" is confirmed for '
    r'tournament "(?P<trn>[^"]+)" with fee (?P<fee>-?\d+)'
)
def step_then_rebuy_confirmed_for(context, name, res, trn, fee):  # noqa: ARG001
    """The Player side's RebuyFeeConfirmed carries the fee; chips_added is
    populated later by the tournament aggregate, so we pin it to 0 here."""
    evt = _expect_result_event(context, rebuy.RebuyFeeConfirmed, "RebuyFeeConfirmed")
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.tournament_root == _id_bytes(trn), (
        f"Expected tournament_root for {trn}, got {evt.tournament_root!r}"
    )
    assert evt.fee.amount == int(fee), f"Expected fee={fee}, got {evt.fee.amount}"
    assert evt.chips_added == 0, (
        f"Expected chips_added=0 at Player-side confirm, got {evt.chips_added}"
    )


@then(rf'{_NAME}\'s rebuy "(?P<res>[^"]+)" is released with reason "(?P<reason>[^"]*)"')
def step_then_rebuy_released_with_reason(context, name, res, reason):  # noqa: ARG001
    evt = _expect_result_event(context, rebuy.RebuyFeeReleased, "RebuyFeeReleased")
    assert evt.reservation_id == _id_bytes(res), (
        f"Expected reservation_id for {res}, got {evt.reservation_id!r}"
    )
    assert evt.reason == reason, f"Expected reason={reason!r}, got {evt.reason!r}"


# --- Then: pending-state assertions ---


def _reservation_state(context) -> ReservationState:
    """Pending-state assertions read the reservation aggregate's state.

    Before the reservation refactor these asserted against ``context.state``
    (a PlayerState with pending dicts). That fused ownership is gone; the
    pending records now live on the reservation aggregate, so the
    assertions go through ``context.reservation_state`` — populated by
    ``_execute_reservation`` after each lifecycle command — or rebuilt
    from the event history when only Givens have run.
    """
    reservation_state = getattr(context, "reservation_state", None)
    if reservation_state is None:
        events = getattr(context, "events", [])
        reservation_state = _build_reservation_state_from_events(events)
    return reservation_state


@then(rf'{_NAME} has no pending buy-in "(?P<res>[^"]+)"')
def step_then_no_pending_buy_in(context, name, res):  # noqa: ARG001
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_buy_ins


@then(rf'{_NAME} has no pending tournament registration "(?P<res>[^"]+)"')
def step_then_no_pending_registration(context, name, res):  # noqa: ARG001
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_registrations


@then(rf'{_NAME} has no pending rebuy "(?P<res>[^"]+)"')
def step_then_no_pending_rebuy(context, name, res):  # noqa: ARG001
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_rebuys
