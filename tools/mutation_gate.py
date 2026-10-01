"""Fail unless mutmut killed at least the given share of its mutants.

Reads the per-file results mutmut writes next to each mutated source
(``mutants/**/*.py.meta``), classified with mutmut's own exit-code table.

Usage: python tools/mutation_gate.py mutants 90
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from mutmut.__main__ import status_by_exit_code


def main(mutants_dir: str, threshold: float) -> int:
    outcomes: Counter = Counter()
    for meta in Path(mutants_dir).rglob("*.py.meta"):
        for code in json.loads(meta.read_text())["exit_code_by_key"].values():
            outcomes[status_by_exit_code.get(code, f"exit {code}")] += 1
    total = sum(outcomes.values())
    if total == 0:
        print("no mutants were generated")
        return 1
    rate = 100.0 * outcomes["killed"] / total
    print(f"killed {outcomes['killed']}/{total} ({rate:.1f}%): {dict(outcomes)}")
    if rate < threshold:
        print(f"FAIL: below the {threshold:.0f}% kill rate")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], float(sys.argv[2])))
