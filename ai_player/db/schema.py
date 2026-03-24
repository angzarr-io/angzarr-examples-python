"""SQLAlchemy models for AI Player database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class PlayerProfile(Base):
    """Persistent opponent statistics learned over time.

    Stores aggregate statistics for each player we've observed,
    enabling opponent modeling across sessions.
    """

    __tablename__ = "player_profiles"

    player_root = Column(LargeBinary, primary_key=True)
    total_hands = Column(Integer, default=0, nullable=False)

    # Core statistics
    vpip = Column(Float, default=0.0, nullable=False)  # Voluntarily put in pot %
    pfr = Column(Float, default=0.0, nullable=False)  # Pre-flop raise %
    af = Column(Float, default=0.0, nullable=False)  # Aggression factor
    wtsd = Column(Float, default=0.0, nullable=False)  # Went to showdown %
    w_sd = Column(Float, default=0.0, nullable=False)  # Won at showdown %

    # Timing tells
    avg_decision_time_ms = Column(Float, default=0.0, nullable=False)

    # Metadata
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExperienceReplay(Base):
    """Experience replay buffer for reinforcement learning.

    Stores (state, action, reward) tuples for training.
    """

    __tablename__ = "experience_replay"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(LargeBinary, nullable=True, index=True)
    step = Column(Integer, default=0, nullable=False)  # Action index in hand

    # Serialized ActionContext
    context_json = Column(Text, nullable=False)

    # Action taken
    action = Column(Integer, nullable=False)
    amount = Column(Integer, default=0, nullable=False)

    # Policy outputs at decision time (for PPO)
    log_prob = Column(Float, default=0.0, nullable=False)
    value_estimate = Column(Float, default=0.0, nullable=False)

    # Outcome (set after hand completes)
    reward = Column(Float, default=0.0, nullable=False)
    terminal = Column(Boolean, default=False, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HandHistory(Base):
    """Complete hand history for analysis and pattern matching."""

    __tablename__ = "hand_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(LargeBinary, unique=True, nullable=False, index=True)
    ai_player_root = Column(LargeBinary, nullable=False, index=True)

    # Serialized data
    events_json = Column(Text, nullable=False)
    hole_cards_json = Column(Text, nullable=False)
    community_cards_json = Column(Text, nullable=True)

    # Outcome
    result = Column(Integer, default=0, nullable=False)  # Chips won/lost
    showdown = Column(Boolean, default=False, nullable=False)

    # Model info
    model_version = Column(String(100), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# Optional: pgvector support for hand embeddings
# Requires: CREATE EXTENSION vector;
# class HandEmbedding(Base):
#     """Vector embeddings for situation similarity search."""
#
#     __tablename__ = "hand_embeddings"
#
#     hand_id = Column(LargeBinary, primary_key=True)
#     embedding = Column(Vector(256))  # Requires pgvector
#     situation_type = Column(String(50), nullable=True)  # "bluff", "value_bet", etc.
#     created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
