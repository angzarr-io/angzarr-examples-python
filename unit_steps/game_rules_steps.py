"""Step definitions for game_rules pure-function tests.

These tests exercise TexasHoldemRules, OmahaRules, FiveCardDrawRules and
the get_game_rules() factory. There is no command/state/event pattern
here — the step defs store the rule instance, hole/community cards, and
evaluator outputs directly on the behave context.

Card-string format:
  Each card is ``<rank><suit>`` where
    rank in {2-9, T, J, Q, K, A}
    suit in {c, d, h, s}
  A card-list is a single string with cards separated by whitespace,
  e.g. ``"As Ah Ks Kh"``.
"""

from behave import given, then, use_step_matcher, when
from hand.agg.handlers.game_rules import (
    FiveCardDrawRules,
    OmahaRules,
    RazzRules,
    SevenCardStudRules,
    StudHiLoRules,
    TexasHoldemRules,
    get_game_rules,
)

from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types

use_step_matcher("re")


# --- Card parsing helpers ---

_SUIT_MAP = {
    "c": poker_types.CLUBS,
    "d": poker_types.DIAMONDS,
    "h": poker_types.HEARTS,
    "s": poker_types.SPADES,
}

_RANK_MAP = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}


def _parse_card(token: str) -> tuple:
    """Parse a single card string like 'As' (Ace-spades) -> (SPADES, 14)."""
    token = token.strip()
    assert len(token) == 2, f"Bad card token: {token!r}"
    rank_char, suit_char = token[0].upper(), token[1].lower()
    return (_SUIT_MAP[suit_char], _RANK_MAP[rank_char])


def _parse_cards(text: str) -> list:
    """Parse a whitespace-separated card list into [(suit, rank), ...]."""
    if not text.strip():
        return []
    return [_parse_card(tok) for tok in text.split()]


def _rules_from_label(label: str):
    """Map the human label in a Given step to a rule instance."""
    key = label.strip().lower().replace("'", "").replace("-", " ").replace("/", " ")
    # Collapse runs of whitespace.
    key = " ".join(key.split())
    if key in ("texas holdem", "texas hold em", "holdem", "hold em"):
        return TexasHoldemRules()
    if key == "omaha":
        return OmahaRules()
    if key in ("five card draw", "5 card draw", "draw"):
        return FiveCardDrawRules()
    if key in ("seven card stud", "7 card stud", "stud"):
        return SevenCardStudRules()
    if key in ("razz",):
        return RazzRules()
    if key in (
        "seven card stud hi lo",
        "seven card stud hi lo 8b",
        "seven card stud hilo",
        "seven card stud hilo 8b",
        "stud hi lo",
        "stud hilo",
        "stud hi lo 8b",
        "stud hilo 8b",
    ):
        return StudHiLoRules()
    raise ValueError(f"Unknown variant label: {label!r}")


def _phase_from_name(name: str) -> int:
    """Resolve a BettingPhase enum from its name (e.g. 'FLOP')."""
    return getattr(poker_types, name.strip().upper())


def _rank_type_from_name(name: str) -> int:
    """Resolve a HandRankType enum from its name (e.g. 'FULL_HOUSE')."""
    return getattr(poker_types, name.strip().upper())


def _rank_name(value: int) -> str:
    """Reverse lookup: HandRankType enum value -> name string."""
    for name in (
        "HIGH_CARD",
        "PAIR",
        "TWO_PAIR",
        "THREE_OF_A_KIND",
        "STRAIGHT",
        "FLUSH",
        "FULL_HOUSE",
        "FOUR_OF_A_KIND",
        "STRAIGHT_FLUSH",
        "ROYAL_FLUSH",
    ):
        if getattr(poker_types, name) == value:
            return name
    return f"<unknown {value}>"


# --- Given: rule selection ---


@given(
    r"(?P<variant>Texas Hold'em|Omaha|Five Card Draw|Seven Card Stud Hi/Lo 8b|"
    r"Seven Card Stud Hi/Lo|Seven Card Stud|Razz) rules"
)
def step_given_rules(context, variant):
    context.rules = _rules_from_label(variant)
    # Reset per-scenario evaluator inputs.
    context.hole_cards = []
    context.community_cards = []
    context.player_cards = []
    context.up_cards_by_player = {}
    context.door_cards = []
    context.hand_results = {}


