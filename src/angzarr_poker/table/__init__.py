"""Table bounded context: the Table aggregate ported onto the angzarr-cli
generated harness seam.

``handler`` carries the business rules (the ``TableAggregateHandler`` Protocol
implementation); ``main`` wires the aggregate into an in-process router via the
generated ``register_table_aggregate`` helper.
"""

from .handler import TableAggregate

__all__ = ["TableAggregate"]
