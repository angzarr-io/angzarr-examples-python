#!/usr/bin/env python3
"""Self-play training driver.

Each player plays through a gRPC AiSidecar client — the in-process PokerNet
inference path has been removed in favor of a single cross-language contract.
The offline trainer (ai_player.training.trainer) still touches PokerNet
directly for gradient updates (that's training, not decisioning), and
publishes new checkpoints via the sidecar's ReloadModel RPC.
"""

from __future__ import annotations

# Add parent paths for imports
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy import create_engine, select

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

# Import the sidecar client from the parent directory (it is a top-level
# module, not part of the ai_player package) — path already set above.
from ai_player_client import AiPlayerClient, AiPlayerConfig
from ai_player.training.schema import Base, TrainingState

from ai_player.training.trainer import Trainer, TrainerConfig

logger = structlog.get_logger()


class SelfPlayGame:
    """Poker game where each player makes decisions via an AiSidecar client."""

    def __init__(
        self,
        client,
        agent_clients: dict[str, AiPlayerClient],
        engine=None,
        small_blind: int = 5,
        big_blind: int = 10,
    ):
        """Initialize self-play game.

        Args:
            client: GatewayClient for game commands.
            agent_clients: Dict mapping player name to their AiPlayerClient
                (each points at a sidecar / session keyed by model_id).
            engine: SQLAlchemy engine for recording training states (optional).
            small_blind: Small blind amount.
            big_blind: Big blind amount.
        """
        from run_game import GameVariant, PokerGame

        self._base_game = PokerGame(
            client,
            variant=GameVariant.TEXAS_HOLDEM,
            small_blind=small_blind,
            big_blind=big_blind,
        )
        self._base_game.log = lambda msg: None

        self._agent_clients = agent_clients
        self._engine = engine

        self._base_game.get_action = self._get_action_via_sidecar

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
                stmt = (
                    insert(TrainingState)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["hand_root", "sequence"])
                )
                session.execute(stmt)

            session.commit()

    def _get_action_via_sidecar(self, player) -> tuple:
        """Get action from the player's sidecar client (pure RPC).

        Raises if no client is registered for this player — there is no
        in-process fallback by design. The only fallback retained is the
        random action one inside AiPlayerClient.get_action itself, which
        triggers on transient channel errors.
        """
        ai_client = self._agent_clients.get(player.name)
        if ai_client is None:
            raise RuntimeError(f"no AiPlayerClient registered for player {player.name}")

        snapshot = self._build_snapshot(player)
        game = self._base_game
        hand_id = getattr(game, "hand_root", None) or b""

        action, action_amount = ai_client.get_action(snapshot, hand_id)

        if self._engine:
            self._record_action_state(player, action, action_amount)

        return action, action_amount

    def _build_snapshot(self, player) -> dict:
        """Build the dict snapshot that AiPlayerClient.get_action expects."""
        game = self._base_game
        to_call = max(0, game.current_bet - player.bet)
        min_raise_increment = getattr(game, "last_raise_increment", game.big_blind)

        phase = 1
        if len(game.community) >= 3:
            phase = 2
        if len(game.community) >= 4:
            phase = 3
        if len(game.community) >= 5:
            phase = 4

        return {
            "game_variant": 1,
            "phase": phase,
            "hole_cards": [
                {"suit": c.suit, "rank": c.rank}
                for c in (player.hole_cards or [])
                if c is not None
            ],
            "community_cards": [
                {"suit": c.suit, "rank": c.rank}
                for c in game.community
                if c is not None
            ],
            "pot_size": game.pot,
            "stack_size": player.stack,
            "amount_to_call": to_call,
            "min_raise": min_raise_increment,
            "max_raise": player.stack + player.bet,
            "position": player.seat,
            "players_remaining": len(
                [p for p in game.players.values() if not p.folded]
            ),
            "players_to_act": len(
                [p for p in game.players.values() if not p.folded and not p.all_in]
            ),
            "opponents": [
                {
                    "player_root": p.root or b"",
                    "position": p.seat,
                    "stack": p.stack,
                }
                for p in game.players.values()
                if p.name != player.name and not p.folded
            ],
        }

    def _record_action_state(self, player, action: int, amount: int) -> None:
        """Record the current state and action for later training."""
        game = self._base_game
        hand_root = getattr(game, "hand_root", None)

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
        min_raise_increment = getattr(game, "last_raise_increment", game.big_blind)

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
            "players_remaining": len(
                [p for p in game.players.values() if not p.folded]
            ),
            "players_to_act": len(
                [p for p in game.players.values() if not p.folded and not p.all_in]
            ),
            "action": action,
            "amount": amount,
        }
        self._pending_states.append(state)


