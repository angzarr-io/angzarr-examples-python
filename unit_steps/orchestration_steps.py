"""Step definitions for cross-domain orchestration BDD tests.

The step regexes are pinned to the business-language phrasing in
``features/example/unit/orchestration.feature``: things like
"Alice's buy-in is processed" rather than implementation-level
"the BuyInOrchestrator handles the BuyInRequested event". Underneath,
the implementations still drive the production
``reservation.pmg.handlers.ReservationPM`` through its real handler
methods. A ``FakeQueryClient`` holds in-memory event books seeded from
the Given steps; the PM queries it synchronously for cross-aggregate
pre-validation and emits the real ``*Failed`` / ``*Initiated`` /
``*Completed`` events. The legacy ``emitted_commands``/``emitted_events``
context shape is retained so the Then-step assertions are unchanged
across the rewrite.
"""

import importlib.util
import sys
from pathlib import Path

from behave import given, then, use_step_matcher, when

from tests.helpers import uuid_for
from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import buy_in_pb2 as buy_in
from angzarr_client.proto.examples.v1 import orchestration_pb2 as orch
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker
from angzarr_client.proto.examples.v1 import rebuy_pb2 as rebuy
from angzarr_client.proto.examples.v1 import registration_pb2 as registration
from angzarr_client.proto.examples.v1 import table_pb2 as table_proto
from angzarr_client.proto.examples.v1 import tournament_pb2 as tournament
from google.protobuf.any_pb2 import Any as ProtoAny

REPO_ROOT = Path(__file__).resolve().parent.parent
PMG_DIR = REPO_ROOT / "reservation" / "pmg"

# The reservation PM imports siblings via bare names (``from state import …``).
# Add the dir to sys.path before loading so those imports resolve.
if str(PMG_DIR) not in sys.path:
    sys.path.insert(0, str(PMG_DIR))


