#!/usr/bin/env python
"""Test runner that executes all test suites from their correct directories.

This handles the module path issues by running pytest from each test's directory.
"""

import os
import subprocess
import sys
from pathlib import Path

# Test suites with their directories and test patterns
TEST_SUITES = [
    # (directory, test_files, description)
    ("player/agg", ["test_handlers.py"], "Player aggregate"),
    ("table/agg/handlers", ["test_table.py"], "Table aggregate"),
    ("hand/agg/handlers", ["test_hand.py", "test_game_rules.py"], "Hand aggregate"),
    ("tournament/agg", ["test_handlers.py"], "Tournament aggregate"),
    ("buy_in/pmg", ["test_handlers.py"], "Buy-in PM"),
    ("rebuy/pmg", ["test_handlers.py"], "Rebuy PM"),
    ("registration/pmg", ["test_handlers.py"], "Registration PM"),
]


def run_tests(verbose: bool = False) -> int:
    """Run all test suites.

    Returns:
        Exit code (0 for success, 1 for failures).
    """
    root = Path(__file__).parent
    total_passed = 0
    total_failed = 0
    failed_suites = []

    for directory, test_files, description in TEST_SUITES:
        test_dir = root / directory
        if not test_dir.exists():
            print(f"⚠️  Skipping {description}: directory not found")
            continue

        print(f"\n{'='*60}")
        print(f"Running {description} tests...")
        print(f"{'='*60}")

        cmd = ["uv", "run", "pytest"] + test_files
        if verbose:
            cmd.append("-v")
        cmd.append("--tb=short")

        # Set PYTHONPATH to include the test directory for local imports
        existing_path = os.environ.get("PYTHONPATH", "")
        new_path = f".:{existing_path}" if existing_path else "."
        env = {**os.environ, "PYTHONPATH": new_path}
        result = subprocess.run(
            cmd,
            cwd=test_dir,
            capture_output=not verbose,
            text=True,
            env=env,
        )

        if result.returncode == 0:
            # Parse passed count from output
            if verbose:
                print("✅ PASSED")
            else:
                # Extract summary from last line
                lines = result.stdout.strip().split("\n")
                for line in reversed(lines):
                    if "passed" in line:
                        print(f"✅ {line.strip()}")
                        break
        else:
            failed_suites.append(description)
            if not verbose:
                print(f"❌ FAILED")
                print(result.stdout)
                print(result.stderr)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    if failed_suites:
        print(f"❌ Failed suites: {', '.join(failed_suites)}")
        return 1
    else:
        print("✅ All test suites passed!")
        return 0


if __name__ == "__main__":
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    sys.exit(run_tests(verbose))
