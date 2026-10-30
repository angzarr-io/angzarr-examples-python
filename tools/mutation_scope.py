"""Name the mutants a push's changed files can carry, for a diff-scoped run.

Given a uv project's directory (holding the ``[tool.mutmut]`` table mutmut
reads) and the repository-relative paths a push changed, prints one mutmut
name glob per changed module mutmut mutates (``angzarr_player.strategy.*``),
judged by the project's own ``paths_to_mutate`` and ``do_not_mutate``. Prints
nothing when the push changes no mutated module.

Usage: python tools/mutation_scope.py player <changed path> [...]
"""

from __future__ import annotations

import fnmatch
import sys
import tomllib
from pathlib import PurePosixPath


def scope(project: str, changed: list[str]) -> list[str]:
    root = PurePosixPath(project)
    with open(root / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)["tool"]["mutmut"]
    globs = []
    for path in changed:
        try:
            rel = PurePosixPath(path).relative_to(root)
        except ValueError:
            continue
        if rel.suffix != ".py":
            continue
        for base in config["paths_to_mutate"]:
            base = PurePosixPath(base)
            try:
                module = rel.relative_to(base)
            except ValueError:
                continue
            if any(
                fnmatch.fnmatch(str(rel), p) for p in config.get("do_not_mutate", [])
            ):
                continue
            glob = ".".join(module.with_suffix("").parts) + ".*"
            if glob not in globs:
                globs.append(glob)
    return globs


if __name__ == "__main__":
    print(" ".join(scope(sys.argv[1], sys.argv[2:])))
