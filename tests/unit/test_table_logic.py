"""The table: house-rule functions and the TableAggregate's guard/validate/
compute paths with exact rejection codes, gRPC classes and messages."""

import uuid

import angzarr_router_ffi as _az
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.cards import next_seed, parse_cards, shuffle
from angzarr_blackjack.table.agg import rules
from angzarr_blackjack.table.agg.handler import TableAggregate, cashout_id

FP = _az.GrpcCode.FAILED_PRECONDITION
IA = _az.GrpcCode.INVALID_ARGUMENT
ROOT = uuid.uuid5(uuid.NAMESPACE_OID, "table:Main").bytes
ALICE, BOB, CAROL = (bytes([n]) * 16 for n in (1, 2, 3))
B1, B2 = b"\xb1" * 16, b"\xb2" * 16
CCTX = _az.CommandContext(
    next_sequence=7,
    had_prior_events=True,
    cover=_t.Cover(domain="table", root=_t.UUID(value=ROOT)),
)
Phase = _table.TableState.Phase
Outcome = _table.SeatOutcome.Outcome


# --- rules ----------------------------------------------------------------------------

VALID = dict(seats=3, decks=1, min_bet=10, max_bet=100, min_buy_in=100, max_buy_in=1000)


@pytest.mark.parametrize(
    "change, valid",
    [
        ({}, True),
        ({"seats": 1}, True),
        ({"seats": 7}, True),
        ({"seats": 0}, False),
        ({"seats": 8}, False),
        ({"decks": 8}, True),
        ({"decks": 0}, False),
        ({"decks": 9}, False),
        ({"min_bet": 0, "max_bet": 0}, False),
        ({"min_bet": 100, "max_bet": 10}, False),
        ({"min_bet": 11}, False),
        ({"max_bet": 101}, False),
        ({"min_bet": 100, "max_bet": 100}, True),
        ({"min_buy_in": 0}, False),
        ({"min_buy_in": 1000, "max_buy_in": 100}, False),
        ({"min_buy_in": 10}, True),
        ({"min_buy_in": 500, "max_buy_in": 500}, True),
        ({"min_buy_in": 5}, False),
    ],
)
def test_table_configuration(change, valid):
    assert rules.config_is_valid(**{**VALID, **change}) is valid


@pytest.mark.parametrize(
    "bettors, left, reshuffle",
    [(1, 21, True), (1, 22, False), (2, 32, True), (2, 33, False)],
)
def test_reshuffle_bound(bettors, left, reshuffle):
    assert rules.cards_needed(bettors) == 11 * (bettors + 1)
    assert rules.needs_reshuffle(left, bettors) is reshuffle


def test_turn_order_skips_finished_hands():
    finished = {0: True, 2: False, 5: False}
    assert rules.next_turn([5, 0, 2], finished) == 2
    assert rules.next_turn([5, 0, 2], finished, after=2) == 5
    assert rules.next_turn([5, 0, 2], finished, after=5) == rules.NO_TURN == -1
    assert rules.next_turn([0], {0: True}) == rules.NO_TURN


@pytest.mark.parametrize(
    "dealer, draws",
    [
        ("10♣ 6♦", True),
        ("10♣ 7♦", False),
        ("A♣ 6♦", False),
        ("A♣ 5♦", True),
        ("9♣ 8♦", False),
    ],
)
def test_dealer_stands_on_every_17(dealer, draws):
    assert rules.dealer_must_draw(parse_cards(dealer)) is draws


def test_dealer_draws_to_17_only_when_a_hand_is_live():
    shoe = parse_cards("2♣ 3♣ 4♣ K♣")
    assert rules.dealer_draws(parse_cards("10♦ 2♦"), shoe, True) == parse_cards("2♣ 3♣")
    assert rules.dealer_draws(parse_cards("10♦ 2♦"), shoe, False) == []
    assert rules.dealer_draws(parse_cards("10♦ 7♦"), shoe, True) == []