@dataclass
class PlayerAgent:
    """An individual player agent with its own sidecar client."""

    name: str
    client: AiPlayerClient
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
    # One sidecar address per agent; must have len == num_players.
    # Each address is a host:port that serves the AiSidecar service.
    sidecar_addresses: list[str] = field(default_factory=list)
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
    hands_per_tournament: int = 20

    # Weight sharing (applied by the offline trainer against checkpoints;
    # published to each sidecar via the ReloadModel RPC).
    share_weights_every: int = 3
    weight_averaging_alpha: float = 0.5

    # Convergence
    target_bb: float = 10.0
    convergence_window: int = 5
    convergence_threshold: float = 0.5


class ClientRegistry:
    """Registry that holds one AiPlayerClient per agent.

    Replaces the old MultiModelRegistry that held in-process PokerNet
    instances and blended their state_dicts. Weight sharing across agents
    now happens offline: the trainer reads experiences from the DB,
    computes averaged/blended checkpoints, writes them to disk, and calls
    ReloadModel on each sidecar via AiPlayerClient.reload_model to publish.
    """

    def __init__(self) -> None:
        self._clients: dict[str, AiPlayerClient] = {}

    def register(self, model_id: str, client: AiPlayerClient) -> None:
        self._clients[model_id] = client
        logger.debug("client_registered", model_id=model_id)

    def get(self, model_id: str) -> AiPlayerClient | None:
        return self._clients.get(model_id)

    def all_clients(self) -> list[tuple[str, AiPlayerClient]]:
        return list(self._clients.items())

    def close_all(self) -> None:
        for _, c in self._clients.items():
            c.close()


