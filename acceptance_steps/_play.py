"""What a client of the deployed example does, and how it reads the result.

Every read goes back to the cluster: an aggregate's state is folded from its
stored history by the component's own appliers, the ledger is asked through
LedgerQueryService, and waiting is done on stored history or the event bus.
"""

from __future__ import annotations

import grpc

from acceptance_steps._client import CASCADE_ERROR, MERGE, PLAYER, SYNC, TABLE
from acceptance_steps._world import World, eventually
from angzarr_blackjack._gen.io.angzarr.examples.v1 import player_pb2 as _p
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack._runtime.books import type_name, unpack

TABLE_CONFIG = dict(
    min_bet=10, max_bet=100, min_buy_in=100, max_buy_in=1000, seats=3, decks=1
)
Phase = _table.TableState.Phase


def send(w: World, domain: str, root: bytes, message, **options):
    """Send a client command; keep the answer or the refusal on the world."""
    options.setdefault("correlation", w.correlation)
    w.response, w.error = None, None
    try:
        w.response = w.client.command(domain, root, message, **options)
    except grpc.RpcError as exc:
        w.error = exc
    return w.response


def must(w: World, domain: str, root: bytes, message, **options):
    response = send(w, domain, root, message, **options)
    assert w.error is None, f"{type(message).__name__} was refused: {w.error.details()}"
    return response


def refused_with(error, code: str) -> bool:
    return error is not None and code in (error.details() or "")


# --- reading -----------------------------------------------------------------------


def wallet(w: World, name: str, **query) -> _p.PlayerState:
    return w.client.state(PLAYER, w.player(name), **query)


def table_state(w: World, table: str = "Main", **query) -> _table.TableState:
    return w.client.state(TABLE, w.table(table), **query)


def stored(w: World, domain: str, root: bytes, message_class, **query) -> list:
    name = message_class.DESCRIPTOR.full_name
    return [
        unpack(p.event, message_class)
        for p in w.client.book(domain, root, **query).pages
        if type_name(p.event.type_url) == name
    ]


def seat_of(state: _table.TableState, player_root: bytes) -> int | None:
    for number, seat in state.seated.items():
        if seat.player_root == player_root:
            return number
    return None


# --- the wallet ----------------------------------------------------------------------


def register(w: World, name: str, deposit: int = 0, *, enroll: bool = False) -> None:
    must(
        w,
        PLAYER,
        w.player(name),
        _p.RegisterPlayer(display_name=name, email=f"{name.lower()}@example.com"),
    )
    if deposit:
        must(w, PLAYER, w.player(name), _p.DepositFunds(amount=deposit))
    if enroll:
        must(w, PLAYER, w.player(name), _p.EnrollLoyalty())


# --- the table -------------------------------------------------------------------------


def open_table(w: World, table: str = "Main", seed: int = 2, **config) -> None:
    if table_state(w, table).phase != Phase.PHASE_UNSPECIFIED:
        return
    must(
        w,
        TABLE,
        w.table(table),
        _table.CreateTable(name=table, shoe_seed=seed, **{**TABLE_CONFIG, **config}),
    )


def ask_for_seat(
    w: World,
    name: str,
    seat: int,
    amount: int,
    table: str = "Main",
    sync=SYNC.SYNC_MODE_ASYNC,
):
    """A buy-in request, in a conversation of its own."""
    label = f"buy-in:{name}:{seat}"
    w.notes["last buy-in"] = label
    return send(
        w,
        TABLE,
        w.table(table),
        _table.RequestSeat(
            player_root=w.player(name),
            seat=seat,
            amount=amount,
            request_id=w.request(label),
        ),
        correlation=w.conversation(label),
        sync_mode=sync,
    )


def buy_in(
    w: World,
    name: str,
    seat: int,
    amount: int,
    table: str = "Main",
    within: float = 15.0,
) -> None:
    """Ask for a seat and wait until the table seats the player and the wallet spent the hold."""
    ask_for_seat(w, name, seat, amount, table, sync=SYNC.SYNC_MODE_CASCADE)
    assert w.error is None, f"the seat request was refused: {w.error.details()}"
    hold = w.request(f"buy-in:{name}:{seat}")

    def seated_and_spent():
        assert seat_of(table_state(w, table), w.player(name)) == seat
        assert (
            wallet(w, name).holds[hold.hex()].status == _p.Hold.Status.STATUS_CAPTURED
        )

    eventually(seated_and_spent, within)


def seated_player(
    w: World, name: str, seat: int, stack: int, wallet_left: int, table="Main", seed=2
) -> None:
    register(w, name, stack + wallet_left)
    open_table(w, table, seed)
    buy_in(w, name, seat, stack, table)


def top_up(
    w: World, name: str, amount: int, table: str = "Main", sync=SYNC.SYNC_MODE_ASYNC
):
    count = w.notes.get(f"top-ups:{name}", 0) + 1
    w.notes[f"top-ups:{name}"] = count
    label = f"top-up:{name}:{count}"
    w.notes["last top-up"] = label
    return send(
        w,
        PLAYER,
        w.player(name),
        _p.RequestTopUp(
            table_root=w.table(table), amount=amount, request_id=w.request(label)
        ),
        correlation=w.conversation(label),
        sync_mode=sync,
    )


def bet(w: World, name: str, amount: int, table: str = "Main", **options):
    seat = seat_of(table_state(w, table), w.player(name))
    return send(
        w, TABLE, w.table(table), _table.PlaceBet(seat=seat, amount=amount), **options
    )


def deal(w: World, table: str = "Main") -> None:
    must(w, TABLE, w.table(table), _table.DealRound())


def stand_all(w: World, table: str = "Main") -> None:
    """Every seat stands on its turn until the round is settled."""
    state = table_state(w, table)
    while state.phase == Phase.PHASE_PLAYER_TURNS:
        must(w, TABLE, w.table(table), _table.Stand(seat=state.turn))
        state = table_state(w, table)


def play_round(w: World, name: str, amount: int = 20, table: str = "Main") -> None:
    if bet(w, name, amount, table) is None:
        raise AssertionError(f"the bet was refused: {w.error.details()}")
    deal(w, table)
    stand_all(w, table)


def leave(w: World, name: str, table: str = "Main", sync=SYNC.SYNC_MODE_ASYNC):
    seat = seat_of(table_state(w, table), w.player(name))
    return send(w, TABLE, w.table(table), _table.LeaveTable(seat=seat), sync_mode=sync)


def merge(name: str) -> int:
    return getattr(MERGE, name)


def cascade(name: str) -> int:
    return getattr(CASCADE_ERROR, name)