def _load(module_name: str, full_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(full_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_name} from {full_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Load production PM module + state types. The dir-based import path means
# we re-export sibling modules under their bare names too.
_state_mod = _load("state", PMG_DIR / "state.py")
_table_state_mod = _load("table_state", PMG_DIR / "table_state.py")
_tournament_state_mod = _load("tournament_state", PMG_DIR / "tournament_state.py")
_handlers_mod = _load("_reservation_pm_handlers", PMG_DIR / "handlers.py")

ReservationPM = _handlers_mod.ReservationPM
ReservationPMState = _state_mod.ReservationPMState
KIND_BUY_IN = _state_mod.KIND_BUY_IN
KIND_REBUY = _state_mod.KIND_REBUY
KIND_REGISTRATION = _state_mod.KIND_REGISTRATION

use_step_matcher("re")


# =============================================================================
# Fake query client — in-memory event books for cross-aggregate reads.
# =============================================================================


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


class _QueryResult:
    def __init__(self, book: types.EventBook):
        self._book = book

    def get_event_book(self) -> types.EventBook:
        return self._book


class FakeQueryClient:
    """Mimics ``angzarr_client.QueryClient`` for synchronous reads.

    Stores events keyed by (domain, root). ``query(...)`` returns an object
    whose ``.get_event_book()`` matches what the PM's helpers expect.
    """

    def __init__(self):
        self._books: dict[tuple[str, bytes], list] = {}

    def append(self, domain: str, root: bytes, event_msg) -> None:
        key = (domain, root)
        self._books.setdefault(key, []).append(event_msg)

    def query(self, domain: str, root: bytes) -> _QueryResult:
        events = self._books.get((domain, root), [])
        pages = [
            types.EventPage(
                header=types.PageHeader(sequence=i),
                event=_pack(ev),
            )
            for i, ev in enumerate(events)
        ]
        return _QueryResult(types.EventBook(pages=pages))


# =============================================================================
# Context helpers
# =============================================================================


def _init_orchestration_context(context):
    """Reset orchestration scratch fields on the behave context."""
    context.emitted_commands = []
    context.emitted_events = []
    if not hasattr(context, "fake_query"):
        context.fake_query = FakeQueryClient()
    if not hasattr(context, "occupied_seats"):
        context.occupied_seats = {}
    context.table_min_buy_in = getattr(context, "table_min_buy_in", 0)
    context.table_max_buy_in = getattr(context, "table_max_buy_in", 0)
    context.table_max_players = getattr(context, "table_max_players", 0)
    context.tournament_max_players = getattr(context, "tournament_max_players", 0)
    context.tournament_registered_count = getattr(
        context, "tournament_registered_count", 0
    )
    context.tournament_registration_open = getattr(
        context, "tournament_registration_open", False
    )
    context.tournament_status = getattr(
        context,
        "tournament_status",
        tournament.TournamentStatus.TOURNAMENT_STATUS_UNSPECIFIED,
    )
    context.rebuy_window_open = getattr(context, "rebuy_window_open", False)
    context.player_is_seated = getattr(context, "player_is_seated", False)
    context.player_seat_position = getattr(context, "player_seat_position", -1)


_FAILURE_EVENT_TYPES = {
    "buy_in.BuyInFailed": buy_in.BuyInFailed,
    "rebuy.RebuyFailed": rebuy.RebuyFailed,
    "registration.RegistrationFailed": registration.RegistrationFailed,
}


def _seed_table(context):
    """Seed the fake query with table state derived from context vars."""
    table_root = getattr(context, "table_root", b"")
    if not table_root:
        return
    if context.table_max_players <= 0:
        return
    context.fake_query.append(
        "table",
        table_root,
        table_proto.TableCreated(
            table_name="Test",
            game_variant=poker.TEXAS_HOLDEM,
            small_blind=5,
            big_blind=10,
            min_buy_in=context.table_min_buy_in,
            max_buy_in=context.table_max_buy_in,
            max_players=context.table_max_players,
            action_timeout_seconds=30,
        ),
    )
    for seat, player_root in context.occupied_seats.items():
        context.fake_query.append(
            "table",
            table_root,
            table_proto.PlayerJoined(
                player_root=player_root,
                seat_position=seat,
                buy_in_amount=500,
                stack=500,
            ),
        )
    if context.player_is_seated and context.player_seat_position >= 0:
        context.fake_query.append(
            "table",
            table_root,
            table_proto.PlayerJoined(
                player_root=context.player_root,
                seat_position=context.player_seat_position,
                buy_in_amount=1000,
                stack=1000,
            ),
        )


def _seed_tournament(context):
    """Seed the fake query with tournament state derived from context vars."""
    tournament_root = getattr(context, "tournament_root", b"")
    if not tournament_root:
        return
    rebuy_window = getattr(context, "rebuy_window_open", False)
    rebuy_cost = 1000 if rebuy_window else 0
    rebuy_chips = 5000 if rebuy_window else 0
    rebuy_config = tournament.RebuyConfig(
        enabled=rebuy_window,
        rebuy_cost=rebuy_cost,
        rebuy_chips=rebuy_chips,
        max_rebuys=3,
    )
    context.fake_query.append(
        "tournament",
        tournament_root,
        tournament.TournamentCreated(
            name="Test Tour",
            game_variant=poker.TEXAS_HOLDEM,
            buy_in=1000,
            starting_stack=5000,
            max_players=context.tournament_max_players or 9,
            min_players=2,
            rebuy_config=rebuy_config,
        ),
    )
    status = context.tournament_status
    if status == tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN:
        context.fake_query.append(
            "tournament", tournament_root, tournament.RegistrationOpened()
        )
    elif status in (
        tournament.TournamentStatus.TOURNAMENT_RUNNING,
        tournament.TournamentStatus.TOURNAMENT_COMPLETED,
    ):
        context.fake_query.append(
            "tournament",
            tournament_root,
            tournament.RegistrationClosed(total_registrations=0),
        )
        context.fake_query.append(
            "tournament",
            tournament_root,
            tournament.TournamentStarted(
                total_players=context.tournament_registered_count or 4,
                tables_created=1,
            ),
        )
    elif not context.tournament_registration_open:
        context.fake_query.append(
            "tournament",
            tournament_root,
            tournament.RegistrationClosed(total_registrations=0),
        )

    # Approximate 'registered_count' by enrolling synthetic players.
    for i in range(min(context.tournament_registered_count, 1000)):
        context.fake_query.append(
            "tournament",
            tournament_root,
            tournament.TournamentPlayerEnrolled(
                player_root=uuid_for(f"reg-{i}"),
                fee_paid=1000,
                starting_stack=5000,
                registration_number=i + 1,
            ),
        )


def _build_pm(context) -> ReservationPM:
    """Seed the fake query and build the production PM."""
    _seed_table(context)
    _seed_tournament(context)
    return ReservationPM(query_client=context.fake_query)


def _state_for(context, kind: str) -> ReservationPMState:
    return ReservationPMState(
        reservation_id=getattr(context, "reservation_id", b""),
        kind=kind,
        player_root=getattr(context, "player_root", b""),
        table_root=getattr(context, "table_root", b""),
        tournament_root=getattr(context, "tournament_root", b""),
        seat=getattr(context, "player_seat_position", -1),
        amount=getattr(context, "buy_in_amount", 0),
        fee=getattr(context, "registration_fee", 0)
        or getattr(context, "rebuy_amount", 0),
    )


def _short_type_name(type_url: str) -> str:
    """``type.googleapis.com/angzarr_client.proto.examples.v1.SeatPlayer`` → ``SeatPlayer``."""
    return type_url.rsplit(".", 1)[-1]


_FAILED_PROTO_BY_NAME = {
    "BuyInFailed": buy_in.BuyInFailed,
    "RebuyFailed": rebuy.RebuyFailed,
    "RegistrationFailed": registration.RegistrationFailed,
}


def _record_response(context, response) -> None:
    """Translate a real ProcessManagerResponse into the legacy context shape.

    The @then steps assert against:
      - ``context.emitted_commands``: list of command type names (strings)
      - ``context.emitted_events``: list of (event_name, failure_code) tuples,
        ``failure_code`` is ``None`` for non-failure events.
    """
    context.emitted_commands = []
    for cmd_book in getattr(response, "commands", []) or []:
        for page in cmd_book.pages:
            if not page.HasField("command"):
                continue
            context.emitted_commands.append(_short_type_name(page.command.type_url))

    context.emitted_events = []
    process_events = getattr(response, "process_events", None)
    if process_events is None:
        return
    pages = list(process_events.pages) if hasattr(process_events, "pages") else []
    for page in pages:
        if not page.HasField("event"):
            continue
        name = _short_type_name(page.event.type_url)
        proto_cls = _FAILED_PROTO_BY_NAME.get(name)
        if proto_cls is not None:
            evt = proto_cls()
            page.event.Unpack(evt)
            code = evt.failure.code if evt.HasField("failure") else None
            context.emitted_events.append((name, code))
        else:
            context.emitted_events.append((name, None))


# =============================================================================
# Buy-in coordination — Given steps
# =============================================================================


@given(
    r'table "(?P<table>[^"]+)" has seat (?P<seat>\d+) available with a buy-in range '
    r"of (?P<min>\d+) to (?P<max>\d+)"
)
def step_given_table_seat_available_with_range(context, table, seat, min, max):
    """Table has a specific seat available within a buy-in range."""
    _init_orchestration_context(context)
    context.table_min_buy_in = int(min)
    context.table_max_buy_in = int(max)
    context.table_max_players = 9
    context.occupied_seats = {}
    context.table_root = table.encode() if isinstance(table, str) else table
    context.available_seat = int(seat)


@given(
    r"(?P<name>\w+) has requested a buy-in for seat (?P<seat>\d+) with amount (?P<amount>\d+)"
)
def step_given_player_requested_buy_in_for_seat(context, name, seat, amount):
    """Player has requested a buy-in for a specific seat and amount."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.reservation_id = b"res-001"
    context.buy_in_seat = int(seat)
    context.buy_in_amount = int(amount)
    context.buy_in_event = buy_in.BuyInRequested(
        reservation_id=context.reservation_id,
        player_root=context.player_root,
        table_root=getattr(context, "table_root", b"table-1"),
        seat=int(seat),
        amount=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r'table "(?P<table>[^"]+)" has seat (?P<seat>\d+) occupied by another player')
def step_given_seat_occupied(context, table, seat):
    """Table seat is taken by another player."""
    _init_orchestration_context(context)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9
    context.occupied_seats = {int(seat): b"other-player"}
    context.table_root = table.encode() if isinstance(table, str) else table


@given(r'table "(?P<table>[^"]+)" is full with (?P<count>\d+) players')
def step_given_table_full(context, table, count):
    """Every seat at the table is occupied."""
    _init_orchestration_context(context)
    num_players = int(count)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = num_players
    context.occupied_seats = {i: uuid_for(f"player-{i}") for i in range(num_players)}
    context.table_root = table.encode() if isinstance(table, str) else table


@given(r"(?P<name>\w+) has requested a buy-in for any seat with amount (?P<amount>\d+)")
def step_given_player_requested_buy_in_any_seat(context, name, amount):
    """Player has requested a buy-in with no seat preference."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.reservation_id = b"res-001"
    context.buy_in_seat = -1
    context.buy_in_amount = int(amount)
    context.buy_in_event = buy_in.BuyInRequested(
        reservation_id=context.reservation_id,
        player_root=context.player_root,
        table_root=getattr(context, "table_root", b"table-1"),
        seat=-1,
        amount=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r'(?P<name>\w+) has a pending buy-in at table "(?P<table>[^"]+)"')
def step_given_pending_buy_in(context, name, table):
    """Player and table are in a pending buy-in state (seating phase)."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.table_root = table.encode() if isinstance(table, str) else table
    context.reservation_id = b"res-001"
    context.buy_in_amount = 500
    context.buy_in_seat = 0
    context.buy_in_phase = orch.BuyInPhase.BUY_IN_SEATING


# =============================================================================
# Tournament registration coordination — Given steps
# =============================================================================


@given(r'tournament "(?P<trn>[^"]+)" is open for registration with capacity available')
def step_given_tournament_open_with_capacity(context, trn):
    """Tournament is accepting registrations and has room."""
    _init_orchestration_context(context)
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.tournament_registration_open = True
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r"(?P<name>\w+) has requested registration with fee (?P<fee>\d+)")
def step_given_registration_requested(context, name, fee):
    """Player has requested tournament registration with a fee."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.reservation_id = b"res-001"
    context.registration_fee = int(fee)
    context.registration_event = registration.RegistrationRequested(
        reservation_id=context.reservation_id,
        player_root=context.player_root,
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        fee=poker.Currency(amount=int(fee), currency_code="USD"),
    )


@given(r'tournament "(?P<trn>[^"]+)" is full')
def step_given_tournament_full(context, trn):
    """Tournament has reached max capacity."""
    _init_orchestration_context(context)
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.tournament_registration_open = True
    context.tournament_max_players = 4
    context.tournament_registered_count = 4
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r'tournament "(?P<trn>[^"]+)" has registration closed')
def step_given_tournament_registration_closed(context, trn):
    """Tournament has closed registration (in-progress or completed)."""
    _init_orchestration_context(context)
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.tournament_registration_open = False
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING


@given(r'(?P<name>\w+) has a pending registration for tournament "(?P<trn>[^"]+)"')
def step_given_pending_registration(context, name, trn):
    """Player and tournament are in the enrolling phase of registration."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.reservation_id = b"res-001"
    context.registration_fee = 1000
    context.registration_phase = orch.RegistrationPhase.REGISTRATION_ENROLLING


# =============================================================================
# Rebuy coordination — Given steps
# =============================================================================


@given(
    r'tournament "(?P<trn>[^"]+)" is in its rebuy window and (?P<name>\w+) is eligible'
)
def step_given_tournament_rebuy_eligible(context, trn, name):
    """Tournament is in rebuy window and the named player is eligible."""
    _init_orchestration_context(context)
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    context.rebuy_window_open = True
    context.player_eligible_for_rebuy = True


@given(r'(?P<name>\w+) is seated at table "(?P<table>[^"]+)" in seat (?P<pos>\d+)')
def step_given_player_seated_at_table(context, name, table, pos):
    """Named player is seated at a specific seat of the named table."""
    _init_orchestration_context(context)
    context.table_root = table.encode() if isinstance(table, str) else table
    context.player_root = name.lower().encode()
    context.player_seat_position = int(pos)
    context.player_is_seated = True
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9


@given(r"(?P<name>\w+) has requested a rebuy for amount (?P<amount>\d+)")
def step_given_rebuy_requested(context, name, amount):
    """Player has requested a rebuy for a specific amount."""
    _init_orchestration_context(context)
    context.reservation_id = b"res-001"
    context.rebuy_amount = int(amount)
    context.rebuy_event = rebuy.RebuyRequested(
        reservation_id=context.reservation_id,
        player_root=getattr(context, "player_root", name.lower().encode()),
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        table_root=getattr(context, "table_root", b"table-1"),
        seat=getattr(context, "player_seat_position", 2),
        fee=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r'tournament "(?P<trn>[^"]+)" has its rebuy window closed')
def step_given_rebuy_window_closed(context, trn):
    """Tournament's rebuy window has closed."""
    _init_orchestration_context(context)
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    context.rebuy_window_open = False
    context.player_eligible_for_rebuy = False


@given(r"(?P<name>\w+) is not seated at any table in the tournament")
def step_given_player_not_seated(context, name):
    """Player has not been seated at any table in this tournament."""
    _init_orchestration_context(context)
    context.table_root = b"table-1"
    context.player_root = name.lower().encode()
    context.player_is_seated = False
    context.player_seat_position = -1
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9


@given(
    r'(?P<name>\w+) has a pending rebuy at table "(?P<table>[^"]+)" in tournament '
    r'"(?P<trn>[^"]+)"'
)
def step_given_pending_rebuy(context, name, table, trn):
    """All three domains (player, table, tournament) are in the rebuy approval phase."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.table_root = table.encode() if isinstance(table, str) else table
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_APPROVING


@given(
    r'(?P<name>\w+)\'s rebuy chips have been added at table "(?P<table>[^"]+)" in '
    r'tournament "(?P<trn>[^"]+)"'
)
def step_given_rebuy_chips_added(context, name, table, trn):
    """All three domains in the chips-added phase of rebuy."""
    _init_orchestration_context(context)
    context.player_root = name.lower().encode()
    context.tournament_root = trn.encode() if isinstance(trn, str) else trn
    context.table_root = table.encode() if isinstance(table, str) else table
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_ADDING_CHIPS


# =============================================================================
# When steps — buy-in / registration / rebuy actions
# =============================================================================


@when(r"(?P<name>\w+)'s buy-in is processed")
def step_when_buy_in_processed(context, name):
    """Dispatch BuyInRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_BUY_IN)
    response = pm.on_buy_in_requested(context.buy_in_event, state, destinations=None)
    _record_response(context, response)


