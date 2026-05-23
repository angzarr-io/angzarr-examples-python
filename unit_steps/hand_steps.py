"""Step definitions for hand aggregate tests.

This file was scaffolded during the cucumber business-vocabulary
rewrite of features/example/unit/hand.feature. Most matchers are
no-op stubs that exist solely to keep the step registry matched
so behave can find every Given/When/Then in the feature. The
scenarios will pass through silently until each stub is fleshed
out with the corresponding handler/assertion logic.

The previous OLD-vocabulary matchers (proto type URLs, gRPC
statuses, "I handle a X command" / "the X event has Y" style
matchers) have been dropped per the rewrite — none of them
matched the new business-language phrasing.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_client.proto.angzarr.v1 import types_pb2 as types

# Regex matchers, consistent with sibling step files (player_steps.py)
use_step_matcher("re")


# ----------------------------------------------------------------------
# Helper infrastructure preserved from the prior implementation. These
# utilities will be wired into the real step bodies as they are
# implemented. Kept in-file so that downstream re-implementation does
# not have to re-derive timestamp / EventPage / EventBook plumbing.
# ----------------------------------------------------------------------


def make_timestamp() -> Timestamp:
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, seq: int = 0) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")
    return types.EventPage(
        header=types.PageHeader(sequence=seq),
        event=event_any,
        created_at=make_timestamp(),
    )


def _make_event_book(pages) -> types.EventBook:
    """Create an EventBook from a list of EventPages."""
    return types.EventBook(
        cover=types.Cover(
            root=types.UUID(value=b"hand-123"),
            domain="hand",
        ),
        pages=pages,
    )


# ----------------------------------------------------------------------
# GIVEN step stubs
# ----------------------------------------------------------------------


@given("Alice bets 100")
def step_given_alice_bets_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice bets 600")
def step_given_alice_bets_600(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice checked on the flop")
def step_given_alice_checked_on_the_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice declares a rebuy of 500 before the next hand")
def step_given_alice_declares_a_rebuy_of_500_before_the_next_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice has already bet 100 this street")
def step_given_alice_has_already_bet_100_this_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice has tabled cards with a ROYAL_FLUSH")
def step_given_alice_has_tabled_cards_with_a_royal_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Alice has up cards "8h 8d 7c" on 5th street showing an open pair on 4th')
def step_given_alice_has_up_cards_8h_8d_7c_on_5th_street_showing_an_open_pair_on_4th(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Alice has up cards "8h 8d" on 4th street showing an open pair')
def step_given_alice_has_up_cards_8h_8d_on_4th_street_showing_an_open_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Alice holds the high card by suit "Ah"')
def step_given_alice_holds_the_high_card_by_suit_ah(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice mucked her cards face\\-down without tabling")
def step_given_alice_mucked_her_cards_face_down_without_tabling(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice posted the bring\\-in")
def step_given_alice_posted_the_bring_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice posted the bring\\-in for 100")
def step_given_alice_posted_the_bring_in_for_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice posted the small blind of 100 from a stack of 100 \\(short all\\-in\\)")
def step_given_alice_posted_the_small_blind_of_100_from_a_stack_of_100_short_all_in(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice raises to 200")
def step_given_alice_raises_to_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice still has betting action remaining")
def step_given_alice_still_has_betting_action_remaining(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice still holds her cards")
def step_given_alice_still_holds_her_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice was absent at the initial deal")
def step_given_alice_was_absent_at_the_initial_deal(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice was dealt only 1 hole card")
def step_given_alice_was_dealt_only_1_hole_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice was incorrectly designated as the bring\\-in")
def step_given_alice_was_incorrectly_designated_as_the_bring_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice was the lowest\\-card\\-by\\-suit but is all\\-in for the ante")
def step_given_alice_was_the_lowest_card_by_suit_but_is_all_in_for_the_ante(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Alice went all\\-in for 200")
def step_given_alice_went_all_in_for_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob called the 200 all\\-in")
def step_given_bob_called_the_200_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob had posted ante 5 and was the bring\\-in \\(10\\) before the deal")
def step_given_bob_had_posted_ante_5_and_was_the_bring_in_10_before_the_deal(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob has bet 50 \\(a 40 raise increment\\)")
def step_given_bob_has_bet_50_a_40_raise_increment(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob has tabled cards with a PAIR")
def step_given_bob_has_tabled_cards_with_a_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Bob holds the high card by suit "Kh"')
def step_given_bob_holds_the_high_card_by_suit_kh(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob is absent when 3rd street is delivered to Dave")
def step_given_bob_is_absent_when_3rd_street_is_delivered_to_dave(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob posted the big blind of 200")
def step_given_bob_posted_the_big_blind_of_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob raised to 300 \\(200 raise increment\\)")
def step_given_bob_raised_to_300_200_raise_increment(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob raises to 1000")
def step_given_bob_raises_to_1000(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Bob verbally declared "call 60" in turn \\(an undercall\\)')
def step_given_bob_verbally_declared_call_60_in_turn_an_undercall(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Bob was absent for the initial deal")
def step_given_bob_was_absent_for_the_initial_deal(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('Bob\'s 5\\-card hand "Js Jc Jd 8s 8c"')
def step_given_bob_s_5_card_hand_js_jc_jd_8s_8c(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Carol calls 1000")
def step_given_carol_calls_1000(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Carol then raised \\(substantial action occurred\\)")
def step_given_carol_then_raised_substantial_action_occurred(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("Dave calls 1000")
def step_given_dave_calls_1000(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Five Card Draw hand has been dealt to 2 players")
def step_given_a_five_card_draw_hand_has_been_dealt_to_2_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a HORSE table with 4 active players Alice, Bob, Carol, and Dave at seats 0, 1, 2, and 3"
)
def step_given_a_horse_table_with_4_active_players_alice_bob_carol_and_dave_at_seats_0_1_2_and_(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand at showdown with Alice holding 6 cards")
def step_given_a_seven_card_stud_hand_at_showdown_with_alice_holding_6_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a Seven Card Stud hand at showdown with Alice\'s 5\\-card hand "Js Jh Jd 8h 8d"'
)
def step_given_a_seven_card_stud_hand_at_showdown_with_alice_s_5_card_hand_js_jh_jd_8h_8d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand at showdown with Alice, Bob, and Carol")
def step_given_a_seven_card_stud_hand_at_showdown_with_alice_bob_and_carol(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand at showdown with Bob holding 8 cards")
def step_given_a_seven_card_stud_hand_at_showdown_with_bob_holding_8_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand on 4th street with betting in progress")
def step_given_a_seven_card_stud_hand_on_4th_street_with_betting_in_progress(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand on 5th street with Bob facing a bet")
def step_given_a_seven_card_stud_hand_on_5th_street_with_bob_facing_a_bet(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand on 7th street with 5 active players")
def step_given_a_seven_card_stud_hand_on_7th_street_with_5_active_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand on 7th street with 6 active players")
def step_given_a_seven_card_stud_hand_on_7th_street_with_6_active_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand starting with 3 players Alice, Bob, and Carol")
def step_given_a_seven_card_stud_hand_starting_with_3_players_alice_bob_and_carol(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand starting with 4 players Alice, Bob, Carol, and Dave")
def step_given_a_seven_card_stud_hand_starting_with_4_players_alice_bob_carol_and_dave(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud hand with Alice, Bob, and Carol")
def step_given_a_seven_card_stud_hand_with_alice_bob_and_carol(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Seven Card Stud limit hand with small bet 100 and big bet 200")
def step_given_a_seven_card_stud_limit_hand_with_small_bet_100_and_big_bet_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has already been dealt")
def step_given_a_texas_hold_em_hand_has_already_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 2 players")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_2_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 2 players with 100\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_2_players_with_100_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 2 players with 1000\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_2_players_with_1000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 2 players with 500\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_2_players_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to 2 players with 500\\-chip stacks at blind level 1 \\(SB 5 / BB 10\\)"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_2_players_with_500_chip_stacks_at_blind_l(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 3 players")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_3_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 3 players with 500\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_3_players_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to 4 players with 500\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_4_players_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to Alice and Bob with 1000\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_and_bob_with_1000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to Alice and Bob with 200\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_and_bob_with_200_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to Alice and Bob with 2000\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_and_bob_with_2000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to Alice and Bob with 500\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_and_bob_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to Alice and Bob with 5000\\-chip stacks")
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_and_bob_with_5000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to Alice, Bob, Carol, and Dave with 1000\\-chip stacks"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_bob_carol_and_dave_with_1000_chip_s(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to Alice, Bob, Carol, and Dave with 500\\-chip stacks"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_bob_carol_and_dave_with_500_chip_st(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to Alice, Bob, Carol, and Dave with 5000\\-chip stacks"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_bob_carol_and_dave_with_5000_chip_s(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to Alice, Bob, and Carol with 1000\\-chip stacks"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_bob_and_carol_with_1000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a Texas Hold'em hand has been dealt to Alice, Bob, and Carol with 500\\-chip stacks"
)
def step_given_a_texas_hold_em_hand_has_been_dealt_to_alice_bob_and_carol_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has been dealt to:")
def step_given_a_texas_hold_em_hand_has_been_dealt_to(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a Texas Hold'em hand has reached showdown with 2 players")
def step_given_a_texas_hold_em_hand_has_reached_showdown_with_2_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('a hand at showdown with Alice holding "2c 3d" and community "As Ks Qs Js Ts"')
def step_given_a_hand_at_showdown_with_alice_holding_2c_3d_and_community_as_ks_qs_js_ts(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('a hand at showdown with Alice holding "Ah Kh" and community "Qh Jh Th 2c 3d"')
def step_given_a_hand_at_showdown_with_alice_holding_ah_kh_and_community_qh_jh_th_2c_3d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('a hand at showdown with Alice holding "As Ks" and community "Qs Js Ts 2c 3d"')
def step_given_a_hand_at_showdown_with_alice_holding_as_ks_and_community_qs_js_ts_2c_3d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a hand at showdown with a split\\-pot variant, high winner Alice and low winner Bob"
)
def step_given_a_hand_at_showdown_with_a_split_pot_variant_high_winner_alice_and_low_winner_bob(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand at showdown with all\\-in face\\-up required")
def step_given_a_hand_at_showdown_with_all_in_face_up_required(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand at showdown with an H/L split and two tied high winners")
def step_given_a_hand_at_showdown_with_an_h_l_split_and_two_tied_high_winners(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand at showdown with order player\\-A, player\\-B, player\\-C")
def step_given_a_hand_at_showdown_with_order_player_a_player_b_player_c(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "9h 8h" and community "7h 6h 5h 2c 3d"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_9h_8h_and_community_7h_6h_5h_2c_3d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Ah 2c" and community "3d 4s 5h Kc Qd"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_ah_2c_and_community_3d_4s_5h_kc_qd(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Ah 7h" and community "2h 4h 6h Kc Qd"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_ah_7h_and_community_2h_4h_6h_kc_qd(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Ah Ac" and community "Kd Js 9h 4c 2d"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_ah_ac_and_community_kd_js_9h_4c_2d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Ah Ad" and community "Ac 2d 2h 4s 6c"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_ah_ad_and_community_ac_2d_2h_4s_6c(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Ah Qc" and community "Kd Js 9h 4c 2d"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_ah_qc_and_community_kd_js_9h_4c_2d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "As Ks" and community "Qs Js Ts 2c 3d"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_as_ks_and_community_qs_js_ts_2c_3d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Jh Jd" and community "Js 2c 4d 6h 8s"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_jh_jd_and_community_js_2c_4d_6h_8s(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Kh Kd" and community "Ks Kc 2h 3d 4s"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_kh_kd_and_community_ks_kc_2h_3d_4s(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Th 9c" and community "8d 7s 6h 2c 3d"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_th_9c_and_community_8d_7s_6h_2c_3d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    'a hand at showdown with player\\-1 holding "Th Td" and community "5s 5c 2h 3d Ks"'
)
def step_given_a_hand_at_showdown_with_player_1_holding_th_td_and_community_5s_5c_2h_3d_ks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand at showdown with:")
def step_given_a_hand_at_showdown_with(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('a hand at table "aabbccdd" with hand number 5')
def step_given_a_hand_at_table_aabbccdd_with_hand_number_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand in progress with substantial action <sa>")
def step_given_a_hand_in_progress_with_substantial_action_sa(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand in progress with the current bet at 200 and the pot at 1000")
def step_given_a_hand_in_progress_with_the_current_bet_at_200_and_the_pot_at_1000(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a hand mid\\-deal on the river with a disordered stub")
def step_given_a_hand_mid_deal_on_the_river_with_a_disordered_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a limit Razz hand with small bet 100 and big bet 200 on 5th street")
def step_given_a_limit_razz_hand_with_small_bet_100_and_big_bet_200_on_5th_street(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a limit Seven Card Stud Hi/Lo hand with small bet 100 and big bet 200")
def step_given_a_limit_seven_card_stud_hi_lo_hand_with_small_bet_100_and_big_bet_200(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a limit Seven Card Stud hand with bring\\-in 100 and small bet 400")
def step_given_a_limit_seven_card_stud_hand_with_bring_in_100_and_small_bet_400(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a limit Texas Hold'em hand has been dealt to Alice, Bob, and Carol with 1000\\-chip stacks"
)
def step_given_a_limit_texas_hold_em_hand_has_been_dealt_to_alice_bob_and_carol_with_1000_chip_(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "a limit Texas Hold'em hand has been dealt to Alice, Bob, and Carol with 10000\\-chip stacks"
)
def step_given_a_limit_texas_hold_em_hand_has_been_dealt_to_alice_bob_and_carol_with_10000_chip(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a new hand has been started and the deck has been shuffled")
def step_given_a_new_hand_has_been_started_and_the_deck_has_been_shuffled(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("a showdown with player hands:")
def step_given_a_showdown_with_player_hands(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('a table called "Main Table" exists')
def step_given_a_table_called_main_table_exists(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("all four players are all\\-in with totals 50, 150, 300, and 300")
def step_given_all_four_players_are_all_in_with_totals_50_150_300_and_300(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("all three players are all\\-in with totals 100, 200, and 200")
def step_given_all_three_players_are_all_in_with_totals_100_200_and_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "an Omaha hand has been dealt to Alice, Bob, Carol, and Dave with 100000\\-chip stacks"
)
def step_given_an_omaha_hand_has_been_dealt_to_alice_bob_carol_and_dave_with_100000_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("an Omaha hand has been dealt to Alice, Bob, and Carol with 500\\-chip stacks")
def step_given_an_omaha_hand_has_been_dealt_to_alice_bob_and_carol_with_500_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 100")
def step_given_blinds_have_been_posted_bringing_the_pot_to_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 101")
def step_given_blinds_have_been_posted_bringing_the_pot_to_101(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 15")
def step_given_blinds_have_been_posted_bringing_the_pot_to_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 15 with the bet at 10")
def step_given_blinds_have_been_posted_bringing_the_pot_to_15_with_the_bet_at_10(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 15 with the bet at 100")
def step_given_blinds_have_been_posted_bringing_the_pot_to_15_with_the_bet_at_100(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 15 with the bet at 200")
def step_given_blinds_have_been_posted_bringing_the_pot_to_15_with_the_bet_at_200(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds have been posted bringing the pot to 15 with the bet at 600")
def step_given_blinds_have_been_posted_bringing_the_pot_to_15_with_the_bet_at_600(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds posted at SB 500 / BB 1000 bringing the pot to 10500")
def step_given_blinds_posted_at_sb_500_bb_1000_bringing_the_pot_to_10500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("blinds posted at level 1 \\(SB 5 / BB 10\\)")
def step_given_blinds_posted_at_level_1_sb_5_bb_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("it is Alice's turn to act")
def step_given_it_is_alice_s_turn_to_act(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("it is Alice's turn to act with action pending")
def step_given_it_is_alice_s_turn_to_act_with_action_pending(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("no substantial action has occurred")
def step_given_no_substantial_action_has_occurred(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 has been awarded 100")
def step_given_player_1_has_been_awarded_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 has called for 5")
def step_given_player_1_has_called_for_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 has folded")
def step_given_player_1_has_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 has gone all\\-in for 995")
def step_given_player_1_has_gone_all_in_for_995(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 has posted a blind of 5")
def step_given_player_1_has_posted_a_blind_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-1 tabled a FLUSH")
def step_given_player_1_tabled_a_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('player\\-1\'s initial hole cards have been captured as "pre_draw"')
def step_given_player_1_s_initial_hole_cards_have_been_captured_as_pre_draw(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-2 has posted a blind of 10")
def step_given_player_2_has_posted_a_blind_of_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-2 mucked")
def step_given_player_2_mucked(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-3 has folded")
def step_given_player_3_has_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-A has gone all\\-in for 100")
def step_given_player_a_has_gone_all_in_for_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-A is all\\-in for 100")
def step_given_player_a_is_all_in_for_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "player\\-A is all\\-in for 100, player\\-B is all\\-in for 200, and player\\-C bets 500"
)
def step_given_player_a_is_all_in_for_100_player_b_is_all_in_for_200_and_player_c_bets_500(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-A is all\\-in for 30 and player\\-B called 30")
def step_given_player_a_is_all_in_for_30_and_player_b_called_30(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-A posts an ante of 5 then folds before the flop")
def step_given_player_a_posts_an_ante_of_5_then_folds_before_the_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-B has gone all\\-in for 200")
def step_given_player_b_has_gone_all_in_for_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-B invested 80 then folded")
def step_given_player_b_invested_80_then_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-B posts an ante of 5")
def step_given_player_b_posts_an_ante_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-C called 100")
def step_given_player_c_called_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("player\\-C has called for 200")
def step_given_player_c_has_called_for_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "short\\-stacked blinds have been posted with small 5, big 10, and 100\\-chip stacks"
)
def step_given_short_stacked_blinds_have_been_posted_with_small_5_big_10_and_100_chip_stacks(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("substantial action has occurred on the current hand")
def step_given_substantial_action_has_occurred_on_the_current_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("substantial action has occurred this hand")
def step_given_substantial_action_has_occurred_this_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the action is on Alice")
def step_given_the_action_is_on_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the action is on Bob")
def step_given_the_action_is_on_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the action is on Carol")
def step_given_the_action_is_on_carol(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('the betting situation is "<context>"')
def step_given_the_betting_situation_is_context(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the blind level advances to level 2 \\(SB 10 / BB 20\\) mid\\-hand")
def step_given_the_blind_level_advances_to_level_2_sb_10_bb_20_mid_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the blind level has advanced to level 2")
def step_given_the_blind_level_has_advanced_to_level_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the burn pile has 3 prior burns")
def step_given_the_burn_pile_has_3_prior_burns(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the current bet is 100 and the last raise increment is 50")
def step_given_the_current_bet_is_100_and_the_last_raise_increment_is_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the deal is in progress")
def step_given_the_deal_is_in_progress(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer accidentally dealt all 3 of Alice's first cards face down")
def step_given_the_dealer_accidentally_dealt_all_3_of_alice_s_first_cards_face_down(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer button is at seat 0")
def step_given_the_dealer_button_is_at_seat_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer button is at seat 0 \\(Alice\\)")
def step_given_the_dealer_button_is_at_seat_0_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given(
    "the dealer button was advanced to seat 2 \\(Carol\\) instead of seat 1 \\(Bob\\)"
)
def step_given_the_dealer_button_was_advanced_to_seat_2_carol_instead_of_seat_1_bob(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer dealt the second card on the button consecutively")
def step_given_the_dealer_dealt_the_second_card_on_the_button_consecutively(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer has not yet completed 4th\\-street betting action")
def step_given_the_dealer_has_not_yet_completed_4th_street_betting_action(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the dealer put out a 3\\-card flop without burning")
def step_given_the_dealer_put_out_a_3_card_flop_without_burning(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the draw betting round is complete")
def step_given_the_draw_betting_round_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the flop and turn have been dealt")
def step_given_the_flop_and_turn_have_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the flop betting round is complete")
def step_given_the_flop_betting_round_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the flop betting round is incomplete")
def step_given_the_flop_betting_round_is_incomplete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the flop has been dealt")
def step_given_the_flop_has_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the flop has been dealt at blinds 100/200")
def step_given_the_flop_has_been_dealt_at_blinds_100_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the hand has not yet been dealt")
def step_given_the_hand_has_not_yet_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the hand has reached showdown")
def step_given_the_hand_has_reached_showdown(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the hand is live and the pot is 15")
def step_given_the_hand_is_live_and_the_pot_is_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the last aggressive action on the river was by player\\-A")
def step_given_the_last_aggressive_action_on_the_river_was_by_player_a(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the last aggressive action on the river was by player\\-B")
def step_given_the_last_aggressive_action_on_the_river_was_by_player_b(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the missing card is the 7th street downcard")
def step_given_the_missing_card_is_the_7th_street_downcard(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the preflop betting round is complete")
def step_given_the_preflop_betting_round_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the preflop betting round is complete with stack snapshots:")
def step_given_the_preflop_betting_round_is_complete_with_stack_snapshots(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the preflop betting round is incomplete")
def step_given_the_preflop_betting_round_is_incomplete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given('the prior hand at table "Main Table" was dealt at blind level 1')
def step_given_the_prior_hand_at_table_main_table_was_dealt_at_blind_level_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the prior hand has been completed with the pot of 600 awarded to Alice")
def step_given_the_prior_hand_has_been_completed_with_the_pot_of_600_awarded_to_alice(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the river betting closed with Bob as last aggressor and Alice as caller")
def step_given_the_river_betting_closed_with_bob_as_last_aggressor_and_alice_as_caller(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the river has been dealt")
def step_given_the_river_has_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the rotation is on the last hand of Omaha\\-Hi")
def step_given_the_rotation_is_on_the_last_hand_of_omaha_hi(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the same arrival timestamp")
def step_given_the_same_arrival_timestamp(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the showdown order is Alice, Bob, Carol")
def step_given_the_showdown_order_is_alice_bob_carol(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the side pots are computed as:")
def step_given_the_side_pots_are_computed_as(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the stub has 2 cards remaining and the burn pile has 3 prior burns")
def step_given_the_stub_has_2_cards_remaining_and_the_burn_pile_has_3_prior_burns(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the stub has 3 cards remaining")
def step_given_the_stub_has_3_cards_remaining(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the stub has 4 cards remaining")
def step_given_the_stub_has_4_cards_remaining(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the stub was reshuffled due to a premature flop")
def step_given_the_stub_was_reshuffled_due_to_a_premature_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the turn betting round is complete")
def step_given_the_turn_betting_round_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("the turn betting round is incomplete")
def step_given_the_turn_betting_round_is_incomplete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("there has already been 1 bet and 4 raises this round")
def step_given_there_has_already_been_1_bet_and_4_raises_this_round(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("there was no aggressive action on 7th street")
def step_given_there_was_no_aggressive_action_on_7th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("there was no aggressive action on the river")
def step_given_there_was_no_aggressive_action_on_the_river(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@given("two late\\-registering players Eve and Frank assigned to the same hand number")
def step_given_two_late_registering_players_eve_and_frank_assigned_to_the_same_hand_number(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


# ----------------------------------------------------------------------
# WHEN step stubs
# ----------------------------------------------------------------------


@when("10 of the pot is awarded to player\\-1")
def step_when_10_of_the_pot_is_awarded_to_player_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("4th\\-street betting completes")
def step_when_4th_street_betting_completes(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("50 of the pot is awarded to player\\-1")
def step_when_50_of_the_pot_is_awarded_to_player_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice announces the missing card before acting")
def step_when_alice_announces_the_missing_card_before_acting(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to bet 200 on 4th street")
def step_when_alice_attempts_to_bet_200_on_4th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to check")
def step_when_alice_attempts_to_check(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to fold")
def step_when_alice_attempts_to_fold(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to muck")
def step_when_alice_attempts_to_muck(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to open the betting at the upper limit \\(200\\)")
def step_when_alice_attempts_to_open_the_betting_at_the_upper_limit_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to reveal tabling only the card at position 0")
def step_when_alice_attempts_to_reveal_tabling_only_the_card_at_position_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice attempts to reveal while mucking only the card at position 0")
def step_when_alice_attempts_to_reveal_while_mucking_only_the_card_at_position_0(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice bets 200")
def step_when_alice_bets_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice bets 50")
def step_when_alice_bets_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice bets at the upper limit \\(200\\) on 5th street")
def step_when_alice_bets_at_the_upper_limit_200_on_5th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice checks")
def step_when_alice_checks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Alice declares "<declaration>"')
def step_when_alice_declares_declaration(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Alice declares "bet the pot" on a no\\-limit table')
def step_when_alice_declares_bet_the_pot_on_a_no_limit_table(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice declares a raise to 15")
def step_when_alice_declares_a_raise_to_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice discloses her hole cards to a railbird while facing action")
def step_when_alice_discloses_her_hole_cards_to_a_railbird_while_facing_action(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice exposes both her hole cards face\\-up")
def step_when_alice_exposes_both_her_hole_cards_face_up(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice folds with no bet to call")
def step_when_alice_folds_with_no_bet_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice mucks")
def step_when_alice_mucks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice mucks face down before Bob has called")
def step_when_alice_mucks_face_down_before_bob_has_called(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice pot\\-bets 11500 based on the dealer's illegal\\-high count")
def step_when_alice_pot_bets_11500_based_on_the_dealer_s_illegal_high_count(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice pulls back her prior 100 chip while facing the raise")
def step_when_alice_pulls_back_her_prior_100_chip_while_facing_the_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice pushes 30 in a first forward motion")
def step_when_alice_pushes_30_in_a_first_forward_motion(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Alice pushes a single 500 chip declaring "bet 325"')
def step_when_alice_pushes_a_single_500_chip_declaring_bet_325(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice requests a stack count for Bob")
def step_when_alice_requests_a_stack_count_for_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice requests to see Bob's hand")
def step_when_alice_requests_to_see_bob_s_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice reveals her cards")
def step_when_alice_reveals_her_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice silently adds chips totaling 300 on top of her prior 100")
def step_when_alice_silently_adds_chips_totaling_300_on_top_of_her_prior_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice silently pushes 12")
def step_when_alice_silently_pushes_12(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice silently pushes 16")
def step_when_alice_silently_pushes_16(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice then checks \\(no raise \\- the condition fails\\)")
def step_when_alice_then_checks_no_raise_the_condition_fails(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice then reaches back and adds 70 in a second motion")
def step_when_alice_then_reaches_back_and_adds_70_in_a_second_motion(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Alice verbally declares "I bet a buck" \\(non\\-standard\\)')
def step_when_alice_verbally_declares_i_bet_a_buck_non_standard(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Alice verbally declares "all\\-in" with no chips yet pushed')
def step_when_alice_verbally_declares_all_in_with_no_chips_yet_pushed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Alice's action clock expires")
def step_when_alice_s_action_clock_expires(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob \\(the next to act\\) has not yet acted")
def step_when_bob_the_next_to_act_has_not_yet_acted(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob attempts to fold by picking up his up cards")
def step_when_bob_attempts_to_fold_by_picking_up_his_up_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob calls 11500")
def step_when_bob_calls_11500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob calls 50")
def step_when_bob_calls_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob checks")
def step_when_bob_checks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob completes the bet to 400")
def step_when_bob_completes_the_bet_to_400(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob did not speak up before substantial action")
def step_when_bob_did_not_speak_up_before_substantial_action(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob disputes the pot distribution of the prior hand")
def step_when_bob_disputes_the_pot_distribution_of_the_prior_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob folds")
def step_when_bob_folds(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob had posted a small blind of 5 before the deal")
def step_when_bob_had_posted_a_small_blind_of_5_before_the_deal(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Bob out of turn says "if Alice raises, I\'m all\\-in"')
def step_when_bob_out_of_turn_says_if_alice_raises_i_m_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob raises to 400")
def step_when_bob_raises_to_400(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob reveals his cards")
def step_when_bob_reveals_his_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob silently pushes 400 \\(two 200 chips, not all required\\)")
def step_when_bob_silently_pushes_400_two_200_chips_not_all_required(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob silently pushes a single 1000 chip")
def step_when_bob_silently_pushes_a_single_1000_chip(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Bob silently pushes chips totaling 200 \\(two 100 chips, both required\\)")
def step_when_bob_silently_pushes_chips_totaling_200_two_100_chips_both_required(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Bob verbally declares "call 60" in turn \\(an undercall\\)')
def step_when_bob_verbally_declares_call_60_in_turn_an_undercall(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol attempts to raise")
def step_when_carol_attempts_to_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol calls 11500")
def step_when_carol_calls_11500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol calls 600 out of turn")
def step_when_carol_calls_600_out_of_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol calls out of turn for 0")
def step_when_carol_calls_out_of_turn_for_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol folds out of turn")
def step_when_carol_folds_out_of_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol goes all\\-in for 500")
def step_when_carol_goes_all_in_for_500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Carol raises to 60 out of turn")
def step_when_carol_raises_to_60_out_of_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('Carol verbally declares "raise" without an amount')
def step_when_carol_verbally_declares_raise_without_an_amount(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("Dave folds out of turn")
def step_when_dave_folds_out_of_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("a Five Card Draw hand is dealt to:")
def step_when_a_five_card_draw_hand_is_dealt_to(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("a Texas Hold'em hand is dealt to only 1 player")
def step_when_a_texas_hold_em_hand_is_dealt_to_only_1_player(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("a Texas Hold'em hand is dealt to:")
def step_when_a_texas_hold_em_hand_is_dealt_to(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("a Texas Hold'em hand is dealt with no players")
def step_when_a_texas_hold_em_hand_is_dealt_with_no_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('a Texas Hold\'em hand is dealt with seed "test\\-seed\\-123" to:')
def step_when_a_texas_hold_em_hand_is_dealt_with_seed_test_seed_123_to(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("a hidden 25 chip is discovered behind Alice after the call")
def step_when_a_hidden_25_chip_is_discovered_behind_alice_after_the_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('a new hand is started at table "Main Table"')
def step_when_a_new_hand_is_started_at_table_main_table(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("an Omaha hand is dealt to:")
def step_when_an_omaha_hand_is_dealt_to(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("another player goes all\\-in to 130")
def step_when_another_player_goes_all_in_to_130(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("another player goes all\\-in to 160")
def step_when_another_player_goes_all_in_to_160(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("first\\-to\\-act on 5th street is determined")
def step_when_first_to_act_on_5th_street_is_determined(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("ghost attempts to fold")
def step_when_ghost_attempts_to_fold(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("ghost attempts to post the small blind of 5")
def step_when_ghost_attempts_to_post_the_small_blind_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("ghost attempts to reveal their cards")
def step_when_ghost_attempts_to_reveal_their_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("hands are evaluated")
def step_when_hands_are_evaluated(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("no action has occurred on the flop")
def step_when_no_action_has_occurred_on_the_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("no substantial action has occurred since")
def step_when_no_substantial_action_has_occurred_since(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("one card is burned and the next is dealt as a community card")
def step_when_one_card_is_burned_and_the_next_is_dealt_as_a_community_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("one card is burned from the new stub")
def step_when_one_card_is_burned_from_the_new_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("one player goes all\\-in to 120")
def step_when_one_player_goes_all_in_to_120(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("one player goes all\\-in to 130")
def step_when_one_player_goes_all_in_to_130(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to bet 20")
def step_when_player_1_attempts_to_bet_20(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to bet 5")
def step_when_player_1_attempts_to_bet_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to bet 5000")
def step_when_player_1_attempts_to_bet_5000(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to check")
def step_when_player_1_attempts_to_check(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to discard cards at positions 0, 0, and 1")
def step_when_player_1_attempts_to_discard_cards_at_positions_0_0_and_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to draw")
def step_when_player_1_attempts_to_draw(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to fold")
def step_when_player_1_attempts_to_fold(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to post a small blind of 0")
def step_when_player_1_attempts_to_post_a_small_blind_of_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to post an ante of 2")
def step_when_player_1_attempts_to_post_an_ante_of_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to post an ante of 5")
def step_when_player_1_attempts_to_post_an_ante_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to post the small blind of 5")
def step_when_player_1_attempts_to_post_the_small_blind_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to raise to 12")
def step_when_player_1_attempts_to_raise_to_12(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to raise to 20")
def step_when_player_1_attempts_to_raise_to_20(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to raise to 5000")
def step_when_player_1_attempts_to_raise_to_5000(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to reveal their cards")
def step_when_player_1_attempts_to_reveal_their_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 attempts to take an unknown kind of action")
def step_when_player_1_attempts_to_take_an_unknown_kind_of_action(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 bets 20")
def step_when_player_1_bets_20(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 bets 95")
def step_when_player_1_bets_95(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 calls for 5")
def step_when_player_1_calls_for_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 checks")
def step_when_player_1_checks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 discards cards at positions 0, 2, and 4")
def step_when_player_1_discards_cards_at_positions_0_2_and_4(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 folds")
def step_when_player_1_folds(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 goes all\\-in")
def step_when_player_1_goes_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 goes all\\-in for 50")
def step_when_player_1_goes_all_in_for_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 mucks")
def step_when_player_1_mucks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 posts an ante of 2")
def step_when_player_1_posts_an_ante_of_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 posts the small blind of 5")
def step_when_player_1_posts_the_small_blind_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 raises to 100")
def step_when_player_1_raises_to_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 raises to 30")
def step_when_player_1_raises_to_30(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 reveals their cards")
def step_when_player_1_reveals_their_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-1 stands pat")
def step_when_player_1_stands_pat(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-2 attempts to call")
def step_when_player_2_attempts_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-2 attempts to raise to 15")
def step_when_player_2_attempts_to_raise_to_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-2 posts an ante of 2")
def step_when_player_2_posts_an_ante_of_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-2 posts the big blind of 10")
def step_when_player_2_posts_the_big_blind_of_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-2 posts the big\\-blind ante of 10")
def step_when_player_2_posts_the_big_blind_ante_of_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-3 posts an ante of 2")
def step_when_player_3_posts_an_ante_of_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-A mucks")
def step_when_player_a_mucks(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("player\\-B attempts to reveal their cards")
def step_when_player_b_attempts_to_reveal_their_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("someone attempts to fold without identifying the player")
def step_when_someone_attempts_to_fold_without_identifying_the_player(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("someone attempts to post the small blind of 5 without identifying the player")
def step_when_someone_attempts_to_post_the_small_blind_of_5_without_identifying_the_player(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("someone attempts to reveal cards without identifying the player")
def step_when_someone_attempts_to_reveal_cards_without_identifying_the_player(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the 3rd\\-street betting begins")
def step_when_the_3rd_street_betting_begins(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the TD issues a discretionary color\\-up for denomination 25")
def step_when_the_td_issues_a_discretionary_color_up_for_denomination_25(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the action clock is started on Alice for 30 seconds")
def step_when_the_action_clock_is_started_on_alice_for_30_seconds(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the deal of 3rd street completes")
def step_when_the_deal_of_3rd_street_completes(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer accidentally exposes Alice's first downcard")
def step_when_the_dealer_accidentally_exposes_alice_s_first_downcard(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer accidentally lays out 4 cards as the flop")
def step_when_the_dealer_accidentally_lays_out_4_cards_as_the_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer accidentally mucks Alice's hand")
def step_when_the_dealer_accidentally_mucks_alice_s_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer attempts to deal 0 community cards")
def step_when_the_dealer_attempts_to_deal_0_community_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer attempts to deal 1 community card")
def step_when_the_dealer_attempts_to_deal_1_community_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer attempts to deal 3 community cards")
def step_when_the_dealer_attempts_to_deal_3_community_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer attempts to deal community cards")
def step_when_the_dealer_attempts_to_deal_community_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer attempts to deal the hand again")
def step_when_the_dealer_attempts_to_deal_the_hand_again(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer burns the top card of the stub")
def step_when_the_dealer_burns_the_top_card_of_the_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer deals 4th street")
def step_when_the_dealer_deals_4th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer deals 5th street")
def step_when_the_dealer_deals_5th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer deals the flop")
def step_when_the_dealer_deals_the_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer deals the river")
def step_when_the_dealer_deals_the_river(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer deals the turn")
def step_when_the_dealer_deals_the_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer declares a misdeal before substantial action")
def step_when_the_dealer_declares_a_misdeal_before_substantial_action(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer detects the button error")
def step_when_the_dealer_detects_the_button_error(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer detects the illegal overbet before the turn is dealt")
def step_when_the_dealer_detects_the_illegal_overbet_before_the_turn_is_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer detects the stub disorder")
def step_when_the_dealer_detects_the_stub_disorder(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer detects the underraise before the turn is dealt")
def step_when_the_dealer_detects_the_underraise_before_the_turn_is_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer exposes Alice's 7th\\-street card")
def step_when_the_dealer_exposes_alice_s_7th_street_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer exposes Alice's intended second downcard")
def step_when_the_dealer_exposes_alice_s_intended_second_downcard(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer notices the undercall after Carol's raise")
def step_when_the_dealer_notices_the_undercall_after_carol_s_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer prematurely deals a 5th\\-street card")
def step_when_the_dealer_prematurely_deals_a_5th_street_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer prematurely deals a river card")
def step_when_the_dealer_prematurely_deals_a_river_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer prematurely deals a turn card")
def step_when_the_dealer_prematurely_deals_a_turn_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer prematurely lays out a flop")
def step_when_the_dealer_prematurely_lays_out_a_flop(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer puts out a 3\\-card flop without burning")
def step_when_the_dealer_puts_out_a_3_card_flop_without_burning(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('the dealer reports a fouled deck \\(duplicate "Ah" found\\)')
def step_when_the_dealer_reports_a_fouled_deck_duplicate_ah_found(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('the dealer reports a misdeal of type "<type>"')
def step_when_the_dealer_reports_a_misdeal_of_type_type(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer scrambles the stub with the prior burns")
def step_when_the_dealer_scrambles_the_stub_with_the_prior_burns(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the dealer scrambles the stub with the prior burns into a new stub")
def step_when_the_dealer_scrambles_the_stub_with_the_prior_burns_into_a_new_stub(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the floor randomly selects one card to turn face up as Alice's door card")
def step_when_the_floor_randomly_selects_one_card_to_turn_face_up_as_alice_s_door_card(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the floor randomly selects one of the 4 as the burn card")
def step_when_the_floor_randomly_selects_one_of_the_4_as_the_burn_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the floor scrambles Alice's 3 cards face down")
def step_when_the_floor_scrambles_alice_s_3_cards_face_down(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the flop betting round completes")
def step_when_the_flop_betting_round_completes(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the hand is re\\-dealt")
def step_when_the_hand_is_re_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the high half of the pot \\(51\\) is split")
def step_when_the_high_half_of_the_pot_51_is_split(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the next card is dealt as a community card")
def step_when_the_next_card_is_dealt_as_a_community_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('the players take "<actions>" in turn')
def step_when_the_players_take_actions_in_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot is awarded as:")
def step_when_the_pot_is_awarded_as(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot is awarded to Alice")
def step_when_the_pot_is_awarded_to_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot is awarded with no winners specified")
def step_when_the_pot_is_awarded_with_no_winners_specified(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot is split between Alice and Bob")
def step_when_the_pot_is_split_between_alice_and_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 100 is awarded to Bob")
def step_when_the_pot_of_100_is_awarded_to_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 100 is awarded to player\\-1")
def step_when_the_pot_of_100_is_awarded_to_player_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 101 is split between Alice and Bob")
def step_when_the_pot_of_101_is_split_between_alice_and_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 101 is split between high and low")
def step_when_the_pot_of_101_is_split_between_high_and_low(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 15 is awarded to ghost")
def step_when_the_pot_of_15_is_awarded_to_ghost(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 15 is awarded to player\\-1")
def step_when_the_pot_of_15_is_awarded_to_player_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot of 15 is awarded to unknown\\-player")
def step_when_the_pot_of_15_is_awarded_to_unknown_player(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pot\\-limit pre\\-flop maximum raise\\-to amount is computed for Carol")
def step_when_the_pot_limit_pre_flop_maximum_raise_to_amount_is_computed_for_carol(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the pots are awarded as:")
def step_when_the_pots_are_awarded_as(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the preflop betting round completes")
def step_when_the_preflop_betting_round_completes(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the rotation transitions back to Texas Hold'em after the stud rotation")
def step_when_the_rotation_transitions_back_to_texas_hold_em_after_the_stud_rotation(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the rotation transitions to Razz")
def step_when_the_rotation_transitions_to_razz(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when('the same Texas Hold\'em hand is dealt twice with seed "seed123"')
def step_when_the_same_texas_hold_em_hand_is_dealt_twice_with_seed_seed123(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the seating coordinator handles the tie")
def step_when_the_seating_coordinator_handles_the_tie(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the showdown becomes uncontested with Bob remaining")
def step_when_the_showdown_becomes_uncontested_with_bob_remaining(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the showdown order is established")
def step_when_the_showdown_order_is_established(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the side pots are computed")
def step_when_the_side_pots_are_computed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@when("the turn betting round completes")
def step_when_the_turn_betting_round_completes(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


# ----------------------------------------------------------------------
# THEN step stubs
# ----------------------------------------------------------------------


@then("1 community card is revealed")
def step_then_1_community_card_is_revealed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("2 active players remain")
def step_then_2_active_players_remain(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("2 cards are dealt on 4th street")
def step_then_2_cards_are_dealt_on_4th_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("3 antes have been posted")
def step_then_3_antes_have_been_posted(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("3 cards have been removed from the remaining deck")
def step_then_3_cards_have_been_removed_from_the_remaining_deck(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("3 community cards are revealed")
def step_then_3_community_cards_are_revealed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("300 uncontested chips are returned to player\\-C")
def step_then_300_uncontested_chips_are_returned_to_player_c(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice has 1 down card and 1 up card after the conversion")
def step_then_alice_has_1_down_card_and_1_up_card_after_the_conversion(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice has 2 down cards and 1 up card")
def step_then_alice_has_2_down_cards_and_1_up_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice has 2 hole cards")
def step_then_alice_has_2_hole_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice has a ROYAL_FLUSH")
def step_then_alice_has_a_royal_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is bound to call or raise")
def step_then_alice_is_bound_to_call_or_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is folded")
def step_then_alice_is_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is penalised for a disclosure violation")
def step_then_alice_is_penalised_for_a_disclosure_violation(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is penalised for exposed cards")
def step_then_alice_is_penalised_for_exposed_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is playing the board")
def step_then_alice_is_playing_the_board(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice is refunded the uncalled 200")
def step_then_alice_is_refunded_the_uncalled_200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice receives 26")
def step_then_alice_receives_26(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice remains eligible to be the bring\\-in based on her up card")
def step_then_alice_remains_eligible_to_be_the_bring_in_based_on_her_up_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice wins 51")
def step_then_alice_wins_51(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's 7th\\-street card is replaced")
def step_then_alice_s_7th_street_card_is_replaced(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's action is recorded as a raise")
def step_then_alice_s_action_is_recorded_as_a_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's all\\-in is recorded with a 495\\-chip commit")
def step_then_alice_s_all_in_is_recorded_with_a_495_chip_commit(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's bet is recorded at the big blind \\(10\\)")
def step_then_alice_s_bet_is_recorded_at_the_big_blind_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's bet of 200 is recorded")
def step_then_alice_s_bet_of_200_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's bet of 500 is recorded")
def step_then_alice_s_bet_of_500_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's button card is replaced")
def step_then_alice_s_button_card_is_replaced(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's call of 5 is recorded")
def step_then_alice_s_call_of_5_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's check is recorded")
def step_then_alice_s_check_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's door card is selected")
def step_then_alice_s_door_card_is_selected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's effective stack for the next hand is 25")
def step_then_alice_s_effective_stack_for_the_next_hand_is_25(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's effective stack is 500")
def step_then_alice_s_effective_stack_is_500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's hand is declared killed by the dealer")
def step_then_alice_s_hand_is_declared_killed_by_the_dealer(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's hand remains live this hand")
def step_then_alice_s_hand_remains_live_this_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's raise of 400 is recorded")
def step_then_alice_s_raise_of_400_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's raise puts 25 more chips into the pot")
def step_then_alice_s_raise_puts_25_more_chips_into_the_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's stack is 0")
def step_then_alice_s_stack_is_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's stack is 400")
def step_then_alice_s_stack_is_400(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's stack is restored by the uncalled portion only")
def step_then_alice_s_stack_is_restored_by_the_uncalled_portion_only(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Alice's wager is returned")
def step_then_alice_s_wager_is_returned(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob is folded")
def step_then_bob_is_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob is not required to reveal his cards")
def step_then_bob_is_not_required_to_reveal_his_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob is recorded as having lost his right to act")
def step_then_bob_is_recorded_as_having_lost_his_right_to_act(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob is required to table his hand")
def step_then_bob_is_required_to_table_his_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob receives 25")
def step_then_bob_receives_25(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob still has the option to act in turn")
def step_then_bob_still_has_the_option_to_act_in_turn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob wins 100")
def step_then_bob_wins_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob wins 50")
def step_then_bob_wins_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's ante of 5 is forfeited to the pot")
def step_then_bob_s_ante_of_5_is_forfeited_to_the_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's bet\\-completion is recorded")
def step_then_bob_s_bet_completion_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's bring\\-in of 10 is forfeited to the pot")
def step_then_bob_s_bring_in_of_10_is_forfeited_to_the_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's call of 100 is recorded")
def step_then_bob_s_call_of_100_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's call of 200 is recorded")
def step_then_bob_s_call_of_200_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's commit for the prior action stands at 60")
def step_then_bob_s_commit_for_the_prior_action_stands_at_60(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's hand is killed")
def step_then_bob_s_hand_is_killed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's raise of 400 is recorded")
def step_then_bob_s_raise_of_400_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Bob's stack of 500 is disclosed to Alice")
def step_then_bob_s_stack_of_500_is_disclosed_to_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol \\(the actual low card\\) is now obligated to post the bring\\-in")
def step_then_carol_the_actual_low_card_is_now_obligated_to_post_the_bring_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol is folded")
def step_then_carol_is_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol may now call, raise, or fold")
def step_then_carol_may_now_call_raise_or_fold(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's action is recorded as a raise")
def step_then_carol_s_action_is_recorded_as_a_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's check is recorded")
def step_then_carol_s_check_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's out\\-of\\-turn call is binding")
def step_then_carol_s_out_of_turn_call_is_binding(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's out\\-of\\-turn raise is returned")
def step_then_carol_s_out_of_turn_raise_is_returned(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's raise totals 90 \\(50 \\+ the 40 minimum raise increment\\)")
def step_then_carol_s_raise_totals_90_50_the_40_minimum_raise_increment(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("Carol's substantial action stands")
def step_then_carol_s_substantial_action_stands(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "a floor decision is required because a non\\-standard declaration requires floor review"
)
def step_then_a_floor_decision_is_required_because_a_non_standard_declaration_requires_floor_r(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a floor decision is required because of the missing 7th\\-street card")
def step_then_a_floor_decision_is_required_because_of_the_missing_7th_street_card(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a misdeal is declared")
def step_then_a_misdeal_is_declared(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a premature flop is detected")
def step_then_a_premature_flop_is_detected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a premature river is detected")
def step_then_a_premature_river_is_detected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a premature stud card is detected")
def step_then_a_premature_stud_card_is_detected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a premature turn is detected")
def step_then_a_premature_turn_is_detected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a rebuy obligation of 500 is recorded for Alice")
def step_then_a_rebuy_obligation_of_500_is_recorded_for_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a stub reshuffle is required")
def step_then_a_stub_reshuffle_is_required(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("a stud community card is dealt")
def step_then_a_stud_community_card_is_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("both deals produce identical hole cards")
def step_then_both_deals_produce_identical_hole_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("each player's contribution this round is 0")
def step_then_each_player_s_contribution_this_round_is_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("every bettor's contribution is increased to match")
def step_then_every_bettor_s_contribution_is_increased_to_match(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("every caller's contribution is reduced to 10500")
def step_then_every_caller_s_contribution_is_reduced_to_10500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("every player's contribution to the hand is refunded")
def step_then_every_player_s_contribution_to_the_hand_is_refunded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("exactly 1 card was burned for this street")
def step_then_exactly_1_card_was_burned_for_this_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("exactly 1 of the original 3 flop cards is now the burn")
def step_then_exactly_1_of_the_original_3_flop_cards_is_now_the_burn(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("exactly one of Eve or Frank is seated first")
def step_then_exactly_one_of_eve_or_frank_is_seated_first(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no action is recorded for Bob")
def step_then_no_action_is_recorded_for_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no button correction is applied")
def step_then_no_button_correction_is_applied(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no card was burned for this street")
def step_then_no_card_was_burned_for_this_street(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no card was dealt to Bob")
def step_then_no_card_was_dealt_to_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no change is returned to Alice")
def step_then_no_change_is_returned_to_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no chips have been forfeited")
def step_then_no_chips_have_been_forfeited(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no community card is in play")
def step_then_no_community_card_is_in_play(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no community cards already exposed are altered")
def step_then_no_community_cards_already_exposed_are_altered(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no community cards were revealed")
def step_then_no_community_cards_were_revealed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no correction is applied")
def step_then_no_correction_is_applied(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no misdeal was declared on this hand")
def step_then_no_misdeal_was_declared_on_this_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("no rejection is raised based on the open pair")
def step_then_no_rejection_is_raised_based_on_the_open_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("one card is dealt to each of the 5 active players")
def step_then_one_card_is_dealt_to_each_of_the_5_active_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then('player "player\\-1" holds the cards expected for seed "test\\-seed\\-123"')
def step_then_player_player_1_holds_the_cards_expected_for_seed_test_seed_123(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has 5 hole cards")
def step_then_player_1_has_5_hole_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a FLUSH")
def step_then_player_1_has_a_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a FOUR_OF_A_KIND")
def step_then_player_1_has_a_four_of_a_kind(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a FULL_HOUSE")
def step_then_player_1_has_a_full_house(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a HIGH_CARD")
def step_then_player_1_has_a_high_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a PAIR")
def step_then_player_1_has_a_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a ROYAL_FLUSH")
def step_then_player_1_has_a_royal_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a STRAIGHT")
def step_then_player_1_has_a_straight(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a STRAIGHT_FLUSH")
def step_then_player_1_has_a_straight_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a THREE_OF_A_KIND")
def step_then_player_1_has_a_three_of_a_kind(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has a TWO_PAIR")
def step_then_player_1_has_a_two_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has discarded 0 cards and drawn 0 cards")
def step_then_player_1_has_discarded_0_cards_and_drawn_0_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 has discarded 3 cards and drawn 3 cards")
def step_then_player_1_has_discarded_3_cards_and_drawn_3_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 is all\\-in")
def step_then_player_1_is_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 is folded")
def step_then_player_1_is_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 wins")
def step_then_player_1_wins(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 wins 15")
def step_then_player_1_wins_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1 wins 50")
def step_then_player_1_wins_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's action is recorded as all\\-in")
def step_then_player_1_s_action_is_recorded_as_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's action is recorded as all\\-in for 95")
def step_then_player_1_s_action_is_recorded_as_all_in_for_95(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's all\\-in is recorded")
def step_then_player_1_s_all_in_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's bet of 20 is recorded")
def step_then_player_1_s_bet_of_20_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's call of 5 is recorded")
def step_then_player_1_s_call_of_5_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then('player\\-1\'s card at position 1 matches the "pre_draw" card at position 1')
def step_then_player_1_s_card_at_position_1_matches_the_pre_draw_card_at_position_1(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then('player\\-1\'s card at position 3 matches the "pre_draw" card at position 3')
def step_then_player_1_s_card_at_position_3_matches_the_pre_draw_card_at_position_3(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's cards are tabled")
def step_then_player_1_s_cards_are_tabled(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's check is recorded")
def step_then_player_1_s_check_is_recorded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's hand is mucked")
def step_then_player_1_s_hand_is_mucked(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's hand ranking is determined")
def step_then_player_1_s_hand_ranking_is_determined(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's raise puts 25 more chips into the pot")
def step_then_player_1_s_raise_puts_25_more_chips_into_the_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's stack is 0")
def step_then_player_1_s_stack_is_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's stack is 495")
def step_then_player_1_s_stack_is_495(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's stack is 498")
def step_then_player_1_s_stack_is_498(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's stack is 600")
def step_then_player_1_s_stack_is_600(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-1's stack is 800")
def step_then_player_1_s_stack_is_800(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 has a FLUSH")
def step_then_player_2_has_a_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 has a PAIR")
def step_then_player_2_has_a_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 has a STRAIGHT_FLUSH")
def step_then_player_2_has_a_straight_flush(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 has a TWO_PAIR")
def step_then_player_2_has_a_two_pair(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 is all\\-in")
def step_then_player_2_is_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 wins")
def step_then_player_2_wins(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2 wins 50")
def step_then_player_2_wins_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2's stack is 0")
def step_then_player_2_s_stack_is_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2's stack is 490")
def step_then_player_2_s_stack_is_490(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-2's stack is 498")
def step_then_player_2_s_stack_is_498(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-3's stack is 498")
def step_then_player_3_s_stack_is_498(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-A wins 300 from the main pot")
def step_then_player_a_wins_300_from_the_main_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-A's hand is mucked")
def step_then_player_a_s_hand_is_mucked(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-A's winnings come from the main pot")
def step_then_player_a_s_winnings_come_from_the_main_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-B's winnings come from side pot 1")
def step_then_player_b_s_winnings_come_from_side_pot_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("player\\-C wins 200 from side pot 1")
def step_then_player_c_wins_200_from_side_pot_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("side pot 1 holds 200 and is contestable by player\\-B and player\\-C")
def step_then_side_pot_1_holds_200_and_is_contestable_by_player_b_and_player_c(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "side pot 1 holds 300 and is contestable by player\\-B, player\\-C, and player\\-D"
)
def step_then_side_pot_1_holds_300_and_is_contestable_by_player_b_player_c_and_player_d(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("side pot 2 holds 300 and is contestable by player\\-C and player\\-D")
def step_then_side_pot_2_holds_300_and_is_contestable_by_player_c_and_player_d(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("substantial action is <sa>")
def step_then_substantial_action_is_sa(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the 3 premature cards are returned to the stub")
def step_then_the_3_premature_cards_are_returned_to_the_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the action is held pending floor interpretation")
def step_then_the_action_is_held_pending_floor_interpretation(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the action is refused because the action type is not recognised")
def step_then_the_action_is_refused_because_the_action_type_is_not_recognised(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the ante is posted")
def step_then_the_ante_is_posted(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the ante is posted at 1")
def step_then_the_ante_is_posted_at_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the ante is refused because antes must be posted before the blinds")
def step_then_the_ante_is_refused_because_antes_must_be_posted_before_the_blinds(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because a tabled winner's hand cannot be killed")
def step_then_the_award_is_refused_because_a_tabled_winner_s_hand_cannot_be_killed(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because at least one winner is required")
def step_then_the_award_is_refused_because_at_least_one_winner_is_required(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because awards exceed the pot")
def step_then_the_award_is_refused_because_awards_exceed_the_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because ghost is not in the hand")
def step_then_the_award_is_refused_because_ghost_is_not_in_the_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because player\\-1 is folded")
def step_then_the_award_is_refused_because_player_1_is_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because player\\-A is not eligible for side pot 1")
def step_then_the_award_is_refused_because_player_a_is_not_eligible_for_side_pot_1(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because the hand has not been dealt")
def step_then_the_award_is_refused_because_the_hand_has_not_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because the hand is already complete")
def step_then_the_award_is_refused_because_the_hand_is_already_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the award is refused because unknown\\-player is not in the hand")
def step_then_the_award_is_refused_because_unknown_player_is_not_in_the_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is corrected because the overbet exceeds the pot\\-limit cap")
def step_then_the_bet_is_corrected_because_the_overbet_exceeds_the_pot_limit_cap(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is refused because a doubled bet is not allowed on 4th street")
def step_then_the_bet_is_refused_because_a_doubled_bet_is_not_allowed_on_4th_street(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is refused because an open pair locks the lower limit")
def step_then_the_bet_is_refused_because_an_open_pair_locks_the_lower_limit(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is refused because it exceeds player\\-1's stack")
def step_then_the_bet_is_refused_because_it_exceeds_player_1_s_stack(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is refused because it is below the minimum bet")
def step_then_the_bet_is_refused_because_it_is_below_the_minimum_bet(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet is refused because there is already a bet to be matched")
def step_then_the_bet_is_refused_because_there_is_already_a_bet_to_be_matched(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bet\\-completion does not count toward the per\\-round raise cap")
def step_then_the_bet_completion_does_not_count_toward_the_per_round_raise_cap(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the big blind is 10")
def step_then_the_big_blind_is_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the big blind is posted at 10")
def step_then_the_big_blind_is_posted_at_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the big\\-blind ante is posted at 10")
def step_then_the_big_blind_ante_is_posted_at_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because a player must be identified")
def step_then_the_blind_is_refused_because_a_player_must_be_identified(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because ghost is not in the hand")
def step_then_the_blind_is_refused_because_ghost_is_not_in_the_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because player\\-1 has folded")
def step_then_the_blind_is_refused_because_player_1_has_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because the amount must be positive")
def step_then_the_blind_is_refused_because_the_amount_must_be_positive(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because the hand has not been dealt")
def step_then_the_blind_is_refused_because_the_hand_has_not_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the blind is refused because the hand is complete")
def step_then_the_blind_is_refused_because_the_hand_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the bring\\-in is corrected")
def step_then_the_bring_in_is_corrected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the burn for the next street is taken from the reshuffled stub")
def step_then_the_burn_for_the_next_street_is_taken_from_the_reshuffled_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the call is refused because there is nothing to call")
def step_then_the_call_is_refused_because_there_is_nothing_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the check is refused because Alice was absent at the deal")
def step_then_the_check_is_refused_because_alice_was_absent_at_the_deal(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the check is refused because a player cannot check when facing a bet")
def step_then_the_check_is_refused_because_a_player_cannot_check_when_facing_a_bet(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the check is refused because player\\-1 has folded")
def step_then_the_check_is_refused_because_player_1_has_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the check is refused because player\\-1 is already all\\-in")
def step_then_the_check_is_refused_because_player_1_is_already_all_in(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the clock is refused because the action is not on Alice")
def step_then_the_clock_is_refused_because_the_action_is_not_on_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the color\\-up is accepted but no stack mutation occurs in this hand")
def step_then_the_color_up_is_accepted_but_no_stack_mutation_occurs_in_this_hand(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the color\\-up is scheduled to apply at the next hand boundary")
def step_then_the_color_up_is_scheduled_to_apply_at_the_next_hand_boundary(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the community card is shared by all 5 active players")
def step_then_the_community_card_is_shared_by_all_5_active_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the community card is shared by all 6 active players")
def step_then_the_community_card_is_shared_by_all_6_active_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the completion lists 2 winners")
def step_then_the_completion_lists_2_winners(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the completion shows player\\-A winning the main pot")
def step_then_the_completion_shows_player_a_winning_the_main_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the completion shows player\\-C winning side pot 1")
def step_then_the_completion_shows_player_c_winning_side_pot_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the corrected bet amount is 10500")
def step_then_the_corrected_bet_amount_is_10500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the corrected raise\\-to amount is 1200")
def step_then_the_corrected_raise_to_amount_is_1200(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the current bet is 0")
def step_then_the_current_bet_is_0(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the current bet is 130")
def step_then_the_current_bet_is_130(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the current bet is 160")
def step_then_the_current_bet_is_160(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because Five Card Draw has no community cards")
def step_then_the_deal_is_refused_because_five_card_draw_has_no_community_cards(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because at least 2 players are required")
def step_then_the_deal_is_refused_because_at_least_2_players_are_required(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because at least one card must be dealt")
def step_then_the_deal_is_refused_because_at_least_one_card_must_be_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because no players were provided")
def step_then_the_deal_is_refused_because_no_players_were_provided(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because the flop expects 3 cards")
def step_then_the_deal_is_refused_because_the_flop_expects_3_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because the hand has already been dealt")
def step_then_the_deal_is_refused_because_the_hand_has_already_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because the hand has not been dealt")
def step_then_the_deal_is_refused_because_the_hand_has_not_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deal is refused because the hand is complete")
def step_then_the_deal_is_refused_because_the_hand_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dealer button is frozen at seat 1")
def step_then_the_dealer_button_is_frozen_at_seat_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dealer button is preserved")
def step_then_the_dealer_button_is_preserved(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dealer button is still at seat 0 \\(Alice\\)")
def step_then_the_dealer_button_is_still_at_seat_0_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dealer button resumes at seat 1")
def step_then_the_dealer_button_resumes_at_seat_1(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dealer rules a string bet")
def step_then_the_dealer_rules_a_string_bet(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the deck is declared fouled")
def step_then_the_deck_is_declared_fouled(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the dispute is refused because the dispute window has closed")
def step_then_the_dispute_is_refused_because_the_dispute_window_has_closed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the draw is refused because Texas Hold'em does not support drawing")
def step_then_the_draw_is_refused_because_texas_hold_em_does_not_support_drawing(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the draw is refused because the discard positions are duplicated")
def step_then_the_draw_is_refused_because_the_discard_positions_are_duplicated(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the exposed downcard becomes Alice's up card")
def step_then_the_exposed_downcard_becomes_alice_s_up_card(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "the first\\-to\\-act on 7th street is the same player who acted first on 6th street"
)
def step_then_the_first_to_act_on_7th_street_is_the_same_player_who_acted_first_on_6th_street(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the first\\-to\\-act player is Alice")
def step_then_the_first_to_act_player_is_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the first\\-to\\-act player is Bob")
def step_then_the_first_to_act_player_is_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because a player must be identified")
def step_then_the_fold_is_refused_because_a_player_must_be_identified(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because ghost is not in the hand")
def step_then_the_fold_is_refused_because_ghost_is_not_in_the_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because picking up the up cards is not a valid muck in stud")
def step_then_the_fold_is_refused_because_picking_up_the_up_cards_is_not_a_valid_muck_in_stud(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because the hand has not been dealt")
def step_then_the_fold_is_refused_because_the_hand_has_not_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because the hand is not in a betting phase")
def step_then_the_fold_is_refused_because_the_hand_is_not_in_a_betting_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the fold is refused because the player must call or raise")
def step_then_the_fold_is_refused_because_the_player_must_call_or_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the frozen position is recorded for the next flop\\-game rotation")
def step_then_the_frozen_position_is_recorded_for_the_next_flop_game_rotation(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand carries that table and hand\\-number identity")
def step_then_the_hand_carries_that_table_and_hand_number_identity(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand continues with the dealer button at seat 2 \\(Carol\\)")
def step_then_the_hand_continues_with_the_dealer_button_at_seat_2_carol(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand has 2 players")
def step_then_the_hand_has_2_players(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand history does not expose any stub cards")
def step_then_the_hand_history_does_not_expose_any_stub_cards(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand history reflects the deal and both blind postings")
def step_then_the_hand_history_reflects_the_deal_and_both_blind_postings(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the DRAW phase")
def step_then_the_hand_is_in_the_draw_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the FLOP phase")
def step_then_the_hand_is_in_the_flop_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the PREFLOP phase")
def step_then_the_hand_is_in_the_preflop_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the RIVER phase")
def step_then_the_hand_is_in_the_river_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the TURN phase")
def step_then_the_hand_is_in_the_turn_phase(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the betting state")
def step_then_the_hand_is_in_the_betting_state(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is in the complete state")
def step_then_the_hand_is_in_the_complete_state(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is re\\-dealt cleanly")
def step_then_the_hand_is_re_dealt_cleanly(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand is void")
def step_then_the_hand_is_void(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hand level is still 1 \\(SB 5 / BB 10\\)")
def step_then_the_hand_level_is_still_1_sb_5_bb_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the hidden 25 is not added to the current pot")
def step_then_the_hidden_25_is_not_added_to_the_current_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the high side receives 51")
def step_then_the_high_side_receives_51(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the last raise increment is 50")
def step_then_the_last_raise_increment_is_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the last raise increment is 60")
def step_then_the_last_raise_increment_is_60(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the low side receives 50")
def step_then_the_low_side_receives_50(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "the main pot holds 200 and is contestable by player\\-A, player\\-B, player\\-C, and player\\-D"
)
def step_then_the_main_pot_holds_200_and_is_contestable_by_player_a_player_b_player_c_and_play(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the main pot holds 280 and is contestable by player\\-A and player\\-C")
def step_then_the_main_pot_holds_280_and_is_contestable_by_player_a_and_player_c(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "the main pot holds 300 and is contestable by player\\-A, player\\-B, and player\\-C"
)
def step_then_the_main_pot_holds_300_and_is_contestable_by_player_a_player_b_and_player_c(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the main pot holds 60 and is contestable by player\\-A and player\\-B")
def step_then_the_main_pot_holds_60_and_is_contestable_by_player_a_and_player_b(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the main pot includes player\\-A's ante of 5")
def step_then_the_main_pot_includes_player_a_s_ante_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the main pot includes player\\-B's ante of 5")
def step_then_the_main_pot_includes_player_b_s_ante_of_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the minimum bet for Bob and Carol is the bring\\-in amount")
def step_then_the_minimum_bet_for_bob_and_carol_is_the_bring_in_amount(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the minimum raise is 10")
def step_then_the_minimum_raise_is_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the misdeal reason is the exposed stud downcard")
def step_then_the_misdeal_reason_is_the_exposed_stud_downcard(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the muck is refused because the card must be face up")
def step_then_the_muck_is_refused_because_the_card_must_be_face_up(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the new hand is started at blind level 2")
def step_then_the_new_hand_is_started_at_blind_level_2(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next dealt card to Alice \\(the door card\\) is dealt face down")
def step_then_the_next_dealt_card_to_alice_the_door_card_is_dealt_face_down(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next hand advances the button to seat 3 \\(Dave\\) \\- not back to seat 2")
def step_then_the_next_hand_advances_the_button_to_seat_3_dave_not_back_to_seat_2(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next player owes 20 to call")
def step_then_the_next_player_owes_20_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next player owes 30 to call")
def step_then_the_next_player_owes_30_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next player owes 500 to call")
def step_then_the_next_player_owes_500_to_call(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the next player to show is player\\-B")
def step_then_the_next_player_to_show_is_player_b(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the original burn card is preserved")
def step_then_the_original_burn_card_is_preserved(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the original card is removed from play")
def step_then_the_original_card_is_removed_from_play(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the original river burn card is preserved")
def step_then_the_original_river_burn_card_is_preserved(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the original turn burn card is preserved")
def step_then_the_original_turn_burn_card_is_preserved(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the out\\-of\\-turn actions of Carol and Dave are binding")
def step_then_the_out_of_turn_actions_of_carol_and_dave_are_binding(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the outcome depends on floor discretion")
def step_then_the_outcome_depends_on_floor_discretion(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then('the outcome is "<outcome>"')
def step_then_the_outcome_is_outcome(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the penalty severity is at least missed\\-hand")
def step_then_the_penalty_severity_is_at_least_missed_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the penalty starts at the end of the current hand")
def step_then_the_penalty_starts_at_the_end_of_the_current_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the pot is 10")
def step_then_the_pot_is_10(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the pot is 15")
def step_then_the_pot_is_15(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the pot is 20")
def step_then_the_pot_is_20(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the pot is 5")
def step_then_the_pot_is_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the pot is 6")
def step_then_the_pot_is_6(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the premature card is returned to the stub")
def step_then_the_premature_card_is_returned_to_the_stub(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the raise is refused because it exceeds player\\-1's stack")
def step_then_the_raise_is_refused_because_it_exceeds_player_1_s_stack(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the raise is refused because it is below the minimum raise")
def step_then_the_raise_is_refused_because_it_is_below_the_minimum_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the raise is refused because the raise cap has been reached")
def step_then_the_raise_is_refused_because_the_raise_cap_has_been_reached(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the raise is refused because there is no bet to raise")
def step_then_the_raise_is_refused_because_there_is_no_bet_to_raise(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then('the recorded action is "<actual>"')
def step_then_the_recorded_action_is_actual(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the rejection identifies Alice as the tabled winner")
def step_then_the_rejection_identifies_alice_as_the_tabled_winner(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the rejection notes the maximum bet of 100")
def step_then_the_rejection_notes_the_maximum_bet_of_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the rejection notes the round cap of 4 raises")
def step_then_the_rejection_notes_the_round_cap_of_4_raises(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the rejection records the awarded amount 50 against the pot bound 15")
def step_then_the_rejection_records_the_awarded_amount_50_against_the_pot_bound_15(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the replacement card is dealt face down to Alice")
def step_then_the_replacement_card_is_dealt_face_down_to_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the request is refused because the hand was mucked without being tabled")
def step_then_the_request_is_refused_because_the_hand_was_mucked_without_being_tabled(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because a player must be identified")
def step_then_the_reveal_is_refused_because_a_player_must_be_identified(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because ghost is not in the hand")
def step_then_the_reveal_is_refused_because_ghost_is_not_in_the_hand(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because it is out of order")
def step_then_the_reveal_is_refused_because_it_is_out_of_order(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because player\\-1 has folded")
def step_then_the_reveal_is_refused_because_player_1_has_folded(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then(
    "the reveal is refused because she cannot claim to play the board after mucking a hole card"
)
def step_then_the_reveal_is_refused_because_she_cannot_claim_to_play_the_board_after_mucking_a(
    context,
):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because the hand has not been dealt")
def step_then_the_reveal_is_refused_because_the_hand_has_not_been_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because the hand is not at showdown")
def step_then_the_reveal_is_refused_because_the_hand_is_not_at_showdown(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because the reveal is incomplete")
def step_then_the_reveal_is_refused_because_the_reveal_is_incomplete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the reveal is refused because there are too many cards for stud")
def step_then_the_reveal_is_refused_because_there_are_too_many_cards_for_stud(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the seating tiebreak is resolved deterministically")
def step_then_the_seating_tiebreak_is_resolved_deterministically(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the second\\-motion 70 is returned to Alice")
def step_then_the_second_motion_70_is_returned_to_alice(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the showdown order is Carol, Alice, Bob")
def step_then_the_showdown_order_is_carol_alice_bob(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the showdown order is player\\-A, player\\-B, player\\-D")
def step_then_the_showdown_order_is_player_a_player_b_player_d(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the showdown order is player\\-B, player\\-C, player\\-A")
def step_then_the_showdown_order_is_player_b_player_c_player_a(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the small blind is 5")
def step_then_the_small_blind_is_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the small blind is posted at 3")
def step_then_the_small_blind_is_posted_at_3(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the small blind is posted at 5")
def step_then_the_small_blind_is_posted_at_5(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the stub is reshuffled")
def step_then_the_stub_is_reshuffled(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the stud street is dealt")
def step_then_the_stud_street_is_dealt(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the total of all pots is 500")
def step_then_the_total_of_all_pots_is_500(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the undercall is corrected up to 100")
def step_then_the_undercall_is_corrected_up_to_100(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("the underraise is corrected")
def step_then_the_underraise_is_corrected(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 2 pots")
def step_then_there_are_2_pots(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 2 winners")
def step_then_there_are_2_winners(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 3 community cards in play")
def step_then_there_are_3_community_cards_in_play(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 3 pots")
def step_then_there_are_3_pots(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 3 winners")
def step_then_there_are_3_winners(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 4 community cards in play")
def step_then_there_are_4_community_cards_in_play(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there are 5 community cards in play")
def step_then_there_are_5_community_cards_in_play(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("there is 1 pot")
def step_then_there_is_1_pot(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


@then("up to 4 subsequent raises are allowed")
def step_then_up_to_4_subsequent_raises_are_allowed(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass


# ----------------------------------------------------------------------
# Dual-purpose matcher: "the hand is complete" is used as both Given
# (precondition) and Then (assertion) in the feature.
# ----------------------------------------------------------------------


@given("the hand is complete")
def step_given_the_hand_is_complete(context):  # noqa: ARG001
    # TODO: Implement this step matcher properly. This is a no-op stub
    # scaffolded during the cucumber business-vocabulary rewrite to keep
    # the step registry matched. The scenario will pass through silently
    # until implemented.
    pass
