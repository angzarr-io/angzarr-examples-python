"""Steps for features/example/blackjack-framework/snapshot.feature.

Lasting snapshots are the ones the table writes itself (every book that
shuffles a shoe); routine snapshots are the coordinator's, taken every N
events when the deployment asks for them.
"""

from __future__ import annotations

from behave import given, then, when

import angzarr_router_ffi as _az
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.blackjack.v1 import table_pb2 as _table
from angzarr_blackjack._gen.io.angzarr.v1 import types_pb2 as _t
from unit_steps._harness import (
    PLAYER,
    TABLE,
    cover,
    player_root,
    table_root,
)
from unit_steps._helpers import (
    create_table,
    hold_funds,
    ok,
    place_bet,
    play_standing,
    register,
    seat_player,
    table_state,
)

PERSIST = _t.SnapshotRetention.RETENTION_PERSIST
ROUTINE = (
    _t.SnapshotRetention.RETENTION_DEFAULT,
    _t.SnapshotRetention.RETENTION_TRANSIENT,
)
Phase = _table.TableState.Phase


def snapshot_at(w, domain: str, root: bytes, sequence: int) -> _t.Snapshot:
    """The snapshot a coordinator takes once event ``sequence`` is stored."""
    book = _t.EventBook(cover=cover(domain, root))
    book.pages.extend(
        p for p in w.stream(domain, root) if p.header.sequence <= sequence
    )
    state = w.hosts[domain].rebuild(book)
    return _t.Snapshot(sequence=sequence, state=_az.pack(state))


def rebuild_from(w, domain: str, root: bytes, snapshot: _t.Snapshot):
    book = _t.EventBook(cover=cover(domain, root), snapshot=snapshot)
    book.pages.extend(
        p for p in w.stream(domain, root) if p.header.sequence > snapshot.sequence
    )
    return w.hosts[domain].rebuild(book)


def play_round(w, seats: list[int], table: str = "Main") -> None:
    for seat in seats:
        if table_state(w, table).seated[seat].stack >= 20:
            ok(place_bet(w, seat, 20, table))
    play_standing(w, table)


def ensure_table(w, table: str) -> None:
    if table_state(w, table).phase == Phase.PHASE_UNSPECIFIED:
        ok(create_table(w, table))


# --- the table ---------------------------------------------------------------------------


@given(
    'table "{table}" created with shoe seed {seed:d} has played {rounds:d} rounds with two players'
)
def step_played_rounds(context, table, seed, rounds):
    w = context.world
    ok(create_table(w, table, seed=seed))
    seat_player(w, "Alice", 0, 500, table)
    seat_player(w, "Bob", 1, 500, table)
    for _ in range(rounds):
        play_round(w, [0, 1], table)
    assert table_state(w, table).round == rounds


@given('table "{table}" was saved as a snapshot after round {round:d}')
def step_saved_after_round(context, table, round):
    w = context.world
    root = table_root(table)
    settled = [
        p
        for p in w.stream(TABLE, root)
        if p.event.type_url.endswith(_table.RoundSettled.DESCRIPTOR.full_name)
    ]
    context.snapshot = snapshot_at(w, TABLE, root, settled[round - 1].header.sequence)


@when('table "{table}" is rebuilt from that snapshot and the events after it')
def step_rebuild_table(context, table):
    context.rebuilt = rebuild_from(
        context.world, TABLE, table_root(table), context.snapshot
    )


@then('the rebuilt table equals table "{table}" replayed from its first event')
def step_rebuilt_table_equals(context, table):
    replayed = context.world.state(TABLE, table_root(table), from_snapshot=False)
    assert context.rebuilt == replayed
    assert context.rebuilt.round == replayed.round > 0


@then('table "{table}" is saved as a snapshot that is kept for good')
def step_lasting_snapshot(context, table):
    w = context.world
    snaps = w.snapshots.get((TABLE, table_root(table)), [])
    assert snaps, "no snapshot was saved"
    latest = snaps[-1]
    assert latest.retention == PERSIST
    assert latest.sequence == len(w.stream(TABLE, table_root(table))) - 1
    replayed = w.state(TABLE, table_root(table), from_snapshot=False)
    restored = _table.TableState()
    restored.ParseFromString(latest.state.value)
    assert restored == replayed
    context.snapshot_state = restored


