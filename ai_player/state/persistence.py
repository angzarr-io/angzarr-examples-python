"""Database persistence for experience replay and opponent profiles."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from ai_player.db.schema import Base, ExperienceReplay, PlayerProfile, HandHistory

if TYPE_CHECKING:
    from ai_player.proto.examples import ai_player_pb2
    from ai_player.state.session import SessionState

logger = structlog.get_logger()


class ExperienceStore:
    """Store for experience replay data used in training."""

    def __init__(self, database_url: str) -> None:
        """Initialize experience store with database connection.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self._engine = create_engine(database_url)
        Base.metadata.create_all(self._engine)
        logger.info("experience_store_initialized")

    def store(self, experience: ai_player_pb2.Experience) -> int:
        """Store an experience record.

        Args:
            experience: Experience proto message.

        Returns:
            ID of the stored experience.
        """
        with Session(self._engine) as session:
            record = ExperienceReplay(
                hand_id=experience.context.hand_id,
                context_json=self._serialize_context(experience.context),
                action=experience.action_taken,
                amount=experience.amount,
                log_prob=experience.log_prob,
                value_estimate=experience.value_estimate,
                reward=experience.reward,
                terminal=experience.terminal,
                created_at=datetime.utcnow(),
            )
            session.add(record)
            session.commit()
            return record.id

    def _serialize_context(self, context: ai_player_pb2.ActionContext) -> str:
        """Serialize action context to JSON.

        Args:
            context: ActionContext proto message.

        Returns:
            JSON string representation.
        """
        # Convert proto to dict-like structure
        snapshot = context.snapshot
        return json.dumps({
            "session_id": context.session_id,
            "player_root": context.player_root.hex() if context.player_root else None,
            "hand_id": context.hand_id.hex() if context.hand_id else None,
            "snapshot": {
                "model_id": snapshot.model_id,
                "game_variant": snapshot.game_variant,
                "phase": snapshot.phase,
                "pot_size": snapshot.pot_size,
                "stack_size": snapshot.stack_size,
                "amount_to_call": snapshot.amount_to_call,
                "min_raise": snapshot.min_raise,
                "max_raise": snapshot.max_raise,
                "position": snapshot.position,
                "players_remaining": snapshot.players_remaining,
                "players_to_act": snapshot.players_to_act,
            },
            "events_count": len(context.events),
        })

    def count(self) -> int:
        """Count total experiences stored.

        Returns:
            Number of experience records.
        """
        with Session(self._engine) as session:
            return session.scalar(select(func.count(ExperienceReplay.id))) or 0

    def sample_batch(self, batch_size: int) -> list[ExperienceReplay]:
        """Sample a random batch of experiences for training.

        Args:
            batch_size: Number of experiences to sample.

        Returns:
            List of experience records.
        """
        with Session(self._engine) as session:
            # Use random sampling
            stmt = (
                select(ExperienceReplay)
                .order_by(func.random())
                .limit(batch_size)
            )
            return list(session.scalars(stmt))


class OpponentProfileStore:
    """Store for persistent opponent statistics."""

    def __init__(self, database_url: str) -> None:
        """Initialize opponent profile store.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self._engine = create_engine(database_url)
        Base.metadata.create_all(self._engine)
        logger.info("opponent_profile_store_initialized")

    def get_profiles(self, player_roots: list[bytes]) -> dict[bytes, dict]:
        """Get opponent profiles by player roots.

        Args:
            player_roots: List of player root identifiers.

        Returns:
            Dict mapping player_root to profile data.
        """
        if not player_roots:
            return {}

        with Session(self._engine) as session:
            stmt = select(PlayerProfile).where(
                PlayerProfile.player_root.in_(player_roots)
            )
            profiles = {}
            for profile in session.scalars(stmt):
                profiles[profile.player_root] = {
                    "total_hands": profile.total_hands,
                    "vpip": profile.vpip,
                    "pfr": profile.pfr,
                    "af": profile.af,
                    "wtsd": profile.wtsd,
                    "w_sd": profile.w_sd,
                    "avg_decision_time_ms": profile.avg_decision_time_ms,
                    "hands_since_update": 0,
                }
            return profiles

    def update_from_session(self, session_state: SessionState) -> None:
        """Update opponent profiles from session state.

        Args:
            session_state: Session with collected opponent statistics.
        """
        with Session(self._engine) as session:
            for player_root, stats in session_state.opponent_stats.items():
                # Get or create profile
                profile = session.get(PlayerProfile, player_root)
                if profile is None:
                    profile = PlayerProfile(
                        player_root=player_root,
                        total_hands=0,
                        vpip=0.0,
                        pfr=0.0,
                        af=0.0,
                        wtsd=0.0,
                        w_sd=0.0,
                    )
                    session.add(profile)

                # Update with running average
                old_hands = profile.total_hands
                new_hands = stats.hands_observed
                total_hands = old_hands + new_hands

                if total_hands > 0:
                    # Weighted average of old and new stats
                    old_weight = old_hands / total_hands
                    new_weight = new_hands / total_hands

                    profile.vpip = old_weight * profile.vpip + new_weight * stats.vpip
                    profile.pfr = old_weight * profile.pfr + new_weight * stats.pfr
                    profile.af = old_weight * profile.af + new_weight * stats.aggression_factor
                    profile.wtsd = old_weight * profile.wtsd + new_weight * stats.wtsd
                    profile.w_sd = old_weight * profile.w_sd + new_weight * stats.w_sd

                profile.total_hands = total_hands
                profile.updated_at = datetime.utcnow()

            session.commit()

    def count(self) -> int:
        """Count total profiles stored.

        Returns:
            Number of opponent profiles.
        """
        with Session(self._engine) as session:
            return session.scalar(select(func.count(PlayerProfile.player_root))) or 0


class HandHistoryStore:
    """Store for complete hand histories."""

    def __init__(self, database_url: str) -> None:
        """Initialize hand history store.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self._engine = create_engine(database_url)
        Base.metadata.create_all(self._engine)

    def store(
        self,
        hand_id: bytes,
        player_root: bytes,
        events_json: str,
        hole_cards_json: str,
        community_cards_json: str,
        result: int,
        showdown: bool,
        model_version: str,
    ) -> int:
        """Store a complete hand history.

        Args:
            hand_id: Unique hand identifier.
            player_root: AI player's root.
            events_json: JSON of all hand events.
            hole_cards_json: JSON of hole cards.
            community_cards_json: JSON of community cards.
            result: Chips won/lost.
            showdown: Whether hand went to showdown.
            model_version: Model version used.

        Returns:
            ID of stored record.
        """
        with Session(self._engine) as session:
            record = HandHistory(
                hand_id=hand_id,
                ai_player_root=player_root,
                events_json=events_json,
                hole_cards_json=hole_cards_json,
                community_cards_json=community_cards_json,
                result=result,
                showdown=showdown,
                model_version=model_version,
                created_at=datetime.utcnow(),
            )
            session.add(record)
            session.commit()
            return record.id
