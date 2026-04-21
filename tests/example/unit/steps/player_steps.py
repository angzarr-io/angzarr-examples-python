"""Step definitions for player aggregate tests.

Uses functional handler pattern: handlers are standalone functions
that take (cmd, state, seq) and return events.
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

from angzarr_client.errors import CommandRejectedError
from angzarr_client.helpers import try_unpack, type_name_from_url
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import poker_types_pb2 as poker_types
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration

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


# --- Given steps ---


@given(r"no prior events for the player aggregate")
def step_given_no_prior_events(context):
    """Initialize with empty event history."""
    context.events = []


@given(r'a PlayerRegistered event for "(?P<name>[^"]+)"')
def step_given_player_registered(context, name):
    """Add a PlayerRegistered event to history."""
    if not hasattr(context, "events"):
        context.events = []

    event = player.PlayerRegistered(
        display_name=name,
        email=f"{name.lower()}@example.com",
        player_type=poker_types.PlayerType.HUMAN,
        registered_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r"a FundsDeposited event with amount (?P<amount>-?\d+)")
def step_given_funds_deposited(context, amount):
    """Add a FundsDeposited event to history."""
    if not hasattr(context, "events"):
        context.events = []

    # Calculate new balance from prior deposits
    prior_balance = 0
    for ep in context.events:
        if evt := try_unpack(ep.event, player.FundsDeposited):
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
    r'a FundsReserved event with amount (?P<amount>-?\d+) for table "(?P<table_id>[^"]+)"'
)
def step_given_funds_reserved(context, amount, table_id):
    """Add a FundsReserved event to history."""
    if not hasattr(context, "events"):
        context.events = []

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
        key=table_id.encode("utf-8"),
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        reserved_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(r"a FundsWithdrawn event with amount (?P<amount>-?\d+)")
def step_given_funds_withdrawn(context, amount):
    """Add a FundsWithdrawn event to history."""
    if not hasattr(context, "events"):
        context.events = []

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
    r'a FundsReleased event for table "(?P<table_id>[^"]+)" with amount (?P<amount>-?\d+)'
)
def step_given_funds_released(context, table_id, amount):
    """Add a FundsReleased event to history."""
    if not hasattr(context, "events"):
        context.events = []

    total_deposited = 0
    total_reserved = 0
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
        elif evt := try_unpack(ep.event, player.FundsReleased):
            if evt.new_reserved_balance:
                total_reserved = evt.new_reserved_balance.amount

    new_reserved = max(0, total_reserved - int(amount))
    new_available = total_deposited - new_reserved

    event = player.FundsReleased(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        key=table_id.encode("utf-8"),
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
    "angzarr_client.proto.examples.BuyInRequested": (
        buy_in.BuyInRequested,
        _apply_buy_in_requested,
    ),
    "angzarr_client.proto.examples.BuyInConfirmed": (
        buy_in.BuyInConfirmed,
        _apply_buy_in_closed,
    ),
    "angzarr_client.proto.examples.BuyInReservationReleased": (
        buy_in.BuyInReservationReleased,
        _apply_buy_in_closed,
    ),
    "angzarr_client.proto.examples.RegistrationRequested": (
        registration.RegistrationRequested,
        _apply_registration_requested,
    ),
    "angzarr_client.proto.examples.RegistrationFeeConfirmed": (
        registration.RegistrationFeeConfirmed,
        _apply_registration_closed,
    ),
    "angzarr_client.proto.examples.RegistrationFeeReleased": (
        registration.RegistrationFeeReleased,
        _apply_registration_closed,
    ),
    "angzarr_client.proto.examples.RebuyRequested": (
        rebuy.RebuyRequested,
        _apply_rebuy_requested,
    ),
    "angzarr_client.proto.examples.RebuyFeeConfirmed": (
        rebuy.RebuyFeeConfirmed,
        _apply_rebuy_closed,
    ),
    "angzarr_client.proto.examples.RebuyFeeReleased": (
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
    raw = label.encode("utf-8")
    return (raw + b"\x00" * 16)[:16]


def _build_state_from_events(events: list) -> PlayerState:
    """Build player state from list of EventPages."""
    state = PlayerState()
    event_anys = [page.event for page in events if page.HasField("event")]
    return build_state(state, event_anys)


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
        context.result = None
        context.error = e
        context.error_message = str(e)


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
        context.result = None
        context.error = e
        context.error_message = str(e)


@when(
    r'I handle a RegisterPlayer command with name "(?P<name>[^"]*)" and email "(?P<email>[^"]*)"'
)
def step_when_register_player(context, name, email):
    """Handle RegisterPlayer command."""
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.PlayerType.HUMAN,
    )
    _execute_handler(context, "register", cmd)


@when(
    r'I handle a RegisterPlayer command with name "(?P<name>[^"]*)" and email "(?P<email>[^"]*)" as AI'
)
def step_when_register_player_ai(context, name, email):
    """Handle RegisterPlayer command for AI player."""
    cmd = player.RegisterPlayer(
        display_name=name,
        email=email,
        player_type=poker_types.PlayerType.AI,
        ai_model_id="gpt-4",
    )
    _execute_handler(context, "register", cmd)


@when(r"I handle a DepositFunds command with amount (?P<amount>-?\d+)")
def step_when_deposit_funds(context, amount):
    """Handle DepositFunds command."""
    cmd = player.DepositFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
    )
    _execute_handler(context, "deposit", cmd)


@when(r"I handle a WithdrawFunds command with amount (?P<amount>-?\d+)")
def step_when_withdraw_funds(context, amount):
    """Handle WithdrawFunds command."""
    cmd = player.WithdrawFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
    )
    _execute_handler(context, "withdraw", cmd)


@when(
    r'I handle a ReserveFunds command with amount (?P<amount>-?\d+) for table "(?P<table_id>[^"]*)"'
)
def step_when_reserve_funds(context, amount, table_id):
    """Handle ReserveFunds command."""
    cmd = player.ReserveFunds(
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        key=table_id.encode("utf-8") if table_id else b"",
    )
    _execute_handler(context, "reserve", cmd)


@when(r'I handle a ReleaseFunds command for table "(?P<table_id>[^"]*)"')
def step_when_release_funds(context, table_id):
    """Handle ReleaseFunds command."""
    cmd = player.ReleaseFunds(
        key=table_id.encode("utf-8"),
    )
    _execute_handler(context, "release", cmd)


@when(r'I handle a JoinTable rejection notification for table "(?P<table_id>[^"]*)"')
def step_when_join_table_rejection(context, table_id):
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
    rejection.rejected_command.cover.root.value = table_id.encode("utf-8")

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
    r'I handle a TransferFunds command from "(?P<from_player>[^"]*)" '
    r'with amount (?P<amount>-?\d+) for hand "(?P<hand_id>[^"]*)" '
    r'reason "(?P<reason>[^"]*)"'
)
def step_when_transfer_funds(context, from_player, amount, hand_id, reason):
    """Handle TransferFunds command."""
    cmd = player.TransferFunds(
        from_player_root=from_player.encode("utf-8"),
        amount=poker_types.Currency(amount=int(amount), currency_code="CHIPS"),
        hand_root=hand_id.encode("utf-8"),
        reason=reason,
    )
    _execute_handler(context, "transfer", cmd)


@when(r"I rebuild the player state")
def step_when_rebuild_state(context):
    """Rebuild player state from events."""
    context.state = _build_state_from_events(context.events)


# --- Then steps ---


@then(r"the result is a (?P<event_type>\w+) event")
def step_then_result_is_event(context, event_type):
    """Verify the result event type."""
    assert (
        context.result is not None
    ), f"Expected {event_type} event but got error: {context.error}"
    assert context.result.pages, "No event pages in result"
    event_any = context.result.pages[0].event
    actual_type = type_name_from_url(event_any.type_url)
    assert actual_type == event_type, f"Expected {event_type} but got {actual_type}"


@then(r'the player event has display_name "(?P<name>[^"]+)"')
def step_then_event_has_display_name(context, name):
    """Verify the event display_name field."""
    event = player.PlayerRegistered()
    context.result_event_any.Unpack(event)
    assert (
        event.display_name == name
    ), f"Expected display_name={name}, got {event.display_name}"


@then(r'the player event has email "(?P<email>[^"]*)"')
def step_then_event_has_email(context, email):
    evt = try_unpack(context.result_event_any, player.PlayerRegistered)
    assert (
        evt is not None
    ), f"Not a PlayerRegistered: {context.result_event_any.type_url}"
    assert evt.email == email, f"Expected email={email!r}, got {evt.email!r}"


@then(r'the player event has ai_model_id "(?P<model>[^"]*)"')
def step_then_event_has_ai_model_id(context, model):
    evt = try_unpack(context.result_event_any, player.PlayerRegistered)
    assert (
        evt is not None
    ), f"Not a PlayerRegistered: {context.result_event_any.type_url}"
    assert (
        evt.ai_model_id == model
    ), f"Expected ai_model_id={model!r}, got {evt.ai_model_id!r}"


@then(r'the player event has player_type "(?P<ptype>[^"]+)"')
def step_then_event_has_player_type(context, ptype):
    """Verify the event player_type field."""
    event = player.PlayerRegistered()
    context.result_event_any.Unpack(event)
    expected_type = getattr(poker_types.PlayerType, ptype)
    assert (
        event.player_type == expected_type
    ), f"Expected player_type={ptype}, got {event.player_type}"


@then(r"the player event has amount (?P<amount>-?\d+)")
def step_then_event_has_amount(context, amount):
    """Verify the event amount field (value + currency_code)."""
    event_any = context.result_event_any

    # Try different event types that have amount field
    event = (
        try_unpack(event_any, player.FundsDeposited)
        or try_unpack(event_any, player.FundsWithdrawn)
        or try_unpack(event_any, player.FundsReserved)
        or try_unpack(event_any, player.FundsReleased)
        or try_unpack(event_any, player.FundsTransferred)
    )
    if event is None:
        raise AssertionError(f"Unknown event type: {event_any.type_url}")

    assert event.amount.amount == int(
        amount
    ), f"Expected amount={amount}, got {event.amount.amount}"
    assert (
        event.amount.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {event.amount.currency_code!r}"


@then(r"the player event has new_balance (?P<balance>-?\d+)")
def step_then_event_has_new_balance(context, balance):
    """Verify the event new_balance field (value + currency_code)."""
    event_any = context.result_event_any

    # Try different event types that have new_balance field
    event = (
        try_unpack(event_any, player.FundsDeposited)
        or try_unpack(event_any, player.FundsWithdrawn)
        or try_unpack(event_any, player.FundsTransferred)
    )
    if event is None:
        raise AssertionError(
            f"Unknown event type for new_balance: {event_any.type_url}"
        )

    assert event.new_balance.amount == int(
        balance
    ), f"Expected new_balance={balance}, got {event.new_balance.amount}"
    assert (
        event.new_balance.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {event.new_balance.currency_code!r}"


@then(r"the player event has new_reserved_balance (?P<balance>-?\d+)")
def step_then_event_has_new_reserved_balance(context, balance):
    """Verify the event new_reserved_balance field."""
    event_any = context.result_event_any

    event = try_unpack(event_any, player.FundsReserved) or try_unpack(
        event_any, player.FundsReleased
    )
    if event is None:
        raise AssertionError(
            f"Unknown event type for new_reserved_balance: {event_any.type_url}"
        )

    assert event.new_reserved_balance.amount == int(
        balance
    ), f"Expected new_reserved_balance={balance}, got {event.new_reserved_balance.amount}"
    assert (
        event.new_reserved_balance.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {event.new_reserved_balance.currency_code!r}"


@then(r'the player event has table_root "(?P<tbl>[^"]+)"')
def step_then_event_table_root(context, tbl):
    """Pin the reservation key on FundsReserved/FundsReleased (historical
    step name; the proto field is now ``key`` but scenarios still phrase it
    as ``table_root``)."""
    event_any = context.result_event_any
    event = try_unpack(event_any, player.FundsReserved) or try_unpack(
        event_any, player.FundsReleased
    )
    if event is None:
        raise AssertionError(
            f"Unknown event type for reservation key: {event_any.type_url}"
        )
    expected = tbl.encode("utf-8")
    assert event.key == expected, f"Expected key={expected!r}, got {event.key!r}"


@then(r'the player event has reason "(?P<reason>[^"]*)"')
def step_then_event_has_reason(context, reason):
    """Verify the event reason field (FundsTransferred, etc.)."""
    event = try_unpack(context.result_event_any, player.FundsTransferred)
    if event is None:
        raise AssertionError(
            f"No reason field on event type: {context.result_event_any.type_url}"
        )
    assert event.reason == reason, f"Expected reason={reason!r}, got {event.reason!r}"


@then(r"the player event has new_available_balance (?P<balance>-?\d+)")
def step_then_event_has_new_available_balance(context, balance):
    """Verify the event new_available_balance field."""
    event_any = context.result_event_any

    event = try_unpack(event_any, player.FundsReserved) or try_unpack(
        event_any, player.FundsReleased
    )
    if event is None:
        raise AssertionError(
            f"Unknown event type for new_available_balance: {event_any.type_url}"
        )

    assert event.new_available_balance.amount == int(
        balance
    ), f"Expected new_available_balance={balance}, got {event.new_available_balance.amount}"
    assert (
        event.new_available_balance.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {event.new_available_balance.currency_code!r}"


@then(r'the command fails with status "(?P<status>[^"]+)"')
def step_then_command_fails_with_status(context, status):
    """Verify the command failed with expected status."""
    assert context.error is not None, "Expected command to fail but it succeeded"
    assert hasattr(
        context.error, "status_code"
    ), f"Error {type(context.error).__name__} has no status_code attribute"
    assert (
        context.error.status_code == status
    ), f"Expected status {status}, got {context.error.status_code}"


@then(r'the error message contains "(?P<text>[^"]+)"')
def step_then_error_contains(context, text):
    """Verify the error message contains expected text."""
    assert context.error is not None, "Expected an error but got success"
    assert (
        text.lower() in context.error_message.lower()
    ), f"Expected error to contain '{text}', got '{context.error_message}'"


@then(r'the error message equals "(?P<text>[^"]+)"')
def step_then_error_equals(context, text):
    """Verify the error message exactly equals expected text (case-sensitive).

    Use this for precondition checks whose wording is part of the API contract;
    plain ``contains`` lets case- and wrapper-mutations survive (e.g.
    "reservation_id is required" → "RESERVATION_ID IS REQUIRED").
    """
    assert context.error is not None, "Expected an error but got success"
    assert (
        context.error_message == text
    ), f"Expected error to equal {text!r}, got {context.error_message!r}"


@then(r"the player state has bankroll (?P<amount>-?\d+)")
def step_then_state_has_bankroll(context, amount):
    """Verify the player state bankroll."""
    assert context.state is not None, "No player state"
    assert context.state.bankroll == int(
        amount
    ), f"Expected bankroll={amount}, got {context.state.bankroll}"


@then(r"the player state has reserved_funds (?P<amount>-?\d+)")
def step_then_state_has_reserved_funds(context, amount):
    """Verify the player state reserved_funds."""
    assert context.state is not None, "No player state"
    assert context.state.reserved_funds == int(
        amount
    ), f"Expected reserved_funds={amount}, got {context.state.reserved_funds}"


@then(r"the player state has available_balance (?P<amount>-?\d+)")
def step_then_state_has_available_balance(context, amount):
    """Verify the player state available_balance."""
    assert context.state is not None, "No player state"
    available = context.state.available_balance
    assert available == int(
        amount
    ), f"Expected available_balance={amount}, got {available}"


# =============================================================================
# Orchestration Command Step Definitions (buy-in / registration / rebuy)
# =============================================================================
# These commands live on the Player aggregate and emit orchestration events
# that the PMs (BuyInOrchestrator, etc.) react to. PM-level orchestration
# behaviour is in orchestration_steps.py.


# --- Given: pending orchestration state via event replay ---


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


def _append_funds_released(context, table_root: bytes, amount: int) -> None:
    """Simulate the PM hop: a *Released event triggers ReleaseFunds on the
    player aggregate, emitting FundsReleased."""
    state = _build_state_from_events(context.events)
    new_reserved = state.reserved_funds - amount
    new_available = state.bankroll - new_reserved
    event = player.FundsReleased(
        amount=poker_types.Currency(amount=amount, currency_code="CHIPS"),
        key=table_root,
        new_available_balance=poker_types.Currency(
            amount=new_available, currency_code="CHIPS"
        ),
        new_reserved_balance=poker_types.Currency(
            amount=new_reserved, currency_code="CHIPS"
        ),
        released_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))


@given(
    r'a pending buy-in "(?P<res>[^"]+)" for table "(?P<tbl>[^"]+)" '
    r"seat (?P<seat>\d+) amount (?P<amt>\d+)"
)
def step_given_pending_buy_in(context, res, tbl, seat, amt):
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
    r'a pending registration "(?P<res>[^"]+)" for tournament "(?P<trn>[^"]+)" '
    r"fee (?P<fee>\d+)"
)
def step_given_pending_registration(context, res, trn, fee):
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
    r'a pending rebuy "(?P<res>[^"]+)" for tournament "(?P<trn>[^"]+)" '
    r'table "(?P<tbl>[^"]+)" seat (?P<seat>\d+) fee (?P<fee>\d+) '
    r"chips (?P<chips>\d+)"
)
def step_given_pending_rebuy(context, res, trn, tbl, seat, fee, chips):
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


@given(
    r'a BuyInConfirmed event for reservation "(?P<res>[^"]+)" table "(?P<tbl>[^"]+)"'
)
def step_given_buy_in_confirmed_event(context, res, tbl):
    if not hasattr(context, "events"):
        context.events = []
    pending = _pending_buy_in_state(context, res)  # snapshot BEFORE appending Confirmed
    event = buy_in.BuyInConfirmed(
        reservation_id=_id_bytes(res),
        table_root=_id_bytes(tbl),
        confirmed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    if pending is not None:
        _append_funds_deducted(context, _id_bytes(tbl), _id_bytes(res), pending.amount)


@given(
    r'a RegistrationFeeConfirmed event for reservation "(?P<res>[^"]+)" '
    r'tournament "(?P<trn>[^"]+)"'
)
def step_given_registration_confirmed_event(context, res, trn):
    if not hasattr(context, "events"):
        context.events = []
    pending = _pending_registration_state(context, res)
    event = registration.RegistrationFeeConfirmed(
        reservation_id=_id_bytes(res),
        tournament_root=_id_bytes(trn),
        confirmed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, seq=len(context.events)))
    if pending is not None:
        _append_funds_deducted(context, _id_bytes(trn), _id_bytes(res), pending.fee)


@given(r'a RebuyFeeConfirmed event for reservation "(?P<res>[^"]+)"')
def step_given_rebuy_confirmed_event(context, res):
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
    r'I handle an InitiateBuyIn command for table "(?P<tbl>[^"]*)" '
    r"seat (?P<seat>-?\d+) amount (?P<amt>-?\d+)"
)
def step_when_initiate_buy_in(context, tbl, seat, amt):
    cmd = buy_in.InitiateBuyIn(
        table_root=_id_bytes(tbl) if tbl else b"",
        seat=int(seat),
        amount=poker_types.Currency(amount=int(amt), currency_code="CHIPS"),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_buy_in", cmd)


@when(r'I handle a ConfirmBuyIn command for reservation "(?P<res>[^"]*)"')
def step_when_confirm_buy_in(context, res):
    cmd = buy_in.ConfirmBuyIn(reservation_id=_id_bytes(res) if res else b"")
    _execute_handler(context, "confirm_buy_in", cmd)


@when(
    r'I handle a ReleaseBuyIn command for reservation "(?P<res>[^"]*)" '
    r'reason "(?P<reason>[^"]*)"'
)
def step_when_release_buy_in(context, res, reason):
    cmd = buy_in.ReleaseBuyIn(
        reservation_id=_id_bytes(res) if res else b"", reason=reason
    )
    _execute_handler(context, "release_buy_in", cmd)


@when(
    r'I handle an InitiateTournamentRegistration command for tournament "(?P<trn>[^"]*)"'
)
def step_when_initiate_registration(context, trn):
    cmd = registration.InitiateTournamentRegistration(
        tournament_root=_id_bytes(trn) if trn else b"",
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_registration", cmd)


@when(r'I handle a ConfirmRegistrationFee command for reservation "(?P<res>[^"]*)"')
def step_when_confirm_registration(context, res):
    cmd = registration.ConfirmRegistrationFee(
        reservation_id=_id_bytes(res) if res else b""
    )
    _execute_handler(context, "confirm_registration", cmd)


@when(
    r'I handle a ReleaseRegistrationFee command for reservation "(?P<res>[^"]*)" '
    r'reason "(?P<reason>[^"]*)"'
)
def step_when_release_registration(context, res, reason):
    cmd = registration.ReleaseRegistrationFee(
        reservation_id=_id_bytes(res) if res else b"", reason=reason
    )
    _execute_handler(context, "release_registration", cmd)


@when(
    r'I handle an InitiateRebuy command for tournament "(?P<trn>[^"]*)" '
    r'table "(?P<tbl>[^"]*)" seat (?P<seat>-?\d+)'
)
def step_when_initiate_rebuy(context, trn, tbl, seat):
    cmd = rebuy.InitiateRebuy(
        tournament_root=_id_bytes(trn) if trn else b"",
        table_root=_id_bytes(tbl) if tbl else b"",
        seat=int(seat),
        player_root=_UNIT_PLAYER_ROOT,
    )
    _execute_handler(context, "initiate_rebuy", cmd)


@when(r'I handle a ConfirmRebuyFee command for reservation "(?P<res>[^"]*)"')
def step_when_confirm_rebuy(context, res):
    cmd = rebuy.ConfirmRebuyFee(reservation_id=_id_bytes(res) if res else b"")
    _execute_handler(context, "confirm_rebuy", cmd)


@when(
    r'I handle a ReleaseRebuyFee command for reservation "(?P<res>[^"]*)" '
    r'reason "(?P<reason>[^"]*)"'
)
def step_when_release_rebuy(context, res, reason):
    cmd = rebuy.ReleaseRebuyFee(
        reservation_id=_id_bytes(res) if res else b"", reason=reason
    )
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


@then(r'the orchestration event has table_root "(?P<tbl>[^"]+)"')
def step_then_orch_table_root(context, tbl):
    evt = _orch_event(context.result_event_any)
    assert (
        evt is not None
    ), f"Not an orchestration event: {context.result_event_any.type_url}"
    assert evt.table_root == _id_bytes(
        tbl
    ), f"Expected table_root for {tbl}, got {evt.table_root!r}"


@then(r'the orchestration event has tournament_root "(?P<trn>[^"]+)"')
def step_then_orch_tournament_root(context, trn):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.tournament_root == _id_bytes(
        trn
    ), f"Expected tournament_root for {trn}, got {evt.tournament_root!r}"


@then(r"the orchestration event has seat (?P<seat>-?\d+)")
def step_then_orch_seat(context, seat):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.seat == int(seat), f"Expected seat={seat}, got {evt.seat}"


@then(r"the orchestration event has fee (?P<fee>-?\d+)")
def step_then_orch_fee(context, fee):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.fee.amount == int(fee), f"Expected fee={fee}, got {evt.fee.amount}"
    assert (
        evt.fee.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {evt.fee.currency_code!r}"


@then(r"the orchestration event has chips_added (?P<chips>-?\d+)")
def step_then_orch_chips_added(context, chips):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.chips_added == int(
        chips
    ), f"Expected chips_added={chips}, got {evt.chips_added}"


@then(r"the orchestration event has amount (?P<amount>-?\d+)")
def step_then_orch_amount(context, amount):
    """Pin the amount field on orchestration events (BuyInRequested,
    BuyInConfirmed). The generic ``the player event has amount`` step
    doesn't unpack these types, so amount-field mutations slip through."""
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.amount.amount == int(
        amount
    ), f"Expected amount={amount}, got {evt.amount.amount}"
    assert (
        evt.amount.currency_code == "CHIPS"
    ), f"Expected currency_code=CHIPS, got {evt.amount.currency_code!r}"