# --- Given: hole / community cards ---


@given(r'hole cards "(?P<cards>[^"]*)"')
def step_given_hole_cards(context, cards):
    context.hole_cards = _parse_cards(cards)


@given(r'community cards "(?P<cards>[^"]*)"')
def step_given_community_cards(context, cards):
    context.community_cards = _parse_cards(cards)


# --- Given: deck / draw setup ---


@given(r'a deck of "(?P<cards>[^"]*)"')
def step_given_deck(context, cards):
    context.deck = _parse_cards(cards)


@given(r'an existing deck of "(?P<cards>[^"]*)"')
def step_given_existing_deck(context, cards):
    context.existing_deck = _parse_cards(cards)


@given(r'current hole cards "(?P<cards>[^"]*)"')
def step_given_current_hole_cards(context, cards):
    context.hole_cards = _parse_cards(cards)


# --- When: evaluate hand ---


@when(r"the best hand is evaluated")
def step_when_evaluate_hand(context):
    rank, score, kickers = context.rules.evaluate_hand(
        context.hole_cards, context.community_cards
    )
    context.rank = rank
    context.score = score
    context.kickers = kickers


@when(r'the best hand is evaluated from only "(?P<cards>[^"]*)"')
def step_when_evaluate_best_from_few(context, cards):
    # Exercises _find_best_hand directly with <5 cards.
    parsed = _parse_cards(cards)
    rank, score, kickers = context.rules._find_best_hand(parsed)
    context.rank = rank
    context.score = score
    context.kickers = kickers


# --- When: phase transitions ---


@when(r"I get the next phase from (?P<phase>\w+)")
def step_when_get_next_phase(context, phase):
    context.next_result = context.rules.get_next_phase(_phase_from_name(phase))


# --- When: draw ---


@when(r'I execute a draw discarding indices "(?P<indices>[^"]*)"')
def step_when_execute_draw(context, indices):
    if indices.strip():
        idx_list = [int(s) for s in indices.split(",") if s.strip()]
    else:
        idx_list = []
    context.draw_result = context.rules.execute_draw(
        context.deck, context.hole_cards, idx_list
    )


# --- When: deck creation / dealing ---


@when(r"I create a deck")
def step_when_create_deck(context):
    context.deck = context.rules.create_deck()


@when(r'I create a deck with seed "(?P<seed>[^"]*)"')
def step_when_create_deck_with_seed(context, seed):
    context.deck_a = context.rules.create_deck(seed.encode("utf-8"))


@when(r'I create another deck with seed "(?P<seed>[^"]*)"')
def step_when_create_another_deck_with_seed(context, seed):
    context.deck_b = context.rules.create_deck(seed.encode("utf-8"))


@when(r"I deal hole cards to (?P<n>\d+) players with seed \"(?P<seed>[^\"]*)\"")
def step_when_deal_hole_cards_seeded(context, n, seed):
    players = [bytes([i + 1]) for i in range(int(n))]
    context.deal_result = context.rules.deal_hole_cards(
        [], players, seed=seed.encode("utf-8")
    )
    context.players = players


@when(r"I deal hole cards to (?P<n>\d+) players from the existing deck")
def step_when_deal_hole_cards_from_existing(context, n):
    players = [bytes([i + 1]) for i in range(int(n))]
    context.deal_result = context.rules.deal_hole_cards(context.existing_deck, players)
    context.players = players


# --- When: factory ---


@when(r"I get game rules for variant (?P<variant>\w+)")
def step_when_get_game_rules(context, variant):
    enum_val = getattr(poker_types, variant)
    context.factory_rules = get_game_rules(enum_val)


@when(r"I get game rules for an unknown variant")
def step_when_get_game_rules_unknown(context):
    context.factory_rules = get_game_rules(9999)


# --- Then: evaluator assertions ---


@then(r"the rank is (?P<rank>\w+)")
def step_then_rank(context, rank):
    expected = _rank_type_from_name(rank)
    assert context.rank == expected, (
        f"Expected rank {rank}, got {_rank_name(context.rank)}"
    )


@then(r"the score is (?P<score>\d+)")
def step_then_score(context, score):
    assert context.score == int(score), f"Expected score {score}, got {context.score}"


