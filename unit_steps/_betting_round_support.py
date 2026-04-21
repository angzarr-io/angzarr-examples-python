"""Support harness for the betting-round iteration scenarios.

``BettingRoundTester`` is a simplified mirror of the ``betting_round()``
driver in ``run_game.py`` that allows injecting predetermined actions and
observing which seats the round asks to act. The gherkin scenarios under
``features/example/unit/betting_round.feature`` exercise this harness to
pin down the iteration behaviour (originally a bug repro for mid-round
fold handling).
"""

from dataclasses import dataclass

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
            return [
                s
                for s in all_seats
                if not self.players[s].folded and not self.players[s].all_in
            ]

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
                self.players[s].bet == self.current_bet for s in active
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
                if (
                    effective_last_aggressor is None
                    or current_seat == effective_last_aggressor
                ):
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
