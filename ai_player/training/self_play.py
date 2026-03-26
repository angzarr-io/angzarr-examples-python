#!/usr/bin/env python3
"""Self-play training with per-player models and weight sharing.

Each player maintains their own model, learns from their own experiences,
and periodically shares weights with other players.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import structlog
import torch
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Add parent paths for imports
import sys

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

from ai_player.models.poker_net import PokerNet
from ai_player.training.trainer import Trainer, TrainerConfig
from ai_player.training.fitness_tracker import FitnessTracker, FitnessMetrics
from prj_training.schema import Base, TournamentResult, TrainingState

logger = structlog.get_logger()


class SelfPlayGame:
    """Poker game where each player uses their own neural network model."""

    def __init__(
        self,
        client,
        agent_models: dict[str, PokerNet],
        encoder,
        engine=None,
        small_blind: int = 5,
        big_blind: int = 10,
        exploration_temperature: float = 0.0,
    ):
        """Initialize self-play game.

        Args:
            client: GatewayClient for game commands.
            agent_models: Dict mapping player name to their PokerNet model.
            encoder: ActionContextEncoder for state encoding.
            engine: SQLAlchemy engine for recording training states (optional).
            small_blind: Small blind amount.
            big_blind: Big blind amount.
            exploration_temperature: Softmax temperature for action sampling (0=greedy).
        """
        self._exploration_temperature = exploration_temperature
        from run_game import PokerGame, GameVariant

        # Create base game with logging disabled
        self._base_game = PokerGame(
            client,
            variant=GameVariant.TEXAS_HOLDEM,
            small_blind=small_blind,
            big_blind=big_blind,
        )
        # Disable verbose logging
        self._base_game.log = lambda msg: None

        self._agent_models = agent_models
        self._encoder = encoder
        self._engine = engine

        # Override the get_action method
        self._base_game.get_action = self._get_model_action

        # Track states during hand for recording
        self._pending_states: list[dict] = []
        self._hand_counter = 0

    @property
    def players(self):
        return self._base_game.players

    def create_table(self, name: str):
        return self._base_game.create_table(name)

    def add_player(self, name: str, stack: int, seat: int):
        return self._base_game.add_player(name, stack, seat)

    def play_hand(self):
        """Play a hand and record training states."""
        # Track stacks before hand
        stacks_before = {p.name: p.stack for p in self._base_game.players.values()}
        self._pending_states = []
        self._hand_counter += 1

        # Play the hand
        result = self._base_game.play_hand()

        # Calculate rewards and record states
        if self._engine and self._pending_states:
            stacks_after = {p.name: p.stack for p in self._base_game.players.values()}
            self._record_hand_states(stacks_before, stacks_after)

        return result

    def _record_hand_states(self, stacks_before: dict, stacks_after: dict) -> None:
        """Record all states from the completed hand with rewards.

        Uses PostgreSQL ON CONFLICT to handle duplicates from concurrent projector.
        """
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy.orm import Session as DBSession

        bb = self._base_game.big_blind

        with DBSession(self._engine) as session:
            for state in self._pending_states:
                player_name = state["player_name"]
                before = stacks_before.get(player_name, 1000)
                after = stacks_after.get(player_name, 0)
                reward = (after - before) / bb  # Reward in BBs

                # Build values dict for upsert
                values = {
                    "hand_root": state["hand_root"],
                    "sequence": state["sequence"],
                    "player_root": state["player_root"],
                    "edition": "selfplay",
                    "hole_card_1": state.get("hole_card_1"),
                    "hole_card_2": state.get("hole_card_2"),
                    "community_1": state.get("community_1"),
                    "community_2": state.get("community_2"),
                    "community_3": state.get("community_3"),
                    "community_4": state.get("community_4"),
                    "community_5": state.get("community_5"),
                    "pot_size": state["pot_size"],
                    "stack_size": state["stack_size"],
                    "amount_to_call": state["amount_to_call"],
                    "current_bet": state["current_bet"],
                    "min_raise": state["min_raise"],
                    "position": state["position"],
                    "phase": state["phase"],
                    "players_remaining": state["players_remaining"],
                    "players_to_act": state["players_to_act"],
                    "action": state["action"],
                    "amount": state["amount"],
                    "reward": reward,
                    "terminal": state == self._pending_states[-1],
                    "game_variant": "texas_holdem",
                    "big_blind": bb,
                }

                # Use INSERT ... ON CONFLICT DO NOTHING to handle duplicates
                stmt = insert(TrainingState).values(**values).on_conflict_do_nothing(
                    index_elements=["hand_root", "sequence"]
                )
                session.execute(stmt)

            session.commit()

    def _get_model_action(self, player) -> tuple:
        """Get action from player's neural network model."""
        from angzarr_client.proto.examples import poker_types_pb2 as types_pb2

        model = self._agent_models.get(player.name)
        if model is None:
            # Fallback to random if no model
            return self._random_action(player)

        # Build state tensor from game state
        state_tensor = self._encode_game_state(player)

        # Run model inference with exploration
        action_idx, amount, probs, value = model.predict(
            state_tensor, temperature=self._exploration_temperature
        )

        game = self._base_game

        # Key betting context - "it's X to you"
        to_call = max(0, game.current_bet - player.bet)

        # The minimum raise increment (tracked by the game)
        min_raise_increment = getattr(game, 'last_raise_increment', game.big_blind)

        # Calculate minimum valid raise-to amount
        # Server requires: raise_amount >= min_raise, where raise_amount = raise_to - current_bet
        min_raise_to = game.current_bet + min_raise_increment

        # Maximum we can put in (all-in)
        max_raise_to = player.stack + player.bet

        # Map action index to proto action type
        # 0 = FOLD, 1 = CHECK/CALL, 2 = BET/RAISE
        if action_idx == 0:
            action = types_pb2.FOLD
            action_amount = 0
        elif action_idx == 1:
            if to_call == 0:
                action = types_pb2.CHECK
                action_amount = 0
            else:
                action = types_pb2.CALL
                action_amount = min(to_call, player.stack)
        else:  # action_idx == 2 - BET or RAISE
            if game.current_bet == 0:
                # Opening bet - minimum is big blind, max is stack
                bet_amount = max(game.big_blind, min(amount, player.stack))
                if bet_amount >= game.big_blind and bet_amount <= player.stack:
                    action = types_pb2.BET
                    action_amount = bet_amount
                else:
                    action = types_pb2.CHECK
                    action_amount = 0
            else:
                # Raise - compute valid raise amount
                # Actual max we can put in: our stack (chips we have) + our current bet
                actual_max = player.stack + player.bet

                # Can we make a valid raise?
                if actual_max >= min_raise_to and player.stack > to_call:
                    # Compute raise amount, clamped strictly to [min_raise_to, actual_max]
                    pot_raise = game.current_bet + game.pot
                    target_raise = min(pot_raise, actual_max)  # Don't exceed actual max
                    target_raise = max(target_raise, min_raise_to)  # At least min raise
                    target_raise = min(target_raise, actual_max)  # Double-check cap

                    action = types_pb2.RAISE
                    action_amount = int(target_raise)
                else:
                    # Can't make valid raise, just call
                    if to_call > 0:
                        action = types_pb2.CALL
                        action_amount = min(to_call, player.stack)
                    else:
                        action = types_pb2.CHECK
                        action_amount = 0

        # Record state for training (if engine configured)
        if self._engine:
            self._record_action_state(player, action, action_amount)

        return action, action_amount

    def _record_action_state(self, player, action: int, amount: int) -> None:
        """Record the current state and action for later training."""
        game = self._base_game
        hand_root = getattr(game, 'hand_root', None)

        # Encode cards
        def encode_card(card):
            if card is None:
                return None
            return (card.rank - 2) * 4 + (card.suit - 1)

        hole_cards = player.hole_cards or []
        community = game.community or []

        # Determine phase
        phase = 1  # preflop
        if len(community) >= 3:
            phase = 2  # flop
        if len(community) >= 4:
            phase = 3  # turn
        if len(community) >= 5:
            phase = 4  # river

        # Get the actual min raise increment (not just big blind)
        min_raise_increment = getattr(game, 'last_raise_increment', game.big_blind)

        state = {
            "hand_root": hand_root.hex() if hand_root else f"hand_{self._hand_counter}",
            "sequence": len(self._pending_states),
            "player_root": player.root if player.root else b"\x00" * 32,
            "player_name": player.name,
            "hole_card_1": encode_card(hole_cards[0]) if len(hole_cards) > 0 else None,
            "hole_card_2": encode_card(hole_cards[1]) if len(hole_cards) > 1 else None,
            "community_1": encode_card(community[0]) if len(community) > 0 else None,
            "community_2": encode_card(community[1]) if len(community) > 1 else None,
            "community_3": encode_card(community[2]) if len(community) > 2 else None,
            "community_4": encode_card(community[3]) if len(community) > 3 else None,
            "community_5": encode_card(community[4]) if len(community) > 4 else None,
            "pot_size": game.pot,
            "stack_size": player.stack,
            "amount_to_call": max(0, game.current_bet - player.bet),
            "current_bet": game.current_bet,
            "min_raise": min_raise_increment,  # Actual min raise, not just big blind
            "position": player.seat,
            "phase": phase,
            "players_remaining": len([p for p in game.players.values() if not p.folded]),
            "players_to_act": len([p for p in game.players.values() if not p.folded and not p.all_in]),
            "action": action,
            "amount": amount,
        }
        self._pending_states.append(state)

    def _encode_game_state(self, player) -> torch.Tensor:
        """Encode current game state for model input."""
        import numpy as np

        features = np.zeros(PokerNet.INPUT_DIM, dtype=np.float32)
        game = self._base_game
        bb = game.big_blind

        # Betting features - "it's X to you"
        pot = game.pot
        stack = player.stack
        to_call = max(0, game.current_bet - player.bet)

        # Get actual min raise increment (may be larger than BB after raises)
        min_raise_increment = getattr(game, 'last_raise_increment', bb)

        # Min raise-to amount (what the model needs to reach to make a valid raise)
        min_raise_to = game.current_bet + min_raise_increment

        features[0] = pot / bb / 100.0
        features[1] = stack / bb / 100.0
        features[2] = to_call / bb / 10.0  # "It's X to call"
        features[3] = min_raise_increment / bb / 10.0  # Min raise increment
        features[4] = min_raise_to / bb / 10.0  # Min raise-to amount

        if pot > 0 and to_call > 0:
            features[5] = to_call / (pot + to_call)
        if pot > 0:
            features[6] = min(10.0, stack / pot) / 10.0

        features[7] = 1.0 if to_call == 0 else 0.0
        features[8] = 1.0 if to_call > 0 else 0.0

        # Position
        features[10] = player.seat / 10.0
        features[14] = len([p for p in game.players.values() if not p.folded]) / 10.0

        # Phase
        phase = 1
        if len(game.community) >= 3:
            phase = 2
        if len(game.community) >= 4:
            phase = 3
        if len(game.community) >= 5:
            phase = 4
        features[15 + phase] = 1.0

        # Hole cards
        for i, card in enumerate(player.hole_cards or []):
            if card is not None:
                card_idx = (card.rank - 2) * 4 + (card.suit - 1)
                if 0 <= card_idx < 52:
                    features[20 + i * 52 + card_idx] = 1.0

        # Community cards
        for card in game.community:
            if card is not None:
                card_idx = (card.rank - 2) * 4 + (card.suit - 1)
                if 0 <= card_idx < 52:
                    features[124 + card_idx] = 1.0

        return torch.tensor(features, dtype=torch.float32).unsqueeze(0)

    def _random_action(self, player) -> tuple:
        """Fallback random action."""
        import random
        from angzarr_client.proto.examples import poker_types_pb2 as types_pb2

        to_call = max(0, self._base_game.current_bet - player.bet)

        if to_call == 0:
            if random.random() < 0.2 and player.stack >= self._base_game.big_blind:
                return types_pb2.BET, self._base_game.big_blind * 2
            return types_pb2.CHECK, 0
        elif to_call >= player.stack:
            if random.random() < 0.4:
                return types_pb2.CALL, to_call
            return types_pb2.FOLD, 0
        else:
            if random.random() < 0.7:
                return types_pb2.CALL, to_call
            return types_pb2.FOLD, 0