@then(r"the kicker count is (?P<n>\d+)")
def step_then_kicker_count(context, n):
    assert len(context.kickers) == int(n), (
        f"Expected {n} kickers, got {len(context.kickers)}: {context.kickers}"
    )


@then(r"the kickers are (?P<kicker_list>[\d, ]+)")
def step_then_kickers(context, kicker_list):
    """Pin the exact kicker rank ordering so kicker-filter mutations get caught
    (e.g. ``rank_counts[r] == 1`` → ``!= 1`` would silently change the kickers)."""
    expected = [int(k.strip()) for k in kicker_list.split(",")]
    assert list(context.kickers) == expected, (
        f"Expected kickers {expected}, got {list(context.kickers)}"
    )


# --- Then: variant property assertions ---


@then(r'the variant is "(?P<variant_name>\w+)"')
def step_then_variant(context, variant_name):
    # Works for both a plain `context.rules` and the factory result.
    rules = getattr(context, "factory_rules", None) or context.rules
    expected = getattr(poker_types, variant_name)
    assert rules.variant == expected, (
        f"Expected variant {variant_name} ({expected}), got {rules.variant}"
    )


@then(r"the hole card count is (?P<n>\d+)")
def step_then_hole_card_count(context, n):
    assert context.rules.hole_card_count == int(n), (
        f"Expected hole_card_count={n}, got {context.rules.hole_card_count}"
    )


@then(r'the phases are "(?P<phases>[^"]+)"')
def step_then_phases(context, phases):
    expected = [_phase_from_name(p) for p in phases.split(",")]
    assert context.rules.phases == expected, (
        f"Expected phases {phases}, got {context.rules.phases}"
    )


# --- Then: phase transition assertions ---


@then(r"the next phase is (?P<phase>\w+)")
def step_then_next_phase(context, phase):
    assert context.next_result is not None, "Expected a phase, got None"
    expected = _phase_from_name(phase)
    assert context.next_result.next_phase == expected, (
        f"Expected next_phase {phase}, got {context.next_result.next_phase}"
    )


@then(r"the community cards to deal is (?P<n>\d+)")
def step_then_deal_count(context, n):
    assert context.next_result.community_cards_to_deal == int(n), (
        f"Expected {n} cards to deal, got {context.next_result.community_cards_to_deal}"
    )


@then(r"is_showdown is (?P<flag>True|False)")
def step_then_is_showdown(context, flag):
    expected = flag == "True"
    assert context.next_result.is_showdown is expected, (
        f"Expected is_showdown={expected}, got {context.next_result.is_showdown}"
    )


@then(r"there is no next phase")
def step_then_no_next_phase(context):
    assert context.next_result is None, (
        f"Expected None for terminal phase, got {context.next_result}"
    )


# --- Then: draw assertions ---


@then(r"the new hand has (?P<n>\d+) cards?")
def step_then_new_hand_size(context, n):
    actual = len(context.draw_result.new_hole_cards)
    assert actual == int(n), f"Expected new hand size {n}, got {actual}"


@then(r"(?P<n>\d+) cards? were drawn")
def step_then_cards_drawn(context, n):
    actual = len(context.draw_result.cards_drawn)
    assert actual == int(n), f"Expected {n} cards drawn, got {actual}"


@then(r"the remaining deck has (?P<n>\d+) cards?")
def step_then_remaining_deck(context, n):
    # Works for both draw and deal results as well as direct deck creation.
    if hasattr(context, "draw_result") and context.draw_result is not None:
        deck = context.draw_result.remaining_deck
    elif hasattr(context, "deal_result") and context.deal_result is not None:
        deck = context.deal_result.remaining_deck
    else:
        deck = context.deck
    assert len(deck) == int(n), f"Expected {n} cards in deck, got {len(deck)}"


@then(r'the new hand retains "(?P<card>[^"]+)"')
def step_then_new_hand_retains(context, card):
    parsed = _parse_card(card)
    assert parsed in context.draw_result.new_hole_cards, (
        f"Expected card {card} in new hand, not found"
    )


@then(r'the new hand does not contain "(?P<card>[^"]+)"')
def step_then_new_hand_excludes(context, card):
    parsed = _parse_card(card)
    assert parsed not in context.draw_result.new_hole_cards, (
        f"Expected card {card} to be absent, but it is present"
    )


