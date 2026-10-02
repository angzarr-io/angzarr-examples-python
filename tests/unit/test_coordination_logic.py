"""The coordinating components' contracts that features do not spell out:
emitted commands are deferred with no correlation id or sequence, PM commands
are decided synchronously, facts carry their external id, and the ledger
applies each event once."""

from contextlib import closing

import angzarr_client.router as _az
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import buy_in_pb2 as _b
from angzarr_blackjack._gen.io.angzarr.examples.v1 import ledger_pb2 as _l
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_client.proto.io.angzarr.v1 import upcaster_pb2 as _up
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.player.agg.upcaster import PlayerUpcaster, upcast_book
from angzarr_blackjack.player.saga_table.handler import PlayerTableSaga
from angzarr_blackjack.pmg_buy_in.handler import BuyInProcessManager
from angzarr_blackjack._runtime.inprocess import InProcess
from angzarr_blackjack.table.saga_player.handler import (
    TablePlayerHistorySaga,
    TablePlayerLoyaltySaga,
    TablePlayerSettlementSaga,
)

TABLE, ALICE, BOB = b"\x01" * 16, b"\x0a" * 16, b"\x0b" * 16
B1, B7 = b"\xb1" * 16, b"\xb7" * 16
Phase = _b.BuyInState.Phase
DECISION = _t.SyncMode.SYNC_MODE_DECISION


def cover(domain, root, corr=""):
    return _t.Cover(domain=domain, root=_t.UUID(value=root), correlation_id=corr)


def source(domain, root, sequence=0) -> _az.PageContext:
    """The page context a saga sees for a source event."""
    return _az.PageContext(cover=cover(domain, root), sequence=sequence)


def assert_deferred(book: _t.CommandBook, domain: str, root: bytes):
    """A saga/PM command: addressed by root, deferred, no correlation id."""
    assert (book.cover.domain, book.cover.root.value, book.cover.correlation_id) == (
        domain,
        root,
        "",
    )
    (page,) = book.pages
    assert page.header.WhichOneof("sequence_type") == "angzarr_deferred"
    assert page.header.angzarr_deferred == _t.AngzarrDeferredSequence()
    assert page.command.type_url.startswith("/io.angzarr.examples.v1.")


# --- buy-in process manager -----------------------------------------------------------


def state_at(phase, buy_in_id=B1):
    return _b.BuyInState(
        buy_in_id=buy_in_id,
        player_root=ALICE,
        table_root=TABLE,
        seat=0,
        amount=500,
        phase=phase,
    )


def only_command(response, message_class):
    (book,) = response.commands
    assert (
        type_name(book.pages[0].command.type_url) == message_class.DESCRIPTOR.full_name
    )
    return book, unpack(book.pages[0].command, message_class)


def process_event(response, message_class):
    (book,) = response.process_events
    (page,) = book.pages
    return unpack(page.event, message_class)


def seat_held_through_router(prior=()) -> _pm.ProcessManagerHandleResponse:
    """A SeatHeld from table TABLE dispatched to the buy-in process, with
    ``prior`` as its own history."""
    with closing(InProcess()) as host:
        trigger = _t.EventBook(cover=cover("table", TABLE, "C1"))
        trigger.pages.add(
            event=_az.pack(
                _table.SeatHeld(buy_in_id=B1, player_root=ALICE, seat=2, amount=500)
            )
        )
        state = _t.EventBook(cover=cover("buy-in", B1, "C1"))
        for event in prior:
            state.pages.add(event=_az.pack(event))
        return host.handle_process(
            _pm.ProcessManagerHandleRequest(trigger=trigger, process_state=state)
        )


def test_seat_held_starts_the_buy_in_with_a_decided_hold():
    response = seat_held_through_router()
    assert process_event(response, _b.BuyInStarted) == _b.BuyInStarted(
        buy_in_id=B1, player_root=ALICE, table_root=TABLE, seat=2, amount=500
    )
    book, hold = only_command(response, _p.HoldFunds)
    assert book.cover.root.value == ALICE
    assert book.pages[0].header.WhichOneof("sequence_type") == "angzarr_deferred"
    assert book.pages[0].header.sync_mode == DECISION
    assert hold == _p.HoldFunds(hold_id=B1, table_root=TABLE, amount=500)


def test_seat_held_ignored_once_a_buy_in_started():
    started = _b.BuyInStarted(buy_in_id=B1, player_root=ALICE, table_root=TABLE)
    response = seat_held_through_router([started])
    assert not response.commands and not response.process_events


