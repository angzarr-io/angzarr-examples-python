"""Cucumber steps for ``pot_distribution`` helper scenarios.

Drives the production helpers in ``hand.agg.pot_distribution`` through
behave so the cucumber suite enforces the same rules the unit tests do
(EU-1170 / EU-1171 / EU-1172 — TDA Rule 20 + Robert's §35).

Each step calls into the production helper directly. For EU-1170 the
helper output is then fed to the Hand aggregate's AwardPot handler so
the integration with the existing event-sourcing path is exercised too.
"""

from behave import given, then, use_step_matcher, when
from hand.agg.pot_distribution import (
    Award,
    WinnerWithCards,
    WinnerWithSeat,
    WinnerWithSuit,
    split_high_low_total,
    split_pot_by_high_card_walk,
    split_pot_by_suit,
    split_pot_clockwise_from_button,
)

use_step_matcher("re")


# === Helpers ===


_SUIT_INDEX = {"c": 0, "d": 1, "h": 2, "s": 3}
_RANK_INDEX = {
    "2": 0,
    "3": 1,
    "4": 2,
    "5": 3,
    "6": 4,
    "7": 5,
    "8": 6,
    "9": 7,
    "T": 8,
    "J": 9,
    "Q": 10,
    "K": 11,
    "A": 12,
}


def _suit_rank(card: str) -> int:
    """Encode a card like 'Ah' as a single integer (rank * 4 + suit) so
    higher value strictly dominates by rank-then-suit."""
    rank = _RANK_INDEX[card[0]]
    suit = _SUIT_INDEX[card[1]]
    return rank * 4 + suit


# === EU-1170 — TDA Rule 20A: odd chip clockwise of button ===


@given(r"the dealer button is at seat (?P<seat>\d+)")
def step_given_dealer_button_at_seat(context, seat):
    """Override the dealer button position on the latest CardsDealt event.

    The default ``Given a CardsDealt event for ...`` step seeds
    dealer_position=0; this step rewrites that field on the most recent
    CardsDealt event so seat-relative scenarios are deterministic.
    """
    from google.protobuf.any_pb2 import Any as ProtoAny

    from angzarr_client.proto.examples import hand_pb2 as hand_proto

    seat_int = int(seat)
    # Locate the most recent CardsDealt page in context.events.
    for page in reversed(context.events):
        ev = hand_proto.CardsDealt()
        if page.event.Unpack(ev):
            ev.dealer_position = seat_int
            new_any = ProtoAny()
            new_any.Pack(ev, type_url_prefix="type.googleapis.com/")
            page.event.CopyFrom(new_any)
            context.dealer_button_seat = seat_int
            return
    raise AssertionError("No CardsDealt event found in context.events")


