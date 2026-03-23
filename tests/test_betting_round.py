"""Tests for betting round iteration logic.

This test reproduces a bug where players are skipped in betting rounds
after other players fold. The bug manifests when:
1. Multiple players fold in sequence
2. A raise is made
3. The iteration logic skips players who haven't acted yet
"""

import pytest
from dataclasses import dataclass
from typing import Optional


# Action types (mirroring poker_types_pb2)
FOLD = 1
CHECK = 2
CALL = 3
BET = 4
RAISE = 5


@dataclass
class MockPlayer:
    """Simplified player for testing betting logic."""
    name: str
    seat: int
    stack: int = 1000
    bet: int = 0
    folded: bool = False
    all_in: bool = False


class BettingRoundTester:
    """
    Extract and test the betting round iteration logic from run_game.py.
    
    This class mirrors the betting_round() method but allows us to
    inject predetermined actions and track which players are asked to act.
    """
    
    def __init__(self, players: dict[int, MockPlayer], big_blind: int = 10):
        self.players = players
        self.big_blind = big_blind
        self.current_bet = 0
        self.pot = 0
        self.actions_to_return: list[tuple[int, int]] = []  # (action, amount)
        self.action_index = 0
        self.seats_asked_to_act: list[int] = []
    
    def set_actions(self, actions: list[tuple[int, int]]):
        """Set the sequence of actions to return from get_action."""
        self.actions_to_return = actions
        self.action_index = 0
    
    def get_action(self, player: MockPlayer) -> tuple[int, int]:
        """Return the next predetermined action."""
        self.seats_asked_to_act.append(player.seat)
        if self.action_index < len(self.actions_to_return):
            action, amount = self.actions_to_return[self.action_index]
            self.action_index += 1
            return action, amount
        # Default: fold if we run out of actions
        return FOLD, 0
    
    def betting_round(self, first_to_act_seat: int, preflop: bool = False):
        """
        Run a betting round - FIXED VERSION using seat-based iteration.

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
            if action == CALL and to_call == 0:
                action = CHECK
                amount = 0

            # Convert CHECK to CALL if there's a bet to call
            if action == CHECK and to_call > 0:
                action = CALL
                amount = to_call

            # Convert BET to RAISE if there's already a bet
            if action == BET and self.current_bet > 0:
                action = RAISE

            # Ensure raise amount is valid
            if action == RAISE:
                # Min raise is the size of the last bet/raise
                min_raise_to = self.current_bet * 2  # Simplified: at least double
                if amount < min_raise_to:
                    # If we can't make a valid raise, just call instead
                    if to_call > 0 and player.stack >= to_call:
                        action = CALL
                        amount = to_call
                    elif to_call == 0:
                        action = CHECK
                        amount = 0
                    else:
                        action = FOLD
                        amount = 0

            # Ensure bet/raise doesn't exceed stack (go all-in if needed)
            if action in (BET, RAISE):
                max_bet = player.stack + player.bet  # Total amount player can bet to
                if amount > max_bet:
                    amount = max_bet  # All-in
                # If all-in amount is less than min raise, convert to call/check
                if action == RAISE and amount < self.current_bet * 2:
                    if to_call > 0 and player.stack >= to_call:
                        action = CALL
                        amount = to_call
                    elif player.stack > 0:
                        # All-in call (short stack)
                        action = CALL
                        amount = player.stack
                    else:
                        action = FOLD
                        amount = 0

            # Ensure call doesn't exceed stack (all-in if short)
            if action == CALL:
                if to_call > player.stack:
                    amount = player.stack  # All-in call

            # Update local state
            if action == FOLD:
                player.folded = True
            elif action == CALL:
                call_amount = min(self.current_bet - player.bet, player.stack)
                player.stack -= call_amount
                player.bet += call_amount
                self.pot += call_amount
                if player.stack == 0:
                    player.all_in = True
            elif action in (BET, RAISE):
                bet_amount = amount - player.bet
                player.stack -= bet_amount
                player.bet = amount
                self.pot += bet_amount
                self.current_bet = amount
                last_aggressor = current_seat
                if player.stack == 0:
                    player.all_in = True

            acted.add(current_seat)

            # Move to next active seat clockwise
            current_seat = next_active_seat(current_seat)
            if current_seat is None or len(get_active_seats()) < 2:
                break


class TestBettingRoundIteration:
    """Test that betting round iteration visits all players correctly."""
    
    def create_6_player_game(self) -> BettingRoundTester:
        """Create a 6-player game setup."""
        players = {
            0: MockPlayer("Alice", 0, stack=1000),
            1: MockPlayer("Bob", 1, stack=1000),
            2: MockPlayer("Carol", 2, stack=1000),
            3: MockPlayer("Dave", 3, stack=1000),
            4: MockPlayer("Eve", 4, stack=1000),
            5: MockPlayer("Frank", 5, stack=1000),
        }
        return BettingRoundTester(players, big_blind=10)
    
    def test_preflop_with_raise_all_players_act(self):
        """
        Test that all players get to act after a raise.
        
        Scenario from tournament2.log:
        - Dealer: Alice (seat 0)
        - SB: Bob (seat 1) posts $5
        - BB: Carol (seat 2) posts $10
        - Preflop starts at UTG (seat 3 = Dave)
        
        Actions:
        - Dave (seat 3): FOLD
        - Eve (seat 4): FOLD  
        - Frank (seat 5): RAISE to $48
        - Alice (seat 0): FOLD
        - Bob (seat 1): CALL $43  <-- BUG: Bob is skipped in buggy version!
        - Carol (seat 2): CALL $38
        - Round should end (back to raiser Frank, all bets matched)
        
        The bug causes Frank to be asked to act again before Bob.
        """
        game = self.create_6_player_game()
        
        # Set up blinds
        game.players[1].bet = 5   # Bob SB
        game.players[2].bet = 10  # Carol BB
        game.current_bet = 10
        game.pot = 15
        
        # Predetermined actions
        game.set_actions([
            (FOLD, 0),        # Dave folds
            (FOLD, 0),        # Eve folds
            (RAISE, 48),      # Frank raises to $48
            (FOLD, 0),        # Alice folds
            (CALL, 43),       # Bob calls $43 (total $48)
            (CALL, 38),       # Carol calls $38 (total $48)
        ])
        
        # UTG is seat 3 (dealer 0 + 3)
        game.betting_round(first_to_act_seat=3, preflop=True)
        
        # Check which seats were asked to act
        print(f"Seats asked to act: {game.seats_asked_to_act}")
        
        # The correct order should include Bob (seat 1) before asking Frank again
        expected_order = [3, 4, 5, 0, 1, 2]  # Dave, Eve, Frank, Alice, Bob, Carol
        
        # This test will FAIL with the current buggy code
        # because Bob (seat 1) is skipped and Frank (seat 5) is asked to act again
        assert game.seats_asked_to_act == expected_order, (
            f"Expected action order {expected_order}, "
            f"got {game.seats_asked_to_act}. "
            f"Bug: Bob (seat 1) was likely skipped!"
        )
    
    def test_preflop_with_raise_bob_must_act(self):
        """
        Simpler test: verify Bob (SB) gets to act after Frank's raise.
        
        This test specifically checks that seat 1 (Bob) appears in the
        seats_asked_to_act list after seat 5 (Frank) raises.
        """
        game = self.create_6_player_game()
        
        # Set up blinds
        game.players[1].bet = 5   # Bob SB  
        game.players[2].bet = 10  # Carol BB
        game.current_bet = 10
        game.pot = 15
        
        # Actions: Dave folds, Eve folds, Frank raises, Alice folds, then...
        game.set_actions([
            (FOLD, 0),        # Dave folds
            (FOLD, 0),        # Eve folds
            (RAISE, 48),      # Frank raises
            (FOLD, 0),        # Alice folds
            (CALL, 43),       # Bob should be asked here
            (CALL, 38),       # Carol
        ])
        
        game.betting_round(first_to_act_seat=3, preflop=True)
        
        # Get the order of non-folded actions after Frank's raise
        frank_index = game.seats_asked_to_act.index(5)  # Frank is seat 5
        seats_after_frank = game.seats_asked_to_act[frank_index + 1:]
        
        print(f"Full action order: {game.seats_asked_to_act}")
        print(f"Seats asked after Frank's raise: {seats_after_frank}")
        
        # Bob (seat 1) MUST be asked to act after Frank raises
        assert 1 in seats_after_frank, (
            f"Bob (seat 1) was not asked to act after Frank's raise! "
            f"Seats after Frank: {seats_after_frank}"
        )
    
    def test_no_repeat_asking_raiser(self):
        """
        The raiser should not be asked to act again unless someone re-raises.
        
        When Frank raises and everyone calls, Frank should NOT be asked again.
        """
        game = self.create_6_player_game()
        
        # Set up blinds
        game.players[1].bet = 5
        game.players[2].bet = 10
        game.current_bet = 10
        game.pot = 15
        
        game.set_actions([
            (FOLD, 0),        # Dave
            (FOLD, 0),        # Eve
            (RAISE, 48),      # Frank raises
            (FOLD, 0),        # Alice
            (CALL, 43),       # Bob calls
            (CALL, 38),       # Carol calls
            (FOLD, 0),        # This should NOT happen - extra in case of bug
        ])
        
        game.betting_round(first_to_act_seat=3, preflop=True)
        
        # Count how many times Frank (seat 5) was asked to act
        frank_asks = game.seats_asked_to_act.count(5)
        
        print(f"Full action order: {game.seats_asked_to_act}")
        print(f"Frank was asked {frank_asks} times")
        
        # Frank should only be asked ONCE (when he raises)
        assert frank_asks == 1, (
            f"Frank (seat 5) was asked to act {frank_asks} times! "
            f"Should only be once. Full order: {game.seats_asked_to_act}"
        )


    def test_all_in_aggressor_terminates_round(self):
        """
        Bug: When the last aggressor goes all-in, the termination condition fails.

        Scenario from tournament_50hands.log:
        - Eve raises all-in to $27 (last_aggressor = Eve)
        - Frank, Bob, Dave all call
        - Eve is now all-in, removed from active seats
        - But last_aggressor is still Eve
        - Termination check: current_seat == last_aggressor? NO (Frank != Eve)
        - Round continues forever, asking Frank repeatedly

        Fix: If last_aggressor is no longer in active seats, treat as no aggressor.
        """
        players = {
            0: MockPlayer("Bob", 0, stack=1000),
            1: MockPlayer("Dave", 1, stack=1000),
            2: MockPlayer("Eve", 2, stack=27),  # Short stack
            3: MockPlayer("Frank", 3, stack=1000),
        }
        game = BettingRoundTester(players, big_blind=10)

        # Preflop blinds
        game.players[0].bet = 5   # Bob SB
        game.players[1].bet = 10  # Dave BB
        game.current_bet = 10
        game.pot = 15

        # Eve (short stack) goes all-in, others call
        game.set_actions([
            (RAISE, 27),    # Eve raises all-in to $27
            (CALL, 27),     # Frank calls
            (CALL, 22),     # Bob calls ($27 - $5 SB)
            (CALL, 17),     # Dave calls ($27 - $10 BB)
            # Round should END here - but bug caused it to continue
        ])

        # UTG is seat 2 (Eve)
        game.betting_round(first_to_act_seat=2, preflop=True)

        print(f"Seats asked to act: {game.seats_asked_to_act}")

        # Eve, Frank, Bob, Dave - then STOP
        # Bug would cause Frank to be asked again (and again, and again...)
        expected_order = [2, 3, 0, 1]

        assert game.seats_asked_to_act == expected_order, (
            f"Expected action order {expected_order}, "
            f"got {game.seats_asked_to_act}. "
            f"Bug: Round continued after all-in aggressor's bet was called!"
        )

        # Verify Eve is all-in
        assert game.players[2].all_in, "Eve should be all-in"
        assert game.players[2].stack == 0, "Eve should have 0 chips left"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