@pytest.mark.parametrize(
    "method, event, phase, next_event, command, domain, root",
    [
        (
            "funds_held",
            _p.FundsHeld(hold_id=B1),
            Phase.PHASE_AWAITING_HOLD,
            _b.BuyInFundsHeld(buy_in_id=B1),
            _table.ConfirmSeat(buy_in_id=B1),
            "table",
            TABLE,
        ),
        (
            "player_seated",
            _table.PlayerSeated(buy_in_id=B1, stack=500),
            Phase.PHASE_AWAITING_SEAT,
            _b.BuyInSeated(buy_in_id=B1, stack=500),
            _p.CaptureFunds(hold_id=B1),
            "player",
            ALICE,
        ),
    ],
)
def test_each_step_sends_the_next_decided_command(
    method, event, phase, next_event, command, domain, root
):
    response = getattr(BuyInProcessManager(), method)(
        event, state_at(phase), None, cover("table", TABLE)
    )
    assert process_event(response, type(next_event)) == next_event
    book, sent = only_command(response, type(command))
    assert sent == command
    assert_deferred(book, domain, root)
    assert book.pages[0].header.sync_mode == DECISION


def test_captured_funds_complete_without_commands():
    response = BuyInProcessManager().funds_captured(
        _p.FundsCaptured(hold_id=B1),
        state_at(Phase.PHASE_AWAITING_CAPTURE),
        None,
        cover("player", ALICE),
    )
    assert process_event(response, _b.BuyInCompleted) == _b.BuyInCompleted(buy_in_id=B1)
    assert not response.commands


@pytest.mark.parametrize(
    "method, event, phase",
    [
        ("funds_held", _p.FundsHeld(hold_id=B7), Phase.PHASE_AWAITING_HOLD),
        ("funds_held", _p.FundsHeld(hold_id=B1), Phase.PHASE_AWAITING_SEAT),
        ("player_seated", _table.PlayerSeated(buy_in_id=B7), Phase.PHASE_AWAITING_SEAT),
        (
            "player_seated",
            _table.PlayerSeated(buy_in_id=B1),
            Phase.PHASE_AWAITING_CAPTURE,
        ),
        ("funds_captured", _p.FundsCaptured(hold_id=B7), Phase.PHASE_AWAITING_CAPTURE),
        ("funds_captured", _p.FundsCaptured(hold_id=B1), Phase.PHASE_COMPLETED),
    ],
)
def test_foreign_or_repeated_news_is_a_no_op(method, event, phase):
    response = getattr(BuyInProcessManager(), method)(
        event, state_at(phase), None, cover("table", TABLE)
    )
    assert not response.commands and not response.process_events


def rejection_of(command, code):
    rejected = _t.CommandBook()
    rejected.pages.add().command.CopyFrom(_az.pack(command))
    return _t.RejectionNotification(
        rejected_command=rejected, code=code, rejection_reason="refused for a reason"
    )


def test_refused_hold_fails_the_buy_in_and_releases_the_seat():
    response = BuyInProcessManager().on_hold_funds_rejected(
        _t.Notification(),
        rejection_of(_p.HoldFunds(hold_id=B1), "INSUFFICIENT_AVAILABLE_FUNDS"),
        state_at(Phase.PHASE_AWAITING_HOLD),
    )
    assert process_event(response, _b.BuyInFailed) == _b.BuyInFailed(
        buy_in_id=B1,
        failed_in=Phase.PHASE_AWAITING_HOLD,
        reason="INSUFFICIENT_AVAILABLE_FUNDS",
    )
    book, release = only_command(response, _table.ReleaseSeat)
    assert release == _table.ReleaseSeat(
        buy_in_id=B1, reason="INSUFFICIENT_AVAILABLE_FUNDS"
    )
    assert_deferred(book, "table", TABLE)


