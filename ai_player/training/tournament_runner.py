"""Tournament runner for model evaluation.

Orchestrates running 9-player tournaments and records results
to the database for fitness tracking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Add parent paths for imports
import sys

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

from prj_training.schema import Base, TournamentResult
from run_game import GatewayClient, PokerGame, GameVariant

logger = structlog.get_logger()


@dataclass
class TournamentConfig:
    """Configuration for tournament execution."""

    players: int = 9
    starting_stack: int = 1000
    small_blind: int = 5
    big_blind: int = 10
    max_hands: int = 200
    gateway_address: str = "localhost:9084"
    ai_player_address: str | None = None


@dataclass
class TournamentStats:
    """Statistics from a completed tournament."""

    tournament_id: str
    hands_played: int
    winner_name: str
    results: list[dict]  # Per-player results


class TournamentRunner:
    """Runs tournaments and records results for fitness evaluation."""

    def __init__(
        self,
        engine: Engine,
        config: TournamentConfig | None = None,
    ) -> None:
        """Initialize runner.

        Args:
            engine: SQLAlchemy database engine.
            config: Tournament configuration.
        """
        self._engine = engine
        self._config = config or TournamentConfig()

        # Ensure tables exist
        Base.metadata.create_all(engine)

    def run_tournament(self, model_version: str) -> TournamentStats:
        """Run a single tournament and record results.

        Args:
            model_version: Model version being evaluated.

        Returns:
            TournamentStats with results.
        """
        tournament_id = f"tourney-{uuid.uuid4().hex[:8]}"
        cfg = self._config

        logger.info(
            "tournament_starting",
            tournament_id=tournament_id,
            model=model_version,
            players=cfg.players,
            starting_chips=cfg.starting_stack,
        )

        # Track initial stacks for calculating deltas
        player_names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank", "Ivan"][:cfg.players]

        with GatewayClient(cfg.gateway_address) as client:
            game = PokerGame(
                client,
                variant=GameVariant.TEXAS_HOLDEM,
                small_blind=cfg.small_blind,
                big_blind=cfg.big_blind,
                ai_player_address=cfg.ai_player_address,
            )

            # Setup table and players
            game.create_table(f"Tournament-{tournament_id[:8]}")

            for i, name in enumerate(player_names):
                game.add_player(name, cfg.starting_stack, i)

            # Store initial player info before tournament
            initial_players = {
                p.name: {"root": p.root, "stack": p.stack, "seat": p.seat}
                for p in game.players.values()
            }

            # Play tournament
            hands_played = 0
            while len(game.players) > 1 and hands_played < cfg.max_hands:
                game.play_hand()
                hands_played += 1

            # Collect results
            results = []
            remaining_players = list(game.players.values())

            # Winner is the remaining player (or highest stack if multiple)
            if remaining_players:
                remaining_players.sort(key=lambda p: -p.stack)
                winner_name = remaining_players[0].name
            else:
                winner_name = "unknown"

            # Build results for all players (both eliminated and remaining)
            position = 1
            for p in remaining_players:
                initial = initial_players.get(p.name, {"stack": cfg.starting_stack})
                chip_delta = p.stack - initial["stack"]
                bb_won = chip_delta / cfg.big_blind

                results.append({
                    "player_name": p.name,
                    "player_root": p.root,
                    "final_position": position,
                    "final_stack": p.stack,
                    "chip_delta": chip_delta,
                    "bb_won": bb_won,
                    "roi": chip_delta / cfg.starting_stack,
                })
                position += 1

            # Add eliminated players (they're no longer in game.players)
            for name, initial in initial_players.items():
                if not any(r["player_name"] == name for r in results):
                    results.append({
                        "player_name": name,
                        "player_root": initial["root"],
                        "final_position": position,
                        "final_stack": 0,
                        "chip_delta": -cfg.starting_stack,
                        "bb_won": -cfg.starting_stack / cfg.big_blind,
                        "roi": -1.0,
                    })
                    position += 1

        # Record results to database
        self._record_results(tournament_id, model_version, hands_played, results)

        logger.info(
            "tournament_complete",
            tournament_id=tournament_id,
            hands=hands_played,
            winner=winner_name,
        )

        return TournamentStats(
            tournament_id=tournament_id,
            hands_played=hands_played,
            winner_name=winner_name,
            results=results,
        )

    def _record_results(
        self,
        tournament_id: str,
        model_version: str,
        hands_played: int,
        results: list[dict],
    ) -> None:
        """Record tournament results to database.

        Args:
            tournament_id: Unique tournament identifier.
            model_version: Model version used.
            hands_played: Total hands in tournament.
            results: Per-player results.
        """
        cfg = self._config

        with Session(self._engine) as session:
            for r in results:
                result = TournamentResult(
                    tournament_id=tournament_id,
                    model_version=model_version,
                    player_root=r["player_root"],
                    player_name=r["player_name"],
                    players_count=cfg.players,
                    starting_stack=cfg.starting_stack,
                    big_blind=cfg.big_blind,
                    final_position=r["final_position"],
                    final_stack=r["final_stack"],
                    hands_played=hands_played,
                    chip_delta=r["chip_delta"],
                    bb_won=r["bb_won"],
                    roi=r["roi"],
                )
                session.add(result)

            session.commit()

        logger.debug(
            "results_recorded",
            tournament_id=tournament_id,
            players=len(results),
        )

    def run_evaluation(
        self,
        model_version: str,
        num_tournaments: int = 5,
    ) -> list[TournamentStats]:
        """Run multiple tournaments for evaluation.

        Args:
            model_version: Model version to evaluate.
            num_tournaments: Number of tournaments to run.

        Returns:
            List of tournament statistics.
        """
        stats = []
        for i in range(num_tournaments):
            logger.info(
                "evaluation_progress",
                tournament=i + 1,
                total=num_tournaments,
                model=model_version,
            )
            stat = self.run_tournament(model_version)
            stats.append(stat)

        return stats
