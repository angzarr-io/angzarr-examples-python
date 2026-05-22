"""Polymorphic game rules for different poker variants."""

import hashlib
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types

# SplitMix64 — portable PRNG used so seeded shuffles produce byte-identical
# decks across language implementations. Specified by the cucumber spec
# (hand.feature EU-0004 asserts specific cards for a given seed); any
# non-portable PRNG would silently break that assertion across languages.
_SPLITMIX64_MASK = (1 << 64) - 1
_SPLITMIX64_GAMMA = 0x9E3779B97F4A7C15
_SPLITMIX64_MIX1 = 0xBF58476D1CE4E5B9
_SPLITMIX64_MIX2 = 0x94D049BB133111EB


class _SplitMix64:
    """SplitMix64 reference implementation. Output identical to the Rust
    `SplitMix64` in `examples-rust/main/hand/agg/src/handlers/deal_cards.rs`.
    """

    def __init__(self, seed: int):
        self.state = seed & _SPLITMIX64_MASK

    def next_u64(self) -> int:
        self.state = (self.state + _SPLITMIX64_GAMMA) & _SPLITMIX64_MASK
        z = self.state
        z = ((z ^ (z >> 30)) * _SPLITMIX64_MIX1) & _SPLITMIX64_MASK
        z = ((z ^ (z >> 27)) * _SPLITMIX64_MIX2) & _SPLITMIX64_MASK
        return z ^ (z >> 31)


def _shuffle_with_seed(deck: list, seed: bytes) -> None:
    """In-place Fisher-Yates shuffle using the canonical PRNG.

    Seed derivation: SHA-256(seed_bytes) → first 8 bytes big-endian → u64 →
    SplitMix64 state. Both languages must use this exact derivation for
    decks to match.
    """
    digest = hashlib.sha256(seed).digest()
    seed_int = int.from_bytes(digest[:8], "big")
    rng = _SplitMix64(seed_int)
    n = len(deck)
    for i in range(n - 1, 0, -1):
        j = rng.next_u64() % (i + 1)
        deck[i], deck[j] = deck[j], deck[i]


@dataclass
class DealResult:
    """Result of dealing cards."""

    player_cards: dict  # player_root -> list of (suit, rank) tuples
    remaining_deck: list  # Remaining cards in deck


@dataclass
class DrawResult:
    """Result of executing a draw."""

    new_hole_cards: list  # Updated hole cards after draw
    cards_drawn: list  # New cards drawn from deck
    remaining_deck: list  # Remaining cards in deck


@dataclass
class PhaseTransition:
    """Information about phase transition.

    For board games (Hold'em / Omaha) ``community_cards_to_deal`` carries the
    new flop/turn/river count and ``per_player_cards_to_deal`` stays 0. For
    stud variants those flip — community is always 0 (no shared board) and
    per-player is the up-card count for 4th-6th street, then a final down
    card for 7th street. ``is_up_card`` distinguishes the two.
    """

    next_phase: int  # BettingPhase enum (or StudStreet for stud variants)
    community_cards_to_deal: int
    is_showdown: bool
    per_player_cards_to_deal: int = 0
    is_up_card: bool = False