@given('"{name}" sits at seat {seat:d} of table "{table}" and has bet {amount:d}')
def step_sits_and_bets(context, name, seat, table, amount):
    seat_player(context.world, name, seat, 500, table)
    ok(place_bet(context.world, seat, amount, table))


@given('"{name}" sits at seat {seat:d} of table "{table}"')
def step_sits(context, name, seat, table):
    seat_player(context.world, name, seat, 500, table)


@then(
    "the snapshot holds shoe {number:d}, shuffled from seed {seed:d}, with the "
    "round's {dealt:d} opening cards dealt and {left:d} cards left"
)
def step_snapshot_holds_shoe(context, number, seed, dealt, left):
    w = context.world
    state = context.snapshot_state
    (shoe,) = w.last.decoded(_table.ShoeShuffled)
    assert (state.shoe_number, state.shoe_seed) == (number, seed)
    assert (shoe.shoe_number, shoe.seed) == (number, seed)
    (round_dealt,) = w.last.decoded(_table.RoundDealt)
    opening = [c for h in round_dealt.hands for c in h.cards] + [
        round_dealt.dealer_up,
        round_dealt.dealer_hole,
    ]
    assert len(opening) == dealt
    assert list(state.shoe) == list(shoe.cards)[dealt:]
    assert len(state.shoe) == left


@then("the snapshot shows round {round:d} waiting on seat {seat:d}")
def step_snapshot_round(context, round, seat):
    state = context.snapshot_state
    assert state.round == round
    assert state.phase == _table.TableState.Phase.PHASE_PLAYER_TURNS
    assert state.turn == seat


@given('table "{table}" saves a routine snapshot every {count:d} events')
def step_routine_every(context, table, count):
    w = context.world
    ensure_table(w, table)
    w.snapshot_every = count


@when('enough rounds are played for table "{table}" to reach a routine snapshot')
def step_play_until_routine(context, table):
    w = context.world
    root = table_root(table)
    for _ in range(20):
        if any(s.retention in ROUTINE for s in w.snapshots.get((TABLE, root), [])):
            break
        play_round(w, [0], table)
    context.routine = [s for s in w.snapshots[(TABLE, root)] if s.retention in ROUTINE]
    assert context.routine, "no routine snapshot was taken"


@then("that snapshot is marked to be replaced by the next one")
def step_routine_replaced(context):
    snap = context.routine[0]
    assert snap.retention in ROUTINE
    assert (snap.sequence + 1) % context.world.snapshot_every == 0


# --- the wallet ---------------------------------------------------------------------------


@given('"{name}" has a history of {count:d} deposits, holds and withdrawals')
def step_wallet_history(context, name, count):
    w = context.world
    register(w, name)
    root = player_root(name)
    for i in range(count):
        if i % 3 == 0:
            ok(w.command(PLAYER, root, _p.DepositFunds(amount=100 + i)))
        elif i % 3 == 1:
            ok(hold_funds(w, name, f"hold-{i}", "Main", 10))
        else:
            ok(w.command(PLAYER, root, _p.WithdrawFunds(amount=5)))
    assert len(w.stream(PLAYER, root)) == count + 1


@given('"{name}"\'s wallet was saved as a snapshot after the {nth:d}th')
def step_wallet_snapshot(context, name, nth):
    context.snapshot = snapshot_at(context.world, PLAYER, player_root(name), nth)


@when('"{name}"\'s wallet is rebuilt from that snapshot and the events after it')
def step_rebuild_wallet(context, name):
    context.rebuilt = rebuild_from(
        context.world, PLAYER, player_root(name), context.snapshot
    )


@then('the rebuilt wallet equals "{name}"\'s wallet replayed from its first event')
def step_rebuilt_wallet_equals(context, name):
    replayed = context.world.state(PLAYER, player_root(name), from_snapshot=False)
    assert context.rebuilt == replayed
    assert replayed.bankroll > 0 and len(replayed.holds) > 0