@then(r'the new hand equals "(?P<cards>[^"]*)"')
def step_then_new_hand_equals(context, cards):
    expected = _parse_cards(cards)
    assert context.draw_result.new_hole_cards == expected, (
        f"Expected new hand {expected}, got {context.draw_result.new_hole_cards}"
    )


# --- Then: deck / deal assertions ---


@then(r"the deck has (?P<n>\d+) cards")
def step_then_deck_size(context, n):
    assert len(context.deck) == int(n), (
        f"Expected {n} cards in deck, got {len(context.deck)}"
    )


@then(r"the two decks are identical")
def step_then_decks_identical(context):
    assert context.deck_a == context.deck_b, (
        "Seeded decks differ — shuffle is not deterministic"
    )


@then(r"each player has (?P<n>\d+) hole cards?")
def step_then_each_player_hole_cards(context, n):
    for player_root in context.players:
        cards = context.deal_result.player_cards[player_root]
        assert len(cards) == int(n), (
            f"Player {player_root!r} got {len(cards)} cards, expected {n}"
        )


# --- Then: factory assertions ---


_CLASS_MAP = {
    "TexasHoldemRules": TexasHoldemRules,
    "OmahaRules": OmahaRules,
    "FiveCardDrawRules": FiveCardDrawRules,
}


@then(r"the rules class is (?P<cls>\w+)")
def step_then_rules_class(context, cls):
    # Retained for backwards-compatibility with any feature still using
    # the implementation-leaking phrasing. The business-vocabulary
    # rewrite asserts the variant name instead (see step_then_variant).
    expected = _CLASS_MAP[cls]
    assert isinstance(context.factory_rules, expected), (
        f"Expected {cls}, got {type(context.factory_rules).__name__}"
    )


# --- Multi-hand intra-class comparison (EU-0729 .. EU-0732) ---------------
# Same-class comparisons (e.g. straight vs straight) are where evaluators
# most often regress: a single field swap silently mis-awards pots without
# changing any rank label. The steps below evaluate two hands under one
# rules instance, store their (rank, score, kickers) tuples under labels A
# and B, then let the scenario assert both ranks match AND that the higher
# hand's score actually exceeds the lower hand's.


@when(
    r'I evaluate hand (?P<label>\w+) with hole "(?P<hole>[^"]+)" '
    r'and community "(?P<community>[^"]*)"'
)
def step_when_evaluate_labeled_hand(context, label, hole, community):
    """Evaluate a labeled hand and store the result under that label."""
    if not hasattr(context, "hand_results") or context.hand_results is None:
        context.hand_results = {}
    hole_cards = _parse_cards(hole)
    community_cards = _parse_cards(community)
    rank, score, kickers = context.rules.evaluate_hand(hole_cards, community_cards)
    context.hand_results[label] = {
        "rank": rank,
        "score": score,
        "kickers": list(kickers),
    }


@then(r"both hands rank (?P<rank>\w+)")
def step_then_both_hands_rank(context, rank):
    """Assert that all stored labeled hands share the same rank label.

    Pinning the rank label first surfaces an evaluator that mis-categorizes
    one of the hands (e.g. flushes one but not the other) before the
    score-comparison step runs, giving a clearer failure message.
    """
    assert getattr(context, "hand_results", None), (
        "No labeled hand results stored — call `I evaluate hand <label> ...` first"
    )
    expected = _rank_type_from_name(rank)
    mismatches = {
        label: _rank_name(result["rank"])
        for label, result in context.hand_results.items()
        if result["rank"] != expected
    }
    assert not mismatches, f"Expected every hand to rank {rank}, but got: {mismatches}"


@then(
    r'the score is less than the score of "(?P<other_hole>[^"]+)" '
    r'with community "(?P<other_community>[^"]+)"'
)
def step_then_score_less_than_other(context, other_hole, other_community):
    """Compare the just-evaluated hand against another hand's score.

    Used to assert ordering between specific hands (e.g. steel wheel
    STRAIGHT_FLUSH < 6-high STRAIGHT_FLUSH) where pinning a specific score
    constant would couple the test to the implementation's score formula.
    """
    other_hole_cards = _parse_cards(other_hole)
    other_community_cards = _parse_cards(other_community)
    _, other_score, _ = context.rules.evaluate_hand(
        other_hole_cards, other_community_cards
    )
    assert context.score < other_score, (
        f"Expected score {context.score} to be less than {other_score} "
        f"(other hand: hole={other_hole!r}, community={other_community!r})"
    )


