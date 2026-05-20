"""Step definitions for orchestration BDD tests.

Drives the production ``reservation.pmg.handlers.ReservationPM`` through
its real handler methods. A ``FakeQueryClient`` holds in-memory event
books seeded from the Given steps; the PM queries it synchronously for
cross-aggregate pre-validation and emits the real ``*Failed`` /
``*Initiated`` / ``*Completed`` events.

Mirrors the Rust ``orchestration.rs`` test target.
"""

import importlib.util
import sys
from pathlib import Path

from behave import given, then, use_step_matcher, when

from tests.helpers import uuid_for
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import orchestration_pb2 as orch
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import table_pb2 as table_proto
from angzarr_client.proto.examples import tournament_pb2 as tournament
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
    """``type.googleapis.com/angzarr_client.proto.examples.SeatPlayer`` → ``SeatPlayer``."""
    return type_url.rsplit(".", 1)[-1]


_FAILED_PROTO_BY_NAME = {
    "BuyInFailed": buy_in.BuyInFailed,
    "RebuyFailed": rebuy.RebuyFailed,
    "RegistrationFailed": registration.RegistrationFailed,
}


def _record_response(context, response) -> None:
    """Translate a real ProcessManagerResponse into the legacy context shape.

    Existing @then steps assert against:
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
# BuyInOrchestrator - Given steps
# =============================================================================


@given(
    r"a table with seat (?P<seat>\d+) available and buy-in range (?P<min>\d+)-(?P<max>\d+)"
)
def step_given_table_seat_available_with_range(context, seat, min, max):
    """Set up a table with a specific seat available and buy-in range."""
    _init_orchestration_context(context)
    context.table_min_buy_in = int(min)
    context.table_max_buy_in = int(max)
    context.table_max_players = 9
    context.occupied_seats = {}
    context.table_root = b"table-1"
    context.available_seat = int(seat)


@given(
    r"a player with a BuyInRequested event for seat (?P<seat>\d+) with amount (?P<amount>\d+)"
)
def step_given_buy_in_requested_for_seat(context, seat, amount):
    """Create a BuyInRequested event for a specific seat and amount."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
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


@given(r"a table with seat (?P<seat>\d+) occupied by another player")
def step_given_seat_occupied(context, seat):
    """Set up a table where a specific seat is already occupied."""
    _init_orchestration_context(context)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9
    context.occupied_seats = {int(seat): b"other-player"}
    context.table_root = b"table-1"


@given(r"a table that is full with (?P<count>\d+) players")
def step_given_table_full(context, count):
    """Set up a table that is full."""
    _init_orchestration_context(context)
    num_players = int(count)
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = num_players
    context.occupied_seats = {i: uuid_for(f"player-{i}") for i in range(num_players)}
    context.table_root = b"table-1"


@given(r"a player with a BuyInRequested event for any seat with amount (?P<amount>\d+)")
def step_given_buy_in_requested_any_seat(context, amount):
    """Create a BuyInRequested event for any available seat."""
    _init_orchestration_context(context)
    context.player_root = b"player-new"
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


@given(r"a player and table in a pending buy-in state")
def step_given_pending_buy_in(context):
    """Set up a player and table in a pending buy-in state (seating phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.buy_in_amount = 500
    context.buy_in_seat = 0
    context.buy_in_phase = orch.BuyInPhase.BUY_IN_SEATING


# =============================================================================
# RegistrationOrchestrator - Given steps
# =============================================================================


@given(r"a tournament with registration open and capacity available")
def step_given_tournament_open_with_capacity(context):
    """Set up a tournament with open registration and available capacity."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = True
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r"a player with a RegistrationRequested event with fee (?P<fee>\d+)")
def step_given_registration_requested(context, fee):
    """Create a RegistrationRequested event with a specific fee."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.reservation_id = b"res-001"
    context.registration_fee = int(fee)
    context.registration_event = registration.RegistrationRequested(
        reservation_id=context.reservation_id,
        player_root=context.player_root,
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        fee=poker.Currency(amount=int(fee), currency_code="USD"),
    )


@given(r"a tournament that is full")
def step_given_tournament_full(context):
    """Set up a tournament that has reached max capacity."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = True
    context.tournament_max_players = 4
    context.tournament_registered_count = 4
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


