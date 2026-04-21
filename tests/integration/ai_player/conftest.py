"""Integration-test fixtures for AiSidecar.

Boots the real production container image (built from ai_player/Containerfile)
on an ephemeral port, waits for gRPC readiness, and yields a grpc.Channel
plus address. The container is the subject under test — these are not unit
tests; they verify the cross-language-callable contract on the running image.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

# Add the ai_player generated proto dir so `from examples import ...` resolves,
# and the parent so the ai_player package imports resolve too.
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "ai_player" / "proto"))

from ai_player.proto.examples import ai_sidecar_pb2, ai_sidecar_pb2_grpc  # noqa: E402

AI_IMAGE = os.environ.get(
    "AI_IMAGE", "ghcr.io/angzarr-io/poker-python-ai-player:latest"
)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_ready(address: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with grpc.insecure_channel(address) as ch:
                grpc.channel_ready_future(ch).result(timeout=2.0)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"sidecar at {address} never became ready: {last_err}")


@pytest.fixture(scope="session")
def sidecar_address() -> Iterator[str]:
    """Run the AiSidecar container for the session. Address is host:port."""
    if shutil.which("docker") is None:
        pytest.skip("docker not available on PATH")

    # Ensure the image exists locally. Try to pull if missing; if the pull
    # fails (offline, no registry auth), skip — the caller should have built
    # it via `just build-ai-image` or `just build-images`.
    inspect = subprocess.run(
        ["docker", "image", "inspect", AI_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode != 0:
        pytest.skip(
            f"{AI_IMAGE} not present locally; "
            f"run `just build-ai-image` or `docker pull {AI_IMAGE}`"
        )

    host_port = _pick_free_port()
    address = f"localhost:{host_port}"

    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-p",
            f"{host_port}:50500",
            AI_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        pytest.fail(f"docker run failed: {run.stderr}")
    container_id = run.stdout.strip()

    try:
        _wait_ready(address)
        yield address
    finally:
        subprocess.run(
            ["docker", "stop", container_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@pytest.fixture()
def channel(sidecar_address):
    with grpc.insecure_channel(sidecar_address) as ch:
        yield ch


@pytest.fixture()
def stub(channel):
    return ai_sidecar_pb2_grpc.AiSidecarStub(channel)


@pytest.fixture()
def pb():
    return ai_sidecar_pb2
