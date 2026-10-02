"""Property tests for the two aggregate ledger invariants.

L1 (wallet): after every event, bankroll >= sum(open holds) >= 0, every open
hold is positive, and bankroll = deposited - withdrawn - to tables + from tables.

L2 (table): after every event, sum(stacks) + sum(wagers) + house result =
chips in - chips out.

Each draws a random sequence of requests, runs the ones the component accepts
(refusals are part of the sequence too) and checks the invariant after every
event it records.
"""

import angzarr_client.router as _az
from hypothesis import given, settings
from hypothesis import strategies as st

from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.player.agg import logic as L
from angzarr_blackjack.player.agg.handler import PlayerAggregate
from angzarr_blackjack.table.agg import rules
from angzarr_blackjack.table.agg.handler import TableAggregate

TABLE_ROOT = b"\x07" * 16
CCTX = _az.CommandContext(
    next_sequence=1,
    had_prior_events=True,
    cover=_t.Cover(domain="table", root=_t.UUID(value=TABLE_ROOT)),
)
HOLD_IDS = [bytes([i]) * 16 for i in range(1, 6)]

_PLAYER_APPLY = {
    "FundsDeposited": L.apply_deposited,
    "FundsWithdrawn": L.apply_withdrawn,
    "FundsHeld": L.apply_funds_held,
    "FundsCaptured": L.apply_funds_captured,
    "HoldReleased": L.apply_hold_released,
    "TopUpRequested": L.apply_top_up_requested,
    "TopUpRefused": L.apply_top_up_refused,
    "TopUpSettled": L.apply_top_up_settled,
    "CashOutCredited": L.apply_cash_out_credited,
}


def _fold(state, book):
    for page in book.pages:
        name = type_name(page.event.type_url).rsplit(".", 1)[-1]
        _PLAYER_APPLY[name](state, unpack(page.event, getattr(_p, name)))
        assert L.ledger_balances(state), f"L1 broken after {name}: {state}"


money = st.integers(min_value=-5, max_value=600)
hold_id = st.sampled_from(HOLD_IDS)
wallet_step = st.one_of(
    st.tuples(st.just("deposit"), money),
    st.tuples(st.just("withdraw"), money),
    st.tuples(st.just("hold"), money, hold_id),
    st.tuples(st.just("capture"), hold_id),
    st.tuples(st.just("release"), hold_id),
    st.tuples(st.just("top-up"), money, hold_id),
    st.tuples(st.just("refuse"), hold_id),
    st.tuples(st.just("settle"), hold_id),
    st.tuples(st.just("cash-out"), money),
)


@settings(max_examples=300, deadline=None)
@given(st.lists(wallet_step, max_size=40))
def test_wallet_ledger_balances_after_every_event(steps):
    player = PlayerAggregate()
    state = _p.PlayerState(registered=True)
    for step in steps:
        kind = step[0]
        try:
            if kind == "deposit":
                book = player.deposit_funds(
                    _p.DepositFunds(amount=step[1]), state, CCTX
                )
            elif kind == "withdraw":
                book = player.withdraw_funds(
                    _p.WithdrawFunds(amount=step[1]), state, CCTX
                )
            elif kind == "hold":
                book = player.hold_funds(
                    _p.HoldFunds(
                        hold_id=step[2], table_root=TABLE_ROOT, amount=step[1]
                    ),
                    state,
                    CCTX,
                )
            elif kind == "capture":
                book = player.capture_funds(
                    _p.CaptureFunds(hold_id=step[1]), state, CCTX
                )
            elif kind == "release":
                book = player.release_hold(_p.ReleaseHold(hold_id=step[1]), state, CCTX)
            elif kind == "top-up":
                book = player.request_top_up(
                    _p.RequestTopUp(
                        table_root=TABLE_ROOT, amount=step[1], request_id=step[2]
                    ),
                    state,
                    CCTX,
                )
            elif kind == "refuse":
                rejected = _t.CommandBook()
                rejected.pages.add().command.CopyFrom(
                    _az.pack(_table.AddChips(hold_id=step[1]))
                )
                response = player.on_add_chips_rejected(
                    _t.Notification(),
                    _t.RejectionNotification(
                        rejected_command=rejected,
                        code="WAGER_IN_PLAY",
                        rejection_reason="the seat has a wager in play",
                    ),
                    state,
                    CCTX,
                )
                book = response.events if response is not None else None
            elif kind == "settle":
                hold = L.open_hold(state, step[1], L.TOP_UP)
                if hold is None:
                    continue
                record = player.on_top_up_settled_fact(
                    _p.TopUpSettled(hold_id=step[1], amount=hold.amount), state
                )
                fact = record.fact
                assert fact.anomaly == "" and record.flags == ()
                book = _t.EventBook()
                book.pages.add().event.CopyFrom(_az.pack(fact))
            else:
                if step[1] <= 0:
                    continue
                book = _t.EventBook()
                book.pages.add().event.CopyFrom(
                    _az.pack(_p.CashOutCredited(amount=step[1]))
                )
        except _az.CodedError:
            continue
        if book is not None:
            _fold(state, book)


