"""PyTorch neural network for poker decision making."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

if TYPE_CHECKING:
    from numpy.typing import NDArray


class PokerNet(nn.Module):
    """Actor-Critic network for poker decision making.

    Architecture:
    - Shared feature extractor (MLP)
    - Policy head (action probabilities)
    - Value head (state value estimate)
    - Bet sizing head (continuous output for raise amounts)
    """

    # Input features (must match encoder output)
    INPUT_DIM = 256

    # Action space: fold, check/call, bet/raise
    NUM_ACTIONS = 3

    def __init__(
        self,
        hidden_dim: int = 256,
        num_layers: int = 3,
        device: str = "cpu",
    ) -> None:
        """Initialize the network.

        Args:
            hidden_dim: Hidden layer dimension.
            num_layers: Number of hidden layers in feature extractor.
            device: Device to run on ('cpu' or 'cuda').
        """
        super().__init__()
        self._device = device
        self._version = "random"  # Will be set when loading trained weights

        # Feature extractor
        layers = []
        in_dim = self.INPUT_DIM
        for _ in range(num_layers):
            layers.extend([
                nn.Linear(in_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
            ])
            in_dim = hidden_dim
        self.features = nn.Sequential(*layers)

        # Policy head (action logits)
        self.policy_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, self.NUM_ACTIONS),
        )

        # Value head (state value)
        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

        # Bet sizing head (fraction of pot to bet)
        self.bet_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
            nn.Sigmoid(),  # Output [0, 1] for bet fraction
        )

        self.to(device)

    @property
    def version(self) -> str:
        """Model version string."""
        return self._version

    def forward(
        self,
        x: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            x: Input tensor of shape (batch, INPUT_DIM).

        Returns:
            Tuple of (action_logits, value, bet_fraction).
        """
        features = self.features(x)
        action_logits = self.policy_head(features)
        value = self.value_head(features)
        bet_fraction = self.bet_head(features)
        return action_logits, value.squeeze(-1), bet_fraction.squeeze(-1)

    def predict(
        self,
        state: NDArray[np.float32],
    ) -> tuple[int, int, list[float], float]:
        """Predict action for a single state.

        Args:
            state: State tensor from encoder.

        Returns:
            Tuple of (action, amount, probabilities, value).
        """
        # Convert to tensor
        x = torch.tensor(state, dtype=torch.float32, device=self._device)
        if x.dim() == 1:
            x = x.unsqueeze(0)

        with torch.no_grad():
            logits, value, bet_fraction = self.forward(x)

            # Get action probabilities
            probs = F.softmax(logits, dim=-1)

            # Sample action (or argmax for inference)
            action = torch.argmax(probs, dim=-1).item()

            # Calculate bet amount (placeholder - needs pot/stack from state)
            # For now, return bet_fraction as-is; caller maps to actual amount
            bet_frac = bet_fraction.item()

        # Convert action index to proto ActionType
        # 0=fold, 1=check/call, 2=bet/raise
        action_mapping = {0: 1, 1: 2, 2: 4}  # Maps to poker_types_pb2.FOLD, CHECK, BET
        proto_action = action_mapping.get(action, 1)

        # Amount is placeholder - will be calculated by caller based on context
        amount = int(bet_frac * 100)  # Placeholder

        return (
            proto_action,
            amount,
            probs[0].tolist(),
            value.item(),
        )

    @classmethod
    def load(cls, path: str | Path, device: str = "cpu") -> PokerNet:
        """Load model from checkpoint.

        Args:
            path: Path to checkpoint file.
            device: Device to load to.

        Returns:
            Loaded model.

        Raises:
            FileNotFoundError: If checkpoint doesn't exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model checkpoint not found: {path}")

        checkpoint = torch.load(path, map_location=device, weights_only=True)

        # Extract config from checkpoint or use defaults
        config = checkpoint.get("config", {})
        model = cls(
            hidden_dim=config.get("hidden_dim", 256),
            num_layers=config.get("num_layers", 3),
            device=device,
        )

        model.load_state_dict(checkpoint["model_state_dict"])
        model._version = checkpoint.get("version", path.stem)
        model.eval()

        return model

    def save(self, path: str | Path, version: str | None = None) -> None:
        """Save model checkpoint.

        Args:
            path: Path to save checkpoint.
            version: Optional version string.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "model_state_dict": self.state_dict(),
            "version": version or self._version,
            "config": {
                "hidden_dim": self.features[0].out_features,
                "num_layers": len([m for m in self.features if isinstance(m, nn.Linear)]),
            },
        }

        torch.save(checkpoint, path)