def test_refused_confirmation_releases_money_and_seat():
    response = BuyInProcessManager().on_confirm_seat_rejected(
        _t.Notification(),
        rejection_of(_table.ConfirmSeat(buy_in_id=B1), "PLAYER_ALREADY_SEATED"),
        state_at(Phase.PHASE_AWAITING_SEAT),
    )
    failed = process_event(response, _b.BuyInFailed)
    assert (failed.failed_in, failed.reason) == (
        Phase.PHASE_AWAITING_SEAT,
        "PLAYER_ALREADY_SEATED",
    )
    hold_book, seat_book = response.commands
    assert unpack(hold_book.pages[0].command, _p.ReleaseHold) == _p.ReleaseHold(
        hold_id=B1, reason="PLAYER_ALREADY_SEATED"
    )
    assert unpack(seat_book.pages[0].command, _table.ReleaseSeat).buy_in_id == B1
    assert_deferred(hold_book, "player", ALICE)
    assert all(b.pages[0].header.sync_mode == DECISION for b in response.commands)


@pytest.mark.parametrize(
    "method, command, phase",
    [
        ("on_hold_funds_rejected", _p.HoldFunds(hold_id=B1), Phase.PHASE_COMPLETED),
        ("on_hold_funds_rejected", _p.HoldFunds(hold_id=B7), Phase.PHASE_AWAITING_HOLD),
        (
            "on_confirm_seat_rejected",
            _table.ConfirmSeat(buy_in_id=B1),
            Phase.PHASE_AWAITING_HOLD,
        ),
        (
            "on_confirm_seat_rejected",
            _table.ConfirmSeat(buy_in_id=B7),
            Phase.PHASE_AWAITING_SEAT,
        ),
    ],
)
def test_late_or_foreign_refusals_change_nothing(method, command, phase):
    response = getattr(BuyInProcessManager(), method)(
        _t.Notification(), rejection_of(command, "X"), state_at(phase)
    )
    assert not response.commands and not response.process_events


def test_buy_in_state_folds_its_own_events():
    pm = BuyInProcessManager()
    state = _b.BuyInState()
    pm.apply_buy_in_started(
        state,
        _b.BuyInStarted(
            buy_in_id=B1, player_root=ALICE, table_root=TABLE, seat=1, amount=400
        ),
        _az.PageContext(),
    )
    assert (state.phase, state.seat, state.amount) == (
        Phase.PHASE_AWAITING_HOLD,
        1,
        400,
    )
    for apply, event, phase in [
        (pm.apply_buy_in_funds_held, _b.BuyInFundsHeld(), Phase.PHASE_AWAITING_SEAT),
        (pm.apply_buy_in_seated, _b.BuyInSeated(), Phase.PHASE_AWAITING_CAPTURE),
        (pm.apply_buy_in_completed, _b.BuyInCompleted(), Phase.PHASE_COMPLETED),
    ]:
        apply(state, event, _az.PageContext())
        assert state.phase == phase
    pm.apply_buy_in_failed(state, _b.BuyInFailed(reason="R"), _az.PageContext())
    assert (state.phase, state.failure_reason) == (Phase.PHASE_FAILED, "R")


# --- sagas ---------------------------------------------------------------------------------


def test_top_up_becomes_deferred_add_chips_for_the_named_table():
    commands, facts = PlayerTableSaga().top_up_requested(
        _p.TopUpRequested(hold_id=B1, table_root=TABLE, amount=200),
        None,
        source("player", ALICE),
    )
    assert facts == []
    (book,) = commands
    assert_deferred(book, "table", TABLE)
    assert unpack(book.pages[0].command, _table.AddChips) == _table.AddChips(
        player_root=ALICE, hold_id=B1, amount=200
    )


@pytest.mark.parametrize(
    "method, event, fact",
    [
        (
            "chips_added",
            _table.ChipsAdded(hold_id=B1, player_root=ALICE, amount=200),
            _p.TopUpSettled(hold_id=B1, table_root=TABLE, amount=200),
        ),
        (
            "player_cashed_out",
            _table.PlayerCashedOut(cashout_id=B7, player_root=ALICE, amount=640),
            _p.CashOutCredited(cashout_id=B7, table_root=TABLE, amount=640),
        ),
    ],
)
def test_settlement_facts_carry_their_external_id(method, event, fact):
    commands, facts = getattr(TablePlayerSettlementSaga(), method)(
        event, None, source("table", TABLE)
    )
    assert commands == []
    (book,) = facts
    assert (book.cover.domain, book.cover.root.value, book.cover.correlation_id) == (
        "player",
        ALICE,
        "",
    )
    (page,) = book.pages
    expected_id = (B1 if method == "chips_added" else B7).hex()
    assert page.header.external_deferred.external_id == expected_id
    assert page.header.external_deferred.description
    assert unpack(page.event, type(fact)) == fact