@then(r"the orchestration event has a reservation_id")
def step_then_orch_has_reservation_id(context):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.reservation_id, "reservation_id was empty"


@then(r'the orchestration event has reservation_id "(?P<res>[^"]+)"')
def step_then_orch_reservation_id(context, res):
    """Check the orchestration event carries the exact reservation_id passed in.

    Use this on confirm/release scenarios to lock in ``reservation_id=cmd.reservation_id``
    field assignments — without it, mutations swapping that source survive.
    """
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    expected = _id_bytes(res)
    assert (
        evt.reservation_id == expected
    ), f"Expected reservation_id={expected!r}, got {evt.reservation_id!r}"


@then(r'the orchestration event has reason "(?P<reason>[^"]*)"')
def step_then_orch_reason(context, reason):
    evt = _orch_event(context.result_event_any)
    assert evt is not None
    assert evt.reason == reason, f"Expected reason={reason!r}, got {evt.reason!r}"


@then(r'the player event has from_player_root "(?P<label>[^"]+)"')
def step_then_event_from_player_root(context, label):
    """Check FundsTransferred.from_player_root matches the labelled bytes."""
    evt = try_unpack(context.result_event_any, player.FundsTransferred)
    assert (
        evt is not None
    ), f"Not a FundsTransferred event: {context.result_event_any.type_url}"
    expected = label.encode("utf-8")
    assert (
        evt.from_player_root == expected
    ), f"Expected from_player_root={expected!r}, got {evt.from_player_root!r}"