@dataclass
class PlayerAgent:
    """An individual player agent with its own model."""

    name: str
    model: PokerNet
    model_id: str
    total_hands: int = 0
    total_chips_won: int = 0
    tournaments_played: int = 0
    wins: int = 0

    @property
    def bb_per_100(self) -> float:
        """Calculate BB/100 for this player."""
        if self.total_hands == 0:
            return 0.0
        return (self.total_chips_won / 10) / (self.total_hands / 100)

    @property
    def win_rate(self) -> float:
        """Tournament win rate."""
        if self.tournaments_played == 0:
            return 0.0
        return self.wins / self.tournaments_played


@dataclass
class SelfPlayConfig:
    """Configuration for self-play training."""

    num_players: int = 9
    database_url: str = "sqlite:///selfplay.db"
    output_dir: str = "./models/selfplay"
    device: str = "cpu"

    # Training parameters
    epochs_per_iteration: int = 3
    batch_size: int = 64
    learning_rate: float = 3e-4

    # Self-play parameters
    tournaments_per_iteration: int = 5
    max_iterations: int = 50
    hands_per_tournament: int = 100  # Reduced from 200 for faster iteration

    # Weight sharing
    share_weights_every: int = 3  # Share every N iterations
    weight_averaging_alpha: float = 0.5  # How much to blend (0=keep own, 1=full average)

    # Exploration
    exploration_temperature: float = 0.5  # Softmax temperature for action sampling (0=greedy)

    # Convergence
    target_bb: float = 10.0
    convergence_window: int = 5
    convergence_threshold: float = 0.5