def settled():
    return _table.RoundSettled(
        round=4,
        outcomes=[
            _table.SeatOutcome(seat=1, player_root=BOB, wager=30, net=-30),
            _table.SeatOutcome(seat=0, player_root=ALICE, wager=20, net=20),
        ],
    )


def test_history_records_each_seat_in_seat_order():
    commands, facts = TablePlayerHistorySaga().round_settled(
        settled(), None, source("table", TABLE)
    )
    assert facts == []
    for book in commands:
        assert_deferred(book, "player", book.cover.root.value)
    assert [
        (b.cover.root.value, unpack(b.pages[0].command, _p.RecordRoundResult))
        for b in commands
    ] == [
        (ALICE, _p.RecordRoundResult(table_root=TABLE, round=4, wager=20, net=20)),
        (BOB, _p.RecordRoundResult(table_root=TABLE, round=4, wager=30, net=-30)),
    ]


def test_loyalty_awards_a_point_per_chip_wagered():
    commands, facts = TablePlayerLoyaltySaga().round_settled(
        settled(), None, source("table", TABLE)
    )
    assert facts == []
    assert [
        (b.cover.root.value, unpack(b.pages[0].command, _p.AwardLoyaltyPoints))
        for b in commands
    ] == [
        (ALICE, _p.AwardLoyaltyPoints(table_root=TABLE, round=4, points=20)),
        (BOB, _p.AwardLoyaltyPoints(table_root=TABLE, round=4, points=30)),
    ]


# --- upcaster -----------------------------------------------------------------------------


def test_upcaster_rewrites_only_the_legacy_deposit():
    legacy = _t.EventPage(event=_az.pack(_p.FundsDepositedV1(amount_chips=300)))
    legacy.header.sequence = 3
    current = _t.EventPage(event=_az.pack(_p.FundsWithdrawn(amount=5)))
    response = PlayerUpcaster().upcast(
        _up.UpcastRequest(domain="player", events=[legacy, current])
    )
    first, second = response.events
    assert first.header.sequence == 3
    assert first.event.type_url == "/io.angzarr.examples.v1.FundsDeposited"
    assert unpack(first.event, _p.FundsDeposited) == _p.FundsDeposited(amount=300)
    assert second == current
    book = _t.EventBook(cover=cover("player", ALICE), pages=[legacy])
    assert upcast_book(book).pages[0].event.type_url.endswith("FundsDeposited")
    assert book.pages[0].event.type_url.endswith("FundsDepositedV1")


# --- errors ---------------------------------------------------------------------------------


def test_type_names_accept_any_prefix():
    assert type_name("io.angzarr.v1.Notification") == "io.angzarr.v1.Notification"
    assert type_name("/io.angzarr.v1.Notification") == "io.angzarr.v1.Notification"
    assert type_name("type.googleapis.com/a/io.x.Y") == "io.x.Y"


# --- ledger ------------------------------------------------------------------------------------


@pytest.fixture
def ledger():
    components = InProcess()
    yield components
    components.close()


def deliver(host, domain, root, *events, start=0):
    book = _t.EventBook(cover=cover(domain, root))
    for offset, event in enumerate(events):
        page = book.pages.add(event=_az.pack(event))
        page.header.sequence = start + offset
    return host.project(book)


def test_ledger_applies_each_event_once(ledger):
    deliver(
        ledger,
        "player",
        ALICE,
        _p.PlayerRegistered(display_name="A"),
        _p.FundsDeposited(amount=100),
    )
    deliver(
        ledger,
        "player",
        ALICE,
        _p.PlayerRegistered(display_name="A"),
        _p.FundsDeposited(amount=100),
    )
    deliver(ledger, "player", ALICE, _p.FundsDeposited(amount=50), start=1)
    view = ledger.ledger.player_view(ALICE)
    assert (view.found, view.player.bankroll, view.available) == (True, 100, 100)
    assert ledger.ledger.projection.totals.deposits == 100


def test_ledger_projection_reports_the_changed_row(ledger):
    projection = deliver(
        ledger,
        "player",
        ALICE,
        _p.PlayerRegistered(display_name="A"),
        _p.FundsDeposited(amount=70),
    )
    assert (projection.projector, projection.sequence, projection.cover.root.value) == (
        "LedgerProjector",
        1,
        ALICE,
    )
    view = unpack(projection.projection, _l.PlayerBalanceView)
    assert (view.player.bankroll, view.found) == (70, True)
    projection = deliver(ledger, "table", TABLE, _table.TableCreated(name="Main"))
    assert unpack(projection.projection, _l.LedgerView).balanced


