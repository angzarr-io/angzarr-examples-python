"""Reroot the generated protobuf imports under the packages they live in.

The protocolbuffers/python and grpc/python plugins import other proto files
by path (``from io.angzarr.v1 import types_pb2``), which cannot be imported
as written (``io`` is the stdlib module). Each import whose module starts
with a mapped prefix (longest first) is rewritten to its package; ``google.*``
is never mapped (protobuf runtime, googleapis-common-protos).

    fixup_gen_imports.py <gen dir> <from>=<to> [<from>=<to> ...]
"""

from __future__ import annotations

import pathlib
import re
import sys

GLOBS = ("*_pb2.py", "*_pb2.pyi", "*_pb2_grpc.py")


def fixup(gen_dir: pathlib.Path, mapping: dict[str, str]) -> int:
    """Rewrite the mapped imports under ``gen_dir``; the number of files changed."""
    prefixes = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(
        r"^(\s*)(from|import) (" + "|".join(map(re.escape, prefixes)) + r")(?=[.\s])",
        re.MULTILINE,
    )
    changed = 0
    for glob in GLOBS:
        for path in gen_dir.rglob(glob):
            text = path.read_text()
            new = pattern.sub(lambda m: f"{m[1]}{m[2]} {mapping[m[3]]}", text)
            if new != text:
                path.write_text(new)
                changed += 1
    return changed


def main(argv: list[str]) -> int:
    gen_dir = pathlib.Path(argv[0])
    mapping = dict(arg.split("=", 1) for arg in argv[1:])
    print(f"rerooted imports in {fixup(gen_dir, mapping)} file(s) under {gen_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