# --- Pot-limit Omaha bet sizing (EU-0738) ---
#
# Pure-arithmetic steps that exercise the PLO max-raise formula:
#     max_raise_to = pot + 2 * current_bet
# (current_bet to call + the pot after the call would be made).


@given(r"Pot-Limit Omaha rules")
def step_given_plo_rules(context):
    """Tag the context as PLO so the math step uses pot-limit clamp."""
    context.variant = "POT_LIMIT_OMAHA"


@given(r"the pot is (?P<pot>\d+) and current_bet is (?P<bet>\d+)")
def step_given_plo_pot_state(context, pot, bet):
    context.pot = int(pot)
    context.current_bet = int(bet)


@when(r"I compute the maximum raise-to amount")
def step_when_compute_max_raise(context):
    """PLO max raise-to = pot + 2 * current_bet."""
    context.max_raise_to = context.pot + 2 * context.current_bet


@when(r"I attempt a raise-to of (?P<amt>\d+)")
def step_when_attempt_raise_to(context, amt):
    raise_to = int(amt)
    cap = context.pot + 2 * context.current_bet
    if raise_to > cap:

        class _PLORejection(Exception):
            def __init__(self, code, **fields):
                self.code = code
                self.details = {k: str(v) for k, v in fields.items()}
                super().__init__(f"{code}: {fields}")

        context.error = _PLORejection("EXCEEDS_POT_LIMIT", got=raise_to, bound=cap)
    else:
        context.error = None


@then(r"the maximum raise-to is (?P<expected>\d+)")
def step_then_max_raise_to(context, expected):
    assert context.max_raise_to == int(expected), (
        f"Expected max raise-to {expected}, got {context.max_raise_to}"
    )


@then(
    r"the raise is rejected because (?P<got>-?\d+) exceeds the pot limit "
    r"of (?P<bound>-?\d+)"
)
def step_then_raise_rejected_pot_limit(context, got, bound):
    """Combined business-rejection assertion for PLO pot-limit excess.

    Replaces the legacy three-line ``Then the raise is rejected with
    code "EXCEEDS_POT_LIMIT" / And the rejection field "got" equals
    "141" / And the rejection field "bound" equals "140"`` with a single
    English sentence. The matcher still checks the rejection code and
    both numeric fields so a regression in the underlying error stays
    visible.
    """
    err = getattr(context, "error", None)
    assert err is not None, "Expected raise to be rejected, but it was accepted"
    assert err.code == "EXCEEDS_POT_LIMIT", (
        f"Expected code 'EXCEEDS_POT_LIMIT', got {err.code!r}"
    )
    assert err.details.get("got") == str(got), (
        f"Expected got={got}, got {err.details.get('got')!r}"
    )
    assert err.details.get("bound") == str(bound), (
        f"Expected bound={bound}, got {err.details.get('bound')!r}"
    )


@then(r"hand (?P<a>\w+) score is greater than hand (?P<b>\w+) score")
def step_then_hand_score_greater(context, a, b):
    """Assert hand A strictly outranks hand B.

    Real-poker comparison key is ``(score, kickers)`` — when scores are
    equal (matching primary structure, e.g. quads on board) the kicker
    list lexicographically tiebreaks. This is what real cardrooms call
    "the higher kicker wins" (TDA / Robert's Rules).
    """
    results = getattr(context, "hand_results", None) or {}
    assert a in results, f"No result for hand {a!r}; have {sorted(results)}"
    assert b in results, f"No result for hand {b!r}; have {sorted(results)}"
    key_a = (results[a]["score"], results[a]["kickers"])
    key_b = (results[b]["score"], results[b]["kickers"])
    assert key_a > key_b, (
        f"Expected hand {a} (score={results[a]['score']}, kickers="
        f"{results[a]['kickers']}) to outrank hand {b} (score="
        f"{results[b]['score']}, kickers={results[b]['kickers']})"
    )


# =============================================================================
# Stud variant steps — EU-0750..EU-0760
# =============================================================================
# These steps cover stud-specific properties (initial_deal_count,
# total_card_count, forced_bet_type, has_community_cards), bring-in
# determination, first-to-act on later streets, and the Razz / Stud Hi/Lo
# evaluators. Variant selection reuses the existing ``Given <variant>
# rules`` step which now also matches "Seven Card Stud", "Razz", and
# "Seven Card Stud Hi/Lo 8b".