def test_ledger_holds_and_transfers(ledger):
    deliver(
        ledger,
        "player",
        ALICE,
        _p.FundsDeposited(amount=1000),
        _p.FundsHeld(hold_id=B1, amount=400),
        _p.TopUpRequested(hold_id=B7, amount=100),
    )
    assert ledger.ledger.player_view(ALICE).player.held == 500
    deliver(ledger, "player", ALICE, _p.TopUpRefused(hold_id=B7, amount=100), start=3)
    assert ledger.ledger.player_view(ALICE).available == 600
    deliver(ledger, "table", TABLE, _table.PlayerSeated(buy_in_id=B1, stack=400))
    ledger.ledger.refresh_totals()
    assert (
        ledger.ledger.projection.totals.in_flight,
        ledger.ledger.projection.totals.in_flight_transfers,
    ) == (400, 1)
    assert not ledger.ledger.balanced()
    deliver(ledger, "player", ALICE, _p.FundsCaptured(hold_id=B1, amount=400), start=4)
    ledger.ledger.refresh_totals()
    assert ledger.ledger.in_flight() == (0, 0)
    assert ledger.ledger.balanced()
    row = ledger.ledger.player_view(ALICE).player
    assert (row.bankroll, row.held) == (600, 0)


def test_ledger_settlement_without_a_hold_still_moves_money(ledger):
    deliver(
        ledger,
        "player",
        ALICE,
        _p.FundsDeposited(amount=1000),
        _p.TopUpSettled(hold_id=B7, amount=200),
    )
    row = ledger.ledger.player_view(ALICE).player
    assert (row.bankroll, row.held) == (800, 0)


def test_ledger_round_results_keep_the_newest_ten(ledger):
    events = [
        _p.RoundResultRecorded(table_root=TABLE, round=r, net=r) for r in range(1, 13)
    ]
    deliver(
        ledger,
        "player",
        ALICE,
        *events,
        _p.RoundResultRetracted(table_root=TABLE, round=12),
    )
    results = ledger.ledger.player_view(ALICE).player.recent_results
    assert [r.round for r in results] == list(range(3, 13))
    assert [r.retracted for r in results] == [False] * 9 + [True]


def test_speculation_leaves_the_ledger_untouched(ledger):
    deliver(ledger, "player", ALICE, _p.FundsDeposited(amount=10))
    book = _t.EventBook(cover=cover("player", ALICE))
    book.pages.add(event=_az.pack(_p.FundsDeposited(amount=5))).header.sequence = 1
    book.pages.add(
        event=_az.pack(_p.FundsHeld(hold_id=B1, amount=3))
    ).header.sequence = 2
    before = _l.LedgerProjection()
    before.CopyFrom(ledger.ledger.projection)
    applied = set(ledger.ledger.applied)
    projection = ledger.router.dispatch_projector(book, speculative=True)
    assert ledger.ledger.projection == before
    assert ledger.ledger.applied == applied
    assert ledger.ledger.open_holds == {}
    view = unpack(projection.projection, _l.PlayerBalanceView)
    assert (view.player.bankroll, view.player.held) == (10, 0)
    ledger.project(book)
    row = ledger.ledger.player_view(ALICE)
    assert (row.player.bankroll, row.player.held, row.available) == (15, 3, 12)


def test_unknown_player_is_not_found(ledger):
    assert not ledger.ledger.player_view(BOB).found


def test_ledger_identity_and_doubled_wagers(ledger):
    deliver(
        ledger,
        "player",
        ALICE,
        _p.PlayerImported(display_name="Carol"),
        _p.ProfileUpdated(display_name="C"),
    )
    assert ledger.ledger.player_view(ALICE).player.display_name == "C"
    deliver(ledger, "player", BOB, _p.PlayerImported(display_name="Bea"))
    assert ledger.ledger.player_view(BOB).player.display_name == "Bea"
    deliver(
        ledger,
        "table",
        TABLE,
        _table.PlayerSeated(buy_in_id=B1, stack=500),
        _table.BetPlaced(amount=20),
        _table.HandDoubled(added=20),
    )
    row = ledger.ledger.projection.tables[TABLE.hex()]
    assert (row.stacks, row.wagers, row.chips_in) == (460, 40, 500)