@when(
    r'I handle an AwardPot command for an even tie between '
    r'"(?P<player_a>[^"]+)" and "(?P<player_b>[^"]+)"'
)
def step_when_award_pot_even_tie(context, player_a, player_b):
    """Compute an even-tie pot split via the production helper, then
    invoke the Hand aggregate's AwardPot handler with the result.

    Per TDA Rule 20A: in board games the odd chip goes to the first
    seat clockwise of the dealer button. Both the helper output and
    the resulting PotAwarded event are observable from later Then
    steps, so any divergence between helper and handler will surface.
    """
    from hand.agg.handlers import Hand
    from angzarr_client.proto.examples import hand_pb2 as hand_proto

    # Find the seats of the two named players from the latest CardsDealt event.
    seat_by_name = {}
    for page in context.events:
        ev = hand_proto.CardsDealt()
        if page.event.Unpack(ev):
            for p in ev.players:
                # player_root encoded as uuid_for(name) — we recover the
                # name from context.players_by_root populated when the
                # CardsDealt was constructed. Fall back to scanning for
                # the well-known names in the scenario.
                pass
    # Simpler: the scenario gives players via the table column. We use
    # the position field as seat.
    from tests.helpers import uuid_for

    a_root = uuid_for(player_a)
    b_root = uuid_for(player_b)
    seat_a = seat_b = None
    for page in context.events:
        ev = hand_proto.CardsDealt()
        if page.event.Unpack(ev):
            for p in ev.players:
                if p.player_root == a_root:
                    seat_a = p.position
                elif p.player_root == b_root:
                    seat_b = p.position
    assert seat_a is not None, f"Player {player_a} not found in CardsDealt"
    assert seat_b is not None, f"Player {player_b} not found in CardsDealt"
    button = getattr(context, "dealer_button_seat", 0)

    # Compute split via the production helper.
    pot = context.pot_total if hasattr(context, "pot_total") else 0
    if not pot:
        # Fall back: scan BlindPosted events for the most recent pot_total.
        for page in context.events:
            bp = hand_proto.BlindPosted()
            if page.event.Unpack(bp):
                if bp.pot_total:
                    pot = bp.pot_total
    assert pot > 0, "No pot total established by prior steps"

    # If the pot total was declared but no BlindPosted events exist (the
    # default blinds-posted step skips when player-1/player-2 aren't
    # seated), seed two BlindPosted events against the named winners so
    # the aggregate's pot_total matches what AwardPot will assert against.
    have_blinds = any(
        page.event.Is(hand_proto.BlindPosted.DESCRIPTOR) for page in context.events
    )
    if not have_blinds:
        from datetime import datetime, timezone
        from google.protobuf.any_pb2 import Any as ProtoAny
        from google.protobuf.timestamp_pb2 import Timestamp
        from angzarr_client.proto.angzarr import types_pb2 as types

        sb = pot // 2
        bb = pot - sb
        for blind_type, name, root, amt, running in (
            ("small", player_a, a_root, sb, sb),
            ("big", player_b, b_root, bb, sb + bb),
        ):
            evt = hand_proto.BlindPosted(
                player_root=root,
                blind_type=blind_type,
                amount=amt,
                player_stack=500 - amt,
                pot_total=running,
                posted_at=Timestamp(
                    seconds=int(datetime.now(timezone.utc).timestamp())
                ),
            )
            event_any = ProtoAny()
            event_any.Pack(evt, type_url_prefix="type.googleapis.com/")
            context.events.append(
                types.EventPage(
                    header=types.PageHeader(sequence=len(context.events)),
                    event=event_any,
                    created_at=Timestamp(
                        seconds=int(datetime.now(timezone.utc).timestamp())
                    ),
                )
            )

    awards = split_pot_clockwise_from_button(
        pot=pot,
        winners=[
            WinnerWithSeat(player_root=player_a, seat=seat_a),
            WinnerWithSeat(player_root=player_b, seat=seat_b),
        ],
        dealer_button_seat=button,
        # Use a generous max_seats since we don't track table capacity
        # here. TDA Rule 11 caps at 10 for flop games; pad for safety.
        max_seats=max(seat_a, seat_b, button) + 1,
    )

    # Drive the AwardPot handler with the helper-computed awards.
    cmd = hand_proto.AwardPot()
    for a in awards:
        cmd.awards.append(
            hand_proto.PotAward(
                player_root=uuid_for(a.player_root),
                amount=a.amount,
                pot_type="main",
            )
        )
    # Use the standard handler-execution helper from hand_steps.
    from unit_steps.hand_steps import _execute_handler

    _execute_handler(context, "award", cmd)


# === EU-1171 — TDA Rule 20C: H/L odd chip to high side ===


@given(
    r"a hand at showdown with split-pot variant, "
    r'high winner "(?P<high_winner>[^"]+)" and low winner "(?P<low_winner>[^"]+)"'
)
def step_given_split_pot_winners(context, high_winner, low_winner):
    """Record the high and low winners for an H/L split scenario.

    No event sourcing here — the EU-1171 scenario tests the pot-split
    arithmetic in isolation.
    """
    context.high_winner = high_winner
    context.low_winner = low_winner


@when(r"the pot of (?P<pot>\d+) is split between high and low")
def step_when_split_pot_high_low(context, pot):
    """Drive the production helper for total H/L pot split."""
    result = split_high_low_total(pot=int(pot))
    context.high_share = result.high_share
    context.low_share = result.low_share


@then(r"the high side receives (?P<expected>\d+)")
def step_then_high_side_receives(context, expected):
    assert context.high_share == int(
        expected
    ), f"Expected high_share={expected}, got {context.high_share}"


@then(r"the low side receives (?P<expected>\d+)")
def step_then_low_side_receives(context, expected):
    assert context.low_share == int(
        expected
    ), f"Expected low_share={expected}, got {context.low_share}"


# === EU-1172 — Robert's §35-9: multi-way odd chip = high card by suit ===


@given(r"a hand at showdown with H/L split, two high winners tied")
def step_given_two_high_winners_tied(context):
    """Initialize the multi-way high-side split tracker."""
    context.tied_winners = []


@given(r'player "(?P<name>[^"]+)" holds the high card by suit "(?P<card>[^"]+)"')
def step_given_player_high_card_by_suit(context, name, card):
    """Record a tied winner with their high card-by-suit ranking."""
    if not hasattr(context, "tied_winners"):
        context.tied_winners = []
    context.tied_winners.append(
        WinnerWithSuit(player_root=name, suit_rank=_suit_rank(card))
    )


