"""HandFlowProcessManager — orchestrates a hand through dealing, blinds, the
betting rounds, community-card streets, and showdown (event-sourced).

A process manager is stateful and event-sourced: it folds its OWN prior events
into ``HandFlowState`` (via the appliers) and reacts to triggers from the table
and hand domains, emitting the next COMMAND that drives the hand forward.

  table.HandStarted        -> own HandFlowStarted (enter DEALING, capture roster)
  hand.CardsDealt          -> PostBlind(small)            (enter BLINDS)
  hand.BlindPosted(small)  -> PostBlind(big)
  hand.BlindPosted(big)    -> open betting               (enter BETTING, UTG to act)
  hand.ActionTaken         -> advance/reopen action, or recognise round close
  hand.BettingRoundComplete-> DealCommunityCards / AwardPot (deal next street / showdown)

The PM keeps only the betting-relevant slice it sequences against; the hand
aggregate remains the authority on turn order and round completion (it emits
TurnAssigned / BettingRoundComplete). Each post-deal transition is recorded as a
single ``HandFlowAdvanced`` own-event carrying the post-transition state, emitted
alongside the command and a snapshot for fast-path rebuild.
"""

from __future__ import annotations

from typing import List, Optional

import angzarr_router_ffi as _az

from angzarr_poker._gen.io.angzarr.examples.v1 import hand_pb2 as _hand
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as _pt
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_poker._gen.io.angzarr.v1 import process_manager_pb2 as _pm
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t
from angzarr_poker._gen.io.angzarr.examples.v1.hand_flow_process_manager_angzarr import (
    HandFlowProcessManagerHandler,
)

# HandFlowState.phase values (mirrors the proto comment).
_AWAITING_DEAL = 0
_DEALING = 1
_BLINDS = 2
_BETTING = 3
_COMPLETE = 4
_DEALING_COMMUNITY = 5
_SHOWDOWN = 6
_DRAW = 7

_DOMAIN = "hand"


def _seat_by_position(state: _hand.HandFlowState, position: int):
    for seat in state.seats:
        if seat.position == position:
            return seat
    return None


def _seat_by_root(state: _hand.HandFlowState, root: bytes):
    for seat in state.seats:
        if seat.player_root == root:
            return seat
    return None


def _next_active(state: _hand.HandFlowState, after_position: int) -> int:
    """The next seat clockwise from ``after_position`` that can still act (not
    folded, not all-in). -1 when none remains."""
    positions = sorted(seat.position for seat in state.seats)
    n = len(positions)
    if n == 0:
        return -1
    start = 0
    for i, pos in enumerate(positions):
        if pos > after_position:
            start = i
            break
    else:
        start = 0
    for i in range(n):
        pos = positions[(start + i) % n]
        seat = _seat_by_position(state, pos)
        if seat is not None and not seat.has_folded and not seat.is_all_in:
            return pos
    return -1


def _round_complete(state: _hand.HandFlowState) -> bool:
    """A betting round closes once every contender that can still act has acted
    and matched the current bet (or everyone is all-in). A lone contender is the
    hand-end path, not a round close."""
    contenders = [s for s in state.seats if not s.has_folded]
    if len(contenders) < 2:
        return False
    actionable = [s for s in contenders if not s.is_all_in]
    return all(
        s.has_acted and s.bet_this_round == state.current_bet for s in actionable
    )