class GameRules(ABC):
    """Abstract base class for poker variant rules."""

    @property
    @abstractmethod
    def variant(self) -> int:
        """Return the GameVariant enum value."""
        pass

    @property
    @abstractmethod
    def hole_card_count(self) -> int:
        """Number of hole cards dealt to each player."""
        pass

    @property
    @abstractmethod
    def phases(self) -> list:
        """List of betting phases for this variant."""
        pass

    @abstractmethod
    def get_next_phase(self, current_phase: int) -> Optional[PhaseTransition]:
        """Get the next phase after the current one, or None if hand is complete."""
        pass

    @abstractmethod
    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        """
        Evaluate a hand and return (rank_type, score, kickers).

        rank_type: HandRankType enum
        score: Numeric score for comparison
        kickers: List of Rank values for tie-breaking
        """
        pass

    @property
    def initial_deal_count(self) -> int:
        """Cards dealt to each player at the start of the hand. Defaults to
        ``hole_card_count`` for board-game variants; stud overrides to 3
        (two down + one up door card)."""
        return self.hole_card_count

    @property
    def total_card_count(self) -> int:
        """Total cards held by a single player at showdown. 7 for stud,
        2 for Hold'em (hole only — community is shared), 4 for Omaha,
        5 for Five-Card Draw."""
        return self.hole_card_count

    @property
    def has_community_cards(self) -> bool:
        """True for Hold'em/Omaha; False for stud and draw."""
        return False

    @property
    def forced_bet_type(self) -> str:
        """Forced-bet model: ``BLINDS`` for board games / draw,
        ``ANTE_AND_BRINGIN`` for stud variants. Used by tournament/table
        configuration to know how to seed the pot before the deal."""
        return "BLINDS"

    def create_deck(self, seed: Optional[bytes] = None) -> list:
        """Create and shuffle a standard 52-card deck."""
        deck = []
        for suit in [
            poker_types.CLUBS,
            poker_types.DIAMONDS,
            poker_types.HEARTS,
            poker_types.SPADES,
        ]:
            for rank in range(2, 15):  # 2-14 (Ace)
                deck.append((suit, rank))

        if seed:
            _shuffle_with_seed(deck, seed)
        else:
            random.shuffle(deck)

        return deck

    def deal_hole_cards(
        self, deck: list, players: list, seed: Optional[bytes] = None
    ) -> DealResult:
        """Deal hole cards to all players."""
        if seed:
            working_deck = self.create_deck(seed)
        elif not deck:
            working_deck = self.create_deck()
        else:
            working_deck = deck.copy()

        player_cards = {}
        for player_root in players:
            cards = []
            for _ in range(self.hole_card_count):
                if working_deck:
                    cards.append(working_deck.pop(0))
            player_cards[player_root] = cards

        return DealResult(
            player_cards=player_cards,
            remaining_deck=working_deck,
        )