@pytest.mark.parametrize(
    "player, dealer, result",
    [
        ("10♣ 9♣", "10♦ 8♦", Outcome.OUTCOME_WIN),
        ("10♣ 8♣", "10♦ 8♦", Outcome.OUTCOME_PUSH),
        ("10♣ 7♣", "10♦ 8♦", Outcome.OUTCOME_LOSE),
        ("10♣ 6♣ K♣", "10♦ 6♦ K♦", Outcome.OUTCOME_LOSE),
        ("10♣ 6♣", "10♦ 6♦ K♦", Outcome.OUTCOME_WIN),
        ("A♣ K♣", "10♦ 9♦", Outcome.OUTCOME_BLACKJACK),
        ("A♣ K♣", "A♦ Q♦", Outcome.OUTCOME_PUSH),
        ("10♣ 5♣ 6♣", "A♦ Q♦", Outcome.OUTCOME_LOSE),
        ("10♣ 5♣ 6♣", "10♦ 5♦ 6♦", Outcome.OUTCOME_PUSH),
        ("A♣ K♣", "10♦ 5♦ 6♦", Outcome.OUTCOME_BLACKJACK),
    ],
)
def test_outcome(player, dealer, result):
    assert rules.outcome(parse_cards(player), parse_cards(dealer)) == result


@pytest.mark.parametrize(
    "result, wager, paid",
    [
        (Outcome.OUTCOME_WIN, 20, 40),
        (Outcome.OUTCOME_BLACKJACK, 20, 50),
        (Outcome.OUTCOME_BLACKJACK, 30, 75),
        (Outcome.OUTCOME_PUSH, 20, 20),
        (Outcome.OUTCOME_LOSE, 20, 0),
    ],
)
def test_returned(result, wager, paid):
    assert rules.returned(result, wager) == paid


def test_busted():
    assert rules.is_busted(parse_cards("10♣ 6♣ 6♦"))
    assert not rules.is_busted(parse_cards("10♣ A♣ K♦"))


# --- the aggregate ----------------------------------------------------------------------


@pytest.fixture
def table():
    return TableAggregate()


def run(table, method, cmd, state, cctx=CCTX):
    """Run a command; return its events and fold them into ``state``."""
    book = getattr(table, method)(cmd, state, cctx)
    events = []
    if book is not None:
        for page in book.pages:
            cls = getattr(_table, type_name(page.event.type_url).rsplit(".", 1)[-1])
            event = unpack(page.event, cls)
            table.apply(state, event)
            events.append(event)
    return events, book


def refused(table, method, cmd, state):
    with pytest.raises(_az.CodedError) as info:
        getattr(table, method)(cmd, state, CCTX)
    return info.value


def created(table, seed=42, **config):
    state = _table.TableState()
    run(
        table,
        "create_table",
        _table.CreateTable(name="Main", shoe_seed=seed, **{**VALID, **config}),
        state,
    )
    return state


def seated(table, state, player, seat, stack=500, request=None):
    request = request or bytes([seat + 0xA0]) * 16
    run(
        table,
        "request_seat",
        _table.RequestSeat(
            player_root=player, seat=seat, amount=stack, request_id=request
        ),
        state,
    )
    run(table, "confirm_seat", _table.ConfirmSeat(buy_in_id=request), state)
    return state


def with_shoe(table, state, text):
    top = parse_cards(text)
    table.apply(
        state,
        _table.ShoeShuffled(
            shoe_number=state.shoe_number,
            seed=state.shoe_seed,
            decks=1,
            cards=top + shuffle(3, 1),
        ),
    )
    return state