def _run(table, method, cmd, state):
    book = getattr(table, method)(cmd, state, CCTX)
    if book is None:
        return
    for page in book.pages:
        name = type_name(page.event.type_url).rsplit(".", 1)[-1]
        table.apply(state, unpack(page.event, getattr(_table, name)))
        assert rules.ledger_balances(state), f"L2 broken after {name}"


@settings(max_examples=150, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=2**64 - 1),
    stacks=st.lists(st.integers(min_value=100, max_value=1000), min_size=1, max_size=3),
    data=st.data(),
)
def test_table_ledger_balances_after_every_event(seed, stacks, data):
    table = TableAggregate()
    state = _table.TableState()
    _run(
        table,
        "create_table",
        _table.CreateTable(
            name="P",
            min_bet=10,
            max_bet=100,
            min_buy_in=100,
            max_buy_in=1000,
            seats=3,
            decks=1,
            shoe_seed=seed,
        ),
        state,
    )
    for seat, stack in enumerate(stacks):
        request = bytes([seat + 1]) * 16
        _run(
            table,
            "request_seat",
            _table.RequestSeat(
                player_root=request, seat=seat, amount=stack, request_id=request
            ),
            state,
        )
        _run(table, "confirm_seat", _table.ConfirmSeat(buy_in_id=request), state)
    for _ in range(data.draw(st.integers(min_value=1, max_value=6))):
        for seat in list(state.seated):
            if data.draw(st.booleans()):
                amount = data.draw(st.integers(min_value=5, max_value=50)) * 2
                try:
                    _run(
                        table,
                        "place_bet",
                        _table.PlaceBet(seat=seat, amount=amount),
                        state,
                    )
                except _az.CodedError:
                    pass
        try:
            _run(table, "deal_round", _table.DealRound(), state)
        except _az.CodedError:
            continue
        while state.phase == _table.TableState.Phase.PHASE_PLAYER_TURNS:
            method = data.draw(st.sampled_from(["hit", "stand", "double_down"]))
            command = {
                "hit": _table.Hit,
                "stand": _table.Stand,
                "double_down": _table.DoubleDown,
            }[method]
            try:
                _run(table, method, command(seat=state.turn), state)
            except _az.CodedError:
                _run(table, "stand", _table.Stand(seat=state.turn), state)
        assert state.phase == _table.TableState.Phase.PHASE_IDLE
        if state.seated and data.draw(st.booleans()):
            seat = data.draw(st.sampled_from(sorted(state.seated)))
            _run(table, "leave_table", _table.LeaveTable(seat=seat), state)
    assert rules.ledger_balances(state)
    assert all(seat.wager == 0 for seat in state.seated.values())
