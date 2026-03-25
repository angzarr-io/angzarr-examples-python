#!/usr/bin/env python3
"""Tournament-train loop for poker AI.

Runs tournaments to evaluate model fitness, trains on new data,
and repeats until convergence or target fitness is reached.

Usage:
    python -m ai_player.training.training_loop \
        --database-url postgresql://localhost/poker \
        --target-bb 10.0 \
        --tournaments-per-iteration 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog
from sqlalchemy import create_engine

# Add parent paths for imports
root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

from ai_player.training.trainer import Trainer, TrainerConfig
from ai_player.training.fitness_tracker import FitnessTracker, FitnessMetrics
from ai_player.training.tournament_runner import TournamentRunner, TournamentConfig

logger = structlog.get_logger()


def run_training_loop(
    database_url: str,
    output_dir: str = "./models",
    target_bb: float = 10.0,
    tournaments_per_iteration: int = 5,
    max_iterations: int = 50,
    epochs_per_iteration: int = 3,
    gateway_address: str = "localhost:9084",
    ai_player_address: str | None = None,
    checkpoint: str | None = None,
) -> FitnessMetrics:
    """Run the tournament-train loop until convergence or target.

    Args:
        database_url: PostgreSQL connection string.
        output_dir: Directory for model checkpoints.
        target_bb: Target BB/100 fitness (default: 10.0).
        tournaments_per_iteration: Tournaments to run each iteration.
        max_iterations: Maximum training iterations.
        epochs_per_iteration: Training epochs per iteration.
        gateway_address: Angzarr gateway gRPC address.
        ai_player_address: AI player service address (optional).
        checkpoint: Path to initial checkpoint (optional).

    Returns:
        Final fitness metrics.
    """
    engine = create_engine(database_url)

    # Initialize components
    trainer_config = TrainerConfig(
        database_url=database_url,
        output_dir=output_dir,
        epochs=epochs_per_iteration,
    )
    trainer = Trainer(trainer_config)

    tournament_config = TournamentConfig(
        gateway_address=gateway_address,
        ai_player_address=ai_player_address,
    )
    runner = TournamentRunner(engine, tournament_config)

    fitness_tracker = FitnessTracker(engine)

    # Load initial checkpoint if provided
    if checkpoint:
        trainer.load_checkpoint(checkpoint)
        model_version = Path(checkpoint).stem
    else:
        model_version = "initial"

    logger.info(
        "training_loop_starting",
        target_bb=target_bb,
        max_iterations=max_iterations,
        tournaments_per_iter=tournaments_per_iteration,
        epochs_per_iter=epochs_per_iteration,
    )

    iteration = 0
    final_metrics = None

    while iteration < max_iterations:
        iteration += 1
        logger.info("iteration_starting", iteration=iteration, model=model_version)

        # Phase 1: Run tournaments to evaluate current model
        logger.info("phase_tournaments", iteration=iteration)
        runner.run_evaluation(model_version, num_tournaments=tournaments_per_iteration)

        # Phase 2: Evaluate fitness and check convergence
        metrics, converged = fitness_tracker.evaluate(model_version)
        final_metrics = metrics

        logger.info(
            "iteration_fitness",
            iteration=iteration,
            bb_per_100=round(metrics.bb_per_100, 2),
            roi=round(metrics.avg_roi, 4),
            converged=converged,
        )

        # Check termination conditions
        if fitness_tracker.meets_target(metrics, target_bb):
            logger.info(
                "target_reached",
                iteration=iteration,
                bb_per_100=round(metrics.bb_per_100, 2),
                target=target_bb,
            )
            break

        if converged:
            logger.info(
                "convergence_detected",
                iteration=iteration,
                bb_per_100=round(metrics.bb_per_100, 2),
            )
            break

        # Phase 3: Train on accumulated data
        logger.info("phase_training", iteration=iteration)
        trainer.train()

        # Save checkpoint with new version
        model_version = f"iter_{iteration}"
        trainer.save_checkpoint(model_version)

    logger.info(
        "training_loop_complete",
        iterations=iteration,
        final_bb_per_100=round(final_metrics.bb_per_100, 2) if final_metrics else 0,
        final_roi=round(final_metrics.avg_roi, 4) if final_metrics else 0,
    )

    return final_metrics


def main():
    parser = argparse.ArgumentParser(
        description="Run tournament-train loop for poker AI"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        required=True,
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./models",
        help="Directory for model checkpoints (default: ./models)",
    )
    parser.add_argument(
        "--target-bb",
        type=float,
        default=10.0,
        help="Target BB/100 fitness (default: 10.0)",
    )
    parser.add_argument(
        "--tournaments-per-iteration",
        type=int,
        default=5,
        help="Tournaments to run each iteration (default: 5)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        help="Maximum training iterations (default: 50)",
    )
    parser.add_argument(
        "--epochs-per-iteration",
        type=int,
        default=3,
        help="Training epochs per iteration (default: 3)",
    )
    parser.add_argument(
        "--gateway-address",
        type=str,
        default="localhost:9084",
        help="Angzarr gateway gRPC address (default: localhost:9084)",
    )
    parser.add_argument(
        "--ai-player-address",
        type=str,
        default=None,
        help="AI player service gRPC address (optional)",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Initial model checkpoint path (optional)",
    )

    args = parser.parse_args()

    try:
        metrics = run_training_loop(
            database_url=args.database_url,
            output_dir=args.output_dir,
            target_bb=args.target_bb,
            tournaments_per_iteration=args.tournaments_per_iteration,
            max_iterations=args.max_iterations,
            epochs_per_iteration=args.epochs_per_iteration,
            gateway_address=args.gateway_address,
            ai_player_address=args.ai_player_address,
            checkpoint=args.checkpoint,
        )

        print(f"\nFinal Results:")
        print(f"  BB/100: {metrics.bb_per_100:.2f}")
        print(f"  ROI: {metrics.avg_roi:.2%}")
        print(f"  Tournaments: {metrics.tournaments_played}")
        print(f"  Hands: {metrics.total_hands}")

    except KeyboardInterrupt:
        print("\nTraining interrupted")
        sys.exit(1)


if __name__ == "__main__":
    main()
