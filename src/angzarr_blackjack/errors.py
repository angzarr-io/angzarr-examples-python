"""Business rejections, coded as the protos catalogue them.

A rejection that depends on the aggregate's state is FAILED_PRECONDITION; one
that is wrong whatever the state is INVALID_ARGUMENT.
"""

from __future__ import annotations

import angzarr_client.router as _az


class Rejection(_az.CodedError):
    """A coded business rejection raised by a guard or validate function."""


def precondition(code: str, message: str) -> Rejection:
    return Rejection(code=code, message=message, grpc=_az.GrpcCode.FAILED_PRECONDITION)


def invalid(code: str, message: str) -> Rejection:
    return Rejection(code=code, message=message, grpc=_az.GrpcCode.INVALID_ARGUMENT)
