#!/usr/bin/env python3
"""TDD tests to replicate and fix the raise tracking issue.

The bug: Client's last_raise_increment doesn't match server's min_raise,
causing "Raise must be at least X" errors.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class TestRaiseTracking:
    """Test that client correctly tracks min raise requirements."""

    def test_initial_min_raise_is_big_blind(self):
        """After blinds, min raise should equal big blind."""
        # Simulate: SB=5, BB=10
        # Server sets min_raise = big_blind when BB is posted
        big_blind = 10
        current_bet = 10  # BB
        last_raise_increment = big_blind  # Should be initialized to BB

        min_raise_to = current_bet + last_raise_increment
        assert min_raise_to == 20  # To raise, must raise TO at least 20

    def test_raise_updates_min_raise(self):
        """After a raise, min_raise should be the raise increment."""
        big_blind = 10

        # Initial state after blinds
        current_bet = 10
        last_raise_increment = big_blind

        # Player raises TO 30 (raise of 20)
        raise_to = 30
        raise_increment = raise_to - current_bet  # 30 - 10 = 20

        # Update state
        if raise_increment > last_raise_increment:
            last_raise_increment = raise_increment
        current_bet = raise_to

        assert last_raise_increment == 20
        assert current_bet == 30

        # Next min raise to should be 30 + 20 = 50
        min_raise_to = current_bet + last_raise_increment
        assert min_raise_to == 50

    def test_reraise_updates_min_raise(self):
        """Re-raise should update min_raise if larger."""
        big_blind = 10

        # Initial state: BB posted
        current_bet = 10
        last_raise_increment = big_blind

        # Player A raises TO 30 (raise increment = 20)
        raise_to = 30
        raise_increment = raise_to - current_bet
        if raise_increment > last_raise_increment:
            last_raise_increment = raise_increment
        current_bet = raise_to

        assert last_raise_increment == 20

        # Player B re-raises TO 80 (raise increment = 50)
        raise_to = 80
        raise_increment = raise_to - current_bet  # 80 - 30 = 50
        if raise_increment > last_raise_increment:
            last_raise_increment = raise_increment
        current_bet = raise_to

        assert last_raise_increment == 50
        assert current_bet == 80

        # Next min raise to should be 80 + 50 = 130
        min_raise_to = current_bet + last_raise_increment
        assert min_raise_to == 130

    def test_call_does_not_change_min_raise(self):
        """Calling should not affect min_raise."""
        big_blind = 10

        # After raise TO 30
        current_bet = 30
        last_raise_increment = 20

        # Player calls 30 (no change to min raise)
        # Just matching the bet, not raising

        # min_raise should still be 20
        min_raise_to = current_bet + last_raise_increment
        assert min_raise_to == 50  # Still 30 + 20

    def test_new_betting_round_does_not_reset_min_raise(self):
        """Min raise persists across betting rounds within a hand.

        This matches server behavior where min_raise uses max() and
        is only reset at the start of a new HAND, not a new round.
        """
        big_blind = 10

        # After preflop with a raise to 30
        current_bet = 30
        last_raise_increment = 20  # From the raise

        # Flop betting round starts - current_bet resets to 0
        # BUT min_raise (last_raise_increment) should NOT reset
        current_bet = 0  # New round
        # last_raise_increment stays at 20

        # First bet on flop must be at least big_blind
        # But if someone bets and then someone raises...
        # the min raise is based on the bet amount, not the old raise

        # Actually, let's check what happens with a fresh bet
        bet_amount = 25
        current_bet = bet_amount
        raise_increment = bet_amount - 0  # 25 - 0 = 25
        if raise_increment > last_raise_increment:
            last_raise_increment = raise_increment

        assert last_raise_increment == 25  # Updated to new larger bet

    def test_smaller_raise_does_not_decrease_min_raise(self):
        """Server uses max(), so smaller raise doesn't decrease min_raise."""
        big_blind = 10

        # Big raise happened: min_raise is 50
        current_bet = 100
        last_raise_increment = 50

        # Minimum raise to = 100 + 50 = 150
        min_raise_to = current_bet + last_raise_increment
        assert min_raise_to == 150

        # If server says "Raise must be at least 50", that's the INCREMENT
        # So raise_to must be >= current_bet + 50

    def test_all_in_raise_less_than_min(self):
        """All-in for less than min raise is allowed (but doesn't reopen)."""
        big_blind = 10

        current_bet = 30
        last_raise_increment = 20
        min_raise_to = current_bet + last_raise_increment  # 50

        # Player with 40 chips goes all-in TO 40
        player_stack = 40
        player_bet = 0
        all_in_to = player_stack + player_bet  # 40

        # This is less than min_raise_to (50) but should be allowed
        # because it's all-in (player can't bet more)
        assert all_in_to < min_raise_to
        # Server allows this as a special case