class TexasHoldemRules(GameRules):
    """Rules for Texas Hold'em poker."""

    # Phase transition table - avoids if/elif chain
    _PHASE_TRANSITIONS: dict[int, PhaseTransition] = {
        poker_types.PREFLOP: PhaseTransition(
            next_phase=poker_types.FLOP,
            community_cards_to_deal=3,
            is_showdown=False,
        ),
        poker_types.FLOP: PhaseTransition(
            next_phase=poker_types.TURN,
            community_cards_to_deal=1,
            is_showdown=False,
        ),
        poker_types.TURN: PhaseTransition(
            next_phase=poker_types.RIVER,
            community_cards_to_deal=1,
            is_showdown=False,
        ),
        poker_types.RIVER: PhaseTransition(
            next_phase=poker_types.SHOWDOWN,
            community_cards_to_deal=0,
            is_showdown=True,
        ),
    }

    @property
    def variant(self) -> int:
        return poker_types.TEXAS_HOLDEM

    @property
    def hole_card_count(self) -> int:
        return 2

    @property
    def phases(self) -> list:
        return [
            poker_types.PREFLOP,
            poker_types.FLOP,
            poker_types.TURN,
            poker_types.RIVER,
            poker_types.SHOWDOWN,
        ]

    @property
    def has_community_cards(self) -> bool:
        return True

    @property
    def total_card_count(self) -> int:
        # 2 hole + 5 community shared
        return 7

    def get_next_phase(self, current_phase: int) -> Optional[PhaseTransition]:
        return self._PHASE_TRANSITIONS.get(current_phase)

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        """Evaluate best 5-card hand from 7 cards (2 hole + 5 community)."""
        all_cards = hole_cards + community_cards
        return self._find_best_hand(all_cards)

    def _find_best_hand(self, cards: list) -> tuple:
        """Find the best 5-card hand from available cards.

        Comparison key is (score, kickers) so kicker lists tiebreak when
        scores are equal — required for FOUR_OF_A_KIND with quads on board,
        TWO_PAIR with both pairs on board, and THREE_OF_A_KIND with trips
        on board (real-poker rule: highest remaining card decides).
        """
        if len(cards) < 5:
            return (poker_types.HIGH_CARD, 0, [])

        from itertools import combinations

        best = (poker_types.HIGH_CARD, 0, [])
        for combo in combinations(cards, 5):
            result = self._evaluate_five(list(combo))
            if (result[1], result[2]) > (best[1], best[2]):
                best = result

        return best

    def _evaluate_five(self, cards: list) -> tuple:
        """Evaluate exactly 5 cards."""
        suits = [c[0] for c in cards]
        ranks = sorted([c[1] for c in cards], reverse=True)

        is_flush = len(set(suits)) == 1
        is_straight = self._is_straight(ranks)

        rank_counts = {}
        for r in ranks:
            rank_counts[r] = rank_counts.get(r, 0) + 1

        counts = sorted(rank_counts.values(), reverse=True)
        sorted_by_count = sorted(
            rank_counts.keys(), key=lambda x: (rank_counts[x], x), reverse=True
        )

        # Calculate score
        if is_straight and is_flush:
            if ranks == [14, 13, 12, 11, 10]:
                return (poker_types.ROYAL_FLUSH, 10000000, [])
            # Wheel (A-2-3-4-5) sorts as [14,5,4,3,2] but is 5-high — the
            # LOWEST straight flush. Score by the actual high card (5),
            # not the Ace, so 6-high SF correctly beats the steel wheel.
            high_card = 5 if ranks == [14, 5, 4, 3, 2] else ranks[0]
            return (poker_types.STRAIGHT_FLUSH, 9000000 + high_card, [])
        elif counts == [4, 1]:
            return (
                poker_types.FOUR_OF_A_KIND,
                8000000 + sorted_by_count[0] * 100,
                [sorted_by_count[1]],
            )
        elif counts == [3, 2]:
            return (
                poker_types.FULL_HOUSE,
                7000000 + sorted_by_count[0] * 100 + sorted_by_count[1],
                [],
            )
        elif is_flush:
            return (poker_types.FLUSH, 6000000 + self._rank_score(ranks), ranks)
        elif is_straight:
            # Wheel score uses 5 (high card), not 14 (Ace plays low).
            high_card = 5 if ranks == [14, 5, 4, 3, 2] else ranks[0]
            return (poker_types.STRAIGHT, 5000000 + high_card, [])
        elif counts == [3, 1, 1]:
            kickers = [r for r in sorted_by_count if rank_counts[r] == 1]
            return (
                poker_types.THREE_OF_A_KIND,
                4000000 + sorted_by_count[0] * 1000,
                kickers,
            )
        elif counts == [2, 2, 1]:
            pairs = [r for r in sorted_by_count if rank_counts[r] == 2]
            kicker = [r for r in sorted_by_count if rank_counts[r] == 1]
            return (
                poker_types.TWO_PAIR,
                3000000 + max(pairs) * 100 + min(pairs),
                kicker,
            )
        elif counts == [2, 1, 1, 1]:
            pair = [r for r in sorted_by_count if rank_counts[r] == 2][0]
            kickers = [r for r in sorted_by_count if rank_counts[r] == 1]
            return (poker_types.PAIR, 2000000 + pair * 1000, kickers)
        else:
            return (poker_types.HIGH_CARD, 1000000 + self._rank_score(ranks), ranks)

    def _is_straight(self, ranks: list) -> bool:
        """Check if sorted ranks form a straight."""
        if ranks == [14, 5, 4, 3, 2]:  # Wheel (A-2-3-4-5)
            return True
        for i in range(len(ranks) - 1):
            if ranks[i] - ranks[i + 1] != 1:
                return False
        return True

    def _rank_score(self, ranks: list) -> int:
        """Calculate a score from ranks for comparison."""
        score = 0
        for i, r in enumerate(ranks):
            score += r * (15 ** (4 - i))
        return score


class OmahaRules(TexasHoldemRules):
    """Rules for Omaha poker (uses 2 of 4 hole cards)."""

    @property
    def variant(self) -> int:
        return poker_types.OMAHA

    @property
    def hole_card_count(self) -> int:
        return 4

    @property
    def total_card_count(self) -> int:
        # 4 hole + 5 community shared
        return 9

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        """Evaluate best hand using exactly 2 hole cards and 3 community cards."""
        from itertools import combinations

        best = (poker_types.HIGH_CARD, 0, [])

        # Must use exactly 2 hole cards and 3 community cards.
        # Comparison key is (score, kickers) so kickers tiebreak — see
        # TexasHoldemRules._find_best_hand for the rationale.
        for hole_combo in combinations(hole_cards, 2):
            for comm_combo in combinations(community_cards, 3):
                cards = list(hole_combo) + list(comm_combo)
                result = self._evaluate_five(cards)
                if (result[1], result[2]) > (best[1], best[2]):
                    best = result

        return best


