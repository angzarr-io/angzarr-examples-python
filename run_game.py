#!/usr/bin/env python3
"""Run a poker game through the angzarr gateway.

Starts angzarr-standalone, then runs a complete poker game with 6 AI players
until one player remains.
"""

import argparse
import os
import random
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Add paths for imports
root = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "angzarr"))
sys.path.insert(0, str(root / "agg-player"))  # Contains proto/poker stubs

import grpc

from angzarr_client.proto.examples import hand_pb2, player_pb2, table_pb2
from angzarr_client.proto.examples import poker_types_pb2 as types_pb2
from client import GatewayClient, derive_root, SYNC_MODE_SIMPLE, SYNC_MODE_CASCADE

# Optional AI Player integration
try:
    from ai_player_client import AiPlayerClient, AiPlayerConfig
    AI_PLAYER_AVAILABLE = True
except ImportError:
    AI_PLAYER_AVAILABLE = False
    AiPlayerClient = None
    AiPlayerConfig = None

# Card display
SUIT_SYMBOLS = {
    types_pb2.CLUBS: "♣",
    types_pb2.DIAMONDS: "♦",
    types_pb2.HEARTS: "♥",
    types_pb2.SPADES: "♠",
}

RANK_SYMBOLS = {
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "T",
    11: "J",
    12: "Q",
    13: "K",
    14: "A",
}

HAND_NAMES = {
    types_pb2.HIGH_CARD: "High Card",
    types_pb2.PAIR: "Pair",
    types_pb2.TWO_PAIR: "Two Pair",
    types_pb2.THREE_OF_A_KIND: "Three of a Kind",
    types_pb2.STRAIGHT: "Straight",
    types_pb2.FLUSH: "Flush",
    types_pb2.FULL_HOUSE: "Full House",
    types_pb2.FOUR_OF_A_KIND: "Four of a Kind",
    types_pb2.STRAIGHT_FLUSH: "Straight Flush",
    types_pb2.ROYAL_FLUSH: "Royal Flush",
}


class GameVariant(Enum):
    TEXAS_HOLDEM = "holdem"
    FIVE_CARD_DRAW = "draw"


def card_str(card) -> str:
    """Format a card for display."""
    return f"{RANK_SYMBOLS[card.rank]}{SUIT_SYMBOLS[card.suit]}"


def cards_str(cards) -> str:
    """Format multiple cards for display."""
    return "[" + " ".join(card_str(c) for c in cards) + "]"


def chips(amount: int) -> str:
    """Format chip amount."""
    return f"${amount:,}"


@dataclass
class Player:
    """Track player state locally."""

    name: str
    root: bytes
    stack: int
    seat: int
    hole_cards: list = None
    bet: int = 0
    folded: bool = False
    all_in: bool = False
    sequence: int = 0  # Track aggregate sequence

    def __post_init__(self):
        if self.hole_cards is None:
            self.hole_cards = []


