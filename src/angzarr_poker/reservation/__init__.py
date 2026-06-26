"""Reservation bounded context: the Reservation aggregate ported onto the
angzarr-cli generated harness seam.

The reservation aggregate owns the lifecycle *records* for the three two-phase
fund-commitment flows — buy-in, rebuy, tournament registration. Each flow has the
same shape: ``Initiate*`` opens a pending record, ``Confirm*`` closes it on
success, ``Release*`` closes it on failure. It records intent only; it does NOT
check the player's funds — that invariant belongs to the player aggregate, which
the reservation process manager drives via ``ReserveFunds`` / ``DeductReservedFunds``
/ ``ReleaseFunds`` and which rejects on its own when funds are short.
"""

from .aggregate.handler import ReservationAggregate

__all__ = ["ReservationAggregate"]
