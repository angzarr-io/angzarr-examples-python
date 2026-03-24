"""In-memory session state management for AI Player."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ai_player.proto.examples import ai_player_pb2, poker_types_pb2

logger = structlog.get_logger()


@dataclass
class LiveOpponentStats:
    """Running statistics for an opponent during a session."""

    player_root: bytes
    hands_observed: int = 0
    vpip_count: int = 0  # Voluntarily put in pot
    pfr_count: int = 0  # Pre-flop raise
    bets: int = 0
    raises: int = 0
    calls: int = 0
    folds: int = 0
    showdowns: int = 0
    showdown_wins: int = 0

    @property
    def vpip(self) -> float:
        """Voluntarily put in pot percentage."""
        if self.hands_observed == 0:
            return 0.0
        return self.vpip_count / self.hands_observed

    @property
    def pfr(self) -> float:
        """Pre-flop raise percentage."""
        if self.hands_observed == 0:
            return 0.0
        return self.pfr_count / self.hands_observed

    @property
    def aggression_factor(self) -> float:
        """Aggression factor: (bets + raises) / calls."""
        if self.calls == 0:
            return float(self.bets + self.raises) if (self.bets + self.raises) > 0 else 0.0
        return (self.bets + self.raises) / self.calls

    @property
    def wtsd(self) -> float:
        """Went to showdown percentage."""
        if self.hands_observed == 0:
            return 0.0
        return self.showdowns / self.hands_observed

    @property
    def w_sd(self) -> float:
        """Won at showdown percentage."""
        if self.showdowns == 0:
            return 0.0
        return self.showdown_wins / self.showdowns


@dataclass
class SessionState:
    """In-memory state for a single AI player session.

    This state persists across all gRPC calls for the server lifetime.
    It tracks:
    - Session metadata
    - Current hand state
    - Running opponent statistics
    - Historical actions for sequence reasoning
    """

    session_id: str
    player_root: bytes
    model_id: str = ""
    created_at: float = field(default_factory=time.time)

    # Session-level statistics
    hands_played: int = 0
    total_result: int = 0

    # Current hand state
    current_hand_id: bytes | None = None
    hole_cards: list = field(default_factory=list)
    community_cards: list = field(default_factory=list)
    pot_committed: int = 0
    position: int = 0

    # Running opponent statistics (persists across hands)
    opponent_stats: dict[bytes, LiveOpponentStats] = field(default_factory=dict)

    # Action history for current hand
    action_history: list = field(default_factory=list)

    def update_from_events(self, events: list[ai_player_pb2.HandEvent]) -> None:
        """Update session state from hand events.

        Args:
            events: List of hand events to process.
        """
        for event in events:
            self._process_event(event)

    def update_from_action_history(self, history: list) -> None:
        """Update session state from action history (from ActionRequest).

        Args:
            history: List of ActionHistory proto messages.
        """
        for action_hist in history:
            self._record_action(
                player_root=action_hist.player_root,
                action=action_hist.action,
                amount=action_hist.amount,
                phase=action_hist.phase,
            )

    def _process_event(self, event: ai_player_pb2.HandEvent) -> None:
        """Process a single hand event.

        Args:
            event: Hand event to process.
        """
        # Import proto enums
        from ai_player.proto.examples import ai_player_pb2, poker_types_pb2

        event_type = event.event_type

        if event_type == ai_player_pb2.CARDS_DEALT:
            # New hand started
            self.hole_cards = list(event.cards_dealt.cards)
            self.community_cards = []
            self.pot_committed = 0
            self.action_history = []

        elif event_type == ai_player_pb2.COMMUNITY_DEALT:
            self.community_cards.extend(event.community_dealt.cards)

        elif event_type == ai_player_pb2.ACTION_TAKEN:
            action_event = event.action_taken
            self._record_action(
                player_root=action_event.player_root,
                action=action_event.action,
                amount=action_event.amount,
                phase=action_event.phase,
            )

        elif event_type == ai_player_pb2.SHOWDOWN:
            for player_showdown in event.showdown.players:
                self._record_showdown(player_showdown.player_root)

        elif event_type == ai_player_pb2.POT_AWARDED:
            if event.pot_awarded.winner_root == self.player_root:
                self.total_result += event.pot_awarded.amount
            self.hands_played += 1

    def _record_action(
        self,
        player_root: bytes,
        action: int,
        amount: int,
        phase: int,
    ) -> None:
        """Record an action for opponent modeling.

        Args:
            player_root: Player who took the action.
            action: Action type enum value.
            amount: Amount bet/raised.
            phase: Betting phase enum value.
        """
        from ai_player.proto.examples import poker_types_pb2

        # Track own pot commitment
        if player_root == self.player_root:
            if action in (poker_types_pb2.BET, poker_types_pb2.RAISE, poker_types_pb2.CALL):
                self.pot_committed += amount
            return

        # Update opponent stats
        if player_root not in self.opponent_stats:
            self.opponent_stats[player_root] = LiveOpponentStats(player_root=player_root)

        stats = self.opponent_stats[player_root]

        if action == poker_types_pb2.FOLD:
            stats.folds += 1
        elif action == poker_types_pb2.CALL:
            stats.calls += 1
            stats.vpip_count += 1
        elif action == poker_types_pb2.BET:
            stats.bets += 1
            stats.vpip_count += 1
        elif action == poker_types_pb2.RAISE:
            stats.raises += 1
            stats.vpip_count += 1
            if phase == poker_types_pb2.PREFLOP:
                stats.pfr_count += 1
        elif action == poker_types_pb2.ALL_IN:
            stats.raises += 1
            stats.vpip_count += 1

        # Add to action history
        self.action_history.append({
            "player_root": player_root,
            "action": action,
            "amount": amount,
            "phase": phase,
        })

    def _record_showdown(self, player_root: bytes) -> None:
        """Record that a player went to showdown.

        Args:
            player_root: Player who showed cards.
        """
        if player_root in self.opponent_stats:
            self.opponent_stats[player_root].showdowns += 1

    def new_hand(self, hand_id: bytes) -> None:
        """Reset state for a new hand.

        Args:
            hand_id: ID of the new hand.
        """
        self.current_hand_id = hand_id
        self.hole_cards = []
        self.community_cards = []
        self.pot_committed = 0
        self.action_history = []

        # Increment hands observed for all tracked opponents
        for stats in self.opponent_stats.values():
            stats.hands_observed += 1


class SessionManager:
    """Manages multiple AI player sessions.

    Sessions persist for the server lifetime and are keyed by session_id.
    """

    def __init__(self) -> None:
        """Initialize empty session manager."""
        self._sessions: dict[str, SessionState] = {}

    def __len__(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)

    def get(self, session_id: str) -> SessionState | None:
        """Get session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            Session state or None if not found.
        """
        return self._sessions.get(session_id)

    def get_or_create(
        self,
        session_id: str,
        player_root: bytes,
        model_id: str = "",
    ) -> SessionState:
        """Get existing session or create new one.

        Args:
            session_id: Session identifier.
            player_root: AI player's root identifier.
            model_id: Optional model identifier.

        Returns:
            Session state (existing or newly created).
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        return self.create(session_id, player_root, model_id)

    def create(
        self,
        session_id: str,
        player_root: bytes,
        model_id: str = "",
    ) -> SessionState:
        """Create a new session.

        Args:
            session_id: Session identifier.
            player_root: AI player's root identifier.
            model_id: Optional model identifier.

        Returns:
            Newly created session state.
        """
        session = SessionState(
            session_id=session_id,
            player_root=player_root,
            model_id=model_id,
        )
        self._sessions[session_id] = session
        logger.info(
            "session_created",
            session_id=session_id,
            player_root=player_root.hex() if player_root else None,
        )
        return session

    def remove(self, session_id: str) -> SessionState | None:
        """Remove and return a session.

        Args:
            session_id: Session to remove.

        Returns:
            Removed session or None if not found.
        """
        session = self._sessions.pop(session_id, None)
        if session:
            logger.info(
                "session_removed",
                session_id=session_id,
                hands_played=session.hands_played,
                total_result=session.total_result,
            )
        return session