class MultiModelRegistry:
    """Registry that holds multiple models for different players."""

    def __init__(self, device: str = "cpu") -> None:
        self._models: dict[str, PokerNet] = {}
        self._device = device

    def register(self, model_id: str, model: PokerNet) -> None:
        """Register a model for a player."""
        self._models[model_id] = model
        logger.debug("model_registered", model_id=model_id)

    def get(self, model_id: str) -> PokerNet | None:
        """Get model by ID."""
        return self._models.get(model_id)

    def get_or_create(self, model_id: str) -> PokerNet:
        """Get existing model or create new one."""
        if model_id not in self._models:
            self._models[model_id] = PokerNet(device=self._device)
            logger.debug("model_created", model_id=model_id)
        return self._models[model_id]

    def all_models(self) -> list[tuple[str, PokerNet]]:
        """Get all registered models."""
        return list(self._models.items())

    def average_weights(self) -> dict:
        """Compute average weights across all models."""
        if not self._models:
            return {}

        models = list(self._models.values())
        avg_state = {}

        # Get state dict from first model as template
        first_state = models[0].state_dict()

        for key in first_state:
            # Stack all model weights for this key
            stacked = torch.stack([m.state_dict()[key].float() for m in models])
            avg_state[key] = stacked.mean(dim=0)

        return avg_state

    def share_weights(self, alpha: float = 0.5) -> None:
        """Share weights across all models using averaging.

        Args:
            alpha: Blend factor. 0 = keep own weights, 1 = use full average.
        """
        if len(self._models) < 2:
            return

        avg_weights = self.average_weights()

        for model_id, model in self._models.items():
            current_state = model.state_dict()
            blended_state = {}

            for key in current_state:
                # Blend: (1-alpha) * own + alpha * average
                blended_state[key] = (
                    (1 - alpha) * current_state[key].float() +
                    alpha * avg_weights[key]
                )

            model.load_state_dict(blended_state)

        logger.info("weights_shared", alpha=alpha, num_models=len(self._models))

    def share_from_winner(self, winner_model_id: str, alpha: float = 0.3) -> None:
        """Share winning model's weights to all other models.

        The winner "teaches" the losers by blending their weights.

        Args:
            winner_model_id: Model ID of the tournament winner.
            alpha: How much to learn from winner. 0 = keep own, 1 = copy winner.
        """
        winner_model = self._models.get(winner_model_id)
        if winner_model is None:
            logger.warning("winner_model_not_found", model_id=winner_model_id)
            return

        winner_state = winner_model.state_dict()

        for model_id, model in self._models.items():
            if model_id == winner_model_id:
                continue  # Winner keeps their weights

            current_state = model.state_dict()
            blended_state = {}

            for key in current_state:
                # Blend: (1-alpha) * own + alpha * winner
                blended_state[key] = (
                    (1 - alpha) * current_state[key].float() +
                    alpha * winner_state[key].float()
                )

            model.load_state_dict(blended_state)

        logger.info(
            "winner_weights_shared",
            winner=winner_model_id,
            alpha=alpha,
            learners=len(self._models) - 1,
        )


