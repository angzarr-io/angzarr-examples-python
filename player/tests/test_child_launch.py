"""The player launched as angzarr-embedded launches it: a child process
(``python -m angzarr_player``, the interpreter of this locked environment,
what ``uv run --locked angzarr-player`` runs) that writes the handshake line
and then answers Describe and Handle on the socket it names."""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
import tempfile

import angzarr_client.router as _az
import grpc
import pytest
from angzarr_client.child import SOCKET_ENV, parse_handshake
from angzarr_client.proto.io.angzarr.v1 import (
    command_handler_pb2_grpc,
    component_pb2,
    component_pb2_grpc,
)
from angzarr_client.proto.io.angzarr.v1 import types_pb2 as _t

from angzarr_player._gen.io.angzarr.examples.v1 import cards_pb2 as _cards
from angzarr_player._gen.io.angzarr.examples.v1 import player_pb2 as _player


@pytest.fixture
def child():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "player.sock")
        proc = subprocess.Popen(
            [sys.executable, "-m", "angzarr_player"],
            env=dict(os.environ, **{SOCKET_ENV: path}),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            sel = selectors.DefaultSelector()
            sel.register(proc.stdout, selectors.EVENT_READ)
            assert sel.select(timeout=30), "no handshake within 30s"
            line = proc.stdout.readline().decode()
            if not line:
                pytest.fail(
                    f"exited before its handshake: {proc.stderr.read().decode()}"
                )
            assert line == f"angzarr-handshake v1 unix:{path}\n"
            yield proc, parse_handshake(line)
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                proc.wait(timeout=30)
            proc.stdout.close()
            proc.stderr.close()


def test_the_launched_player_describes_itself(child):
    _, address = child
    with grpc.insecure_channel(address) as channel:
        descriptor = component_pb2_grpc.ComponentServiceStub(channel).Describe(
            component_pb2.DescribeRequest(), timeout=10
        )
    from angzarr_player._descriptor import DESCRIPTOR

    assert descriptor == DESCRIPTOR
    assert descriptor.name == "PlayerAggregate"
    assert descriptor.kind == _t.COMPONENT_KIND_AGGREGATE


def test_the_launched_player_decides_a_move(child):
    _, address = child
    command = _t.ContextualCommand(
        events=_t.EventBook(
            cover=_t.Cover(domain="player", root=_t.UUID(value=b"\x0a" * 16))
        )
    )
    command.command.cover.CopyFrom(command.events.cover)
    command.command.page.command.payload.CopyFrom(
        _az.pack(
            _player.DecideMove(
                table_root=b"\x01" * 16,
                round=1,
                seat=0,
                cards=[
                    _cards.Card(rank=10, suit=_cards.CLUBS),
                    _cards.Card(rank=7, suit=_cards.SPADES),
                ],
                total=17,
                dealer_up=_cards.Card(rank=9, suit=_cards.DIAMONDS),
                stack=480,
                wager=20,
            )
        )
    )
    with grpc.insecure_channel(address) as channel:
        response = command_handler_pb2_grpc.CommandHandlerServiceStub(channel).Handle(
            command, timeout=10
        )
    (page,) = response.events.pages
    decided = _player.MoveDecided()
    decided.ParseFromString(page.payload.value)
    assert decided.action == _player.MOVE_ACTION_STAND


def test_closing_stdin_ends_the_launched_player(child):
    proc, address = child
    proc.stdin.close()
    assert proc.wait(timeout=30) == 0
    assert not os.path.exists(address.removeprefix("unix:"))