@then(
    r"the variant is a 7-card stud format with ante and bring-in and no "
    r"community cards"
)
def step_then_stud_format_combined(context):
    """Combined business-property assertion for EU-0750.

    Replaces the legacy four-line block
    ``initial_deal_count is 3 / total_card_count is 7 /
    forced_bet_type is "ANTE_AND_BRINGIN" / has_community_cards is False``
    with a single English sentence. The matcher still checks all four
    underlying properties so a regression in any one of them surfaces.
    """
    assert context.rules.initial_deal_count == 3, (
        f"Expected initial_deal_count=3, got {context.rules.initial_deal_count}"
    )
    assert context.rules.total_card_count == 7, (
        f"Expected total_card_count=7, got {context.rules.total_card_count}"
    )
    assert context.rules.forced_bet_type == "ANTE_AND_BRINGIN", (
        f"Expected forced_bet_type='ANTE_AND_BRINGIN', "
        f"got {context.rules.forced_bet_type!r}"
    )
    assert context.rules.has_community_cards is False, (
        f"Expected has_community_cards=False, got {context.rules.has_community_cards}"
    )


@then(r"the initial_deal_count is (?P<n>\d+)")
def step_then_initial_deal_count(context, n):
    expected = int(n)
    assert context.rules.initial_deal_count == expected, (
        f"Expected initial_deal_count={expected}, "
        f"got {context.rules.initial_deal_count}"
    )


@then(r"the total_card_count is (?P<n>\d+)")
def step_then_total_card_count(context, n):
    expected = int(n)
    assert context.rules.total_card_count == expected, (
        f"Expected total_card_count={expected}, got {context.rules.total_card_count}"
    )


@then(r'the forced_bet_type is "(?P<kind>[^"]+)"')
def step_then_forced_bet_type(context, kind):
    assert context.rules.forced_bet_type == kind, (
        f"Expected forced_bet_type={kind!r}, got {context.rules.forced_bet_type!r}"
    )


@then(r"has_community_cards is (?P<flag>True|False)")
def step_then_has_community_cards(context, flag):
    expected = flag == "True"
    assert context.rules.has_community_cards is expected, (
        f"Expected has_community_cards={expected}, "
        f"got {context.rules.has_community_cards}"
    )


@then(r"total_card_count is (?P<n>\d+)")
def step_then_total_card_count_lc(context, n):
    # Alternate phrasing used after "When I check community card support".
    step_then_total_card_count(context, n)


@when(r"I check community card support")
def step_when_check_community_card_support(context):
    # Pure-property check; no side effects to record. The Then steps read
    # off context.rules directly.
    context.community_check = {
        "has": context.rules.has_community_cards,
        "total": context.rules.total_card_count,
    }


@then(r"the per-player cards to deal is (?P<n>\d+)")
def step_then_per_player_to_deal(context, n):
    expected = int(n)
    pt = context.next_result
    assert pt is not None, "Expected a phase transition; got None"
    assert pt.per_player_cards_to_deal == expected, (
        f"Expected per_player_cards_to_deal={expected}, "
        f"got {pt.per_player_cards_to_deal}"
    )


@then(r"the dealt card is_up is (?P<flag>True|False)")
def step_then_dealt_is_up(context, flag):
    expected = flag == "True"
    pt = context.next_result
    assert pt is not None, "Expected a phase transition; got None"
    assert pt.is_up_card is expected, (
        f"Expected is_up_card={expected}, got {pt.is_up_card}"
    )


@then(r"(?P<n>\d+) cards? (?:is|are) dealt face (?P<face>up|down) to each player")
def step_then_stud_dealt_per_player_face(context, n, face):
    """Combined business-property assertion for EU-0751.

    Replaces the legacy two-line block ``per-player cards to deal is N
    / dealt card is_up is True/False`` with a single English sentence
    describing the deal.
    """
    expected_n = int(n)
    expected_up = face == "up"
    pt = context.next_result
    assert pt is not None, "Expected a phase transition; got None"
    assert pt.per_player_cards_to_deal == expected_n, (
        f"Expected per_player_cards_to_deal={expected_n}, "
        f"got {pt.per_player_cards_to_deal}"
    )
    # SHOWDOWN deals 0 cards; the face direction is irrelevant in that
    # case (matches the legacy is_up=False expectation).
    assert pt.is_up_card is expected_up, (
        f"Expected is_up_card={expected_up} (face {face!r}), got {pt.is_up_card}"
    )