@then(r'the player event has hand_root "(?P<label>[^"]+)"')
def step_then_event_hand_root(context, label):
    """Check FundsTransferred.hand_root matches the labelled bytes."""
    evt = try_unpack(context.result_event_any, player.FundsTransferred)
    assert (
        evt is not None
    ), f"Not a FundsTransferred event: {context.result_event_any.type_url}"
    expected = label.encode("utf-8")
    assert (
        evt.hand_root == expected
    ), f"Expected hand_root={expected!r}, got {evt.hand_root!r}"


@then(r'the player event has to_player_root for player "(?P<email>[^"]+)"')
def step_then_event_to_player_root(context, email):
    """Check FundsTransferred.to_player_root matches state.player_id (player_<email>)."""
    evt = try_unpack(context.result_event_any, player.FundsTransferred)
    assert (
        evt is not None
    ), f"Not a FundsTransferred event: {context.result_event_any.type_url}"
    expected = f"player_{email}".encode("utf-8")
    assert (
        evt.to_player_root == expected
    ), f"Expected to_player_root={expected!r}, got {evt.to_player_root!r}"


_TIMESTAMP_EVENT_TYPES = (
    player.PlayerRegistered,
    player.FundsDeposited,
    player.FundsWithdrawn,
    player.FundsReserved,
    player.FundsReleased,
    player.FundsTransferred,
    buy_in.BuyInRequested,
    buy_in.BuyInConfirmed,
    buy_in.BuyInReservationReleased,
    registration.RegistrationRequested,
    registration.RegistrationFeeConfirmed,
    registration.RegistrationFeeReleased,
    rebuy.RebuyRequested,
    rebuy.RebuyFeeConfirmed,
    rebuy.RebuyFeeReleased,
)


