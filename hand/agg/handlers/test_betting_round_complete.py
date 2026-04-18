"""Test Hand.apply_betting_round_complete — ported from Rust
``examples-rust/main/hand/agg/src/state.rs:apply_betting_round_complete``.
"""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand_proto
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from .hand import Hand

TABLE_ROOT = b"\x10" * 16
P1 = b"\x01" * 16
P2 = b"\x02" * 16


def _pack(msg) -> ProtoAny:
    any_msg = ProtoAny()
    any_msg.Pack(msg, type_url_prefix="type.googleapis.com/")
    return any_msg


def _hand_with_cards_dealt(variant: int = poker_types.TEXAS_HOLDEM) -> Hand:
    book = types.EventBook()
    book.pages.append(
        types.EventPage(
            event=_pack(
                hand_proto.CardsDealt(
                    table_root=TABLE_ROOT,
                    hand_number=1,
                    game_variant=variant,
                    dealer_position=0,
                    players=[
                        hand_proto.PlayerInHand(player_root=P1, position=0, stack=1000),
                        hand_proto.PlayerInHand(player_root=P2, position=1, stack=1000),
                    ],
                )
            ),
        )
    )
    return Hand(event_book=book)


def test_resets_per_round_betting_state():
    hand = _hand_with_cards_dealt()
    # Simulate both players having bet this round.
    for p in hand._state.players.values():
        p.bet_this_round = 50
        p.has_acted = True
    hand._state.current_bet = 50

    event = hand_proto.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=100,
    )
    hand._apply_any(_pack(event), hand._state)

    for p in hand._state.players.values():
        assert p.bet_this_round == 0
        assert not p.has_acted
    assert hand._state.current_bet == 0


def test_updates_stack_snapshot():
    hand = _hand_with_cards_dealt()
    event = hand_proto.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=100,
        stacks=[
            hand_proto.PlayerStackSnapshot(
                player_root=P1, stack=800, is_all_in=False, has_folded=False
            ),
            hand_proto.PlayerStackSnapshot(
                player_root=P2, stack=0, is_all_in=True, has_folded=False
            ),
        ],
    )
    hand._apply_any(_pack(event), hand._state)

    p1 = next(p for p in hand._state.players.values() if p.player_root == P1)
    p2 = next(p for p in hand._state.players.values() if p.player_root == P2)
    assert p1.stack == 800
    assert not p1.is_all_in
    assert p2.stack == 0
    assert p2.is_all_in


def test_five_card_draw_advances_preflop_to_draw():
    hand = _hand_with_cards_dealt(variant=poker_types.FIVE_CARD_DRAW)
    event = hand_proto.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=100,
    )
    hand._apply_any(_pack(event), hand._state)
    assert hand._state.current_phase == poker_types.DRAW


def test_five_card_draw_post_draw_does_not_reenter():
    hand = _hand_with_cards_dealt(variant=poker_types.FIVE_CARD_DRAW)
    hand._state.current_phase = poker_types.DRAW
    event = hand_proto.BettingRoundComplete(
        completed_phase=poker_types.DRAW,
        pot_total=100,
    )
    hand._apply_any(_pack(event), hand._state)
    # Completion of the draw phase does not advance further via this applier.
    assert hand._state.current_phase == poker_types.DRAW


def test_texas_holdem_ignores_draw_transition():
    hand = _hand_with_cards_dealt(variant=poker_types.TEXAS_HOLDEM)
    hand._state.current_phase = poker_types.PREFLOP
    event = hand_proto.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        pot_total=100,
    )
    hand._apply_any(_pack(event), hand._state)
    # Holdem does not have a DRAW phase; applier leaves current_phase alone.
    assert hand._state.current_phase == poker_types.PREFLOP
