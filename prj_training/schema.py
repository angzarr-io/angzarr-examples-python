"""Database schema for training data projector.

Training states are materialized from hand events by the projector
and stored in PostgreSQL for efficient training data access.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for training models."""


class TrainingState(Base):
    """Materialized training state from hand events.

    Each row represents a decision point where a player took an action.
    All relevant state is denormalized for fast training reads.
    """

    __tablename__ = "training_states"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identity - hand_root + sequence uniquely identifies this decision
    hand_root = Column(String(64), nullable=False)
    sequence = Column(Integer, nullable=False)  # Event sequence within hand
    player_root = Column(LargeBinary(32), nullable=False)

    # Hole cards (encoded as integers: rank * 4 + suit, 0-51)
    hole_card_1 = Column(Integer)
    hole_card_2 = Column(Integer)

    # Community cards (up to 5, same encoding)
    community_1 = Column(Integer)
    community_2 = Column(Integer)
    community_3 = Column(Integer)
    community_4 = Column(Integer)
    community_5 = Column(Integer)

    # Betting state at decision point
    pot_size = Column(Integer, nullable=False)
    stack_size = Column(Integer, nullable=False)
    amount_to_call = Column(Integer, nullable=False)
    current_bet = Column(Integer, nullable=False)
    min_raise = Column(Integer, nullable=False)

    # Position and game state
    position = Column(Integer, nullable=False)  # 0=BTN, 1=SB, 2=BB, etc.
    phase = Column(Integer, nullable=False)  # 1=preflop, 2=flop, 3=turn, 4=river
    players_remaining = Column(Integer, nullable=False)
    players_to_act = Column(Integer, nullable=False)

    # Action taken (label for supervised learning)
    action = Column(Integer, nullable=False)  # 1=FOLD, 2=CHECK, 3=CALL, 4=BET, 5=RAISE
    amount = Column(Integer, nullable=False)

    # Outcome (updated when hand completes)
    reward = Column(Float)  # Net chips won/lost normalized by BB
    terminal = Column(Boolean, default=False)  # Last action in hand?

    # Metadata
    game_variant = Column(String(32))
    big_blind = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Ensure we don't duplicate projections
        UniqueConstraint("hand_root", "sequence", name="uq_training_state_hand_seq"),
        # Index for loading training batches
        Index("ix_training_states_reward", "reward"),
        Index("ix_training_states_created", "created_at"),
    )


class ProjectorCheckpoint(Base):
    """Tracks projector position for resumption.

    The projector uses this to know which events have been processed,
    enabling incremental projection and recovery from restarts.
    """

    __tablename__ = "projector_checkpoints"

    projector_name = Column(String(64), primary_key=True)
    domain = Column(String(32), nullable=False)
    last_hand_root = Column(String(64))
    last_sequence = Column(Integer, default=0)
    hands_projected = Column(Integer, default=0)
    states_created = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
