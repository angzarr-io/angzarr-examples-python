"""Orchestration (process manager) unit tests.

Wires ``features/specs/unit/orchestration.feature`` into pytest-bdd so the
18 scenarios covering BuyIn / Registration / Rebuy process managers execute
against the real PM classes from ``buy_in/pmg/``, ``registration/pmg/``,
``rebuy/pmg/``.

Each scenario's ``Given`` step seeds a fake ``QueryClient`` with the target
aggregate's event history (TableCreated, TournamentCreated, etc). The PM
reads that state via ``self.query.query(domain, root).get_event_book()``
and pre-validates before emitting commands — matching the "PMs call target
domains synchronously for decisioning" design.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from google.protobuf.any_pb2 import Any as ProtoAny
from pytest_bdd import given, parsers, scenarios, then, when

# Register PM source dirs so ``from handlers import ...`` inside each PM
# resolves. Also required for the state.py siblings they import.
_REPO = Path(__file__).parent.parent.parent
for rel in (
    "buy_in/pmg",
    "rebuy/pmg",
    "registration/pmg",
):
    sys.path.insert(0, str(_REPO / rel))

from angzarr_client import Destinations
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import buy_in_pb2 as buy_in
from angzarr_client.proto.examples import poker_types_pb2 as poker
from angzarr_client.proto.examples import rebuy_pb2 as rebuy
from angzarr_client.proto.examples import registration_pb2 as registration
from angzarr_client.proto.examples import table_pb2 as table
from angzarr_client.proto.examples import tournament_pb2 as tournament

# PM imports (buy_in/pmg first so its handlers shadow any collision first)
import importlib


def _load(module_dir: str, module_name: str):
    """Load a module by file path, bypassing the shared ``handlers`` / ``state``
    namespaces so the three PMs can co-exist in one process."""
    path = _REPO / module_dir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"_orch_{module_dir.replace('/', '_')}_{module_name}", path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Prime sys.modules so relative imports inside each PM resolve.
    orig_state = sys.modules.get("state")
    orig_handlers = sys.modules.get("handlers")
    orig_table_state = sys.modules.get("table_state")
    orig_tournament_state = sys.modules.get("tournament_state")
    try:
        for sib in ("state", "table_state", "tournament_state"):
            sys.modules.pop(sib, None)
        sys.path.insert(0, str(_REPO / module_dir))
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(_REPO / module_dir))
        if orig_state is not None:
            sys.modules["state"] = orig_state
        if orig_handlers is not None:
            sys.modules["handlers"] = orig_handlers
        if orig_table_state is not None:
            sys.modules["table_state"] = orig_table_state
        if orig_tournament_state is not None:
            sys.modules["tournament_state"] = orig_tournament_state
    return mod


_buyin = _load("buy_in/pmg", "handlers")
_buyin_state = _load("buy_in/pmg", "state")
_registration = _load("registration/pmg", "handlers")
_registration_state_mod = _load("registration/pmg", "state")
_rebuy = _load("rebuy/pmg", "handlers")
_rebuy_state_mod = _load("rebuy/pmg", "state")

BuyInPM = _buyin.BuyInPM
BuyInState = _buyin_state.BuyInState
RegistrationPM = _registration.RegistrationPM
RegistrationState = _registration_state_mod.RegistrationState
RebuyPM = _rebuy.RebuyPM
RebuyState = _rebuy_state_mod.RebuyState


scenarios("../../features/specs/unit/orchestration.feature")


# --------------------------------------------------------------------------
# Fake QueryClient
# --------------------------------------------------------------------------


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _event_book(domain: str, root: bytes, events: list) -> types.EventBook:
    book = types.EventBook(
        cover=types.Cover(domain=domain, root=types.UUID(value=root)),
    )
    for ev in events:
        book.pages.append(types.EventPage(event=_pack(ev)))
    return book


class _FakeQueryBuilder:
    def __init__(self, book: types.EventBook):
        self._book = book

    def get_event_book(self) -> types.EventBook:
        return self._book


class FakeQueryClient:
    """Pre-seeded read-only query client for orchestration scenarios."""

    def __init__(self):
        # {(domain, root_hex): EventBook}
        self._books: dict[tuple[str, str], types.EventBook] = {}

    def seed(self, domain: str, root: bytes, events: list) -> None:
        self._books[(domain, root.hex())] = _event_book(domain, root, events)

    def query(self, domain: str, root: bytes) -> _FakeQueryBuilder:
        key = (domain, root.hex() if isinstance(root, bytes) else bytes(root).hex())
        return _FakeQueryBuilder(self._books.get(key, types.EventBook()))


# --------------------------------------------------------------------------
# Scenario context
# --------------------------------------------------------------------------


PLAYER_ROOT = b"\x01" * 16
OTHER_PLAYER_ROOT = b"\x02" * 16
TABLE_ROOT = b"\x03" * 16
TOURNAMENT_ROOT = b"\x04" * 16
RESERVATION_ID = b"\x05" * 16


@dataclass
class OrchWorld:
    query: FakeQueryClient = field(default_factory=FakeQueryClient)
    trigger_event: object = None
    source_cover: types.Cover = None
    pm_response: object = None


@pytest.fixture
def world() -> OrchWorld:
    return OrchWorld()


# --------------------------------------------------------------------------
# Assertion helpers
# --------------------------------------------------------------------------


def _response_command_types(response) -> list[str]:
    out = []
    for book in response.commands or []:
        for page in book.pages:
            if page.HasField("command"):
                out.append(page.command.type_url.split("/")[-1])
    return out


def _response_event_types(response) -> list[str]:
    out = []
    book = response.process_events
    if book is None:
        return out
    for page in book.pages:
        if page.HasField("event"):
            out.append(page.event.type_url.split("/")[-1])
    return out


def _first_process_event(response, proto_cls):
    book = response.process_events
    if book is None:
        return None
    for page in book.pages:
        if not page.HasField("event"):
            continue
        if page.event.type_url.endswith(proto_cls.DESCRIPTOR.full_name):
            evt = proto_cls()
            page.event.Unpack(evt)
            return evt
    return None


# ==========================================================================
# BuyIn — Given
# ==========================================================================


@given(parsers.parse("a table with seat {seat:d} available and buy-in range {lo:d}-{hi:d}"))
def _buyin_table_available(world: OrchWorld, seat: int, lo: int, hi: int):
    created = table.TableCreated(
        table_name="Test Table",
        game_variant=0,
        small_blind=5,
        big_blind=10,
        min_buy_in=lo,
        max_buy_in=hi,
        max_players=9,
        action_timeout_seconds=30,
    )
    world.query.seed("table", TABLE_ROOT, [created])


@given(parsers.parse("a player with a BuyInRequested event for seat {seat:d} with amount {amount:d}"))
def _buyin_player_event(world: OrchWorld, seat: int, amount: int):
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )
    world.trigger_event = buy_in.BuyInRequested(
        reservation_id=RESERVATION_ID,
        table_root=TABLE_ROOT,
        seat=seat,
        amount=poker.Currency(amount=amount, currency_code="USD"),
    )


@given(parsers.parse("a player with a BuyInRequested event for any seat with amount {amount:d}"))
def _buyin_player_event_any_seat(world: OrchWorld, amount: int):
    # Seat 0 is the canonical "any available seat" — tests for TABLE_FULL
    # seed every seat so no position succeeds.
    _buyin_player_event(world, 0, amount)


@given(parsers.parse("a table with seat {seat:d} occupied by another player"))
def _buyin_table_seat_occupied(world: OrchWorld, seat: int):
    created = table.TableCreated(
        table_name="Test Table",
        game_variant=0,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=2000,
        max_players=9,
        action_timeout_seconds=30,
    )
    joined = table.PlayerJoined(
        player_root=OTHER_PLAYER_ROOT,
        seat_position=seat,
        buy_in_amount=500,
        stack=500,
    )
    world.query.seed("table", TABLE_ROOT, [created, joined])


@given("a table that is full with 9 players")
def _buyin_table_full(world: OrchWorld):
    created = table.TableCreated(
        table_name="Test Table",
        game_variant=0,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=2000,
        max_players=9,
        action_timeout_seconds=30,
    )
    events = [created]
    for i in range(9):
        events.append(
            table.PlayerJoined(
                player_root=bytes([0x20 + i]) * 16,
                seat_position=i,
                buy_in_amount=500,
                stack=500,
            )
        )
    world.query.seed("table", TABLE_ROOT, events)


@given("a player and table in a pending buy-in state")
def _buyin_pending(world: OrchWorld):
    # No query lookup needed — PlayerSeated / SeatingRejected handlers are
    # pure translators that don't re-query the aggregates.
    world.source_cover = types.Cover(
        domain="table", root=types.UUID(value=TABLE_ROOT)
    )


# ==========================================================================
# BuyIn — When
# ==========================================================================


@when("the BuyInOrchestrator handles the BuyInRequested event")
def _buyin_handle_requested(world: OrchWorld):
    pm = BuyInPM(query_client=world.query)
    world.pm_response = pm.handle_buy_in_requested(
        world.trigger_event,
        state=BuyInState(),
        destinations=Destinations({"table": 0}),
        source_cover=world.source_cover,
    )


@when("the BuyInOrchestrator handles a PlayerSeated event")
def _buyin_handle_seated(world: OrchWorld):
    pm = BuyInPM(query_client=world.query)
    event = buy_in.PlayerSeated(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        seat_position=0,
        stack=500,
    )
    world.pm_response = pm.handle_player_seated(
        event,
        state=BuyInState(),
        destinations=Destinations({"player": 0}),
    )


@when("the BuyInOrchestrator handles a SeatingRejected event")
def _buyin_handle_rejected(world: OrchWorld):
    pm = BuyInPM(query_client=world.query)
    event = buy_in.SeatingRejected(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        requested_seat=0,
        reason="Seat taken by another player",
    )
    world.pm_response = pm.handle_seating_rejected(
        event,
        state=BuyInState(),
        destinations=Destinations({"player": 0}),
    )


# ==========================================================================
# Registration — Given
# ==========================================================================


@given("a tournament with registration open and capacity available")
def _tour_open(world: OrchWorld):
    created = tournament.TournamentCreated(
        name="Test Tournament",
        buy_in=1000,
        starting_stack=5000,
        max_players=100,
        min_players=2,
    )
    opened = tournament.RegistrationOpened()
    world.query.seed("tournament", TOURNAMENT_ROOT, [created, opened])
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )


@given(parsers.parse("a player with a RegistrationRequested event with fee {fee:d}"))
def _reg_player_event(world: OrchWorld, fee: int):
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )
    world.trigger_event = registration.RegistrationRequested(
        reservation_id=RESERVATION_ID,
        tournament_root=TOURNAMENT_ROOT,
        fee=poker.Currency(amount=fee, currency_code="USD"),
    )


@given("a tournament that is full")
def _tour_full(world: OrchWorld):
    created = tournament.TournamentCreated(
        name="Full Tournament",
        buy_in=1000,
        starting_stack=5000,
        max_players=2,
        min_players=2,
    )
    events = [created, tournament.RegistrationOpened()]
    # Enroll max_players to fill it.
    for i in range(2):
        events.append(
            tournament.TournamentPlayerEnrolled(
                player_root=bytes([0x30 + i]) * 16,
                reservation_id=bytes([0x40 + i]) * 16,
                fee_paid=1000,
                starting_stack=5000,
                registration_number=i + 1,
            )
        )
    world.query.seed("tournament", TOURNAMENT_ROOT, events)


@given("a tournament with registration closed")
def _tour_closed(world: OrchWorld):
    created = tournament.TournamentCreated(
        name="Closed Tournament",
        buy_in=1000,
        starting_stack=5000,
        max_players=100,
        min_players=2,
    )
    closed = tournament.RegistrationClosed()
    world.query.seed("tournament", TOURNAMENT_ROOT, [created, closed])


@given("a player and tournament in a pending registration state")
def _reg_pending(world: OrchWorld):
    world.source_cover = types.Cover(
        domain="tournament", root=types.UUID(value=TOURNAMENT_ROOT)
    )


# ==========================================================================
# Registration — When
# ==========================================================================


@when("the RegistrationOrchestrator handles the RegistrationRequested event")
def _reg_handle_requested(world: OrchWorld):
    pm = RegistrationPM(query_client=world.query)
    world.pm_response = pm.handle_registration_requested(
        world.trigger_event,
        state=RegistrationState(),
        destinations=Destinations({"tournament": 0}),
        source_cover=world.source_cover,
    )


@when("the RegistrationOrchestrator handles a TournamentPlayerEnrolled event")
def _reg_handle_enrolled(world: OrchWorld):
    pm = RegistrationPM(query_client=world.query)
    event = tournament.TournamentPlayerEnrolled(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        fee_paid=1000,
        starting_stack=5000,
        registration_number=1,
    )
    state = RegistrationState(
        player_root=PLAYER_ROOT,
        tournament_root=TOURNAMENT_ROOT,
        fee=1000,
    )
    world.pm_response = pm.handle_player_enrolled(
        event, state=state, destinations=Destinations({"player": 0})
    )


@when("the RegistrationOrchestrator handles a TournamentEnrollmentRejected event")
def _reg_handle_rejected(world: OrchWorld):
    pm = RegistrationPM(query_client=world.query)
    event = tournament.TournamentEnrollmentRejected(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        reason="Tournament full",
    )
    state = RegistrationState(
        player_root=PLAYER_ROOT,
        tournament_root=TOURNAMENT_ROOT,
        fee=1000,
    )
    world.pm_response = pm.handle_enrollment_rejected(
        event, state=state, destinations=Destinations({"player": 0})
    )


# ==========================================================================
# Rebuy — Given
# ==========================================================================


def _tournament_running_with_rebuy(enabled: bool) -> list:
    created = tournament.TournamentCreated(
        name="Running Tournament",
        buy_in=1000,
        starting_stack=5000,
        max_players=100,
        min_players=2,
        rebuy_config=tournament.RebuyConfig(
            enabled=enabled,
            max_rebuys=3,
            rebuy_level_cutoff=3,
            stack_threshold=2500,
            rebuy_cost=1000,
            rebuy_chips=5000,
        ),
    )
    enrolled = tournament.TournamentPlayerEnrolled(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        fee_paid=1000,
        starting_stack=5000,
        registration_number=1,
    )
    started = tournament.TournamentStarted(
        total_players=1,
        tables_created=1,
        total_prize_pool=5000,
    )
    return [created, enrolled, started]


@given("a tournament in rebuy window with player eligible")
def _tour_rebuy_open(world: OrchWorld):
    world.query.seed(
        "tournament", TOURNAMENT_ROOT, _tournament_running_with_rebuy(True)
    )
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )


@given("a tournament with rebuy window closed")
def _tour_rebuy_closed(world: OrchWorld):
    world.query.seed(
        "tournament", TOURNAMENT_ROOT, _tournament_running_with_rebuy(False)
    )
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )


@given(parsers.parse("a table with the player seated at position {seat:d}"))
def _tbl_player_seated(world: OrchWorld, seat: int):
    created = table.TableCreated(
        table_name="Rebuy Table",
        game_variant=0,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=2000,
        max_players=9,
        action_timeout_seconds=30,
    )
    joined = table.PlayerJoined(
        player_root=PLAYER_ROOT, seat_position=seat, buy_in_amount=500, stack=500
    )
    world.query.seed("table", TABLE_ROOT, [created, joined])


@given("a table without the player seated")
def _tbl_player_not_seated(world: OrchWorld):
    created = table.TableCreated(
        table_name="Rebuy Table",
        game_variant=0,
        small_blind=5,
        big_blind=10,
        min_buy_in=200,
        max_buy_in=2000,
        max_players=9,
        action_timeout_seconds=30,
    )
    world.query.seed("table", TABLE_ROOT, [created])


@given(parsers.parse("a player with a RebuyRequested event for amount {amount:d}"))
def _rebuy_player_event(world: OrchWorld, amount: int):
    world.source_cover = types.Cover(
        domain="player", root=types.UUID(value=PLAYER_ROOT)
    )
    world.trigger_event = rebuy.RebuyRequested(
        reservation_id=RESERVATION_ID,
        tournament_root=TOURNAMENT_ROOT,
        table_root=TABLE_ROOT,
        seat=2,
        fee=poker.Currency(amount=amount, currency_code="USD"),
    )


@given("a player, tournament, and table in a pending rebuy state")
def _rebuy_pending(world: OrchWorld):
    world.source_cover = types.Cover(
        domain="tournament", root=types.UUID(value=TOURNAMENT_ROOT)
    )


@given("a player, tournament, and table with chips added")
def _rebuy_chips_added_state(world: OrchWorld):
    world.source_cover = types.Cover(
        domain="table", root=types.UUID(value=TABLE_ROOT)
    )


# ==========================================================================
# Rebuy — When
# ==========================================================================


@when("the RebuyOrchestrator handles the RebuyRequested event")
def _rebuy_handle_requested(world: OrchWorld):
    pm = RebuyPM(query_client=world.query)
    world.pm_response = pm.handle_rebuy_requested(
        world.trigger_event,
        state=RebuyState(),
        destinations=Destinations({"tournament": 0, "table": 0}),
        source_cover=world.source_cover,
    )


@when("the RebuyOrchestrator handles a RebuyProcessed event")
def _rebuy_handle_processed(world: OrchWorld):
    pm = RebuyPM(query_client=world.query)
    event = tournament.RebuyProcessed(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        rebuy_cost=1000,
        chips_added=5000,
        rebuy_count=1,
    )
    state = RebuyState(
        player_root=PLAYER_ROOT,
        tournament_root=TOURNAMENT_ROOT,
        table_root=TABLE_ROOT,
        reservation_id=RESERVATION_ID,
        seat=2,
        fee=1000,
    )
    world.pm_response = pm.handle_rebuy_processed(
        event, state=state, destinations=Destinations({"table": 0})
    )


@when("the RebuyOrchestrator handles a RebuyChipsAdded event")
def _rebuy_handle_chips_added(world: OrchWorld):
    pm = RebuyPM(query_client=world.query)
    event = rebuy.RebuyChipsAdded(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        seat=2,
        amount=5000,
        new_stack=5500,
    )
    state = RebuyState(
        player_root=PLAYER_ROOT,
        tournament_root=TOURNAMENT_ROOT,
        table_root=TABLE_ROOT,
        reservation_id=RESERVATION_ID,
        seat=2,
        fee=1000,
    )
    world.pm_response = pm.handle_chips_added(
        event, state=state, destinations=Destinations({"player": 0})
    )


@when("the RebuyOrchestrator handles a RebuyDenied event")
def _rebuy_handle_denied(world: OrchWorld):
    pm = RebuyPM(query_client=world.query)
    event = tournament.RebuyDenied(
        player_root=PLAYER_ROOT,
        reservation_id=RESERVATION_ID,
        reason="Rebuy limit reached",
    )
    state = RebuyState(
        player_root=PLAYER_ROOT,
        tournament_root=TOURNAMENT_ROOT,
        table_root=TABLE_ROOT,
        reservation_id=RESERVATION_ID,
        seat=2,
        fee=1000,
    )
    world.pm_response = pm.handle_rebuy_denied(
        event, state=state, destinations=Destinations({"player": 0})
    )


# ==========================================================================
# Then steps — command assertions
# ==========================================================================


@then("the PM emits a SeatPlayer command to the table")
def _then_emits_seat_player(world: OrchWorld):
    assert "examples.SeatPlayer" in _response_command_types(world.pm_response)


@then("the PM emits an EnrollPlayer command to the tournament")
def _then_emits_enroll_player(world: OrchWorld):
    assert "examples.EnrollPlayer" in _response_command_types(world.pm_response)


@then("the PM emits a ProcessRebuy command to the tournament")
def _then_emits_process_rebuy(world: OrchWorld):
    assert "examples.ProcessRebuy" in _response_command_types(world.pm_response)


@then("the PM emits a ConfirmBuyIn command to the player")
def _then_emits_confirm_buy_in(world: OrchWorld):
    assert "examples.ConfirmBuyIn" in _response_command_types(world.pm_response)


@then("the PM emits a ReleaseBuyIn command to the player")
def _then_emits_release_buy_in(world: OrchWorld):
    assert "examples.ReleaseBuyIn" in _response_command_types(world.pm_response)


@then("the PM emits a ConfirmRegistrationFee command to the player")
def _then_emits_confirm_registration(world: OrchWorld):
    assert "examples.ConfirmRegistrationFee" in _response_command_types(
        world.pm_response
    )


@then("the PM emits a ReleaseRegistrationFee command to the player")
def _then_emits_release_registration(world: OrchWorld):
    assert "examples.ReleaseRegistrationFee" in _response_command_types(
        world.pm_response
    )


@then("the PM emits an AddRebuyChips command to the table")
def _then_emits_add_rebuy_chips(world: OrchWorld):
    assert "examples.AddRebuyChips" in _response_command_types(world.pm_response)


@then("the PM emits a ConfirmRebuyFee command to the player")
def _then_emits_confirm_rebuy(world: OrchWorld):
    assert "examples.ConfirmRebuyFee" in _response_command_types(world.pm_response)


@then("the PM emits a ReleaseRebuyFee command to the player")
def _then_emits_release_rebuy(world: OrchWorld):
    assert "examples.ReleaseRebuyFee" in _response_command_types(world.pm_response)


@then("the PM emits no commands")
def _then_no_commands(world: OrchWorld):
    assert _response_command_types(world.pm_response) == []


# ==========================================================================
# Then steps — process-event assertions
# ==========================================================================


@then("the PM emits a BuyInInitiated process event")
def _then_buyin_initiated(world: OrchWorld):
    assert "examples.BuyInInitiated" in _response_event_types(world.pm_response)


@then("the PM emits a BuyInCompleted process event")
def _then_buyin_completed(world: OrchWorld):
    assert "examples.BuyInCompleted" in _response_event_types(world.pm_response)


@then(parsers.parse('the PM emits a BuyInFailed process event with code "{code}"'))
def _then_buyin_failed(world: OrchWorld, code: str):
    failed = _first_process_event(world.pm_response, buy_in.BuyInFailed)
    assert failed is not None, "no BuyInFailed event emitted"
    assert failed.failure.code == code


@then("the PM emits a RegistrationInitiated process event")
def _then_registration_initiated(world: OrchWorld):
    assert "examples.RegistrationInitiated" in _response_event_types(
        world.pm_response
    )


@then("the PM emits a RegistrationCompleted process event")
def _then_registration_completed(world: OrchWorld):
    assert "examples.RegistrationCompleted" in _response_event_types(
        world.pm_response
    )


@then(parsers.parse('the PM emits a RegistrationFailed process event with code "{code}"'))
def _then_registration_failed(world: OrchWorld, code: str):
    failed = _first_process_event(world.pm_response, registration.RegistrationFailed)
    assert failed is not None, "no RegistrationFailed event emitted"
    assert failed.failure.code == code


@then("the PM emits a RebuyInitiated process event")
def _then_rebuy_initiated(world: OrchWorld):
    assert "examples.RebuyInitiated" in _response_event_types(world.pm_response)


@then("the PM emits a RebuyCompleted process event")
def _then_rebuy_completed(world: OrchWorld):
    assert "examples.RebuyCompleted" in _response_event_types(world.pm_response)


@then(parsers.parse('the PM emits a RebuyFailed process event with code "{code}"'))
def _then_rebuy_failed(world: OrchWorld, code: str):
    failed = _first_process_event(world.pm_response, rebuy.RebuyFailed)
    assert failed is not None, "no RebuyFailed event emitted"
    assert failed.failure.code == code