@given(r"a tournament with registration closed")
def step_given_tournament_registration_closed(context):
    """Set up a tournament with closed registration."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_registration_open = False
    context.tournament_max_players = 100
    context.tournament_registered_count = 50
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING


@given(r"a player and tournament in a pending registration state")
def step_given_pending_registration(context):
    """Set up a player and tournament in pending registration (enrolling phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.reservation_id = b"res-001"
    context.registration_fee = 1000
    context.registration_phase = orch.RegistrationPhase.REGISTRATION_ENROLLING


# =============================================================================
# RebuyOrchestrator - Given steps
# =============================================================================


@given(r"a tournament in rebuy window with player eligible")
def step_given_tournament_rebuy_eligible(context):
    """Set up a tournament in rebuy window where the player is eligible."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    context.rebuy_window_open = True
    context.player_eligible_for_rebuy = True


@given(r"a table with the player seated at position (?P<pos>\d+)")
def step_given_player_seated_at_position(context, pos):
    """Set up table state with the player seated at a specific position."""
    _init_orchestration_context(context)
    context.table_root = b"table-1"
    context.player_root = b"player-1"
    context.player_seat_position = int(pos)
    context.player_is_seated = True
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9


@given(r"a player with a RebuyRequested event for amount (?P<amount>\d+)")
def step_given_rebuy_requested(context, amount):
    """Create a RebuyRequested event for a specific amount."""
    _init_orchestration_context(context)
    context.reservation_id = b"res-001"
    context.rebuy_amount = int(amount)
    context.rebuy_event = rebuy.RebuyRequested(
        reservation_id=context.reservation_id,
        player_root=getattr(context, "player_root", b"player-1"),
        tournament_root=getattr(context, "tournament_root", b"tournament-1"),
        table_root=getattr(context, "table_root", b"table-1"),
        seat=getattr(context, "player_seat_position", 2),
        fee=poker.Currency(amount=int(amount), currency_code="USD"),
    )


@given(r"a tournament with rebuy window closed")
def step_given_rebuy_window_closed(context):
    """Set up a tournament where the rebuy window is closed."""
    _init_orchestration_context(context)
    context.tournament_root = b"tournament-1"
    context.tournament_status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    context.rebuy_window_open = False
    context.player_eligible_for_rebuy = False


@given(r"a table without the player seated")
def step_given_player_not_seated(context):
    """Set up table state where the player is not seated."""
    _init_orchestration_context(context)
    context.table_root = b"table-1"
    context.player_root = b"player-1"
    context.player_is_seated = False
    context.player_seat_position = -1
    context.table_min_buy_in = 200
    context.table_max_buy_in = 2000
    context.table_max_players = 9


@given(r"a player, tournament, and table in a pending rebuy state")
def step_given_pending_rebuy(context):
    """Set up all three domains in a pending rebuy state (approving phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_APPROVING


@given(r"a player, tournament, and table with chips added")
def step_given_rebuy_chips_added(context):
    """Set up all three domains after chips have been added (adding_chips phase)."""
    _init_orchestration_context(context)
    context.player_root = b"player-1"
    context.tournament_root = b"tournament-1"
    context.table_root = b"table-1"
    context.reservation_id = b"res-001"
    context.rebuy_amount = 1000
    context.player_seat_position = 2
    context.rebuy_phase = orch.RebuyPhase.REBUY_ADDING_CHIPS


# =============================================================================
# BuyInOrchestrator - When steps (dispatch through production ReservationPM)
# =============================================================================


@when(r"the BuyInOrchestrator handles the BuyInRequested event")
def step_when_buy_in_orchestrator_handles_request(context):
    """Dispatch BuyInRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_BUY_IN)
    response = pm.on_buy_in_requested(context.buy_in_event, state, destinations=None)
    _record_response(context, response)


@when(r"the BuyInOrchestrator handles a PlayerSeated event")
def step_when_buy_in_handles_player_seated(context):
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


@when(r"the BuyInOrchestrator handles a SeatingRejected event")
def step_when_buy_in_handles_seating_rejected(context):
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


# =============================================================================
# RegistrationOrchestrator - When steps
# =============================================================================


@when(r"the RegistrationOrchestrator handles the RegistrationRequested event")
def step_when_registration_orchestrator_handles_request(context):
    """Dispatch RegistrationRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REGISTRATION)
    response = pm.on_registration_requested(
        context.registration_event, state, destinations=None
    )
    _record_response(context, response)


@when(r"the RegistrationOrchestrator handles a TournamentPlayerEnrolled event")
def step_when_registration_handles_enrolled(context):
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


@when(r"the RegistrationOrchestrator handles a TournamentEnrollmentRejected event")
def step_when_registration_handles_rejected(context):
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


# =============================================================================
# RebuyOrchestrator - When steps
# =============================================================================


@when(r"the RebuyOrchestrator handles the RebuyRequested event")
def step_when_rebuy_orchestrator_handles_request(context):
    """Dispatch RebuyRequested through the production PM."""
    pm = _build_pm(context)
    state = _state_for(context, KIND_REBUY)
    response = pm.on_rebuy_requested(context.rebuy_event, state, destinations=None)
    _record_response(context, response)


@when(r"the RebuyOrchestrator handles a RebuyProcessed event")
def step_when_rebuy_handles_processed(context):
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


@when(r"the RebuyOrchestrator handles a RebuyChipsAdded event")
def step_when_rebuy_handles_chips_added(context):
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


@when(r"the RebuyOrchestrator handles a RebuyDenied event")
def step_when_rebuy_handles_denied(context):
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
# Then steps - Command assertions
# =============================================================================


def _assert_emitted(context, name: str) -> None:
    assert (
        name in context.emitted_commands
    ), f"Expected {name}, got {context.emitted_commands}"


_RELEASE_COMPENSATIONS = {"ReleaseBuyIn", "ReleaseRebuyFee", "ReleaseRegistrationFee"}


@then(r"the PM emits a SeatPlayer command to the table")
def step_then_pm_emits_seat_player(context):
    _assert_emitted(context, "SeatPlayer")


@then(r"the PM emits a ConfirmBuyIn command to the player")
def step_then_pm_emits_confirm_buy_in(context):
    _assert_emitted(context, "ConfirmBuyIn")


@then(r"the PM emits a ReleaseBuyIn command to the player")
def step_then_pm_emits_release_buy_in(context):
    _assert_emitted(context, "ReleaseBuyIn")


@then(r"the PM emits an EnrollPlayer command to the tournament")
def step_then_pm_emits_enroll_player(context):
    _assert_emitted(context, "EnrollPlayer")


@then(r"the PM emits a ConfirmRegistrationFee command to the player")
def step_then_pm_emits_confirm_registration(context):
    _assert_emitted(context, "ConfirmRegistrationFee")


@then(r"the PM emits a ReleaseRegistrationFee command to the player")
def step_then_pm_emits_release_registration(context):
    _assert_emitted(context, "ReleaseRegistrationFee")


@then(r"the PM emits a ProcessRebuy command to the tournament")
def step_then_pm_emits_process_rebuy(context):
    _assert_emitted(context, "ProcessRebuy")


@then(r"the PM emits an AddRebuyChips command to the table")
def step_then_pm_emits_add_rebuy_chips(context):
    _assert_emitted(context, "AddRebuyChips")


@then(r"the PM emits a ConfirmRebuyFee command to the player")
def step_then_pm_emits_confirm_rebuy(context):
    _assert_emitted(context, "ConfirmRebuyFee")


@then(r"the PM emits a ReleaseRebuyFee command to the player")
def step_then_pm_emits_release_rebuy(context):
    _assert_emitted(context, "ReleaseRebuyFee")


@then(r"the PM emits no commands")
def step_then_pm_emits_no_commands(context):
    """No workflow-advancing commands.

    The PM still emits a Release* compensation to the reservation aggregate
    on early validation failure (the only allowed command); state changes
    against player/table/tournament must not occur.
    """
    workflow_cmds = [
        c for c in context.emitted_commands if c not in _RELEASE_COMPENSATIONS
    ]
    assert not workflow_cmds, f"Expected no workflow commands, got {workflow_cmds}"


# =============================================================================
# Then steps - Process event assertions
# =============================================================================


def _assert_event(context, name: str) -> None:
    names = [n for n, _ in context.emitted_events]
    assert name in names, f"Expected {name} event, got {names}"


def _assert_failure_code(context, event_name: str, code: str) -> None:
    matches = [(n, c) for n, c in context.emitted_events if n == event_name]
    assert (
        matches
    ), f"Expected {event_name} event, got {[n for n, _ in context.emitted_events]}"
    assert matches[0][1] == code, f"Expected code '{code}', got '{matches[0][1]}'"


@then(r"the PM emits a BuyInInitiated process event")
def step_then_pm_emits_buy_in_initiated(context):
    _assert_event(context, "BuyInInitiated")


@then(r'the PM emits a BuyInFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_buy_in_failed(context, code):
    _assert_failure_code(context, "BuyInFailed", code)


@then(r"the PM emits a BuyInCompleted process event")
def step_then_pm_emits_buy_in_completed(context):
    _assert_event(context, "BuyInCompleted")


@then(r"the PM emits a RegistrationInitiated process event")
def step_then_pm_emits_registration_initiated(context):
    _assert_event(context, "RegistrationInitiated")


@then(r'the PM emits a RegistrationFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_registration_failed(context, code):
    _assert_failure_code(context, "RegistrationFailed", code)


@then(r"the PM emits a RegistrationCompleted process event")
def step_then_pm_emits_registration_completed(context):
    _assert_event(context, "RegistrationCompleted")


@then(r"the PM emits a RebuyInitiated process event")
def step_then_pm_emits_rebuy_initiated(context):
    _assert_event(context, "RebuyInitiated")


@then(r'the PM emits a RebuyFailed process event with code "(?P<code>[^"]+)"')
def step_then_pm_emits_rebuy_failed(context, code):
    _assert_failure_code(context, "RebuyFailed", code)


@then(r"the PM emits a RebuyCompleted process event")
def step_then_pm_emits_rebuy_completed(context):
    _assert_event(context, "RebuyCompleted")