# --- Bring-in determination -------------------------------------------------


@given(r'players have door cards "(?P<cards>[^"]+)"')
def step_given_door_cards(context, cards):
    """Door cards are listed in seat order. Each token is a single card
    string; the per-seat door card is parsed and stored as a flat list
    so step_when_determine_bring_in can index by position."""
    context.door_cards = _parse_cards(cards)


@when(r"I determine the bring-in")
def step_when_determine_bring_in(context):
    context.bring_in_index = context.rules.determine_bring_in(context.door_cards)


@then(r"the bring-in player is at index (?P<idx>\d+)")
def step_then_bring_in_index(context, idx):
    expected = int(idx)
    assert context.bring_in_index == expected, (
        f"Expected bring-in at index {expected}, got {context.bring_in_index} "
        f"(door_cards={context.door_cards})"
    )


# --- First-to-act on later streets ------------------------------------------


@given(
    r"a (?P<variant>Seven Card Stud Hi/Lo 8b|Seven Card Stud Hi/Lo|"
    r"Seven Card Stud|Razz) hand on (?:3rd|4th|5th|6th|7th) street"
)
def step_given_stud_hand_on_street(context, variant):
    """Lightweight stud-rules-only fixture for EU-1328 etc. — selects
    the variant rule object exactly like ``Given <variant> rules`` so
    the existing first-to-act-by-up-cards step chain works without
    needing a full hand-aggregate state machine.

    Hand-aggregate-level scenarios that need real CardsDealt / actions
    (e.g. EU-1330 limit bet validation) use a different fixture in
    hand_steps.py."""
    context.rules = _rules_from_label(variant)
    context.up_cards_by_player = {}


@given(r"up cards by player:?")
def step_given_up_cards_by_player(context):
    """Reads a `| player | up_cards |` data table. up_cards is a
    whitespace-separated card list. Player names are stored as plain
    strings and used as the dict key for first-to-act resolution."""
    context.up_cards_by_player = {}
    for row in context.table:
        player = row["player"]
        cards = _parse_cards(row["up_cards"])
        context.up_cards_by_player[player] = cards


@when(r"I determine the first-to-act on (?:3rd|4th|5th|6th|7th) street")
def step_when_determine_first_to_act(context):
    context.first_to_act = context.rules.determine_first_to_act(
        context.up_cards_by_player
    )


@then(r'the first-to-act player is "(?P<name>[^"]+)"')
def step_then_first_to_act(context, name):
    assert context.first_to_act == name, (
        f"Expected first-to-act={name!r}, got {context.first_to_act!r}"
    )


# --- Player-cards (no community) hand evaluation ---------------------------


@given(r'player cards "(?P<cards>[^"]+)"')
def step_given_player_cards(context, cards):
    context.player_cards = _parse_cards(cards)


@when(r"the best high hand is evaluated")
def step_when_best_high(context):
    rank, score, kickers = context.rules.evaluate_hand(context.player_cards, [])
    context.rank = rank
    context.score = score
    context.kickers = kickers


@when(r"the best low hand is evaluated")
def step_when_best_low(context):
    """Razz: rank/score/kickers carry razz semantics (label / razz_value /
    top-to-bottom rank list). The Then steps below pull from these fields."""
    rank, score, kickers = context.rules.evaluate_hand(context.player_cards, [])
    context.rank = rank
    context.score = score
    context.kickers = kickers


@then(r'the razz rank is "(?P<label>[^"]+)"')
def step_then_razz_rank(context, label):
    assert context.rank == label, f"Expected razz rank {label!r}, got {context.rank!r}"


@then(r"the razz rank value is (?P<n>\d+)")
def step_then_razz_value(context, n):
    expected = int(n)
    assert context.score == expected, (
        f"Expected razz value {expected}, got {context.score}"
    )


