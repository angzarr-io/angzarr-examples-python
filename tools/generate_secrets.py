"""Generate cryptographically random passwords for the kind cluster's
angzarr deployment and emit them as a Kubernetes Secret manifest on stdout.

Invocation (via ``just seed-secrets``):

    uv run python tools/generate_secrets.py \
        --namespace angzarr \
        --name angzarr-credentials

The resulting manifest is piped through ``kubectl apply -f -`` so the
generated passwords only ever exist in the cluster's Secret and (briefly)
in the process stdout — they are never written to a file under version
control. Subsequent helm deploys read the same Secret keys.

The script is intentionally zero-dependency (stdlib only) so it runs
with whatever Python the container uses, no ``uv sync`` required.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import string
import sys

DEFAULT_KEYS = ("db-password", "mq-password")
# Symbols omitted intentionally: angzarr-db / angzarr-mq consume the
# password via a URL (``postgres://user:password@host``), and URL-encoding
# the password complicates the deploy recipe with no security win. Alnum
# @ 32 chars is >190 bits of entropy — ample.
_ALPHABET = string.ascii_letters + string.digits


def _generate_password(length: int) -> str:
    """Return a cryptographically random password of ``length`` chars."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def build_manifest(
    *,
    namespace: str,
    name: str,
    keys: tuple[str, ...],
    length: int,
) -> dict:
    """Return a Kubernetes Secret manifest dict with freshly-generated values."""
    data = {key: _b64(_generate_password(length)) for key in keys}
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "data": data,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="angzarr")
    parser.add_argument("--name", default="angzarr-credentials")
    parser.add_argument(
        "--keys",
        nargs="+",
        default=list(DEFAULT_KEYS),
        help="Secret keys to generate. Default: %(default)s",
    )
    parser.add_argument(
        "--length", type=int, default=32, help="Password length (default: %(default)s)"
    )
    parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="Output format. yaml is the default so the manifest pipes into kubectl apply -f -.",
    )
    return parser.parse_args(argv)


def _to_yaml(manifest: dict) -> str:
    """Minimal YAML serializer for the fixed Secret shape — avoids a PyYAML dep."""
    lines = [
        f"apiVersion: {manifest['apiVersion']}",
        f"kind: {manifest['kind']}",
        f"type: {manifest['type']}",
        "metadata:",
        f"  name: {manifest['metadata']['name']}",
        f"  namespace: {manifest['metadata']['namespace']}",
        "data:",
    ]
    for key, value in manifest["data"].items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    manifest = build_manifest(
        namespace=args.namespace,
        name=args.name,
        keys=tuple(args.keys),
        length=args.length,
    )
    if args.format == "json":
        sys.stdout.write(json.dumps(manifest, indent=2) + "\n")
    else:
        sys.stdout.write(_to_yaml(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
