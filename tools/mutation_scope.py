"""Name the mutants a push's changed files can carry, for a diff-scoped run.

Given a uv project's directory (holding the ``[tool.mutmut]`` table mutmut
reads) and the repository-relative paths a push changed, prints one mutmut
name glob per changed module mutmut mutates (``angzarr_player.strategy.*``),
judged by the project's own ``paths_to_mutate`` and ``do_not_mutate``. A
module mutmut finds no mutant in (constants only), or one the push deleted,
names nothing: mutmut refuses a glob that matches no mutant. Prints nothing
when the push changes no module with mutants.

Run from the repository root in an environment holding mutmut, which counts
each module's mutants: python tools/mutation_scope.py player <changed path> [...]
"""

from __future__ import annotations

import fnmatch
import io
import sys
import tomllib
from pathlib import Path, PurePosixPath

from mutmut.__main__ import write_all_mutants_to_file


def _has_mutants(path: Path) -> bool:
    if not path.is_file():
        return False
    names, _ = write_all_mutants_to_file(
        out=io.StringIO(), source=path.read_text(), filename=str(path)
    )
    return bool(names)


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
            if not _has_mutants(Path(path)):
                continue
            glob = ".".join(module.with_suffix("").parts) + ".*"
            if glob not in globs:
                globs.append(glob)
    return globs


if __name__ == "__main__":
    print(" ".join(scope(sys.argv[1], sys.argv[2:])))
