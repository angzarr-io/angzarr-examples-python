"""Tournament bounded context: the cross-table coordination slice of the
Tournament aggregate ported onto the angzarr-cli generated seam.

This is the coordination subset only (per-table counts + TDA Rule 11D
halt/resume decisions). The tournament's own single-aggregate lifecycle
(registration, blind levels, eliminations, payouts, …) is a separate port.
"""

from .handler import TournamentAggregate

__all__ = ["TournamentAggregate"]