def test_create_records_the_first_shoe_and_a_lasting_snapshot(table):
    state = _table.TableState()
    events, book = run(
        table,
        "create_table",
        _table.CreateTable(name="Main", shoe_seed=42, **VALID),
        state,
    )
    created_event, shoe = events
    assert created_event == _table.TableCreated(name="Main", **VALID)
    assert (shoe.shoe_number, shoe.seed, shoe.decks, list(shoe.cards)) == (
        1,
        42,
        1,
        shuffle(42, 1),
    )
    assert book.snapshot.retention == _t.SnapshotRetention.RETENTION_PERSIST
    snap = _table.TableState()
    snap.ParseFromString(book.snapshot.state.value)
    assert snap == state and state.phase == Phase.PHASE_IDLE and state.turn == -1


def test_create_refusals(table):
    err = refused(
        table, "create_table", _table.CreateTable(shoe_seed=1, **VALID), created(table)
    )
    assert (err.code, err.grpc, err.message) == (
        "TABLE_ALREADY_EXISTS",
        FP,
        "the table already exists",
    )
    err = refused(
        table,
        "create_table",
        _table.CreateTable(shoe_seed=1, **{**VALID, "seats": 0}),
        _table.TableState(),
    )
    assert (err.code, err.grpc, err.message) == (
        "INVALID_TABLE_CONFIG",
        IA,
        "the table configuration breaks the house rules",
    )


def test_commands_need_the_table(table):
    err = refused(
        table, "place_bet", _table.PlaceBet(seat=0, amount=10), _table.TableState()
    )
    assert (err.code, err.grpc, err.message) == (
        "TABLE_NOT_FOUND",
        FP,
        "the table does not exist",
    )


def test_seat_request_rules(table):
    state = created(table)
    seated(table, state, BOB, 1)
    cases = [
        (
            _table.RequestSeat(player_root=ALICE, seat=-1, amount=500, request_id=B1),
            "SEAT_OUT_OF_RANGE",
            IA,
            "seat -1 does not exist",
        ),
        (
            _table.RequestSeat(player_root=ALICE, seat=3, amount=500, request_id=B1),
            "SEAT_OUT_OF_RANGE",
            IA,
            "seat 3 does not exist",
        ),
        (
            _table.RequestSeat(player_root=ALICE, seat=0, amount=99, request_id=B1),
            "BUY_IN_OUT_OF_RANGE",
            IA,
            "the buy-in must be within 100 to 1000",
        ),
        (
            _table.RequestSeat(player_root=ALICE, seat=0, amount=1001, request_id=B1),
            "BUY_IN_OUT_OF_RANGE",
            IA,
            "the buy-in must be within 100 to 1000",
        ),
        (
            _table.RequestSeat(player_root=ALICE, seat=1, amount=500, request_id=B1),
            "SEAT_TAKEN",
            FP,
            "seat 1 is taken",
        ),
        (
            _table.RequestSeat(player_root=BOB, seat=2, amount=500, request_id=B1),
            "PLAYER_ALREADY_SEATED",
            FP,
            "the player is already seated",
        ),
    ]
    for cmd, code, grpc, message in cases:
        err = refused(table, "request_seat", cmd, state)
        assert (err.code, err.grpc, err.message) == (code, grpc, message)
    events, _ = run(
        table,
        "request_seat",
        _table.RequestSeat(player_root=ALICE, seat=0, amount=100, request_id=B1),
        state,
    )
    assert events == [
        _table.SeatHeld(buy_in_id=B1, player_root=ALICE, seat=0, amount=100)
    ]
    assert (
        run(
            table,
            "request_seat",
            _table.RequestSeat(player_root=ALICE, seat=0, amount=100, request_id=B1),
            state,
        )[0]
        == []
    )
    err = refused(
        table,
        "request_seat",
        _table.RequestSeat(player_root=CAROL, seat=0, amount=100, request_id=B2),
        state,
    )
    assert err.code == "SEAT_TAKEN"
    err = refused(
        table,
        "request_seat",
        _table.RequestSeat(player_root=ALICE, seat=2, amount=100, request_id=B1),
        state,
    )
    assert err.code == "SEAT_TAKEN"


