"""CLI entry point for AI training."""

from __future__ import annotations

import argparse
import sys

import structlog

from ai_player.training.trainer import Trainer, TrainerConfig

logger = structlog.get_logger()


def main() -> int:
    """Run training CLI."""
    parser = argparse.ArgumentParser(description="Train poker AI model")
    parser.add_argument(
        "--database-url",
        default="postgresql://angzarr:angzarr@localhost:5432/angzarr",
        help="Database URL (same as angzarr, training_states table)",
    )
    parser.add_argument(
        "--output-dir",
        default="./models",
        help="Directory to save model checkpoints",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda", "mps"],
        help="Device to train on",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=10,
        help="Number of training epochs",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Training batch size",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=3e-4,
        help="Learning rate",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Path to checkpoint to resume from",
    )

    args = parser.parse_args()

    # Configure logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    )

    logger.info(
        "training_config",
        database_url=args.database_url.replace(
            args.database_url.split("@")[0].split(":")[-1], "***"
        ) if "@" in args.database_url else args.database_url,
        output_dir=args.output_dir,
        device=args.device,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )

    config = TrainerConfig(
        database_url=args.database_url,
        output_dir=args.output_dir,
        device=args.device,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
    )

    trainer = Trainer(config)

    if args.checkpoint:
        logger.info("loading_checkpoint", path=args.checkpoint)
        trainer.load_checkpoint(args.checkpoint)

    try:
        trainer.train()
        logger.info("training_complete")
        return 0
    except KeyboardInterrupt:
        logger.info("training_interrupted")
        return 1
    except Exception as e:
        logger.exception("training_failed", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