class PokerGame:
    """Manages a poker game through the angzarr gateway."""

    def __init__(
        self,
        client: GatewayClient,
        variant: GameVariant = GameVariant.TEXAS_HOLDEM,
        small_blind: int = 5,
        big_blind: int = 10,
        log_file: str = None,
        ai_player_address: str = None,
    ):
        self.client = client
        self.variant = variant
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.players: dict[int, Player] = {}
        self.table_root: bytes = None
        self.table_sequence: int = 0
        self.hand_root: bytes = None
        self.hand_sequence: int = 0
        self.hand_num: int = 0
        self.dealer_seat: int = None
        self.pot: int = 0
        self.current_bet: int = 0
        self.last_raise_increment: int = 0  # Tracks min raise size for the hand
        self.community: list = []
        self._log_file = None
        self._ai_player_address = ai_player_address
        self._ai_clients: dict[bytes, AiPlayerClient] = {}  # per-player AI clients
        # Session ID to make aggregates unique across runs
        self._session_id = uuid.uuid4().hex[:8]
        if log_file:
            self._log_file = open(log_file, "w", encoding="utf-8")
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.write(f"  ANGZARR POKER - {variant.value.upper()}\n")
            self._log_file.write(f"  Blinds: ${small_blind}/${big_blind}\n")
            self._log_file.write(f"{'=' * 60}\n\n")
            self._log_file.flush()

    def log(self, msg: str):
        """Print a game message and write to log file."""
        print(msg)
        if self._log_file:
            self._log_file.write(msg + "\n")
            self._log_file.flush()

    def close(self):
        """Close the log file."""
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    def create_table(self, name: str = "Main Table"):
        """Create the poker table."""
        # Use session ID to make table unique across runs
        table_name = f"{name.lower().replace(' ', '-')}-{self._session_id}"
        self.table_root = derive_root("table", table_name)

        variant_proto = (
            types_pb2.TEXAS_HOLDEM
            if self.variant == GameVariant.TEXAS_HOLDEM
            else types_pb2.FIVE_CARD_DRAW
        )

        cmd = table_pb2.CreateTable(
            table_name=name,
            game_variant=variant_proto,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            min_buy_in=self.big_blind * 20,
            max_buy_in=self.big_blind * 100,
            max_players=10,
            action_timeout_seconds=30,
        )

        self.log("\n┌─ COMMAND: CreateTable")
        self.log(f"│  table: {name}, variant: {self.variant.value}")
        self.log(f"│  blinds: {chips(self.small_blind)}/{chips(self.big_blind)}")

        # Use SIMPLE for read-after-write consistency (need table ID)
        resp = self.client.execute(
            "table", self.table_root, cmd, sequence=0, sync_mode=SYNC_MODE_SIMPLE
        )
        self.table_sequence = resp.events_book().next_sequence()

        self.log("└─ EVENT: TableCreated")

    def register_player(self, name: str) -> Player:
        """Register a new player."""
        # Use session ID to make player unique across runs
        player_name = f"{name.lower()}-{self._session_id}"
        root = derive_root("player", player_name)

        cmd = player_pb2.RegisterPlayer(
            display_name=name,
            email=f"{name.lower()}@example.com",
            player_type=types_pb2.AI,
        )

        self.log("\n┌─ COMMAND: RegisterPlayer")
        self.log(f"│  name: {name}")

        # SIMPLE: need sequence before DepositFunds
        resp = self.client.execute(
            "player", root, cmd, sequence=0, sync_mode=SYNC_MODE_SIMPLE
        )
        sequence = resp.events_book().next_sequence()

        self.log("└─ EVENT: PlayerRegistered")

        return Player(name=name, root=root, stack=0, seat=-1, sequence=sequence)

    def deposit_funds(self, player: Player, amount: int):
        """Deposit funds to a player's bankroll."""
        cmd = player_pb2.DepositFunds(
            amount=types_pb2.Currency(amount=amount),
        )

        self.log("\n┌─ COMMAND: DepositFunds")
        self.log(f"│  player: {player.name}, amount: {chips(amount)}")

        # Financial operation - use CASCADE for atomicity
        resp = self.client.execute(
            "player", player.root, cmd, sequence=player.sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        player.sequence = resp.events_book().next_sequence()
        player.stack = amount

        self.log("└─ EVENT: FundsDeposited")

    def join_table(self, player: Player, seat: int, buy_in: int):
        """Have a player join the table."""
        # First reserve funds
        cmd = player_pb2.ReserveFunds(
            amount=types_pb2.Currency(amount=buy_in),
            table_root=self.table_root,
        )

        self.log("\n┌─ COMMAND: ReserveFunds")
        self.log(f"│  player: {player.name}, amount: {chips(buy_in)}")

        # Financial operation - use CASCADE for atomicity
        resp = self.client.execute(
            "player", player.root, cmd, sequence=player.sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        player.sequence = resp.events_book().next_sequence()

        self.log("└─ EVENT: FundsReserved")

        # Then join table
        cmd = table_pb2.JoinTable(
            player_root=player.root,
            preferred_seat=seat,
            buy_in_amount=buy_in,
        )

        self.log("\n┌─ COMMAND: JoinTable")
        self.log(f"│  player: {player.name}, seat: {seat}")

        # SIMPLE: need sequence for subsequent table operations
        resp = self.client.execute(
            "table", self.table_root, cmd, sequence=self.table_sequence,
            sync_mode=SYNC_MODE_SIMPLE
        )
        self.table_sequence = resp.events_book().next_sequence()

        self.log("└─ EVENT: PlayerJoined")

        player.seat = seat
        player.stack = buy_in
        self.players[seat] = player

    def add_player(self, name: str, stack: int, seat: int):
        """Convenience: register, deposit, and join in one call."""
        player = self.register_player(name)
        self.deposit_funds(player, stack)
        self.join_table(player, seat, stack)

    def start_hand(self) -> bool:
        """Start a new hand. Returns False if game is over."""
        # Remove eliminated players
        eliminated = [s for s, p in self.players.items() if p.stack <= 0]
        for s in eliminated:
            self.log(f"\n   [{self.players[s].name} eliminated - no chips]")
            del self.players[s]

        if len(self.players) < 2:
            return False

        self.hand_num += 1
        self.pot = 0
        self.current_bet = 0
        self.last_raise_increment = self.big_blind  # Reset to big blind each hand
        self.community = []

        # Reset player state
        for p in self.players.values():
            p.hole_cards = []
            p.bet = 0
            p.folded = False
            p.all_in = False

        # Advance dealer
        seats = sorted(self.players.keys())
        if self.dealer_seat is None:
            self.dealer_seat = seats[0]
        else:
            idx = seats.index(self.dealer_seat) if self.dealer_seat in seats else 0
            self.dealer_seat = seats[(idx + 1) % len(seats)]

        self.log(f"\n{'=' * 60}")
        self.log(
            f"HAND #{self.hand_num} - Dealer: {self.players[self.dealer_seat].name}"
        )
        self.log(f"{'=' * 60}")

        # Create hand root - use session ID to make hand unique across runs
        self.hand_root = derive_root("hand", f"table-main-{self._session_id}-{self.hand_num}")
        self.hand_sequence = 0

        # Build player list for deal
        variant_proto = (
            types_pb2.TEXAS_HOLDEM
            if self.variant == GameVariant.TEXAS_HOLDEM
            else types_pb2.FIVE_CARD_DRAW
        )

        players_in_hand = [
            hand_pb2.PlayerInHand(
                player_root=p.root,
                position=p.seat,
                stack=p.stack,
            )
            for p in sorted(self.players.values(), key=lambda x: x.seat)
        ]

        cmd = hand_pb2.DealCards(
            table_root=self.table_root,
            hand_number=self.hand_num,
            game_variant=variant_proto,
            players=players_in_hand,
            dealer_position=self.dealer_seat,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            deck_seed=random.randbytes(32),
        )

        self.log("\n┌─ COMMAND: DealCards")
        self.log(f"│  hand: #{self.hand_num}, dealer: seat {self.dealer_seat}")

        # ASYNC: events are included in aggregate response
        resp = self.client.execute(
            "hand", self.hand_root, cmd, sequence=0
        )
        self.hand_sequence = resp.events_book().next_sequence()

        # Parse dealt cards from events
        for page in resp.events():
            event = page.proto.event
            if event.Is(hand_pb2.CardsDealt.DESCRIPTOR):
                dealt = hand_pb2.CardsDealt()
                event.Unpack(dealt)
                for pc in dealt.player_cards:
                    for p in self.players.values():
                        if p.root == pc.player_root:
                            p.hole_cards = list(pc.cards)
                            break

        self.log("└─ EVENT: CardsDealt")

        # Show hands to console
        for p in sorted(self.players.values(), key=lambda x: x.seat):
            self.log(f"   {p.name}: {cards_str(p.hole_cards)} ({chips(p.stack)})")

        return True

    def post_blinds(self):
        """Post small and big blinds."""
        seats = sorted(self.players.keys())
        dealer_idx = seats.index(self.dealer_seat)

        if len(seats) == 2:
            sb_seat = self.dealer_seat
            bb_seat = seats[(dealer_idx + 1) % len(seats)]
        else:
            sb_seat = seats[(dealer_idx + 1) % len(seats)]
            bb_seat = seats[(dealer_idx + 2) % len(seats)]

        # Post small blind
        sb_player = self.players[sb_seat]
        sb_amount = min(self.small_blind, sb_player.stack)

        cmd = hand_pb2.PostBlind(
            player_root=sb_player.root,
            blind_type="small",
            amount=sb_amount,
        )

        self.log("\n┌─ COMMAND: PostBlind (small)")
        self.log(f"│  {sb_player.name}: {chips(sb_amount)}")

        # Financial operation - use CASCADE for atomicity
        resp = self.client.execute(
            "hand", self.hand_root, cmd, sequence=self.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        self.hand_sequence = resp.events_book().next_sequence()

        sb_player.stack -= sb_amount
        sb_player.bet = sb_amount
        self.pot += sb_amount

        self.log("└─ EVENT: BlindPosted")

        # Post big blind
        bb_player = self.players[bb_seat]
        bb_amount = min(self.big_blind, bb_player.stack)

        cmd = hand_pb2.PostBlind(
            player_root=bb_player.root,
            blind_type="big",
            amount=bb_amount,
        )

        self.log("\n┌─ COMMAND: PostBlind (big)")
        self.log(f"│  {bb_player.name}: {chips(bb_amount)}")

        # Financial operation - use CASCADE for atomicity
        resp = self.client.execute(
            "hand", self.hand_root, cmd, sequence=self.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        self.hand_sequence = resp.events_book().next_sequence()

        bb_player.stack -= bb_amount
        bb_player.bet = bb_amount
        self.pot += bb_amount
        self.current_bet = bb_amount

        self.log("└─ EVENT: BlindPosted")

    def _get_or_create_ai_client(self, player: Player) -> AiPlayerClient | None:
        """Get or create AI Player client for a player."""
        if not self._ai_player_address or not AI_PLAYER_AVAILABLE:
            return None

        if player.root not in self._ai_clients:
            config = AiPlayerConfig(
                address=self._ai_player_address,
                session_id=f"game-{uuid.uuid4().hex[:8]}",
                player_root=player.root,
            )
            self._ai_clients[player.root] = AiPlayerClient(config)

        return self._ai_clients[player.root]

    def _build_snapshot(self, player: Player) -> dict:
        """Build game state snapshot for AI Player."""
        to_call = max(0, self.current_bet - player.bet)

        # Determine betting phase
        phase = 1  # PREFLOP
        if len(self.community) >= 3:
            phase = 2  # FLOP
        if len(self.community) >= 4:
            phase = 3  # TURN
        if len(self.community) >= 5:
            phase = 4  # RIVER

        # Build opponent info
        opponents = []
        for seat, p in self.players.items():
            if p.root != player.root:
                opponents.append({
                    "player_root": p.root,
                    "position": seat,
                    "stack": p.stack,
                    "bet_this_round": p.bet,
                    "folded": p.folded,
                    "all_in": p.all_in,
                })

        return {
            "game_variant": 1,  # TEXAS_HOLDEM
            "phase": phase,
            "hole_cards": [
                {"suit": c.suit, "rank": c.rank}
                for c in (player.hole_cards or [])
            ],
            "community_cards": [
                {"suit": c.suit, "rank": c.rank}
                for c in self.community
            ],
            "pot_size": self.pot,
            "stack_size": player.stack,
            "amount_to_call": to_call,
            "min_raise": self.big_blind,
            "max_raise": player.stack,
            "position": player.seat,
            "players_remaining": len([p for p in self.players.values() if not p.folded]),
            "players_to_act": len([
                p for p in self.players.values()
                if not p.folded and not p.all_in and p.bet < self.current_bet
            ]),
            "opponents": opponents,
        }

    def get_action(self, player: Player) -> tuple[types_pb2.ActionType, int]:
        """Get AI decision for a player."""
        # Try AI Player service first
        ai_client = self._get_or_create_ai_client(player)
        if ai_client and ai_client.is_connected():
            snapshot = self._build_snapshot(player)
            action, amount = ai_client.get_action(
                snapshot=snapshot,
                hand_id=self.hand_root or b"",
            )
            return action, amount

        # Fallback to simple random logic
        to_call = max(0, self.current_bet - player.bet)

        if to_call == 0:
            # Can check or bet
            if (
                random.random() < 0.2
                and player.stack >= self.big_blind
                and self.current_bet == 0
            ):
                bet_amount = min(self.big_blind * 2, player.stack)
                return types_pb2.BET, bet_amount
            return types_pb2.CHECK, 0
        elif to_call >= player.stack:
            # All-in or fold
            if random.random() < 0.4:
                return types_pb2.CALL, to_call
            return types_pb2.FOLD, 0
        else:
            # Call or fold (no raises to avoid complex validation)
            if random.random() < 0.7:
                return types_pb2.CALL, to_call
            return types_pb2.FOLD, 0

    def betting_round(self, first_to_act_seat: int, preflop: bool = False):
        """Run a betting round.

        Uses seat-based iteration (not list index) to properly handle
        players folding mid-round without skipping active players.
        """
        # All seats at the table (static reference for clockwise ordering)
        all_seats = sorted(self.players.keys())

        def get_active_seats():
            """Get currently active seats (not folded, not all-in)."""
            return [s for s in all_seats
                    if not self.players[s].folded and not self.players[s].all_in]

        def next_active_seat(current: int) -> int | None:
            """Find the next active seat clockwise from current."""
            active = get_active_seats()
            if not active:
                return None
            current_idx = all_seats.index(current)
            for i in range(1, len(all_seats) + 1):
                next_s = all_seats[(current_idx + i) % len(all_seats)]
                if next_s in active:
                    return next_s
            return None

        active = get_active_seats()
        if len(active) < 2:
            return

        # Reset bets for postflop rounds (preflop keeps blinds)
        if not preflop:
            for p in self.players.values():
                p.bet = 0
            self.current_bet = 0

        # Find starting seat
        if first_to_act_seat not in active:
            first_to_act_seat = active[0]

        current_seat = first_to_act_seat
        acted = set()
        last_aggressor = None  # Track who made the last bet/raise

        while True:
            player = self.players[current_seat]

            # Skip folded/all-in players (shouldn't happen, but be safe)
            if player.folded or player.all_in:
                current_seat = next_active_seat(current_seat)
                if current_seat is None:
                    break
                continue

            active = get_active_seats()
            if len(active) <= 1:
                break

            # Check termination: all active players have matched the current bet
            all_bets_matched = all(
                self.players[s].bet == self.current_bet
                for s in active
            )

            # Check if last aggressor is still in active seats
            # If they went all-in, they're no longer in active - treat as no aggressor
            effective_last_aggressor = (
                last_aggressor if last_aggressor in active else None
            )

            # Round ends when:
            # 1. Current player has already acted, AND
            # 2. All bets are matched, AND
            # 3. Either no one raised (or aggressor is all-in), or we've come back to the last aggressor
            if current_seat in acted and all_bets_matched:
                if effective_last_aggressor is None or current_seat == effective_last_aggressor:
                    break

            action, amount = self.get_action(player)
            to_call = max(0, self.current_bet - player.bet)

            # If nothing to call, CHECK instead of CALL
            if action == types_pb2.CALL and to_call == 0:
                action = types_pb2.CHECK
                amount = 0

            # Convert CHECK to CALL if there's a bet to call
            if action == types_pb2.CHECK and to_call > 0:
                action = types_pb2.CALL
                amount = to_call

            # Convert BET to RAISE if there's already a bet
            if action == types_pb2.BET and self.current_bet > 0:
                action = types_pb2.RAISE

            # Ensure BET amount is at least big blind and within stack
            if action == types_pb2.BET:
                # If can't afford min bet, convert to check
                if player.stack < self.big_blind:
                    if to_call == 0:
                        action = types_pb2.CHECK
                        amount = 0
                    else:
                        # Can't bet, can't check - go all-in call
                        action = types_pb2.CALL
                        amount = min(to_call, player.stack)
                else:
                    if amount < self.big_blind:
                        amount = self.big_blind
                    # Cap to stack (all-in) - use strict inequality for safety
                    if amount >= player.stack:
                        amount = player.stack

            # Ensure raise amount is valid
            if action == types_pb2.RAISE:
                # Min raise = current_bet + last_raise_increment
                min_raise_to = self.current_bet + self.last_raise_increment
                if amount < min_raise_to:
                    # If we can't make a valid raise, just call instead
                    if to_call > 0 and player.stack >= to_call:
                        action = types_pb2.CALL
                        amount = to_call
                    elif to_call == 0:
                        action = types_pb2.CHECK
                        amount = 0
                    else:
                        action = types_pb2.FOLD
                        amount = 0

            # Ensure bet/raise doesn't exceed stack (go all-in if needed)
            if action in (types_pb2.BET, types_pb2.RAISE):
                max_bet = player.stack + player.bet  # Total amount player can bet to
                if amount > max_bet:
                    amount = max_bet  # All-in
                # If all-in amount is less than min raise, convert to call/check
                min_raise_to = self.current_bet + self.last_raise_increment
                if action == types_pb2.RAISE and amount < min_raise_to:
                    if to_call > 0 and player.stack >= to_call:
                        action = types_pb2.CALL
                        amount = to_call
                    elif player.stack > 0:
                        # All-in call (short stack)
                        action = types_pb2.CALL
                        amount = player.stack
                    else:
                        action = types_pb2.FOLD
                        amount = 0

            # Ensure call doesn't exceed stack (all-in if short)
            if action == types_pb2.CALL:
                if to_call > player.stack:
                    amount = player.stack  # All-in call

            # Final safety: if RAISE but amount not significantly above current bet, convert to CALL
            # This catches edge cases where our min_raise calculation differs from server
            if action == types_pb2.RAISE:
                min_raise_to = self.current_bet + self.last_raise_increment
                # If we're not raising enough, just call
                if amount < min_raise_to:
                    if to_call > 0:
                        action = types_pb2.CALL
                        amount = min(to_call, player.stack)
                    else:
                        action = types_pb2.CHECK
                        amount = 0

            # Final sanity check - ensure we never exceed stack
            final_amount = amount
            if action == types_pb2.BET and final_amount > player.stack:
                final_amount = player.stack
            if action == types_pb2.RAISE and final_amount > player.stack + player.bet:
                final_amount = player.stack + player.bet
            if action == types_pb2.CALL and final_amount > player.stack:
                final_amount = player.stack

            cmd = hand_pb2.PlayerAction(
                player_root=player.root,
                action=action,
                amount=(
                    final_amount
                    if action in (types_pb2.CALL, types_pb2.RAISE, types_pb2.BET)
                    else 0
                ),
            )

            action_name = types_pb2.ActionType.Name(action)
            self.log("\n┌─ COMMAND: PlayerAction")
            self.log(
                f"│  {player.name}: {action_name}"
                + (f" {chips(final_amount)}" if final_amount else "")
            )

            resp = self.client.execute(
                "hand", self.hand_root, cmd, sequence=self.hand_sequence
            )
            self.hand_sequence = resp.events_book().next_sequence()

            self.log("└─ EVENT: ActionTaken")

            # Update local state
            if action == types_pb2.FOLD:
                player.folded = True
            elif action == types_pb2.CALL:
                call_amount = min(self.current_bet - player.bet, player.stack)
                player.stack -= call_amount
                player.bet += call_amount
                self.pot += call_amount
                # Mark as all-in if can't afford minimum action (big blind)
                if player.stack < self.big_blind:
                    player.all_in = True
            elif action in (types_pb2.BET, types_pb2.RAISE):
                bet_amount = amount - player.bet
                # Update last_raise_increment: the raise size above current bet
                raise_increment = amount - self.current_bet
                if raise_increment > self.last_raise_increment:
                    self.last_raise_increment = raise_increment
                player.stack -= bet_amount
                player.bet = amount
                self.pot += bet_amount
                self.current_bet = amount
                last_aggressor = current_seat
                # Mark as all-in if can't afford minimum action (big blind)
                if player.stack < self.big_blind:
                    player.all_in = True

            acted.add(current_seat)

            # Move to next active seat clockwise
            current_seat = next_active_seat(current_seat)
            if current_seat is None or len(get_active_seats()) < 2:
                break

    def deal_community(self, count: int, phase_name: str):
        """Deal community cards."""
        cmd = hand_pb2.DealCommunityCards(count=count)

        self.log(f"\n┌─ COMMAND: DealCommunityCards ({phase_name})")

        # ASYNC: events are included in aggregate response
        resp = self.client.execute(
            "hand", self.hand_root, cmd, sequence=self.hand_sequence
        )
        self.hand_sequence = resp.events_book().next_sequence()

        # Parse dealt cards
        for page in resp.events():
            event = page.proto.event
            if event.Is(hand_pb2.CommunityCardsDealt.DESCRIPTOR):
                dealt = hand_pb2.CommunityCardsDealt()
                event.Unpack(dealt)
                self.community = list(dealt.all_community_cards)

        self.log("└─ EVENT: CommunityCardsDealt")
        self.log(f"   Board: {cards_str(self.community)}")

    def showdown(self):
        """Determine winner and award pot."""
        active = [p for p in self.players.values() if not p.folded]

        if len(active) == 1:
            winner = active[0]
            self.log(f"\n   {winner.name} wins {chips(self.pot)} (others folded)")
            winner.stack += self.pot
        else:
            # For simplicity, pick random winner among active
            # In real implementation, evaluate hands
            winner = random.choice(active)
            self.log(f"\n   {winner.name} wins {chips(self.pot)}")
            winner.stack += self.pot

        # Award pot command
        cmd = hand_pb2.AwardPot(
            awards=[
                hand_pb2.PotAward(
                    player_root=winner.root,
                    amount=self.pot,
                    pot_type="main",
                )
            ]
        )

        self.log("\n┌─ COMMAND: AwardPot")
        self.log(f"│  {winner.name}: {chips(self.pot)}")

        # Financial operation - use CASCADE for atomicity
        resp = self.client.execute(
            "hand", self.hand_root, cmd, sequence=self.hand_sequence,
            sync_mode=SYNC_MODE_CASCADE
        )
        self.hand_sequence = resp.events_book().next_sequence()

        self.log("└─ EVENT: PotAwarded")

    def play_hand(self):
        """Play a complete hand."""
        if not self.start_hand():
            return False

        self.post_blinds()

        # Determine first to act
        seats = sorted(self.players.keys())
        dealer_idx = seats.index(self.dealer_seat)

        if len(seats) == 2:
            first_preflop = self.dealer_seat  # Heads up: dealer acts first preflop
        else:
            first_preflop = seats[(dealer_idx + 3) % len(seats)]  # UTG

        # Preflop betting
        self.log("\n--- PREFLOP ---")
        self.betting_round(first_preflop, preflop=True)

        # Check if hand is over (all but one folded)
        active = [p for p in self.players.values() if not p.folded]
        if len(active) == 1:
            self.showdown()
            return True

        if self.variant == GameVariant.TEXAS_HOLDEM:
            # Flop
            self.deal_community(3, "FLOP")
            self.log("\n--- FLOP ---")
            first_postflop = seats[(dealer_idx + 1) % len(seats)]
            self.betting_round(first_postflop)

            active = [p for p in self.players.values() if not p.folded]
            if len(active) == 1:
                self.showdown()
                return True

            # Turn
            self.deal_community(1, "TURN")
            self.log("\n--- TURN ---")
            self.betting_round(first_postflop)

            active = [p for p in self.players.values() if not p.folded]
            if len(active) == 1:
                self.showdown()
                return True

            # River
            self.deal_community(1, "RIVER")
            self.log("\n--- RIVER ---")
            self.betting_round(first_postflop)

        self.showdown()
        return True

    def show_standings(self):
        """Show current chip counts."""
        self.log("\n--- STANDINGS ---")
        for p in sorted(self.players.values(), key=lambda x: -x.stack):
            self.log(f"   {p.name}: {chips(p.stack)}")

    def play_tournament(self, max_hands: int = 100):
        """Play until one player remains or max hands reached."""
        hands_played = 0
        while len(self.players) > 1 and hands_played < max_hands:
            self.play_hand()
            self.show_standings()
            hands_played += 1
            time.sleep(0.1)  # Brief pause between hands

        if len(self.players) == 1:
            winner = list(self.players.values())[0]
            self.log(f"\n{'=' * 60}")
            self.log(f"TOURNAMENT WINNER: {winner.name} with {chips(winner.stack)}")
            self.log(f"{'=' * 60}")
        else:
            self.log(f"\n{'=' * 60}")
            self.log(f"Tournament ended after {max_hands} hands")
            self.log(f"{'=' * 60}")


def start_standalone() -> subprocess.Popen:
    """Start angzarr-standalone in the background."""
    # Kill any existing processes from previous runs
    subprocess.run(["pkill", "-9", "-f", "angzarr-standalone"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "agg-player"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "agg-table"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "agg-hand"], capture_output=True)
    time.sleep(0.5)  # Let processes fully terminate

    # Clean up old sockets
    for sock in Path("tmp").glob("*.sock"):
        sock.unlink()

    # Clean up SQLite databases for fresh start
    for db_file in Path("data").glob("*.db*"):
        db_file.unlink()

    env = os.environ.copy()
    env["ANGZARR_CONFIG"] = "standalone.yaml"

    proc = subprocess.Popen(
        ["./bin/angzarr-standalone"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for gateway to be ready (5s for aggregates + projector)
    print("Starting angzarr-standalone...")
    time.sleep(5)

    return proc


def main():
    parser = argparse.ArgumentParser(description="Run a poker game")
    parser.add_argument(
        "--variant",
        choices=["holdem", "draw"],
        default="holdem",
        help="Game variant (default: holdem)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=6,
        help="Number of players (default: 6)",
    )
    parser.add_argument(
        "--stack",
        type=int,
        default=1000,
        help="Starting stack per player (default: 1000)",
    )
    parser.add_argument(
        "--max-hands",
        type=int,
        default=100,
        help="Maximum hands to play (default: 100)",
    )
    parser.add_argument(
        "--no-standalone",
        action="store_true",
        help="Don't start standalone (assume it's already running)",
    )
    parser.add_argument(
        "--ai-player",
        type=str,
        default=None,
        help="AI Player gRPC service address (e.g., localhost:50500)",
    )
    args = parser.parse_args()

    proc = None
    if not args.no_standalone:
        proc = start_standalone()

    try:
        variant = (
            GameVariant.TEXAS_HOLDEM
            if args.variant == "holdem"
            else GameVariant.FIVE_CARD_DRAW
        )

        with GatewayClient("localhost:9084") as client:
            game = PokerGame(
                client,
                variant=variant,
                ai_player_address=args.ai_player,
            )

            # Setup
            game.create_table("Main Table")

            names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"]
            for i in range(min(args.players, len(names))):
                game.add_player(names[i], args.stack, i)

            # Play
            game.play_tournament(max_hands=args.max_hands)

    except KeyboardInterrupt:
        print("\nGame interrupted")
    except grpc.RpcError as e:
        print(f"\nRPC Error: {e.code()}: {e.details()}")
    finally:
        if proc:
            print("\nShutting down standalone...")
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    main()