@when(r"(?P<name>\w+) is seated at the table")
def step_when_player_seated(context, name):
    """Dispatch PlayerSeated through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_BUY_IN)
    event = buy_in.PlayerSeated(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        seat_position=context.buy_in_seat,
        stack=context.buy_in_amount,
    )
    response = pm.on_player_seated(event, state, destinations=None)
    _record_response(context, response)


@when(r"the table refuses to seat (?P<name>\w+)")
def step_when_table_refuses_to_seat(context, name):
    """Dispatch SeatingRejected through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_BUY_IN)
    event = buy_in.SeatingRejected(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        requested_seat=context.buy_in_seat,
        reason="Seat taken by another player",
    )
    response = pm.on_seating_rejected(event, state, destinations=None)
    _record_response(context, response)


@when(r"(?P<name>\w+)'s registration is processed")
def step_when_registration_processed(context, name):
    """Dispatch RegistrationRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REGISTRATION)
    response = pm.on_registration_requested(
        context.registration_event, state, destinations=None
    )
    _record_response(context, response)


@when(r"(?P<name>\w+) is enrolled in the tournament")
def step_when_player_enrolled(context, name):
    """Dispatch TournamentPlayerEnrolled through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REGISTRATION)
    event = tournament.TournamentPlayerEnrolled(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        fee_paid=context.registration_fee,
        starting_stack=5000,
        registration_number=1,
    )
    response = pm.on_player_enrolled(event, state, destinations=None)
    _record_response(context, response)


