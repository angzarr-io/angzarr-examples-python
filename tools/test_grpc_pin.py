"""The grpcio-tools that builds angzarr-client is the grpcio uv.lock installs.

angzarr-client's build generates its *_pb2_grpc.py modules with grpcio-tools,
and they refuse to import on a grpcio older than the generating version, so
pyproject.toml pins the build's grpcio-tools (``[tool.uv]
build-constraint-dependencies``) to the locked grpcio.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> dict:
    return tomllib.loads((ROOT / name).read_text())


def _pinned_grpcio_tools() -> str:
    constraints = _load("pyproject.toml")["tool"]["uv"]["build-constraint-dependencies"]
    pins = [
        c.removeprefix("grpcio-tools==")
        for c in constraints
        if c.startswith("grpcio-tools==")
    ]
    assert len(pins) == 1, f"one exact grpcio-tools pin expected, got {constraints}"
    return pins[0]


def _locked(name: str) -> str:
    versions = [p["version"] for p in _load("uv.lock")["package"] if p["name"] == name]
    assert len(versions) == 1, f"one locked {name} expected, got {versions}"
    return versions[0]


def test_the_build_grpcio_tools_is_the_locked_grpcio():
    assert _pinned_grpcio_tools() == _locked("grpcio")


def test_the_lock_records_the_pin():
    recorded = _load("uv.lock")["manifest"]["build-constraints"]
    assert {
        "name": "grpcio-tools",
        "specifier": f"=={_pinned_grpcio_tools()}",
    } in recorded
