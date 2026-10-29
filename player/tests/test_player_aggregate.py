"""The PlayerAggregate through the router binding: DecideMove records one
MoveDecided for the turn it answers, and the state after a few decisions
counts them (decisions) and the hands they were on (hands_seen)."""

from __future__ import annotations

import angzarr_client.router as _az
import pytest
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

from angzarr_player._gen.io.angzarr.examples.v1 import cards_pb2 as _cards
from angzarr_player._gen.io.angzarr.examples.v1 import player_pb2 as _player
from angzarr_player.main import register

PLAYER = b"\x0a" * 16
TABLE = b"\x01" * 16


class Player:
    """The player's stream, driven through a router: each command is sent
    with the events recorded so far."""

    def __init__(self) -> None:
        from angzarr_client import ComponentHost

        self.host = register(ComponentHost(_az.Router(), rules_version="0.0.0+test"))
        self.history = _t.EventBook(
            cover=_t.Cover(domain="player", root=_t.UUID(value=PLAYER))
        )

    def decide(self, **fields) -> tuple[list[_player.MoveDecided], _player.PlayerState]:
        command = _t.ContextualCommand(events=self.history)
        command.command.cover.CopyFrom(self.history.cover)
        command.command.page.command.payload.CopyFrom(
            _az.pack(_player.DecideMove(**fields))
        )
        response = self.host.router.dispatch(command)
        events = []
        for page in response.events.pages:
            event = _player.MoveDecided()
            assert page.payload.type_url.endswith("/io.angzarr.examples.v1.MoveDecided")
            event.ParseFromString(page.payload.value)
            events.append(event)
            stored = self.history.pages.add(payload=page.payload)
            stored.sequence = len(self.history.pages) - 1
        state = _player.PlayerState()
        state.ParseFromString(response.events.snapshot.state.value)
        return events, state

    def close(self) -> None:
        self.host.router.close()


@pytest.fixture
def player():
    p = Player()
    yield p
    p.close()


def card(rank: int, suit=_cards.CLUBS) -> _cards.Card:
    return _cards.Card(rank=rank, suit=suit)


def hand(*ranks: int, total: int, up: int = 9, soft=False, can_double=False, round=1):
    return dict(
        table_root=TABLE,
        round=round,
        seat=0,
        cards=[card(r) for r in ranks],
        total=total,
        soft=soft,
        dealer_up=card(up, _cards.DIAMONDS),
        can_double=can_double,
        stack=480,
        wager=20,
    )


def test_a_first_decision_on_an_empty_stream(player):
    """EU-1602: no registration; the stream starts at the first DecideMove."""
    events, state = player.decide(**hand(2, 4, total=6, can_double=True))
    assert len(events) == 1
    (decided,) = events
    assert (decided.table_root, decided.round, decided.seat) == (TABLE, 1, 0)
    assert decided.action == _player.MOVE_ACTION_HIT
    assert (state.decisions, state.hands_seen) == (1, 1)


def test_the_move_is_basic_strategys(player):
    events, _ = player.decide(**hand(6, 5, total=11, up=6, can_double=True))
    assert events[0].action == _player.MOVE_ACTION_DOUBLE_DOWN
    events, _ = player.decide(**hand(6, 5, total=11, up=6, can_double=False, round=2))
    assert events[0].action == _player.MOVE_ACTION_HIT
    events, _ = player.decide(**hand(1, 7, total=18, soft=True, round=3))
    assert events[0].action == _player.MOVE_ACTION_STAND


def test_the_state_after_a_few_decisions(player):
    # One hand, decided three times (EU-1606's shape): 6, then 9, then 14.
    _, state = player.decide(**hand(2, 4, total=6))
    _, state = player.decide(**hand(2, 4, 3, total=9))
    events, state = player.decide(**hand(2, 4, 3, 5, total=14))
    assert events[0].action == _player.MOVE_ACTION_HIT  # hard 14 against a 9
    assert (state.decisions, state.hands_seen) == (3, 1)
    # A second hand, next round.
    events, state = player.decide(**hand(10, 7, total=17, round=2))
    assert events[0].action == _player.MOVE_ACTION_STAND
    assert (state.decisions, state.hands_seen) == (4, 2)


def test_the_player_describes_itself_with_its_build_version(player):
    from angzarr_player._version import __version__
    from angzarr_player.main import host

    h = host()
    try:
        descriptor = h.router.component_descriptor()
    finally:
        h.router.close()
    assert descriptor.name == "PlayerAggregate"
    assert descriptor.kind == _t.COMPONENT_KIND_AGGREGATE
    assert descriptor.rules_version == __version__ != ""
