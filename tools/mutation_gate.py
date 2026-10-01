"""Fail unless mutmut killed at least the given share of its mutants.

Usage: python tools/mutation_gate.py mutants/mutmut-cicd-stats.json 90
"""

from __future__ import annotations

import json
import sys


def main(stats_path: str, threshold: float) -> int:
    with open(stats_path) as handle:
        stats = json.load(handle)
    total = stats["total"]
    killed = stats["killed"] + stats.get("timeout", 0)
    if total == 0:
        print("no mutants were generated")
        return 1
    rate = 100.0 * killed / total
    print(
        f"killed {killed}/{total} mutants ({rate:.1f}%); survived {stats['survived']}, no tests {stats.get('no_tests', 0)}"
    )
    if rate < threshold:
        print(f"FAIL: below the {threshold:.0f}% kill rate")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], float(sys.argv[2])))
