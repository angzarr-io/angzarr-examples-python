#!/usr/bin/env python3
"""What-if scenario generator for poker training data.

Uses angzarr editions to explore counterfactual outcomes:
- Play hands on main timeline
- At decision points, create editions to explore alternative actions
- Generate training data from all branches
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from random import randbytes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import structlog

# Add paths for imports
root = Path(__file__).parent
sys.path.insert(0, str(root))

from angzarr_client.proto.angzarr.types_pb2 import (
    Edition,
    DomainDivergence,
    SYNC_MODE_CASCADE,
)
from angzarr_client.proto.examples import hand_pb2
from angzarr_client.proto.examples import poker_types_pb2 as types_pb2
from client import GatewayClient, derive_root

logger = structlog.get_logger()

# Action types for exploration
ACTION_FOLD = types_pb2.FOLD
ACTION_CHECK = types_pb2.CHECK
ACTION_CALL = types_pb2.CALL
ACTION_BET = types_pb2.BET
ACTION_RAISE = types_pb2.RAISE


@dataclass
class DecisionPoint:
    """Represents a decision point in a hand."""
    hand_root: bytes
    sequence: int  # Sequence BEFORE this decision
    player_root: bytes
    player_name: str
    actual_action: int
    actual_amount: int
    # State info for exploring alternatives
    to_call: int
    stack: int
    pot: int
    min_raise: int
    current_bet: int = 0  # Current bet level in the round


@dataclass
class WhatIfBranch:
    """An edition branch exploring an alternative action."""
    edition_name: str
    decision_point: DecisionPoint
    action: int
    amount: int
    completed: bool = False


@dataclass
class HandState:
    """Tracks state for a hand being played."""
    hand_root: bytes
    hand_sequence: int = 0
    pot: int = 0
    current_bet: int = 0
    community_cards: list = field(default_factory=list)
    decision_points: list[DecisionPoint] = field(default_factory=list)


class WhatIfGenerator:
    """Generates what-if scenarios for poker training."""

    def __init__(
        self,
        gateway_address: str = "localhost:1320",
        exploration_rate: float = 0.5,
        max_branches_per_hand: int = 3,
    ):
        self.client = GatewayClient(gateway_address)
        self.exploration_rate = exploration_rate
        self.max_branches_per_hand = max_branches_per_hand
        self._session_id = uuid.uuid4().hex[:8]
        self._branch_counter = 0

    def close(self):
        """Close client connections."""
        self.client.close()

    def _make_edition(self, name: str, domain: str, sequence: int) -> Edition:
        """Create an edition with explicit divergence point."""
        return Edition(
            name=name,
            divergences=[DomainDivergence(domain=domain, sequence=sequence)],
        )

    def _get_alternative_actions(self, dp: DecisionPoint) -> list[tuple[int, int]]:
        """Get alternative actions to explore for a decision point.

        Returns list of (action_type, amount) tuples.
        """
        alternatives = []

        # Always consider FOLD if there's a bet to call
        if dp.to_call > 0 and dp.actual_action != ACTION_FOLD:
            alternatives.append((ACTION_FOLD, 0))

        # Consider CALL if didn't call
        if dp.to_call > 0 and dp.actual_action != ACTION_CALL and dp.stack >= dp.to_call:
            alternatives.append((ACTION_CALL, dp.to_call))

        # Consider CHECK if no bet to call
        if dp.to_call == 0 and dp.actual_action != ACTION_CHECK:
            alternatives.append((ACTION_CHECK, 0))

        # Consider RAISE/BET if stack allows
        if dp.stack > dp.to_call + dp.min_raise:
            if dp.actual_action not in (ACTION_BET, ACTION_RAISE):
                raise_amount = min(dp.min_raise * 2, dp.stack - dp.to_call)
                if dp.current_bet == 0:
                    alternatives.append((ACTION_BET, raise_amount))
                else:
                    alternatives.append((ACTION_RAISE, raise_amount))

        return alternatives

    def explore_decision_point(
        self,
        dp: DecisionPoint,
        branch_name: str,
    ) -> bool:
        """Explore an alternative action at a decision point using an edition.

        Returns True if branch was successfully created.
        """
        alternatives = self._get_alternative_actions(dp)
        if not alternatives:
            return False

        # Pick a random alternative
        action, amount = random.choice(alternatives)

        # Create edition diverging from the decision point
        edition = self._make_edition(branch_name, "hand", dp.sequence)

        logger.info(
            "exploring_alternative",
            branch=branch_name,
            player=dp.player_name,
            original_action=dp.actual_action,
            alternative_action=action,
            diverge_sequence=dp.sequence,
        )

        # Send alternative action in this edition
        cmd = hand_pb2.PlayerAction(
            player_root=dp.player_root,
            action=action,
            amount=amount,
        )

        try:
            resp = self.client.execute(
                "hand",
                dp.hand_root,
                cmd,
                sequence=dp.sequence,
                sync_mode=SYNC_MODE_CASCADE,
                edition=edition,
            )

            events_book = resp.events_book()
            if events_book is not None:
                new_seq = events_book.next_sequence()
                logger.info(
                    "branch_action_executed",
                    branch=branch_name,
                    new_sequence=new_seq,
                )
                return True
            else:
                logger.warning(
                    "branch_action_failed",
                    branch=branch_name,
                    error="No events returned",
                )
                return False

        except Exception as e:
            logger.error("branch_error", branch=branch_name, error=str(e))
            return False

    def run_hand_with_whatifs(
        self,
        hand_id: str,
        players: list[dict],
        dealer_seat: int = 0,
        small_blind: int = 5,
        big_blind: int = 10,
    ) -> tuple[HandState, list[str]]:
        """Run a hand and create what-if branches at decision points.

        Args:
            hand_id: Unique identifier for this hand
            players: List of player dicts with 'name', 'root', 'stack', 'seat'
            dealer_seat: Seat of the dealer
            small_blind: Small blind amount
            big_blind: Big blind amount

        Returns:
            Tuple of (HandState, list of edition branch names created)
        """
        hand_root = derive_root("hand", f"whatif-{self._session_id}-{hand_id}")
        state = HandState(hand_root=hand_root)
        branches_created = []

        # Build player map
        player_map = {p['seat']: p for p in players}
        seats = sorted(player_map.keys())

        # Deal cards
        variant = types_pb2.TEXAS_HOLDEM
        players_in_hand = [
            hand_pb2.PlayerInHand(
                player_root=player_map[s]['root'],
                position=s,
                stack=player_map[s]['stack'],
            )
            for s in seats
        ]

        cmd = hand_pb2.DealCards(
            table_root=b'\x00' * 16,  # Dummy table root for what-if scenarios
            hand_number=int(hand_id.split('-')[-1]) if '-' in hand_id else 1,
            game_variant=variant,
            players=players_in_hand,
            dealer_position=dealer_seat,
            small_blind=small_blind,
            big_blind=big_blind,
            deck_seed=randbytes(32),
        )

        logger.info("dealing_cards", hand_id=hand_id, players=len(players))

        resp = self.client.execute(
            "hand", hand_root, cmd,
            sequence=state.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )

        events_book = resp.events_book()
        if events_book is None:
            logger.error("deal_failed", error="No events returned")
            return state, branches_created

        state.hand_sequence = events_book.next_sequence()

        # Post blinds
        dealer_idx = seats.index(dealer_seat)
        if len(seats) == 2:
            sb_seat = dealer_seat
            bb_seat = seats[(dealer_idx + 1) % len(seats)]
        else:
            sb_seat = seats[(dealer_idx + 1) % len(seats)]
            bb_seat = seats[(dealer_idx + 2) % len(seats)]

        # Small blind
        sb_player = player_map[sb_seat]
        sb_amount = min(small_blind, sb_player['stack'])
        cmd = hand_pb2.PostBlind(
            player_root=sb_player['root'],
            blind_type="small",
            amount=sb_amount,
        )
        resp = self.client.execute(
            "hand", hand_root, cmd,
            sequence=state.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        state.hand_sequence = resp.events_book().next_sequence()
        sb_player['stack'] -= sb_amount
        sb_player['bet'] = sb_amount
        state.pot += sb_amount

        # Big blind
        bb_player = player_map[bb_seat]
        bb_amount = min(big_blind, bb_player['stack'])
        cmd = hand_pb2.PostBlind(
            player_root=bb_player['root'],
            blind_type="big",
            amount=bb_amount,
        )
        resp = self.client.execute(
            "hand", hand_root, cmd,
            sequence=state.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        state.hand_sequence = resp.events_book().next_sequence()
        bb_player['stack'] -= bb_amount
        bb_player['bet'] = bb_amount
        state.pot += bb_amount
        state.current_bet = bb_amount

        logger.info("blinds_posted", pot=state.pot)

        # Play betting rounds with what-if exploration
        for round_name in ["preflop", "flop", "turn", "river"]:
            # Deal community cards if needed
            if round_name == "flop":
                cmd = hand_pb2.DealCommunityCards(count=3)
                resp = self.client.execute(
                    "hand", hand_root, cmd,
                    sequence=state.hand_sequence,
                    sync_mode=SYNC_MODE_CASCADE
                )
                state.hand_sequence = resp.events_book().next_sequence()
                logger.info("community_dealt", round=round_name)
            elif round_name in ("turn", "river"):
                cmd = hand_pb2.DealCommunityCards(count=1)
                resp = self.client.execute(
                    "hand", hand_root, cmd,
                    sequence=state.hand_sequence,
                    sync_mode=SYNC_MODE_CASCADE
                )
                state.hand_sequence = resp.events_book().next_sequence()
                logger.info("community_dealt", round=round_name)

            # Betting round
            active_players = [p for p in player_map.values() if not p.get('folded') and p['stack'] > 0]
            if len(active_players) < 2:
                break

            # Reset bets for new round (except preflop)
            if round_name != "preflop":
                for p in player_map.values():
                    p['bet'] = 0
                state.current_bet = 0

            # Simple betting loop
            for _ in range(len(active_players) * 2):  # Max iterations
                active = [p for p in player_map.values() if not p.get('folded') and p['stack'] > 0]
                if len(active) < 2:
                    break

                for player in active:
                    if player.get('folded') or player['stack'] <= 0:
                        continue

                    to_call = max(0, state.current_bet - player.get('bet', 0))

                    # Record decision point before action
                    dp_sequence = state.hand_sequence

                    # Random action for main timeline
                    # Min raise is current_bet + big_blind (or double current bet)
                    min_raise_total = max(state.current_bet + big_blind, state.current_bet * 2)
                    can_raise = player['stack'] > to_call and (player['stack'] - to_call) >= big_blind

                    if to_call == 0:
                        # No bet to call - can check or bet
                        if random.random() < 0.2 and player['stack'] >= big_blind:
                            action = ACTION_BET
                            amount = min(big_blind * 2, player['stack'])
                        else:
                            action = ACTION_CHECK
                            amount = 0
                    elif random.random() < 0.6:
                        # Call
                        action = ACTION_CALL
                        amount = min(to_call, player['stack'])
                    elif random.random() < 0.5:
                        # Fold
                        action = ACTION_FOLD
                        amount = 0
                    elif can_raise:
                        # Raise (total amount, not increment)
                        action = ACTION_RAISE
                        raise_to = min(min_raise_total, player['stack'])
                        amount = raise_to
                    else:
                        # Can't raise, just call
                        action = ACTION_CALL
                        amount = min(to_call, player['stack'])

                    # Execute action on main timeline
                    cmd = hand_pb2.PlayerAction(
                        player_root=player['root'],
                        action=action,
                        amount=amount,
                    )

                    try:
                        resp = self.client.execute(
                            "hand", hand_root, cmd,
                            sequence=state.hand_sequence,
                            sync_mode=SYNC_MODE_CASCADE
                        )

                        events_book = resp.events_book()
                        if events_book is None:
                            logger.warning("action_failed", player=player['name'], error="No events returned")
                            continue

                        state.hand_sequence = events_book.next_sequence()
                    except Exception as e:
                        logger.warning("action_error", player=player['name'], error=str(e))
                        # Try fold instead
                        cmd = hand_pb2.PlayerAction(
                            player_root=player['root'],
                            action=ACTION_FOLD,
                            amount=0,
                        )
                        try:
                            resp = self.client.execute(
                                "hand", hand_root, cmd,
                                sequence=state.hand_sequence,
                                sync_mode=SYNC_MODE_CASCADE
                            )
                            events_book = resp.events_book()
                            if events_book:
                                state.hand_sequence = events_book.next_sequence()
                                player['folded'] = True
                        except Exception:
                            pass
                        continue

                    # Record decision point
                    dp = DecisionPoint(
                        hand_root=hand_root,
                        sequence=dp_sequence,
                        player_root=player['root'],
                        player_name=player['name'],
                        actual_action=action,
                        actual_amount=amount,
                        to_call=to_call,
                        stack=player['stack'],
                        pot=state.pot,
                        min_raise=big_blind,
                        current_bet=state.current_bet,
                    )
                    state.decision_points.append(dp)

                    # Maybe explore alternative (create what-if branch)
                    if (
                        random.random() < self.exploration_rate
                        and len(branches_created) < self.max_branches_per_hand
                    ):
                        self._branch_counter += 1
                        branch_name = f"whatif-{self._session_id}-{hand_id}-b{self._branch_counter}"

                        if self.explore_decision_point(dp, branch_name):
                            branches_created.append(branch_name)

                    # Update player state
                    if action == ACTION_FOLD:
                        player['folded'] = True
                    elif action in (ACTION_CALL, ACTION_BET, ACTION_RAISE):
                        actual_amount = min(amount if action != ACTION_CALL else to_call, player['stack'])
                        player['stack'] -= actual_amount
                        player['bet'] = player.get('bet', 0) + actual_amount
                        state.pot += actual_amount
                        if action in (ACTION_BET, ACTION_RAISE):
                            state.current_bet = player['bet']

        logger.info(
            "hand_complete",
            hand_id=hand_id,
            decision_points=len(state.decision_points),
            branches_created=len(branches_created),
        )

        return state, branches_created


def main():
    """Run what-if scenario generation."""
    parser = argparse.ArgumentParser(description="Generate what-if scenarios for poker training")
    parser.add_argument(
        "--hands", type=int, default=5,
        help="Number of hands to play (default: 5)"
    )
    parser.add_argument(
        "--players", type=int, default=4,
        help="Number of players (default: 4)"
    )
    parser.add_argument(
        "--stack", type=int, default=1000,
        help="Starting stack per player (default: 1000)"
    )
    parser.add_argument(
        "--exploration-rate", type=float, default=0.3,
        help="Probability of creating a what-if branch at each decision (default: 0.3)"
    )
    parser.add_argument(
        "--max-branches", type=int, default=5,
        help="Maximum branches per hand (default: 5)"
    )

    args = parser.parse_args()

    # Configure logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )

    logger.info(
        "starting_whatif_generation",
        hands=args.hands,
        players=args.players,
        exploration_rate=args.exploration_rate,
    )

    generator = WhatIfGenerator(
        exploration_rate=args.exploration_rate,
        max_branches_per_hand=args.max_branches,
    )

    # Create players
    player_names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank"][:args.players]
    players = []
    for i, name in enumerate(player_names):
        player_root = derive_root("player", f"whatif-player-{name.lower()}")
        players.append({
            'name': name,
            'root': player_root,
            'stack': args.stack,
            'seat': i,
            'bet': 0,
            'folded': False,
        })

    total_branches = 0
    total_decisions = 0

    try:
        for hand_num in range(1, args.hands + 1):
            # Reset player state
            for p in players:
                p['stack'] = args.stack
                p['bet'] = 0
                p['folded'] = False

            state, branches = generator.run_hand_with_whatifs(
                hand_id=f"hand-{hand_num}",
                players=players,
                dealer_seat=(hand_num - 1) % len(players),
            )

            total_branches += len(branches)
            total_decisions += len(state.decision_points)

            logger.info(
                "hand_summary",
                hand=hand_num,
                decisions=len(state.decision_points),
                branches=len(branches),
            )

    finally:
        generator.close()

    logger.info(
        "generation_complete",
        total_hands=args.hands,
        total_decisions=total_decisions,
        total_branches=total_branches,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