class FiveCardDrawRules(GameRules):
    """Rules for Five Card Draw poker."""

    # Phase transition table - avoids if/elif chain
    _PHASE_TRANSITIONS: dict[int, PhaseTransition] = {
        poker_types.PREFLOP: PhaseTransition(
            next_phase=poker_types.DRAW,
            community_cards_to_deal=0,
            is_showdown=False,
        ),
        poker_types.DRAW: PhaseTransition(
            next_phase=poker_types.SHOWDOWN,
            community_cards_to_deal=0,
            is_showdown=True,
        ),
    }

    @property
    def variant(self) -> int:
        return poker_types.FIVE_CARD_DRAW

    @property
    def hole_card_count(self) -> int:
        return 5

    @property
    def phases(self) -> list:
        return [
            poker_types.PREFLOP,  # Initial betting
            poker_types.DRAW,  # Draw phase
            poker_types.SHOWDOWN,
        ]

    def get_next_phase(self, current_phase: int) -> Optional[PhaseTransition]:
        return self._PHASE_TRANSITIONS.get(current_phase)

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        """Evaluate 5-card hand (no community cards in draw)."""
        # Reuse Hold'em evaluation since it's standard poker hand ranking
        evaluator = TexasHoldemRules()
        return evaluator._evaluate_five(hole_cards)

    def execute_draw(
        self, deck: list, hole_cards: list, discard_indices: list
    ) -> DrawResult:
        """
        Execute a draw - discard selected cards and draw replacements.

        Args:
            deck: Current deck to draw from
            hole_cards: Player's current hole cards
            discard_indices: Indices of cards to discard (0-4)

        Returns:
            DrawResult with new hand, cards drawn, and remaining deck
        """
        new_hole = hole_cards.copy()
        remaining_deck = deck.copy()

        # Remove discarded cards (in reverse order to maintain indices)
        for i in sorted(discard_indices, reverse=True):
            new_hole.pop(i)

        # Draw new cards
        cards_drawn = []
        for _ in range(len(discard_indices)):
            if remaining_deck:
                card = remaining_deck.pop()
                cards_drawn.append(card)
                new_hole.append(card)

        return DrawResult(
            new_hole_cards=new_hole,
            cards_drawn=cards_drawn,
            remaining_deck=remaining_deck,
        )


# =============================================================================
# Stud variants — Seven Card Stud, Razz, Stud Hi/Lo (8-or-better)
# =============================================================================
# Stud differs from board games in two structural ways: there are no
# community cards (each player holds 7 of their own), and the betting order
# changes per street based on the up-cards showing. The shared base class
# ``StudRulesBase`` factors out the parts that don't change between the
# three stud variants — phase machine, deal counts, antes-and-bringin
# forced-bet model. Subclasses override:
#
#   * ``determine_bring_in`` — Stud Hi & Hi/Lo use low-by-suit; Razz uses
#     high-by-suit (the wheel A-2-3-4-5 is the *target* hand in Razz, so
#     the bring-in penalty falls on the high card).
#   * ``determine_first_to_act`` — Stud Hi & Hi/Lo: high hand showing acts
#     first on 4th-7th street. Razz: low hand showing.
#   * ``evaluate_hand`` — Stud Hi: standard 5-of-7 high. Razz: 5-of-7 low
#     (no straights/flushes; aces low). Stud Hi/Lo: returns BOTH a high
#     ranking and a qualifying low (≤8 unpaired) when present.

# Suit ranking (high → low) for stud tiebreaks. TDA Rule 20B / RP-10D and
# WSOP §Seven Card Games both fix the order as spades > hearts > diamonds
# > clubs.
_SUIT_RANK = {
    poker_types.SPADES: 4,
    poker_types.HEARTS: 3,
    poker_types.DIAMONDS: 2,
    poker_types.CLUBS: 1,
}


def _card_high_key(card: tuple) -> tuple:
    """Sort key for "highest card by rank-then-suit" — used by Stud Hi
    and Razz first-to-act tiebreaks."""
    suit, rank = card
    return (rank, _SUIT_RANK[suit])


def _card_low_key(card: tuple) -> tuple:
    """Sort key for "lowest card by rank-then-suit" — used by the Stud Hi
    bring-in determination (TDA RP-10D)."""
    suit, rank = card
    return (rank, _SUIT_RANK[suit])


