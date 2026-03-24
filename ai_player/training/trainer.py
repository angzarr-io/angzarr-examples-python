"""PPO trainer for poker AI.

Uses materialized training data from the projector (training_states table)
which is derived from event logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import structlog
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from ai_player.models.poker_net import PokerNet

# Import TrainingState schema - shared with prj_training projector
import sys
from pathlib import Path

# Add parent directory to allow importing prj_training
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from prj_training.schema import TrainingState

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = structlog.get_logger()


@dataclass
class TrainerConfig:
    """Configuration for training."""

    database_url: str
    output_dir: str = "./models"
    device: str = "cpu"

    # Training hyperparameters
    batch_size: int = 64
    learning_rate: float = 3e-4
    epochs: int = 10
    clip_epsilon: float = 0.2  # PPO clip parameter
    value_coef: float = 0.5  # Value loss coefficient
    entropy_coef: float = 0.01  # Entropy bonus coefficient
    max_grad_norm: float = 0.5  # Gradient clipping

    # Model architecture
    hidden_dim: int = 256
    num_layers: int = 3

    # Data loading
    max_examples: int = 100000  # Max training examples to load


class Trainer:
    """PPO trainer for poker AI using experience replay."""

    def __init__(self, config: TrainerConfig) -> None:
        """Initialize trainer.

        Args:
            config: Training configuration.
        """
        self._config = config
        self._device = config.device
        self._model = PokerNet(
            hidden_dim=config.hidden_dim,
            num_layers=config.num_layers,
            device=config.device,
        )
        self._optimizer = torch.optim.Adam(
            self._model.parameters(),
            lr=config.learning_rate,
        )

        # Connect to database
        from sqlalchemy import create_engine
        self._engine = create_engine(config.database_url)

        self._epoch = 0
        self._total_loss_history: list[float] = []

    def load_training_data(self, limit: int | None = None) -> list[dict]:
        """Load training data from materialized training_states table.

        Args:
            limit: Maximum number of examples to load (defaults to config).

        Returns:
            List of training state dictionaries.
        """
        from sqlalchemy.orm import Session
        from sqlalchemy import select

        limit = limit or self._config.max_examples
        examples = []

        with Session(self._engine) as session:
            stmt = (
                select(TrainingState)
                .where(TrainingState.reward.isnot(None))  # Only use completed hands
                .order_by(TrainingState.id)
                .limit(limit)
            )
            for ts in session.scalars(stmt):
                examples.append({
                    "hole_cards": [ts.hole_card_1, ts.hole_card_2],
                    "community_cards": [
                        c for c in [ts.community_1, ts.community_2, ts.community_3,
                                    ts.community_4, ts.community_5] if c is not None
                    ],
                    "pot_size": ts.pot_size,
                    "stack_size": ts.stack_size,
                    "amount_to_call": ts.amount_to_call,
                    "min_raise": ts.min_raise,
                    "position": ts.position,
                    "phase": ts.phase,
                    "players_remaining": ts.players_remaining,
                    "action": ts.action,
                    "amount": ts.amount,
                    "reward": ts.reward,
                    "terminal": ts.terminal,
                })

        logger.info("training_data_loaded", count=len(examples))
        return examples

    def prepare_batch(
        self,
        examples: list[dict],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Prepare training batch from training states.

        Args:
            examples: List of training state dicts from projector.

        Returns:
            Tuple of (states, actions, rewards, terminals).
        """
        states = []
        actions = []
        rewards = []
        terminals = []

        for ex in examples:
            # Encode state to feature vector
            state = self._encode_state(ex)
            states.append(state)

            # Map action to index (FOLD=1->0, CHECK/CALL=2/3->1, BET/RAISE=4/5->2)
            action = ex["action"]
            if action == 1:  # FOLD
                action_idx = 0
            elif action in (2, 3):  # CHECK, CALL
                action_idx = 1
            else:  # BET, RAISE
                action_idx = 2
            actions.append(action_idx)

            rewards.append(ex["reward"])
            terminals.append(1.0 if ex.get("terminal") else 0.0)

        # Convert to tensors
        states_t = torch.tensor(np.array(states), dtype=torch.float32, device=self._device)
        actions_t = torch.tensor(actions, dtype=torch.long, device=self._device)
        rewards_t = torch.tensor(rewards, dtype=torch.float32, device=self._device)
        terminals_t = torch.tensor(terminals, dtype=torch.float32, device=self._device)

        return states_t, actions_t, rewards_t, terminals_t

    def _encode_state(self, example: dict) -> np.ndarray:
        """Encode training state to feature vector.

        Args:
            example: Training state dictionary from projector.

        Returns:
            Feature array of shape (INPUT_DIM,).
        """
        features = np.zeros(PokerNet.INPUT_DIM, dtype=np.float32)

        bb = 100.0  # Assume 100 chip big blind

        # Betting features (indices 0-9)
        pot = example.get("pot_size", 0)
        stack = example.get("stack_size", 0)
        to_call = example.get("amount_to_call", 0)
        min_raise = example.get("min_raise", 0)

        features[0] = pot / bb / 100.0  # Normalized pot
        features[1] = stack / bb / 100.0  # Normalized stack
        features[2] = to_call / bb / 10.0  # Normalized call amount
        features[3] = min_raise / bb / 10.0  # Normalized min raise
        features[4] = stack / bb / 100.0  # Max raise is stack (simplified)

        # Pot odds
        if pot > 0 and to_call > 0:
            features[5] = to_call / (pot + to_call)

        # Stack-to-pot ratio
        if pot > 0:
            features[6] = min(10.0, stack / pot) / 10.0

        features[7] = 1.0 if to_call == 0 else 0.0  # Check available
        features[8] = 1.0 if to_call > 0 else 0.0  # Facing bet

        # Position features (indices 10-15)
        position = example.get("position", 0)
        features[10] = position / 10.0
        features[11] = 1.0 if position == 0 else 0.0  # Button
        features[12] = 1.0 if position == 1 else 0.0  # SB
        features[13] = 1.0 if position == 2 else 0.0  # BB
        features[14] = example.get("players_remaining", 0) / 10.0

        # Phase one-hot (indices 16-19)
        phase = example.get("phase", 1)
        if 1 <= phase <= 4:
            features[15 + phase] = 1.0

        # Hole cards (indices 20-71) - one-hot encoding for each card (52 cards)
        hole_cards = example.get("hole_cards", [])
        for i, card in enumerate(hole_cards):
            if card is not None and 0 <= card < 52:
                features[20 + i * 52 + card] = 1.0

        # Community cards (indices 124-228) - one-hot encoding
        community = example.get("community_cards", [])
        for i, card in enumerate(community):
            if card is not None and 0 <= card < 52:
                features[124 + card] = 1.0  # Single bit per community card

        return features

    def train_epoch(self, examples: list[dict]) -> float:
        """Train for one epoch using behavioral cloning with value estimation.

        Args:
            examples: List of training states to train on.

        Returns:
            Average loss for the epoch.
        """
        self._model.train()

        # Prepare data
        states, actions, rewards, terminals = self.prepare_batch(examples)

        # Create dataloader
        dataset = TensorDataset(states, actions, rewards, terminals)
        dataloader = DataLoader(
            dataset,
            batch_size=self._config.batch_size,
            shuffle=True,
        )

        total_loss = 0.0
        total_policy_loss = 0.0
        total_value_loss = 0.0
        num_batches = 0

        for batch in dataloader:
            batch_states, batch_actions, batch_rewards, batch_terminals = batch

            # Forward pass
            logits, values, _ = self._model(batch_states)
            values = values.squeeze()

            # Compute policy loss (cross-entropy for imitation learning)
            # This learns to imitate the actions from the event log
            policy_loss = F.cross_entropy(logits, batch_actions)

            # Value loss - predict returns
            value_loss = F.mse_loss(values, batch_rewards)

            # Entropy bonus for exploration
            probs = F.softmax(logits, dim=-1)
            log_probs = F.log_softmax(logits, dim=-1)
            entropy = -(probs * log_probs).sum(dim=-1).mean()

            # Total loss
            loss = (
                policy_loss
                + self._config.value_coef * value_loss
                - self._config.entropy_coef * entropy
            )

            # Backward pass
            self._optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(
                self._model.parameters(),
                self._config.max_grad_norm,
            )
            self._optimizer.step()

            total_loss += loss.item()
            total_policy_loss += policy_loss.item()
            total_value_loss += value_loss.item()
            num_batches += 1

        avg_loss = total_loss / max(num_batches, 1)
        avg_policy_loss = total_policy_loss / max(num_batches, 1)
        avg_value_loss = total_value_loss / max(num_batches, 1)

        self._epoch += 1
        self._total_loss_history.append(avg_loss)

        logger.info(
            "epoch_complete",
            epoch=self._epoch,
            avg_loss=round(avg_loss, 4),
            policy_loss=round(avg_policy_loss, 4),
            value_loss=round(avg_value_loss, 4),
            num_batches=num_batches,
        )

        return avg_loss

    def train(self, epochs: int | None = None) -> None:
        """Run full training loop.

        Args:
            epochs: Number of epochs (defaults to config value).
        """
        epochs = epochs or self._config.epochs

        # Load training data from projector's materialized view
        examples = self.load_training_data()

        if len(examples) < self._config.batch_size:
            logger.warning(
                "insufficient_training_data",
                count=len(examples),
                required=self._config.batch_size,
            )
            return

        logger.info("training_started", epochs=epochs, examples=len(examples))

        for epoch in range(epochs):
            avg_loss = self.train_epoch(examples)

            # Save checkpoint every epoch
            self.save_checkpoint(f"epoch_{self._epoch}")

        logger.info(
            "training_complete",
            total_epochs=self._epoch,
            final_loss=self._total_loss_history[-1] if self._total_loss_history else 0.0,
        )

    def save_checkpoint(self, version: str) -> Path:
        """Save model checkpoint.

        Args:
            version: Version string for the checkpoint.

        Returns:
            Path to saved checkpoint.
        """
        output_dir = Path(self._config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_path = output_dir / f"poker_{version}.pt"
        self._model.save(checkpoint_path, version=version)

        # Also save as 'latest'
        latest_path = output_dir / "poker_latest.pt"
        self._model.save(latest_path, version=version)

        logger.info("checkpoint_saved", path=str(checkpoint_path))
        return checkpoint_path

    def load_checkpoint(self, path: str | Path) -> None:
        """Load model from checkpoint.

        Args:
            path: Path to checkpoint file.
        """
        self._model = PokerNet.load(path, device=self._device)
        self._optimizer = torch.optim.Adam(
            self._model.parameters(),
            lr=self._config.learning_rate,
        )
        logger.info("checkpoint_loaded", path=str(path))