class HandFlowProcessManager:
    """Implements ``HandFlowProcessManagerHandler``."""

    # ------------------------------------------------------------------ #
    # Plumbing
    # ------------------------------------------------------------------ #

    def _seq(self, dests: Optional[_az.Destinations], domain: str) -> int:
        if dests is None:
            return 0
        seq = dests.sequence_for(domain)
        return seq if seq is not None else 0

    def _command(
        self, dests: Optional[_az.Destinations], domain: str, root: bytes, cmd
    ) -> _t.CommandBook:
        book = _t.CommandBook()
        book.cover.domain = domain
        book.cover.root.value = root
        page = book.pages.add()
        page.header.sequence = self._seq(dests, domain)
        page.command.CopyFrom(_az.pack(cmd))
        return book

    def _advanced(
        self, state: _hand.HandFlowState, commands: List[_t.CommandBook]
    ) -> _pm.ProcessManagerHandleResponse:
        """Emit a HandFlowAdvanced own-event recording ``state`` (plus a snapshot
        to augment rebuild) alongside any downstream commands."""
        resp = _pm.ProcessManagerHandleResponse()
        for book in commands:
            resp.commands.append(book)
        book = resp.process_events.add()
        book.cover.domain = _DOMAIN
        book.cover.root.value = state.hand_root
        event = _hand.HandFlowAdvanced(state=state)
        book.pages.add().event.CopyFrom(_az.pack(event))
        book.snapshot.state.CopyFrom(_az.pack(state))
        return resp

    # ------------------------------------------------------------------ #
    # Triggers (react to other domains, emit own events + next command)
    # ------------------------------------------------------------------ #

    def hand_started(
        self,
        event: _table.HandStarted,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        flow_event = _hand.HandFlowStarted(
            hand_root=event.hand_root,
            player_count=len(event.active_players),
            dealer_position=event.dealer_position,
            small_blind_position=event.small_blind_position,
            big_blind_position=event.big_blind_position,
            small_blind=event.small_blind,
            big_blind=event.big_blind,
            game_variant=event.game_variant,
            seats=[
                _hand.HandFlowSeat(
                    position=p.position,
                    player_root=p.player_root,
                    stack=p.stack,
                )
                for p in event.active_players
            ],
        )
        folded = _hand.HandFlowState()
        self.apply_hand_flow_started(folded, flow_event)

        resp = _pm.ProcessManagerHandleResponse()
        book = resp.process_events.add()
        book.cover.domain = _DOMAIN
        book.cover.root.value = event.hand_root
        book.pages.add().event.CopyFrom(_az.pack(flow_event))
        book.snapshot.state.CopyFrom(_az.pack(folded))
        return resp

    def cards_dealt(
        self,
        event: _hand.CardsDealt,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """Cards are dealt -> move to posting blinds and ask the small blind."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)
        ns.phase = _BLINDS
        ns.small_blind_posted = False
        ns.big_blind_posted = False

        commands: List[_t.CommandBook] = []
        sb = _seat_by_position(ns, ns.small_blind_position)
        if sb is not None:
            cmd = _hand.PostBlind(
                player_root=sb.player_root, blind_type="small", amount=ns.small_blind
            )
            commands.append(self._command(dests, _DOMAIN, ns.hand_root, cmd))
        return self._advanced(ns, commands)

    def blind_posted(
        self,
        event: _hand.BlindPosted,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """Small blind posted -> ask the big blind; big blind posted -> open
        betting with action under the gun."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)

        commands: List[_t.CommandBook] = []
        if event.blind_type == "small":
            ns.small_blind_posted = True
            ns.current_bet = ns.small_blind
            bb = _seat_by_position(ns, ns.big_blind_position)
            if bb is not None:
                cmd = _hand.PostBlind(
                    player_root=bb.player_root, blind_type="big", amount=ns.big_blind
                )
                commands.append(self._command(dests, _DOMAIN, ns.hand_root, cmd))
        elif event.blind_type == "big":
            ns.big_blind_posted = True
            ns.current_bet = ns.big_blind
            self._open_betting(ns)
        return self._advanced(ns, commands)

    def action_taken(
        self,
        event: _hand.ActionTaken,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """A player acts -> fold the action into the round, reopen on a raise,
        and either pass action to the next seat or recognise the round close."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)

        seat = _seat_by_root(ns, event.player_root)
        if seat is not None:
            seat.has_acted = True
            seat.stack = event.player_stack
            if event.action == _pt.FOLD:
                seat.has_folded = True
            elif event.action == _pt.ALL_IN:
                seat.is_all_in = True
                seat.bet_this_round += event.amount
            elif event.action in (_pt.CALL, _pt.BET, _pt.RAISE):
                seat.bet_this_round += event.amount

            # A bet/raise/all-in above the current level reopens the action for
            # everyone else still able to act.
            if (
                event.action
                in (
                    _pt.BET,
                    _pt.RAISE,
                    _pt.ALL_IN,
                )
                and seat.bet_this_round > ns.current_bet
            ):
                ns.current_bet = seat.bet_this_round
                for other in ns.seats:
                    if (
                        other.position != seat.position
                        and not other.has_folded
                        and not other.is_all_in
                    ):
                        other.has_acted = False

        if _round_complete(ns):
            # The round has closed; the PM leaves the betting phase. The actual
            # next-street deal is driven by the aggregate's BettingRoundComplete.
            ns.action_on = -1
            ns.phase = (
                _SHOWDOWN if ns.betting_phase == _pt.RIVER else _DEALING_COMMUNITY
            )
        else:
            after = seat.position if seat is not None else ns.action_on
            ns.action_on = _next_active(ns, after)
        return self._advanced(ns, [])

    def betting_round_complete(
        self,
        event: _hand.BettingRoundComplete,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """A street's betting closed -> deal the next community cards, or run the
        showdown and award the pot after the river."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)

        commands: List[_t.CommandBook] = []
        completed = event.completed_phase
        if completed == _pt.PREFLOP and ns.game_variant == _pt.FIVE_CARD_DRAW:
            # Draw games interpose the draw between the first and final betting
            # rounds — no community cards are dealt.
            ns.phase = _DRAW
            ns.current_bet = 0
            for seat in ns.seats:
                seat.has_drawn = False
                seat.has_acted = False
                seat.bet_this_round = 0
        elif completed == _pt.PREFLOP:
            ns.phase = _DEALING_COMMUNITY
            ns.betting_phase = _pt.FLOP
            commands.append(
                self._command(
                    dests, _DOMAIN, ns.hand_root, _hand.DealCommunityCards(count=3)
                )
            )
        elif completed == _pt.FLOP:
            ns.phase = _DEALING_COMMUNITY
            ns.betting_phase = _pt.TURN
            commands.append(
                self._command(
                    dests, _DOMAIN, ns.hand_root, _hand.DealCommunityCards(count=1)
                )
            )
        elif completed == _pt.TURN:
            ns.phase = _DEALING_COMMUNITY
            ns.betting_phase = _pt.RIVER
            commands.append(
                self._command(
                    dests, _DOMAIN, ns.hand_root, _hand.DealCommunityCards(count=1)
                )
            )
        elif completed == _pt.RIVER:
            ns.phase = _SHOWDOWN
            ns.betting_phase = _pt.SHOWDOWN
            commands.append(
                self._command(dests, _DOMAIN, ns.hand_root, self._award_pot(event))
            )
        return self._advanced(ns, commands)

    def community_cards_dealt(
        self,
        event: _hand.CommunityCardsDealt,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """New community cards -> open a fresh betting round: nothing committed
        yet, nobody has acted, no bet to face, and action on the first active seat
        to the dealer's left (post-flop order; heads-up this is the big blind)."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)
        ns.phase = _BETTING
        ns.betting_phase = event.phase
        ns.current_bet = 0
        for seat in ns.seats:
            seat.bet_this_round = 0
            seat.has_acted = False
        ns.action_on = _next_active(ns, ns.dealer_position)
        return self._advanced(ns, [])

    def draw_completed(
        self,
        event: _hand.DrawCompleted,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """A player finished drawing -> once every player still in the hand has
        drawn, open the final (post-draw) betting round."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)

        seat = _seat_by_root(ns, event.player_root)
        if seat is not None:
            seat.has_drawn = True

        drawers = [s for s in ns.seats if not s.has_folded]
        if drawers and all(s.has_drawn for s in drawers):
            ns.phase = _BETTING
            ns.betting_phase = _pt.DRAW
            ns.current_bet = 0
            for s in ns.seats:
                s.has_acted = False
                s.bet_this_round = 0
            ns.action_on = _next_active(ns, ns.dealer_position)
        return self._advanced(ns, [])

    def hand_complete(
        self,
        event: _hand.HandComplete,
        state: _hand.HandFlowState,
        dests: _az.Destinations,
    ) -> _pm.ProcessManagerHandleResponse:
        """The hand is over -> mark the flow complete. End-of-hand table cleanup
        lives in the table-sync saga, so the PM issues no further command."""
        ns = _hand.HandFlowState()
        ns.CopyFrom(state)
        ns.phase = _COMPLETE
        ns.action_on = -1
        return self._advanced(ns, [])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _open_betting(self, ns: _hand.HandFlowState) -> None:
        """Open the preflop betting round: action starts under the gun (the first
        active seat after the big blind); the posted blinds stand as the bets."""
        ns.phase = _BETTING
        ns.betting_phase = _pt.PREFLOP
        ns.action_on = _next_active(ns, ns.big_blind_position)

    def _award_pot(self, event: _hand.BettingRoundComplete) -> _hand.AwardPot:
        """Auto-award the pot, split evenly across the players still in the hand
        (a stand-in for hand evaluation, matching the reference orchestrator)."""
        survivors = [s for s in event.stacks if not s.has_folded]
        awards = []
        if survivors:
            split = event.pot_total // len(survivors)
            remainder = event.pot_total % len(survivors)
            for i, s in enumerate(survivors):
                awards.append(
                    _hand.PotAward(
                        player_root=s.player_root,
                        amount=split + (1 if i < remainder else 0),
                        pot_type="main",
                    )
                )
        return _hand.AwardPot(awards=awards)

    # ------------------------------------------------------------------ #
    # Appliers (fold own events into state; used on rebuild)
    # ------------------------------------------------------------------ #

    def apply_hand_flow_started(
        self, state: _hand.HandFlowState, event: _hand.HandFlowStarted
    ) -> None:
        state.hand_root = event.hand_root
        state.phase = _DEALING
        state.player_count = event.player_count
        state.dealer_position = event.dealer_position
        state.small_blind_position = event.small_blind_position
        state.big_blind_position = event.big_blind_position
        state.small_blind = event.small_blind
        state.big_blind = event.big_blind
        state.game_variant = event.game_variant
        del state.seats[:]
        state.seats.extend(event.seats)

    def apply_hand_flow_advanced(
        self, state: _hand.HandFlowState, event: _hand.HandFlowAdvanced
    ) -> None:
        state.CopyFrom(event.state)


_: HandFlowProcessManagerHandler = HandFlowProcessManager()
