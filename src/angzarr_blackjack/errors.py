"""Business rejections, coded as the protos catalogue them.

A rejection that depends on the aggregate's state is FAILED_PRECONDITION; one
that is wrong whatever the state is INVALID_ARGUMENT.
"""

from __future__ import annotations

import angzarr_router_ffi as _az


class Rejection(_az.CodedError):
    """A coded business rejection raised by a guard or validate function."""


def precondition(code: str, message: str) -> Rejection:
    return Rejection(code=code, message=message, grpc=_az.GrpcCode.FAILED_PRECONDITION)


def invalid(code: str, message: str) -> Rejection:
    return Rejection(code=code, message=message, grpc=_az.GrpcCode.INVALID_ARGUMENT)


def status_message(error: _az.CodedError) -> str:
    """The gRPC status message a component reports a coded rejection with:
    the code first, so a rejection reason carries it wherever it travels."""
    return f"{error.code}: {error.message}" if error.code else error.message


def rejection_code(reason: str) -> str:
    """The code at the head of a rejection reason ("WAGER_IN_PLAY: ..."), or
    the whole reason when it carries no code."""
    head, sep, _ = reason.partition(":")
    if sep and head and all(c.isupper() or c.isdigit() or c == "_" for c in head):
        return head
    return reason.strip()