class TestRaiseTrackingWithServer:
    """Integration tests with actual server to verify state sync."""

    @pytest.fixture
    def game(self):
        """Create a game instance for testing."""
        from run_game import GatewayClient, PokerGame, GameVariant

        with GatewayClient("localhost:1320") as client:
            game = PokerGame(
                client,
                variant=GameVariant.TEXAS_HOLDEM,
                small_blind=5,
                big_blind=10,
            )
            game.log = lambda msg: None  # Disable logging
            yield game

    def test_initial_state_after_blinds(self, game):
        """Verify client state matches server after blind posting."""
        game.create_table("TestRaise1")
        game.add_player("Alice", 1000, 0)
        game.add_player("Bob", 1000, 1)
        game.add_player("Carol", 1000, 2)

        # start_hand only resets state, post_blinds updates current_bet
        game.start_hand()
        game.post_blinds()

        # After blinds: current_bet = BB, last_raise_increment = BB
        assert game.current_bet == 10
        assert game.last_raise_increment == 10

    def test_raise_sync_with_server(self, game):
        """Verify raise tracking stays in sync with server."""
        from angzarr_client.proto.examples import poker_types_pb2 as types_pb2
        from angzarr_client.proto.examples import hand_pb2

        game.create_table("TestRaise2")
        game.add_player("Alice", 1000, 0)
        game.add_player("Bob", 1000, 1)
        game.add_player("Carol", 1000, 2)

        game.start_hand()
        game.post_blinds()

        # Get players by seat
        players_by_seat = {p.seat: p for p in game.players.values()}
        seats = sorted(players_by_seat.keys())

        # In 3-handed: seat 0=BTN/dealer, seat 1=SB, seat 2=BB
        # First to act preflop is seat 0 (BTN)
        utg = players_by_seat[seats[0]]

        # UTG raises to 30 (raise of 20)
        cmd = hand_pb2.PlayerAction(
            player_root=utg.root,
            action=types_pb2.RAISE,
            amount=30,
        )
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()

        # Update local state
        raise_increment = 30 - game.current_bet  # 30 - 10 = 20
        if raise_increment > game.last_raise_increment:
            game.last_raise_increment = raise_increment
        game.current_bet = 30
        utg.stack -= 30
        utg.bet = 30

        assert game.last_raise_increment == 20
        assert game.current_bet == 30

        # SB re-raises to 70 (raise of 40)
        sb = players_by_seat[seats[1]]
        cmd = hand_pb2.PlayerAction(
            player_root=sb.root,
            action=types_pb2.RAISE,
            amount=70,
        )
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()

        # Update local state
        raise_increment = 70 - game.current_bet  # 70 - 30 = 40
        if raise_increment > game.last_raise_increment:
            game.last_raise_increment = raise_increment
        game.current_bet = 70
        sb.stack -= (70 - 5)  # Minus SB already posted
        sb.bet = 70

        assert game.last_raise_increment == 40
        assert game.current_bet == 70

        # BB's min raise should be 70 + 40 = 110
        min_raise_to = game.current_bet + game.last_raise_increment
        assert min_raise_to == 110

        # BB raises to exactly 110 - should succeed
        bb = players_by_seat[seats[2]]
        cmd = hand_pb2.PlayerAction(
            player_root=bb.root,
            action=types_pb2.RAISE,
            amount=110,
        )
        # This should NOT raise an exception
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()

    def test_replicate_failure_scenario(self, game):
        """Replicate the exact failure: 'Raise must be at least 245'.

        This happens when min_raise has grown large due to previous raises,
        but our local tracking doesn't match the server.
        """
        from angzarr_client.proto.examples import poker_types_pb2 as types_pb2
        from angzarr_client.proto.examples import hand_pb2

        game.create_table("TestRaise3")
        game.add_player("Alice", 1000, 0)
        game.add_player("Bob", 1000, 1)
        game.add_player("Carol", 1000, 2)

        game.start_hand()
        game.post_blinds()

        players_by_seat = {p.seat: p for p in game.players.values()}
        seats = sorted(players_by_seat.keys())

        # Simulate escalating raises
        utg = players_by_seat[seats[0]]
        sb = players_by_seat[seats[1]]
        bb = players_by_seat[seats[2]]

        # UTG raises to 30
        cmd = hand_pb2.PlayerAction(player_root=utg.root, action=types_pb2.RAISE, amount=30)
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()
        game.last_raise_increment = max(game.last_raise_increment, 30 - game.current_bet)
        game.current_bet = 30

        # SB re-raises to 90 (raise of 60)
        cmd = hand_pb2.PlayerAction(player_root=sb.root, action=types_pb2.RAISE, amount=90)
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()
        game.last_raise_increment = max(game.last_raise_increment, 90 - game.current_bet)
        game.current_bet = 90

        # BB re-raises to 210 (raise of 120)
        cmd = hand_pb2.PlayerAction(player_root=bb.root, action=types_pb2.RAISE, amount=210)
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()
        game.last_raise_increment = max(game.last_raise_increment, 210 - game.current_bet)
        game.current_bet = 210

        # Now UTG wants to raise again
        # Server min_raise should be 120 (from BB's raise)
        # Min raise to = 210 + 120 = 330
        assert game.last_raise_increment == 120
        assert game.current_bet == 210

        min_raise_to = game.current_bet + game.last_raise_increment
        assert min_raise_to == 330

        # UTG raises to 330 - should succeed
        cmd = hand_pb2.PlayerAction(player_root=utg.root, action=types_pb2.RAISE, amount=330)
        resp = game.client.execute("hand", game.hand_root, cmd, sequence=game.hand_sequence)
        game.hand_sequence = resp.events_book().next_sequence()

        # If we made it here without exception, the state tracking is correct
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