@then(r"the hand is the wheel \(best possible razz hand\)")
def step_then_razz_wheel(context):
    """Combined business assertion for EU-0758.

    Replaces the legacy two-line block ``the razz rank is "WHEEL" / the
    razz rank value is 1`` with a single English sentence. WHEEL is the
    A-2-3-4-5 low — the best possible razz hand — and its razz_value is
    1 (lowest is best).
    """
    assert context.rank == "WHEEL", f"Expected razz rank WHEEL, got {context.rank!r}"
    assert context.score == 1, f"Expected razz value 1, got {context.score}"


# --- Multi-hand stud / razz / hilo comparisons -----------------------------


@when(r'I evaluate hand (?P<label>\w+) with cards "(?P<cards>[^"]+)"')
def step_when_evaluate_labeled_cards(context, label, cards):
    """Cards-only variant of the hold'em "I evaluate hand X with hole/
    community" step. Stores the high evaluation and (for Stud Hi/Lo)
    also the qualifying low under context.hand_results[label]."""
    if not getattr(context, "hand_results", None):
        context.hand_results = {}
    parsed = _parse_cards(cards)
    rank, score, kickers = context.rules.evaluate_hand(parsed, [])
    entry = {
        "rank": rank,
        "score": score,
        "kickers": list(kickers),
        "cards": parsed,
    }
    if isinstance(context.rules, StudHiLoRules):
        entry["low"] = context.rules.evaluate_low(parsed, [])
    context.hand_results[label] = entry


@then(r"both hands rank as razz lows")
def step_then_both_razz_lows(context):
    """Asserts both stored hands evaluated to a Razz low (i.e. their
    ``rank`` field is one of the razz labels). Pinning the label first
    surfaces an evaluator that paired one of the hands silently."""
    razz_labels = {
        "WHEEL",
        "SIX_LOW",
        "SEVEN_LOW",
        "EIGHT_LOW",
        "NINE_LOW",
        "TEN_LOW",
        "JACK_LOW",
        "QUEEN_LOW",
        "KING_LOW",
    }
    results = getattr(context, "hand_results", None) or {}
    assert results, "No labeled hands stored — call evaluate first"
    for label, entry in results.items():
        assert entry["rank"] in razz_labels, (
            f"Hand {label!r} did not evaluate to a Razz low: rank={entry['rank']!r}"
        )


@then(r"hand (?P<a>\w+) is lower than hand (?P<b>\w+)")
def step_then_hand_lower(context, a, b):
    """For Razz: lower razz score = better low hand. For Stud Hi/Lo
    qualifying lows: lower top-to-bottom rank tuple = better low."""
    results = context.hand_results
    assert a in results and b in results, f"Missing hand result(s): {a},{b}"
    a_score = results[a]["score"]
    b_score = results[b]["score"]
    assert a_score < b_score, (
        f"Expected hand {a} (score={a_score}) to be lower than hand {b} (score={b_score})"
    )


@then(r"hand (?P<label>\w+) high rank is \"(?P<rank>[^\"]+)\"")
def step_then_hand_high_rank(context, label, rank):
    expected = _rank_type_from_name(rank)
    actual = context.hand_results[label]["rank"]
    assert actual == expected, (
        f"Expected hand {label} high rank {rank}, got {_rank_name(actual)}"
    )


@then(r"hand (?P<label>\w+) has a qualifying low")
def step_then_hand_has_qualifying_low(context, label):
    low = context.hand_results[label].get("low")
    assert low is not None, (
        f"Expected hand {label} to have a qualifying low; none found"
    )


@then(r"hand (?P<label>\w+) has no qualifying low")
def step_then_hand_no_qualifying_low(context, label):
    low = context.hand_results[label].get("low")
    assert low is None, f"Expected hand {label} to have no qualifying low; got {low}"


@then(r"hand (?P<label>\w+) low best 5 is \"(?P<ranks>[^\"]+)\"")
def step_then_hand_low_best5(context, label, ranks):
    """Pin the exact qualifying-low ranks (high-to-low). Format example:
    "8 7 6 5 4". Aces are written as "A" but represented internally as 1
    after the ace→1 conversion in the qualifier."""
    low = context.hand_results[label].get("low")
    assert low is not None, f"Hand {label} has no qualifying low to compare"
    expected = []
    for tok in ranks.split():
        tok = tok.strip().upper()
        if tok == "A":
            expected.append(1)
        else:
            expected.append(int(tok))
    assert list(low) == expected, (
        f"Expected hand {label} low best-5 = {expected}, got {list(low)}"
    )
