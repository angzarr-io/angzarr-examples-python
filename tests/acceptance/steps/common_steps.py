"""Common step definitions for acceptance tests.

Provides shared utilities and the Background step that all scenarios use.
"""

import uuid

from behave import given, use_step_matcher
from google.protobuf.any_pb2 import Any as ProtoAny


use_step_matcher("re")


def new_uuid_bytes() -> bytes:
    """Generate a new random UUID and return its bytes."""
    return uuid.uuid4().bytes


def pack_command(msg, type_name: str) -> ProtoAny:
    """Pack a protobuf message into an Any with the given type name."""
    return ProtoAny(
        type_url=f"type.googleapis.com/{type_name}",
        value=msg.SerializeToString(),
    )


def proto_uuid(raw_bytes: bytes):
    """Convert raw bytes to a proto UUID message."""
    from angzarr_client.proto.angzarr import UUID

    return UUID(value=raw_bytes)


@given(r"the poker system is running in standalone mode")
def step_given_system_running(context):
    """Verify/acknowledge the system is available.

    For InProcessClient this is always true.
    For GrpcClient this could do a connectivity check.
    """
    # The client was already created in environment.py before_all.
    assert hasattr(context, "client"), "CommandClient not initialized"