@when(r"the tournament refuses to enroll (?P<name>\w+)")
def step_when_tournament_refuses_enroll(context, name):
    """Dispatch TournamentEnrollmentRejected through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REGISTRATION)
    event = tournament.TournamentEnrollmentRejected(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        reason="Tournament full",
    )
    response = pm.on_enrollment_rejected(event, state, destinations=None)
    _record_response(context, response)


@when(r"(?P<name>\w+)'s rebuy is processed")
def step_when_rebuy_processed(context, name):
    """Dispatch RebuyRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REBUY)
    response = pm.on_rebuy_requested(context.rebuy_event, state, destinations=None)
    _record_response(context, response)


@when(r"the tournament approves (?P<name>\w+)'s rebuy")
def step_when_tournament_approves_rebuy(context, name):
    """Dispatch RebuyProcessed through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REBUY)
    event = tournament.RebuyProcessed(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        rebuy_cost=1000,
        chips_added=5000,
    )
    response = pm.on_rebuy_processed(event, state, destinations=None)
    _record_response(context, response)


@when(r"the chips are settled at the table")
def step_when_chips_settled(context):
    """Dispatch RebuyChipsAdded through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REBUY)
    event = rebuy.RebuyChipsAdded(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        seat=context.player_seat_position,
        amount=5000,
        new_stack=10000,
    )
    response = pm.on_rebuy_chips_added(event, state, destinations=None)
    _record_response(context, response)