def test_confirm_and_release(table):
    state = created(table)
    run(
        table,
        "request_seat",
        _table.RequestSeat(player_root=ALICE, seat=0, amount=500, request_id=B1),
        state,
    )
    run(
        table,
        "request_seat",
        _table.RequestSeat(player_root=ALICE, seat=1, amount=500, request_id=B2),
        state,
    )
    events, _ = run(table, "confirm_seat", _table.ConfirmSeat(buy_in_id=B1), state)
    assert events == [
        _table.PlayerSeated(buy_in_id=B1, player_root=ALICE, seat=0, stack=500)
    ]
    assert (state.chips_in, state.seated[0].stack, list(state.confirmed_buy_ins)) == (
        500,
        500,
        [B1.hex()],
    )
    assert run(table, "confirm_seat", _table.ConfirmSeat(buy_in_id=B1), state)[0] == []
    err = refused(table, "confirm_seat", _table.ConfirmSeat(buy_in_id=B2), state)
    assert (err.code, err.message) == (
        "PLAYER_ALREADY_SEATED",
        "the player is already seated",
    )
    err = refused(
        table, "confirm_seat", _table.ConfirmSeat(buy_in_id=b"\x99" * 16), state
    )
    assert (err.code, err.grpc, err.message) == (
        "SEAT_HOLD_NOT_FOUND",
        FP,
        f"buy-in {'99' * 16} holds no seat",
    )
    events, _ = run(
        table, "release_seat", _table.ReleaseSeat(buy_in_id=B2, reason="r"), state
    )
    assert events == [
        _table.SeatReleased(buy_in_id=B2, player_root=ALICE, seat=1, reason="r")
    ]
    assert B2.hex() not in state.seat_holds
    assert run(table, "release_seat", _table.ReleaseSeat(buy_in_id=B2), state)[0] == []


def test_add_chips_rules(table):
    state = seated(table, created(table), ALICE, 0, stack=800)
    err = refused(
        table,
        "add_chips",
        _table.AddChips(player_root=BOB, hold_id=B1, amount=100),
        state,
    )
    assert (err.code, err.grpc, err.message) == (
        "NOT_SEATED",
        FP,
        "the player has no seat at this table",
    )
    err = refused(
        table,
        "add_chips",
        _table.AddChips(player_root=ALICE, hold_id=B1, amount=201),
        state,
    )
    assert (err.code, err.grpc, err.message) == (
        "TOP_UP_EXCEEDS_MAX",
        IA,
        "the stack would exceed the maximum buy-in 1000",
    )
    events, _ = run(
        table,
        "add_chips",
        _table.AddChips(player_root=ALICE, hold_id=B1, amount=200),
        state,
    )
    assert events == [
        _table.ChipsAdded(
            hold_id=B1, player_root=ALICE, seat=0, amount=200, stack_after=1000
        )
    ]
    assert (state.seated[0].stack, state.chips_in) == (1000, 1000)
    assert (
        run(
            table,
            "add_chips",
            _table.AddChips(player_root=ALICE, hold_id=B1, amount=200),
            state,
        )[0]
        == []
    )
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state)
    err = refused(
        table,
        "add_chips",
        _table.AddChips(player_root=ALICE, hold_id=B2, amount=10),
        state,
    )
    assert (err.code, err.grpc, err.message) == (
        "WAGER_IN_PLAY",
        FP,
        "the seat has a wager in play",
    )