@then(r"the event has a timestamp (?P<field>\w+)")
def step_then_event_has_timestamp(context, field):
    """Assert <field> is a non-zero protobuf Timestamp.

    Mutmut only mutates ``<field>=now()`` to ``=None`` or removes the kwarg;
    both yield a default Timestamp with seconds=0, so a > 0 check kills them
    without needing any time-mocking infrastructure.
    """
    event_any = context.result_event_any
    event = None
    for cls in _TIMESTAMP_EVENT_TYPES:
        candidate = try_unpack(event_any, cls)
        if candidate is not None:
            event = candidate
            break
    if event is None:
        raise AssertionError(f"Unknown event type: {event_any.type_url}")
    if not event.HasField(field):
        raise AssertionError(f"Event {type(event).__name__} has no field {field!r} set")
    ts = getattr(event, field)
    assert (
        ts.seconds > 0
    ), f"Expected {field}.seconds > 0, got {ts.seconds} (default Timestamp)"


# --- Then: pending-state assertions ---


def _reservation_state(context) -> ReservationState:
    """Pending-state assertions read the reservation aggregate's state.

    Before the reservation refactor these asserted against ``context.state``
    (a PlayerState with pending dicts). That fused ownership is gone; the
    pending records now live on the reservation aggregate, so the
    assertions go through ``context.reservation_state`` — populated by
    ``_execute_reservation`` after each lifecycle command.
    """
    reservation_state = getattr(context, "reservation_state", None)
    if reservation_state is None:
        events = getattr(context, "events", [])
        reservation_state = _build_reservation_state_from_events(events)
    return reservation_state


@then(r'the (?:player|reservation) state has no pending buy-in "(?P<res>[^"]+)"')
def step_then_no_pending_buy_in(context, res):
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_buy_ins


@then(r'the (?:player|reservation) state has no pending registration "(?P<res>[^"]+)"')
def step_then_no_pending_registration(context, res):
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_registrations


@then(r'the (?:player|reservation) state has no pending rebuy "(?P<res>[^"]+)"')
def step_then_no_pending_rebuy(context, res):
    assert _id_bytes(res).hex() not in _reservation_state(context).pending_rebuys