def _showing_hand_high_key(up_cards: list) -> tuple:
    """Order key for "highest poker hand showing" across the up-cards a
    player has accumulated. Used by Stud Hi to decide first-to-act on
    4th-7th street. We reuse the standard 5-card evaluator after padding
    with low-rank, low-suit ghost cards so a 1-up-card comparison still
    distinguishes by rank-then-suit."""
    rule = TexasHoldemRules()
    padding = [(poker_types.CLUBS, 0), (poker_types.CLUBS, 0)]
    cards = (up_cards + padding)[:5] if len(up_cards) < 5 else up_cards
    if len(cards) < 5:
        # Single up-card: rank+suit only.
        return (cards[0][1], _SUIT_RANK[cards[0][0]])
    rank, score, _ = rule._evaluate_five(list(cards))
    high_card = max(up_cards, key=_card_high_key)
    return (score, rank, high_card[1], _SUIT_RANK[high_card[0]])


def _is_pair_or_better_showing(up_cards: list) -> bool:
    """True iff the up-cards include any rank that appears at least
    twice. Used by RP-10F / WSOP open-pair-locks-lower-limit gating."""
    seen: dict[int, int] = {}
    for _, rank in up_cards:
        seen[rank] = seen.get(rank, 0) + 1
        if seen[rank] >= 2:
            return True
    return False


# Razz rank labels — the "wheel" is the canonical low hand. Other lows
# are labelled by their highest card ("seven low", "eight low", etc.).
_RAZZ_WHEEL_NAME = "WHEEL"
_RAZZ_RANK_NAMES = {
    5: _RAZZ_WHEEL_NAME,  # 5-4-3-2-A
    6: "SIX_LOW",
    7: "SEVEN_LOW",
    8: "EIGHT_LOW",
    9: "NINE_LOW",
    10: "TEN_LOW",
    11: "JACK_LOW",
    12: "QUEEN_LOW",
    13: "KING_LOW",
}


def _razz_low_for_five(cards: list) -> Optional[tuple]:
    """Evaluate a single 5-card combination as a Razz low. Aces are low
    (rank 14 → 1 for ranking purposes); straights and flushes don't
    count. Returns ``(razz_value, razz_label, top_to_bottom)`` where
    ``razz_value`` is 1 for the wheel and ascending for higher lows, or
    None when the combo is paired (pairs are not Razz lows)."""
    # Convert ace to 1 for low-ranking purposes.
    low_ranks = sorted([1 if rank == 14 else rank for _, rank in cards], reverse=True)
    # Pair check — pairs disqualify the combo as a "real" low. We can
    # still rank paired hands but only as a fallback against other paired
    # hands.
    seen: dict[int, int] = {}
    for r in low_ranks:
        seen[r] = seen.get(r, 0) + 1
    if any(c >= 2 for c in seen.values()):
        return None
    top = low_ranks[0]
    if top == 5 and low_ranks == [5, 4, 3, 2, 1]:
        return (1, _RAZZ_WHEEL_NAME, tuple(low_ranks))
    label = _RAZZ_RANK_NAMES.get(top, f"{top}_LOW")
    # Razz value: rank the hand by its top-to-bottom tuple. Lower tuple
    # means stronger low. Use a simple positional encoding so ordering is
    # preserved without floating-point math.
    value = 0
    for r in low_ranks:
        value = value * 100 + r
    return (value, label, tuple(low_ranks))


def _best_razz_low(seven_cards: list) -> Optional[tuple]:
    """Best Razz low across all 5-card combinations of the 7 cards. If
    no unpaired 5-card combination exists, return the best available
    paired combination (defensive — TDA assumes 7 cards always contain
    an unpaired 5-card subset, but we don't crash if not)."""
    from itertools import combinations

    best_unpaired = None
    best_paired = None
    for combo in combinations(seven_cards, 5):
        result = _razz_low_for_five(list(combo))
        if result is not None:
            if best_unpaired is None or result < best_unpaired:
                best_unpaired = result
        else:
            # Fall back: rank paired combos by sorted (rank desc) tuple.
            low_ranks = sorted(
                [1 if rank == 14 else rank for _, rank in combo], reverse=True
            )
            paired_key = (10**12, "PAIRED", tuple(low_ranks))
            if best_paired is None or paired_key < best_paired:
                best_paired = paired_key
    return best_unpaired or best_paired