class SelfPlayTrainer:
    """Trainer for multi-agent self-play via AiSidecar clients."""

    def __init__(self, config: SelfPlayConfig) -> None:
        self._config = config
        if len(config.sidecar_addresses) != config.num_players:
            raise ValueError(
                f"sidecar_addresses must have {config.num_players} entries "
                f"(one per agent), got {len(config.sidecar_addresses)}"
            )
        self._engine = create_engine(config.database_url)
        self._registry = ClientRegistry()
        self._agents: list[PlayerAgent] = []
        self._iteration = 0

        Base.metadata.create_all(self._engine)
        Path(config.output_dir).mkdir(parents=True, exist_ok=True)

        self._init_agents()

    def _init_agents(self) -> None:
        """Initialize player agents — each gets its own AiPlayerClient."""
        names = [
            "Alice",
            "Bob",
            "Carol",
            "Dave",
            "Eve",
            "Frank",
            "Grace",
            "Hank",
            "Ivan",
        ]

        for i in range(self._config.num_players):
            name = names[i] if i < len(names) else f"Player{i}"
            model_id = f"agent_{name.lower()}"
            address = self._config.sidecar_addresses[i]

            client = AiPlayerClient(
                AiPlayerConfig(
                    address=address,
                    session_id=model_id,
                    player_root=b"",
                )
            )
            self._registry.register(model_id, client)

            agent = PlayerAgent(
                name=name,
                client=client,
                model_id=model_id,
            )
            self._agents.append(agent)

        logger.info(
            "agents_initialized",
            count=len(self._agents),
            addresses=self._config.sidecar_addresses,
        )

    def run_tournament(self) -> dict[str, dict]:
        """Run a single tournament with each player using their own model.

        Returns:
            Dict mapping player name to their results.
        """
        from run_game import GatewayClient

        tournament_id = f"selfplay-{uuid.uuid4().hex[:8]}"
        cfg = self._config

        logger.debug("tournament_starting", tournament_id=tournament_id)

        agent_clients = {agent.name: agent.client for agent in self._agents}

        with GatewayClient("localhost:1320") as client:
            game = SelfPlayGame(
                client,
                agent_clients=agent_clients,
                engine=self._engine,
                small_blind=5,
                big_blind=10,
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
                examples.append(
                    {
                        "hole_cards": [ts.hole_card_1, ts.hole_card_2],
                        "community_cards": [
                            c
                            for c in [
                                ts.community_1,
                                ts.community_2,
                                ts.community_3,
                                ts.community_4,
                                ts.community_5,
                            ]
                            if c is not None
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
                    }
                )

        if len(examples) < trainer_config.batch_size:
            logger.warning(
                "insufficient_data",
                agent=agent.name,
                examples=len(examples),
            )
            return 0.0

        # Offline training: load the agent's current checkpoint, run SGD on
        # the sampled batch, save the new checkpoint, and tell the sidecar
        # to hot-reload it via ReloadModel.
        checkpoint_path = Path(self._config.output_dir) / f"{agent.model_id}.pt"
        trainer = Trainer(trainer_config)
        if checkpoint_path.exists():
            trainer.load_checkpoint(checkpoint_path)

        total_loss = 0.0
        for epoch in range(trainer_config.epochs):
            loss = trainer.train_epoch(examples)
            total_loss += loss

        avg_loss = total_loss / trainer_config.epochs
        trainer.save_checkpoint(version=agent.model_id)
        agent.client.reload_model(str(checkpoint_path), model_id=agent.model_id)

        logger.debug(
            "agent_trained",
            agent=agent.name,
            epochs=trainer_config.epochs,
            avg_loss=round(avg_loss, 4),
            checkpoint=str(checkpoint_path),
        )

        return avg_loss

    def save_models(self, suffix: str = "") -> None:
        """Checkpoints are now written per-agent from train_agent; this
        method copies the most recent checkpoints into a suffixed snapshot
        and marks the best-performing agent's checkpoint as 'best_model.pt'.
        """
        import shutil

        output_dir = Path(self._config.output_dir)
        for agent in self._agents:
            src = output_dir / f"{agent.model_id}.pt"
            if not src.exists():
                continue
            dst = output_dir / f"{agent.model_id}_{suffix}.pt"
            shutil.copy2(src, dst)

        best_agent = max(self._agents, key=lambda a: a.bb_per_100)
        best_src = output_dir / f"{best_agent.model_id}.pt"
        if best_src.exists():
            best_path = output_dir / "best_model.pt"
            shutil.copy2(best_src, best_path)

        logger.info(
            "models_saved",
            suffix=suffix,
            best_agent=best_agent.name,
            best_bb_per_100=round(best_agent.bb_per_100, 2),
        )

    def _publish_winner_weights(self, winner_model_id: str, alpha: float) -> None:
        """Publish the winning agent's checkpoint to every sidecar.

        Implementation note: weight *blending* (keeping alpha of winner + 1-alpha
        of learner) is now a checkpoint-space operation. This method currently
        publishes the winner's checkpoint directly to all sidecars; blending
        is a follow-up that belongs in the offline trainer, not in the play
        driver. Logged so the operator sees it at runtime.
        """
        winner_agent = next(
            (a for a in self._agents if a.model_id == winner_model_id), None
        )
        if winner_agent is None:
            logger.warning("winner_agent_not_found", model_id=winner_model_id)
            return

        winner_checkpoint = Path(self._config.output_dir) / f"{winner_model_id}.pt"
        if not winner_checkpoint.exists():
            logger.warning(
                "winner_checkpoint_missing",
                model_id=winner_model_id,
                path=str(winner_checkpoint),
            )
            return

        for agent in self._agents:
            if agent.model_id == winner_model_id:
                continue
            agent.client.reload_model(str(winner_checkpoint), model_id=agent.model_id)

        logger.info(
            "winner_weights_published",
            winner=winner_model_id,
            alpha=alpha,
            learners=len(self._agents) - 1,
        )

    def print_leaderboard(self) -> None:
        """Print agent leaderboard."""
        sorted_agents = sorted(self._agents, key=lambda a: -a.bb_per_100)

        print("\n=== Agent Leaderboard ===")
        header = (
            f"{'Rank':<5} {'Agent':<10} {'BB/100':<10} "
            f"{'Win Rate':<10} {'Tournaments':<12} {'Hands':<10}"
        )
        print(header)
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

            # Phase 3: Winner teaches — publish the winning agent's
            # checkpoint to every other sidecar via ReloadModel, optionally
            # blending with each learner's existing checkpoint on disk first.
            if iteration_winners:
                from collections import Counter

                winner_counts = Counter(iteration_winners)
                top_winner = winner_counts.most_common(1)[0][0]
                self._publish_winner_weights(top_winner, cfg.weight_averaging_alpha)

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
    parser.add_argument(
        "--sidecar-addresses",
        type=str,
        required=True,
        help="Comma-separated list of sidecar host:port, one per agent.",
    )
    parser.add_argument("--tournaments-per-iteration", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--share-every", type=int, default=3)
    parser.add_argument("--target-bb", type=float, default=10.0)

    args = parser.parse_args()

    sidecar_addresses = [
        a.strip() for a in args.sidecar_addresses.split(",") if a.strip()
    ]

    config = SelfPlayConfig(
        database_url=args.database_url,
        output_dir=args.output_dir,
        num_players=args.num_players,
        sidecar_addresses=sidecar_addresses,
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