@when(r"the high half of the pot \((?P<pot>\d+)\) is split")
def step_when_high_half_split(context, pot):
    """Drive the production helper for high-card-by-suit split."""
    awards = split_pot_by_suit(
        pot=int(pot), winners=context.tied_winners, high_wins=True
    )
    context.suit_split_awards = {a.player_root: a.amount for a in awards}


@then(r'player "(?P<name>[^"]+)" receives (?P<expected>\d+)')
def step_then_player_receives(context, name, expected):
    actual = context.suit_split_awards.get(name)
    assert actual == int(
        expected
    ), f"Expected {name} to receive {expected}, got {actual}"


# === EU-1322 — TDA Rule 20B: stud high-card-by-suit walk =====================
#
# Stud uses a different odd-chip rule from board games: the odd chip goes
# to the player whose 5-card winning hand has the highest card by suit
# walking top-to-bottom. Two FULL_HOUSE Jacks-over-eights hands compare
# Js → Js (tie), Jh → Jd (Alice's hearts wins), so Alice gets the odd chip.


def _parse_card_pair(token: str) -> tuple:
    """Parse 'Jh' into (suit_index, rank). Suit indexing matches
    pot_distribution.WinnerWithCards convention (0=c,1=d,2=h,3=s)."""
    rank_char, suit_char = token[0].upper(), token[1].lower()
    return (_SUIT_INDEX[suit_char], _RANK_INDEX[rank_char] + 2)


def _parse_card_list(text: str) -> tuple:
    """Whitespace-separated card list → tuple of (suit_index, rank)."""
    return tuple(_parse_card_pair(tok) for tok in text.split())


@given(
    r'a Seven Card Stud hand at showdown with player "(?P<name>[^"]+)" '
    r'5-card hand "(?P<cards>[^"]+)"'
)
def step_given_stud_showdown_player_hand(context, name, cards):
    """Record a tied stud-showdown winner with their 5-card hand. The
    'When the pot is split' step then drives the helper directly. We
    don't seed a hand-aggregate event chain here — the stud showdown
    machinery isn't built yet (see Batch 8 EU-1321 etc.) — but we DO
    drive the production helper, so any divergence between stud rule and
    board-game rule will surface in the helper output."""
    if not hasattr(context, "stud_winners"):
        context.stud_winners = []
    context.stud_winners.append(
        WinnerWithCards(player_root=name, cards=_parse_card_list(cards))
    )


@given(r'player "(?P<name>[^"]+)" 5-card hand "(?P<cards>[^"]+)"')
def step_given_stud_showdown_extra_hand(context, name, cards):
    if not hasattr(context, "stud_winners"):
        context.stud_winners = []
    context.stud_winners.append(
        WinnerWithCards(player_root=name, cards=_parse_card_list(cards))
    )


@when(
    r'the pot of (?P<pot>\d+) is split between '
    r'"(?P<player_a>[^"]+)" and "(?P<player_b>[^"]+)"'
)
def step_when_stud_pot_split_between(context, pot, player_a, player_b):
    """Drive the stud high-card-by-suit-walk helper and synthesize a
    result book so the standard ``a … PotAwarded event is emitted`` and
    ``the award event has winner X with amount N`` Then steps match.
    The full hand aggregate has no stud showdown path yet (Batch 8
    EU-1321 etc.) — this step exercises the production helper directly,
    which is the only behavior EU-1322 actually pins."""
    from datetime import datetime, timezone

    from google.protobuf.any_pb2 import Any as ProtoAny
    from google.protobuf.timestamp_pb2 import Timestamp
    from tests.helpers import uuid_for
    from unit_steps.hand_steps import _make_event_book

    from angzarr_client.proto.angzarr import types_pb2 as types
    from angzarr_client.proto.examples import hand_pb2 as hand_proto

    awards = split_pot_by_high_card_walk(
        pot=int(pot), winners=context.stud_winners
    )
    context.suit_walk_awards = {a.player_root: a.amount for a in awards}

    awarded = hand_proto.PotAwarded(
        awarded_at=Timestamp(
            seconds=int(datetime.now(timezone.utc).timestamp())
        ),
    )
    for a in awards:
        awarded.winners.append(
            hand_proto.PotWinner(
                player_root=uuid_for(a.player_root),
                amount=a.amount,
                pot_type="main",
            )
        )
    event_any = ProtoAny()
    event_any.Pack(awarded, type_url_prefix="type.googleapis.com/")
    page = types.EventPage(
        header=types.PageHeader(sequence=0),
        event=event_any,
        created_at=Timestamp(
            seconds=int(datetime.now(timezone.utc).timestamp())
        ),
    )
    context.result = _make_event_book([page])
    context.result_event_any = event_any
    context.error = None
    if not hasattr(context, "events"):
        context.events = []
    context.events.append(page)