class SelfPlayTrainer:
    """Trainer for multi-agent self-play."""

    def __init__(self, config: SelfPlayConfig) -> None:
        self._config = config
        self._engine = create_engine(config.database_url)
        self._registry = MultiModelRegistry(device=config.device)
        self._agents: list[PlayerAgent] = []
        self._iteration = 0

        # Ensure tables exist
        Base.metadata.create_all(self._engine)

        # Create output directory
        Path(config.output_dir).mkdir(parents=True, exist_ok=True)

        # Initialize agents
        self._init_agents()

    def _init_agents(self) -> None:
        """Initialize player agents with their own models."""
        names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank", "Ivan"]

        for i in range(self._config.num_players):
            name = names[i] if i < len(names) else f"Player{i}"
            model_id = f"agent_{name.lower()}"

            # Create model for this agent
            model = PokerNet(device=self._config.device)
            self._registry.register(model_id, model)

            agent = PlayerAgent(
                name=name,
                model=model,
                model_id=model_id,
            )
            self._agents.append(agent)

        logger.info("agents_initialized", count=len(self._agents))

    def run_tournament(self) -> dict[str, dict]:
        """Run a single tournament with each player using their own model.

        Returns:
            Dict mapping player name to their results.
        """
        from run_game import GatewayClient, GameVariant
        from ai_player.models.encoder import ActionContextEncoder

        tournament_id = f"selfplay-{uuid.uuid4().hex[:8]}"
        cfg = self._config

        logger.debug("tournament_starting", tournament_id=tournament_id)

        # Create encoder for model inference
        encoder = ActionContextEncoder()

        # Map agent names to their models for quick lookup
        agent_models = {agent.name: agent.model for agent in self._agents}

        with GatewayClient("localhost:1320") as client:
            game = SelfPlayGame(
                client,
                agent_models=agent_models,
                encoder=encoder,
                engine=self._engine,  # Pass engine for training state recording
                small_blind=5,
                big_blind=10,
                exploration_temperature=cfg.exploration_temperature,
            )

            # Create table
            game.create_table(f"SelfPlay-{tournament_id[:8]}")

            # Add players
            for i, agent in enumerate(self._agents):
                game.add_player(agent.name, 1000, i)

            # Track initial stacks
            initial_stacks = {p.name: p.stack for p in game.players.values()}

            # Play tournament
            hands_played = 0
            while len(game.players) > 1 and hands_played < cfg.hands_per_tournament:
                game.play_hand()
                hands_played += 1

            # Collect results
            results = {}
            remaining = list(game.players.values())
            remaining.sort(key=lambda p: -p.stack)

            position = 1
            for p in remaining:
                initial = initial_stacks.get(p.name, 1000)
                chip_delta = p.stack - initial
                results[p.name] = {
                    "position": position,
                    "final_stack": p.stack,
                    "chip_delta": chip_delta,
                    "hands": hands_played,
                    "won": position == 1,
                }
                position += 1

            # Add eliminated players
            for name, initial in initial_stacks.items():
                if name not in results:
                    results[name] = {
                        "position": position,
                        "final_stack": 0,
                        "chip_delta": -initial,
                        "hands": hands_played,
                        "won": False,
                    }
                    position += 1

        logger.debug(
            "tournament_complete",
            tournament_id=tournament_id,
            hands=hands_played,
            winner=remaining[0].name if remaining else "none",
        )

        return results

    def update_agent_stats(self, results: dict[str, dict]) -> None:
        """Update agent statistics from tournament results."""
        for agent in self._agents:
            if agent.name in results:
                r = results[agent.name]
                agent.total_hands += r["hands"]
                agent.total_chips_won += r["chip_delta"]
                agent.tournaments_played += 1
                if r["won"]:
                    agent.wins += 1

    def train_agent(self, agent: PlayerAgent) -> float:
        """Train a single agent on their experiences.

        Returns:
            Average loss for the training.
        """
        # Create trainer config for this agent
        trainer_config = TrainerConfig(
            database_url=self._config.database_url,
            output_dir=self._config.output_dir,
            device=self._config.device,
            batch_size=self._config.batch_size,
            learning_rate=self._config.learning_rate,
            epochs=self._config.epochs_per_iteration,
        )

        # Load training data - filter by player if possible
        # For now, train on all data (shared experience)
        from sqlalchemy.orm import Session as DBSession

        with DBSession(self._engine) as session:
            stmt = (
                select(TrainingState)
                .where(TrainingState.reward.isnot(None))
                .order_by(TrainingState.id.desc())
                .limit(trainer_config.max_examples)
            )
            examples = []
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

        if len(examples) < trainer_config.batch_size:
            logger.warning(
                "insufficient_data",
                agent=agent.name,
                examples=len(examples),
            )
            return 0.0

        # Train the agent's model
        from ai_player.training.trainer import Trainer

        # Create a temporary trainer with this agent's model
        trainer = Trainer(trainer_config)
        trainer._model = agent.model  # Use agent's model

        total_loss = 0.0
        for epoch in range(trainer_config.epochs):
            loss = trainer.train_epoch(examples)
            total_loss += loss

        avg_loss = total_loss / trainer_config.epochs
        logger.debug(
            "agent_trained",
            agent=agent.name,
            epochs=trainer_config.epochs,
            avg_loss=round(avg_loss, 4),
        )

        return avg_loss

    def save_models(self, suffix: str = "") -> None:
        """Save all agent models."""
        output_dir = Path(self._config.output_dir)
        for agent in self._agents:
            path = output_dir / f"{agent.model_id}_{suffix}.pt"
            agent.model.save(path, version=f"{agent.model_id}_{suffix}")

        # Also save best model (highest BB/100)
        best_agent = max(self._agents, key=lambda a: a.bb_per_100)
        best_path = output_dir / "best_model.pt"
        best_agent.model.save(best_path, version=f"best_{suffix}")

        logger.info(
            "models_saved",
            suffix=suffix,
            best_agent=best_agent.name,
            best_bb_per_100=round(best_agent.bb_per_100, 2),
        )

    def print_leaderboard(self) -> None:
        """Print agent leaderboard."""
        sorted_agents = sorted(self._agents, key=lambda a: -a.bb_per_100)

        print("\n=== Agent Leaderboard ===")
        print(f"{'Rank':<5} {'Agent':<10} {'BB/100':<10} {'Win Rate':<10} {'Tournaments':<12} {'Hands':<10}")
        print("-" * 60)

        for i, agent in enumerate(sorted_agents, 1):
            print(
                f"{i:<5} {agent.name:<10} {agent.bb_per_100:>8.2f} "
                f"{agent.win_rate:>8.1%} {agent.tournaments_played:>10} "
                f"{agent.total_hands:>10}"
            )
        print()

    def run(self) -> PlayerAgent:
        """Run the self-play training loop.

        Each iteration:
        1. Run tournaments - track winners
        2. Train each agent on experiences
        3. Winner shares weights with losers (winner teaches)

        Returns:
            The best performing agent.
        """
        cfg = self._config

        logger.info(
            "selfplay_starting",
            num_players=cfg.num_players,
            max_iterations=cfg.max_iterations,
            tournaments_per_iter=cfg.tournaments_per_iteration,
        )

        bb_history: list[float] = []

        for iteration in range(1, cfg.max_iterations + 1):
            self._iteration = iteration
            logger.info("iteration_starting", iteration=iteration)

            # Phase 1: Run tournaments and track winners
            iteration_winners: list[str] = []
            for t in range(cfg.tournaments_per_iteration):
                results = self.run_tournament()
                self.update_agent_stats(results)

                # Find tournament winner
                for agent in self._agents:
                    if agent.name in results and results[agent.name]["won"]:
                        iteration_winners.append(agent.model_id)
                        break

            # Phase 2: Train each agent on experiences
            logger.info("training_phase", iteration=iteration)
            for agent in self._agents:
                self.train_agent(agent)

            # Phase 3: Winner teaches - share from most frequent winner
            if iteration_winners:
                # Find model that won most tournaments this iteration
                from collections import Counter
                winner_counts = Counter(iteration_winners)
                top_winner = winner_counts.most_common(1)[0][0]

                # Winner shares their learned weights with others
                self._registry.share_from_winner(
                    top_winner,
                    alpha=cfg.weight_averaging_alpha,
                )

                # Find winner agent for logging
                winner_agent = next(
                    (a for a in self._agents if a.model_id == top_winner),
                    None,
                )
                if winner_agent:
                    logger.info(
                        "winner_teaches",
                        winner=winner_agent.name,
                        wins_this_iteration=winner_counts[top_winner],
                    )

            # Calculate best BB/100
            best_agent = max(self._agents, key=lambda a: a.bb_per_100)
            best_bb = best_agent.bb_per_100
            bb_history.append(best_bb)

            logger.info(
                "iteration_complete",
                iteration=iteration,
                best_agent=best_agent.name,
                best_bb_per_100=round(best_bb, 2),
            )

            self.print_leaderboard()

            # Save checkpoints periodically
            if iteration % 5 == 0:
                self.save_models(suffix=f"iter{iteration}")

        # Final save
        self.save_models(suffix="final")

        best_agent = max(self._agents, key=lambda a: a.bb_per_100)
        logger.info(
            "selfplay_complete",
            iterations=self._iteration,
            best_agent=best_agent.name,
            best_bb_per_100=round(best_agent.bb_per_100, 2),
        )

        return best_agent


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Self-play training")
    parser.add_argument("--database-url", type=str, required=True)
    parser.add_argument("--output-dir", type=str, default="./models/selfplay")
    parser.add_argument("--num-players", type=int, default=9)
    parser.add_argument("--tournaments-per-iteration", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--share-every", type=int, default=3)
    parser.add_argument("--target-bb", type=float, default=10.0)

    args = parser.parse_args()

    config = SelfPlayConfig(
        database_url=args.database_url,
        output_dir=args.output_dir,
        num_players=args.num_players,
        tournaments_per_iteration=args.tournaments_per_iteration,
        max_iterations=args.max_iterations,
        share_weights_every=args.share_every,
        target_bb=args.target_bb,
    )

    trainer = SelfPlayTrainer(config)
    best = trainer.run()

    print(f"\nBest Agent: {best.name}")
    print(f"BB/100: {best.bb_per_100:.2f}")
    print(f"Win Rate: {best.win_rate:.1%}")
    print(f"Model saved to: {config.output_dir}/best_model.pt")


if __name__ == "__main__":
    main()