def test_leave_cashes_out_with_a_deterministic_id(table):
    state = seated(table, created(table), ALICE, 0, stack=640)
    err = refused(table, "leave_table", _table.LeaveTable(seat=2), state)
    assert (err.code, err.grpc, err.message) == (
        "NOT_SEATED",
        FP,
        "seat 2 is not occupied",
    )
    err = refused(table, "leave_table", _table.LeaveTable(seat=9), state)
    assert err.code == "SEAT_OUT_OF_RANGE"
    events, _ = run(table, "leave_table", _table.LeaveTable(seat=0), state)
    expected_id = uuid.uuid5(uuid.UUID(bytes=ROOT), "cashout/7").bytes
    assert cashout_id(ROOT, 7) == expected_id
    assert events == [
        _table.PlayerCashedOut(
            cashout_id=expected_id, player_root=ALICE, seat=0, amount=640
        )
    ]
    assert (dict(state.seated), state.chips_out) == ({}, 640)
    assert rules.ledger_balances(state)


def test_leave_refused_with_a_wager(table):
    state = seated(table, created(table), ALICE, 0)
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state)
    assert (
        refused(table, "leave_table", _table.LeaveTable(seat=0), state).code
        == "WAGER_IN_PLAY"
    )


def test_bet_rules(table):
    state = seated(
        table, seated(table, created(table), ALICE, 0, stack=500), BOB, 1, stack=100
    )
    cases = [
        (
            _table.PlaceBet(seat=2, amount=20),
            "NOT_SEATED",
            FP,
            "seat 2 is not occupied",
        ),
        (
            _table.PlaceBet(seat=0, amount=8),
            "BET_OUT_OF_RANGE",
            IA,
            "the bet must be within 10 to 100",
        ),
        (
            _table.PlaceBet(seat=0, amount=102),
            "BET_OUT_OF_RANGE",
            IA,
            "the bet must be within 10 to 100",
        ),
        (
            _table.PlaceBet(seat=0, amount=15),
            "BET_NOT_EVEN",
            IA,
            "the bet must be an even amount",
        ),
    ]
    for cmd, code, grpc, message in cases:
        err = refused(table, "place_bet", cmd, state)
        assert (err.code, err.grpc, err.message) == (code, grpc, message)
    events, _ = run(table, "place_bet", _table.PlaceBet(seat=1, amount=100), state)
    assert events == [
        _table.BetPlaced(round=1, seat=1, player_root=BOB, amount=100, stack_after=0)
    ]
    assert state.phase == Phase.PHASE_BETTING
    err = refused(table, "place_bet", _table.PlaceBet(seat=1, amount=10), state)
    assert (err.code, err.message) == (
        "ALREADY_BET",
        "seat 1 has already bet this round",
    )
    events, _ = run(table, "place_bet", _table.PlaceBet(seat=0, amount=10), state)
    assert events[0].stack_after == 490


def test_bet_cannot_exceed_the_stack(table):
    state = seated(table, created(table), ALICE, 0, stack=100)
    state.seated[0].stack = 8
    err = refused(table, "place_bet", _table.PlaceBet(seat=0, amount=10), state)
    assert (err.code, err.grpc, err.message) == (
        "INSUFFICIENT_STACK",
        FP,
        "the stack is too small",
    )


