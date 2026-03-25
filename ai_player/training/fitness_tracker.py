"""Fitness tracking for model evaluation.

Calculates BB/100 and ROI metrics from tournament results
and detects convergence to stop training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Import schema - add parent path for imports
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from prj_training.schema import TournamentResult

logger = structlog.get_logger()


@dataclass
class FitnessMetrics:
    """Aggregated fitness metrics for a model version."""

    model_version: str
    tournaments_played: int
    total_hands: int
    total_bb_won: float
    avg_position: float
    avg_roi: float

    @property
    def bb_per_100(self) -> float:
        """Calculate BB/100 (big blinds won per 100 hands)."""
        if self.total_hands == 0:
            return 0.0
        return (self.total_bb_won / self.total_hands) * 100

    def __str__(self) -> str:
        return (
            f"FitnessMetrics(model={self.model_version}, "
            f"bb/100={self.bb_per_100:.2f}, roi={self.avg_roi:.2%}, "
            f"tournaments={self.tournaments_played}, hands={self.total_hands})"
        )


@dataclass
class ConvergenceTracker:
    """Track fitness over time to detect convergence.

    Convergence is detected when the improvement in BB/100
    falls below threshold over a rolling window.
    """

    window_size: int = 5
    improvement_threshold: float = 0.5  # BB/100
    history: list[float] = field(default_factory=list)

    def add(self, bb_per_100: float) -> None:
        """Add a fitness measurement."""
        self.history.append(bb_per_100)

    def is_converged(self) -> bool:
        """Check if training has converged.

        Returns True if:
        - We have at least window_size measurements, AND
        - The improvement over the window is below threshold
        """
        if len(self.history) < self.window_size:
            return False

        recent = self.history[-self.window_size :]
        improvement = recent[-1] - recent[0]

        logger.debug(
            "convergence_check",
            window=recent,
            improvement=improvement,
            threshold=self.improvement_threshold,
        )

        return improvement < self.improvement_threshold

    def improvement_rate(self) -> float:
        """Calculate recent improvement rate (BB/100 per iteration)."""
        if len(self.history) < 2:
            return 0.0
        window = self.history[-self.window_size :] if len(self.history) >= self.window_size else self.history
        return (window[-1] - window[0]) / len(window)


class FitnessTracker:
    """Track and evaluate model fitness from tournament results."""

    def __init__(self, engine: Engine) -> None:
        """Initialize tracker.

        Args:
            engine: SQLAlchemy database engine.
        """
        self._engine = engine
        self._convergence = ConvergenceTracker()

    def get_metrics(self, model_version: str) -> FitnessMetrics:
        """Get aggregated fitness metrics for a model version.

        Args:
            model_version: Model version string to evaluate.

        Returns:
            FitnessMetrics with aggregated statistics.
        """
        with Session(self._engine) as session:
            # Aggregate results for this model
            stmt = select(
                func.count(TournamentResult.id).label("tournaments"),
                func.sum(TournamentResult.hands_played).label("total_hands"),
                func.sum(TournamentResult.bb_won).label("total_bb_won"),
                func.avg(TournamentResult.final_position).label("avg_position"),
                func.avg(TournamentResult.roi).label("avg_roi"),
            ).where(TournamentResult.model_version == model_version)

            row = session.execute(stmt).one()

            return FitnessMetrics(
                model_version=model_version,
                tournaments_played=row.tournaments or 0,
                total_hands=int(row.total_hands or 0),
                total_bb_won=float(row.total_bb_won or 0.0),
                avg_position=float(row.avg_position or 0.0),
                avg_roi=float(row.avg_roi or 0.0),
            )

    def evaluate(self, model_version: str) -> tuple[FitnessMetrics, bool]:
        """Evaluate model and check for convergence.

        Args:
            model_version: Model version to evaluate.

        Returns:
            Tuple of (metrics, is_converged).
        """
        metrics = self.get_metrics(model_version)
        self._convergence.add(metrics.bb_per_100)

        logger.info(
            "fitness_evaluated",
            model=model_version,
            bb_per_100=round(metrics.bb_per_100, 2),
            roi=round(metrics.avg_roi, 4),
            tournaments=metrics.tournaments_played,
            hands=metrics.total_hands,
        )

        return metrics, self._convergence.is_converged()

    def meets_target(self, metrics: FitnessMetrics, target_bb: float = 10.0) -> bool:
        """Check if metrics meet the target fitness.

        Args:
            metrics: Fitness metrics to check.
            target_bb: Target BB/100 (default: 10.0).

        Returns:
            True if target is met.
        """
        return metrics.bb_per_100 >= target_bb

    def get_convergence_tracker(self) -> ConvergenceTracker:
        """Get the convergence tracker for inspection."""
        return self._convergence