@when(r"the tournament denies (?P<name>\w+)'s rebuy")
def step_when_tournament_denies_rebuy(context, name):
    """Dispatch RebuyDenied through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REBUY)
    event = tournament.RebuyDenied(
        player_root=context.player_root,
        reservation_id=context.reservation_id,
        reason="Tournament closed",
    )
    response = pm.on_rebuy_denied(event, state, destinations=None)
    _record_response(context, response)


# =============================================================================
# Then steps — command outcomes ("Alice is offered seat …" etc.)
# =============================================================================


def _assert_emitted(context, name: str) -> None:
    assert name in context.emitted_commands, (
        f"Expected {name}, got {context.emitted_commands}"
    )


_RELEASE_COMPENSATIONS = {"ReleaseBuyIn", "ReleaseRebuyFee", "ReleaseRegistrationFee"}


@then(r'(?P<name>\w+) is offered seat (?P<seat>\d+) at table "(?P<table>[^"]+)"')
def step_then_player_offered_seat(context, name, seat, table):
    """Player is offered a seat at the table — SeatPlayer command was emitted."""
    _assert_emitted(context, "SeatPlayer")


@then(r"(?P<name>\w+) is not offered a seat")
def step_then_player_not_offered_seat(context, name):
    """No SeatPlayer command was emitted (the buy-in was refused)."""
    workflow_cmds = [
        c for c in context.emitted_commands if c not in _RELEASE_COMPENSATIONS
    ]
    assert not workflow_cmds, f"Expected no workflow commands, got {workflow_cmds}"


@then(r"(?P<name>\w+)'s buy-in is confirmed")
def step_then_buy_in_confirmed(context, name):
    """The buy-in funds are confirmed — ConfirmBuyIn was emitted."""
    _assert_emitted(context, "ConfirmBuyIn")


@then(r"(?P<name>\w+)'s reserved buy-in funds are released")
def step_then_buy_in_funds_released(context, name):
    """The buy-in reservation is released — ReleaseBuyIn was emitted."""
    _assert_emitted(context, "ReleaseBuyIn")


@then(r'(?P<name>\w+) is enrolled in tournament "(?P<trn>[^"]+)"')
def step_then_player_enrolled(context, name, trn):
    """The player is enrolled — EnrollPlayer command was emitted."""
    _assert_emitted(context, "EnrollPlayer")


@then(r"(?P<name>\w+) is not enrolled")
def step_then_player_not_enrolled(context, name):
    """No EnrollPlayer command was emitted (the registration was refused)."""
    workflow_cmds = [
        c for c in context.emitted_commands if c not in _RELEASE_COMPENSATIONS
    ]
    assert not workflow_cmds, f"Expected no workflow commands, got {workflow_cmds}"


@then(r"(?P<name>\w+)'s registration fee is confirmed")
def step_then_registration_fee_confirmed(context, name):
    """The registration fee is confirmed — ConfirmRegistrationFee was emitted."""
    _assert_emitted(context, "ConfirmRegistrationFee")


@then(r"(?P<name>\w+)'s reserved registration fee is released")
def step_then_registration_fee_released(context, name):
    """The registration fee reservation is released — ReleaseRegistrationFee."""
    _assert_emitted(context, "ReleaseRegistrationFee")


@then(r'(?P<name>\w+)\'s rebuy is submitted to tournament "(?P<trn>[^"]+)"')
def step_then_rebuy_submitted(context, name, trn):
    """The rebuy is submitted — ProcessRebuy command was emitted."""
    _assert_emitted(context, "ProcessRebuy")


@then(r"(?P<name>\w+)'s rebuy is not submitted")
def step_then_rebuy_not_submitted(context, name):
    """No ProcessRebuy command was emitted (the rebuy was refused)."""
    workflow_cmds = [
        c for c in context.emitted_commands if c not in _RELEASE_COMPENSATIONS
    ]
    assert not workflow_cmds, f"Expected no workflow commands, got {workflow_cmds}"


@then(r"(?P<name>\w+)'s rebuy chips are added at the table")
def step_then_rebuy_chips_added(context, name):
    """The chips are added at the table — AddRebuyChips command was emitted."""
    _assert_emitted(context, "AddRebuyChips")


@then(r"(?P<name>\w+)'s rebuy fee is confirmed")
def step_then_rebuy_fee_confirmed(context, name):
    """The rebuy fee is confirmed — ConfirmRebuyFee was emitted."""
    _assert_emitted(context, "ConfirmRebuyFee")


@then(r"(?P<name>\w+)'s reserved rebuy fee is released")
def step_then_rebuy_fee_released(context, name):
    """The reserved rebuy fee is released — ReleaseRebuyFee was emitted."""
    _assert_emitted(context, "ReleaseRebuyFee")


# =============================================================================
# Then steps — process-event outcomes (recorded as initiated/completed/refused)
# =============================================================================


def _assert_event(context, name: str) -> None:
    names = [n for n, _ in context.emitted_events]
    assert name in names, f"Expected {name} event, got {names}"


def _assert_any_failure(context, *event_names: str) -> None:
    """Verify a failure event of one of the given names was emitted."""
    names = [n for n, _ in context.emitted_events]
    assert any(n in names for n in event_names), (
        f"Expected one of {event_names}, got {names}"
    )


@then(r"the buy-in is recorded as initiated")
def step_then_buy_in_initiated(context):
    _assert_event(context, "BuyInInitiated")


@then(r"the buy-in is recorded as completed")
def step_then_buy_in_completed(context):
    _assert_event(context, "BuyInCompleted")


@then(r"the buy-in is refused because the amount is outside the allowed range")
def step_then_buy_in_refused_amount_range(context):
    _assert_any_failure(context, "BuyInFailed")


@then(r"the buy-in is refused because the seat is already taken")
def step_then_buy_in_refused_seat_taken(context):
    _assert_any_failure(context, "BuyInFailed")


@then(r"the buy-in is refused because the table is full")
def step_then_buy_in_refused_table_full(context):
    _assert_any_failure(context, "BuyInFailed")


@then(r"the buy-in is refused because seating was rejected")
def step_then_buy_in_refused_seating_rejected(context):
    _assert_any_failure(context, "BuyInFailed")


@then(r"the registration is recorded as initiated")
def step_then_registration_initiated(context):
    _assert_event(context, "RegistrationInitiated")


@then(r"the registration is recorded as completed")
def step_then_registration_completed(context):
    _assert_event(context, "RegistrationCompleted")


@then(r"the registration is refused because registration is closed")
def step_then_registration_refused_closed(context):
    _assert_any_failure(context, "RegistrationFailed")


@then(r"the registration is refused because enrollment was rejected")
def step_then_registration_refused_enrollment(context):
    _assert_any_failure(context, "RegistrationFailed")


@then(r"the rebuy is recorded as initiated")
def step_then_rebuy_initiated(context):
    _assert_event(context, "RebuyInitiated")


@then(r"the rebuy is recorded as completed")
def step_then_rebuy_completed(context):
    _assert_event(context, "RebuyCompleted")


@then(r"the rebuy is refused because the tournament is not currently running")
def step_then_rebuy_refused_not_running(context):
    _assert_any_failure(context, "RebuyFailed")


@then(r"the rebuy is refused because (?P<name>\w+) is not seated")
def step_then_rebuy_refused_not_seated(context, name):
    _assert_any_failure(context, "RebuyFailed")


@then(r"the rebuy is refused because the rebuy was denied")
def step_then_rebuy_refused_denied(context):
    _assert_any_failure(context, "RebuyFailed")