def _has_qualifying_low(seven_cards: list) -> Optional[list]:
    """Stud Hi/Lo 8-or-better qualifier — return the best 5-card
    qualifying low hand if one exists, otherwise None. A qualifying low
    requires 5 cards of distinct ranks all ≤ 8 (aces count as 1)."""
    from itertools import combinations

    best = None
    for combo in combinations(seven_cards, 5):
        # Convert ace → 1 for the ≤8 test.
        low_ranks = sorted([1 if rank == 14 else rank for _, rank in combo])
        if any(r > 8 for r in low_ranks):
            continue
        if len(set(low_ranks)) != 5:
            # Pairs disqualify the combo.
            continue
        # Lower top-to-bottom tuple = stronger low.
        key = tuple(reversed(low_ranks))
        if best is None or key < best[0]:
            best = (key, low_ranks)
    if best is None:
        return None
    # ``best[0]`` is the descending key — return high-to-low so the
    # cucumber assertion order matches ("8 7 6 5 4").
    return list(best[0])


class StudRulesBase(GameRules):
    """Shared phase machine and forced-bet model for the three stud
    variants. Concrete subclasses pin the specific GameVariant enum and
    override bring-in / first-to-act / evaluator logic."""

    # Stud street machine — emits 1 up card on 4th-6th street and a
    # final down card on 7th street. The transition from THIRD_STREET
    # comes after the bring-in resolves; from SEVENTH_STREET → SHOWDOWN
    # there are no more cards to deal.
    _PHASE_TRANSITIONS: dict[int, PhaseTransition] = {
        poker_types.THIRD_STREET: PhaseTransition(
            next_phase=poker_types.FOURTH_STREET,
            community_cards_to_deal=0,
            is_showdown=False,
            per_player_cards_to_deal=1,
            is_up_card=True,
        ),
        poker_types.FOURTH_STREET: PhaseTransition(
            next_phase=poker_types.FIFTH_STREET,
            community_cards_to_deal=0,
            is_showdown=False,
            per_player_cards_to_deal=1,
            is_up_card=True,
        ),
        poker_types.FIFTH_STREET: PhaseTransition(
            next_phase=poker_types.SIXTH_STREET,
            community_cards_to_deal=0,
            is_showdown=False,
            per_player_cards_to_deal=1,
            is_up_card=True,
        ),
        poker_types.SIXTH_STREET: PhaseTransition(
            next_phase=poker_types.SEVENTH_STREET,
            community_cards_to_deal=0,
            is_showdown=False,
            per_player_cards_to_deal=1,
            is_up_card=False,
        ),
        poker_types.SEVENTH_STREET: PhaseTransition(
            next_phase=poker_types.SHOWDOWN,
            community_cards_to_deal=0,
            is_showdown=True,
            per_player_cards_to_deal=0,
            is_up_card=False,
        ),
    }

    @property
    def hole_card_count(self) -> int:
        # 2 down cards on initial deal — the third card is the door
        # (up-card). Total down at showdown is 3 (two from 3rd street +
        # 7th street).
        return 2

    @property
    def initial_deal_count(self) -> int:
        # Two down + one up = 3 cards before betting begins on 3rd street.
        return 3

    @property
    def total_card_count(self) -> int:
        return 7

    @property
    def has_community_cards(self) -> bool:
        return False

    @property
    def forced_bet_type(self) -> str:
        return "ANTE_AND_BRINGIN"

    @property
    def phases(self) -> list:
        return [
            poker_types.THIRD_STREET,
            poker_types.FOURTH_STREET,
            poker_types.FIFTH_STREET,
            poker_types.SIXTH_STREET,
            poker_types.SEVENTH_STREET,
            poker_types.SHOWDOWN,
        ]

    def get_next_phase(self, current_phase: int) -> Optional[PhaseTransition]:
        return self._PHASE_TRANSITIONS.get(current_phase)

    def determine_bring_in(self, door_cards: list) -> int:
        """Return the index of the bring-in player among ``door_cards``
        (the visible up-card each player holds after the initial deal).
        Stud Hi: lowest by rank-then-suit. Razz: highest by rank-then-suit."""
        return min(range(len(door_cards)), key=lambda i: _card_low_key(door_cards[i]))

    def determine_first_to_act(self, up_cards_by_player: dict) -> bytes:
        """Return the player_root who acts first based on up-cards.
        Stud Hi: highest hand showing (TDA RP-10D tiebreak by suit when
        equal). Razz overrides for low-hand-showing."""
        return max(
            up_cards_by_player.keys(),
            key=lambda p: _showing_hand_high_key(up_cards_by_player[p]),
        )