def test_deal_and_act_rules(table):
    state = seated(table, seated(table, created(table), ALICE, 0), BOB, 1)
    err = refused(table, "deal_round", _table.DealRound(), state)
    assert (err.code, err.grpc, err.message) == ("NO_BETS", FP, "nobody has bet")
    err = refused(table, "hit", _table.Hit(seat=0), state)
    assert (err.code, err.grpc, err.message) == (
        "NO_ROUND_IN_PROGRESS",
        FP,
        "no round is in progress",
    )
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state)
    run(table, "place_bet", _table.PlaceBet(seat=1, amount=20), state)
    with_shoe(table, state, "2♣ 3♣ 9♦ 4♣ 5♣ 7♠ 6♥")
    events, book = run(table, "deal_round", _table.DealRound(), state)
    assert not book.HasField("snapshot")
    (dealt,) = events
    assert [(h.seat, h.total, h.soft, h.blackjack) for h in dealt.hands] == [
        (0, 6, False, False),
        (1, 8, False, False),
    ]
    assert (dealt.round, dealt.turn) == (1, 0)
    err = refused(table, "deal_round", _table.DealRound(), state)
    assert (err.code, err.message) == ("ROUND_IN_PROGRESS", "a round is in progress")
    assert (
        refused(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state).code
        == "ROUND_IN_PROGRESS"
    )
    err = refused(table, "stand", _table.Stand(seat=1), state)
    assert (err.code, err.grpc, err.message) == (
        "NOT_YOUR_TURN",
        FP,
        "it is not seat 1's turn",
    )
    (hit,) = run(table, "hit", _table.Hit(seat=0), state)[0]
    assert (hit.total, hit.soft, hit.busted, hit.next_turn) == (12, False, False, 0)
    err = refused(table, "double_down", _table.DoubleDown(seat=0), state)
    assert (err.code, err.grpc, err.message) == (
        "DOUBLE_NOT_ALLOWED",
        FP,
        "doubling is only allowed on the first two cards",
    )
    assert (
        refused(table, "double_down", _table.DoubleDown(seat=1), state).code
        == "NOT_YOUR_TURN"
    )


def test_double_needs_a_stack_covering_the_wager(table):
    state = seated(table, created(table), ALICE, 0, stack=100)
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=60), state)
    with_shoe(table, state, "5♣ 9♦ 6♣ 7♠")
    run(table, "deal_round", _table.DealRound(), state)
    err = refused(table, "double_down", _table.DoubleDown(seat=0), state)
    assert (err.code, err.message) == (
        "INSUFFICIENT_STACK",
        "the stack is too small to double",
    )


def test_double_with_an_exact_stack(table):
    state = seated(table, created(table), ALICE, 0, stack=100)
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=50), state)
    with_shoe(table, state, "5♣ 9♦ 6♣ 7♠ K♥ 2♥")
    run(table, "deal_round", _table.DealRound(), state)
    events, _ = run(table, "double_down", _table.DoubleDown(seat=0), state)
    doubled, dealer, settled = events
    assert (doubled.added, doubled.stack_after, doubled.total, doubled.next_turn) == (
        50,
        0,
        21,
        -1,
    )
    assert (dealer.total, list(dealer.drawn)) == (18, parse_cards("2♥"))
    assert [
        (o.wager, o.outcome, o.returned, o.net, o.stack_after) for o in settled.outcomes
    ] == [(100, Outcome.OUTCOME_WIN, 200, 100, 200)]
    assert (settled.house_delta, settled.house_result_after) == (-100, -100)
    assert state.phase == Phase.PHASE_IDLE and rules.ledger_balances(state)


def test_reshuffle_writes_a_lasting_snapshot_of_the_new_shoe(table):
    state = seated(table, created(table), ALICE, 0)
    table.apply(
        state,
        _table.ShoeShuffled(
            shoe_number=1, seed=42, decks=1, cards=shuffle(42, 1)[-21:]
        ),
    )
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state)
    events, book = run(table, "deal_round", _table.DealRound(), state)
    shoe = events[0]
    assert (shoe.shoe_number, shoe.seed) == (2, next_seed(42))
    assert book.snapshot.retention == _t.SnapshotRetention.RETENTION_PERSIST
    assert book.snapshot.state.value == state.SerializeToString()


def test_dealer_blackjack_settles_at_the_deal(table):
    state = seated(table, created(table), ALICE, 0)
    run(table, "place_bet", _table.PlaceBet(seat=0, amount=20), state)
    with_shoe(table, state, "10♣ A♦ 9♣ K♠")
    events, _ = run(table, "deal_round", _table.DealRound(), state)
    dealt, dealer, settled = events
    assert dealt.turn == -1 and dealer.blackjack and not dealer.drawn
    assert settled.outcomes[0].outcome == Outcome.OUTCOME_LOSE
    assert state.phase == Phase.PHASE_IDLE
