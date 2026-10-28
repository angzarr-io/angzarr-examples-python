"""The table: the configuration rule and the TableAggregate's guard/validate/
compute path for CreateTable, with exact rejection codes, gRPC classes and
messages."""

import uuid

import angzarr_client.router as _az
import pytest

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t
from angzarr_blackjack._runtime.books import type_name, unpack
from angzarr_blackjack.cards import shuffle
from angzarr_blackjack.table.agg import rules
from angzarr_blackjack.table.agg.handler import TableAggregate

FP = _az.GrpcCode.FAILED_PRECONDITION
IA = _az.GrpcCode.INVALID_ARGUMENT
ROOT = uuid.uuid5(uuid.NAMESPACE_OID, "table:Main").bytes
CCTX = _az.CommandContext(
    next_sequence=7,
    had_prior_events=True,
    cover=_t.Cover(domain="table", root=_t.UUID(value=ROOT)),
)
Phase = _table.TableState.Phase


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
            cls = getattr(_table, type_name(page.payload.type_url).rsplit(".", 1)[-1])
            event = unpack(page.payload, cls)
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


def test_create_records_the_table_and_its_first_shoe(table):
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
    assert not book.HasField("snapshot")
    assert state == _table.TableState(
        name="Main",
        phase=Phase.PHASE_IDLE,
        shoe_number=1,
        shoe_seed=42,
        shoe=shuffle(42, 1),
        **VALID,
    )


def test_create_shuffles_as_many_decks_as_configured(table):
    state = created(table, seed=7, decks=6)
    assert (state.decks, list(state.shoe)) == (6, shuffle(7, 6))


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


def test_a_later_shoe_replaces_the_undealt_cards(table):
    state = created(table)
    table.apply(
        state,
        _table.ShoeShuffled(shoe_number=2, seed=9, decks=2, cards=shuffle(9, 2)),
    )
    assert (state.shoe_number, state.shoe_seed, state.decks) == (2, 9, 2)
    assert list(state.shoe) == shuffle(9, 2)