class SevenCardStudRules(StudRulesBase):
    """Seven Card Stud (high-only). Standard 5-of-7 evaluator for
    showdown, low-card-by-suit bring-in, high-hand-showing first-to-act."""

    @property
    def variant(self) -> int:
        return poker_types.SEVEN_CARD_STUD

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        # Stud has no community cards; the player's full 7 are passed in
        # ``hole_cards``. We accept either a 7-card list directly or a
        # split (hole + extra) for symmetry with the GameRules contract.
        all_cards = list(hole_cards) + list(community_cards)
        evaluator = TexasHoldemRules()
        return evaluator._find_best_hand(all_cards)


class RazzRules(StudRulesBase):
    """Razz — A-2-3-4-5 wheel is the best possible hand. No straights or
    flushes. High-card-by-suit bring-in, low-hand-showing first-to-act."""

    @property
    def variant(self) -> int:
        return poker_types.RAZZ

    def determine_bring_in(self, door_cards: list) -> int:
        # WSOP §Seven Card Razz: "the high card, with the king of spades
        # being the highest card by rank and suit, is required to make
        # the forced bet on the first round." In Razz aces play LOW, so
        # the King is the highest rank for bring-in selection (NOT the
        # Ace). Convert ace=14 → 1 before taking max.
        def _razz_high_key(card: tuple) -> tuple:
            suit, rank = card
            adjusted = 1 if rank == 14 else rank
            return (adjusted, _SUIT_RANK[suit])

        return max(range(len(door_cards)), key=lambda i: _razz_high_key(door_cards[i]))

    def determine_first_to_act(self, up_cards_by_player: dict) -> bytes:
        # Razz: low hand showing acts first. Compare by best-low key —
        # convert each player's up-cards into a low ordering and pick
        # the smallest tuple.
        def _low_show_key(cards: list) -> tuple:
            low_ranks = sorted(
                [1 if rank == 14 else rank for _, rank in cards], reverse=True
            )
            top_card_suit = _SUIT_RANK[
                min(cards, key=lambda c: (1 if c[1] == 14 else c[1]))[0]
            ]
            return (tuple(low_ranks), -top_card_suit)

        return min(
            up_cards_by_player.keys(),
            key=lambda p: _low_show_key(up_cards_by_player[p]),
        )

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        all_cards = list(hole_cards) + list(community_cards)
        result = _best_razz_low(all_cards)
        if result is None:
            # Defensive — should never happen for 7 cards.
            return (poker_types.HAND_RANK_UNSPECIFIED, 0, [])
        razz_value, razz_label, top_to_bottom = result
        # Reuse HandRanking shape: rank_type holds a sentinel
        # (HIGH_CARD), score is the inverse-encoded razz_value (lower
        # razz_value = better → higher score), kickers are the top-to-
        # bottom rank list for tiebreak inspection.
        return (razz_label, razz_value, list(top_to_bottom))


class StudHiLoRules(StudRulesBase):
    """Stud Hi/Lo (8-or-better). Pot is split between best high hand and
    best qualifying low; same bring-in / first-to-act mechanics as Stud Hi
    (per WSOP/TDA — Razz is the only stud variant that flips bring-in to
    high-by-suit)."""

    @property
    def variant(self) -> int:
        return poker_types.STUD_HI_LO_8B

    def evaluate_hand(self, hole_cards: list, community_cards: list) -> tuple:
        all_cards = list(hole_cards) + list(community_cards)
        evaluator = TexasHoldemRules()
        return evaluator._find_best_hand(all_cards)

    def evaluate_low(self, hole_cards: list, community_cards: list) -> Optional[list]:
        """Return the best 5-card qualifying low (top-to-bottom rank
        list) or None when no qualifying low exists. Aces count as 1."""
        return _has_qualifying_low(list(hole_cards) + list(community_cards))


# Dispatch table for game rules factory - avoids if/elif chain
_GAME_RULES_REGISTRY: dict[int, type[GameRules]] = {
    poker_types.TEXAS_HOLDEM: TexasHoldemRules,
    poker_types.OMAHA: OmahaRules,
    poker_types.FIVE_CARD_DRAW: FiveCardDrawRules,
    poker_types.SEVEN_CARD_STUD: SevenCardStudRules,
    poker_types.RAZZ: RazzRules,
    poker_types.STUD_HI_LO_8B: StudHiLoRules,
}


def get_game_rules(variant: int) -> GameRules:
    """Factory function to get rules for a game variant."""
    rules_class = _GAME_RULES_REGISTRY.get(variant, TexasHoldemRules)
    return rules_class()
