"""mutation_gate: the kill-rate verdict over mutmut's recorded results."""

from __future__ import annotations

import json

from mutation_gate import main


def write_meta(root, codes):
    """One mutated source's meta file, as mutmut writes it."""
    meta = root / "mutants" / "src" / "pkg" / "logic.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"exit_code_by_key": codes}))
    return str(root / "mutants")


def keys(codes):
    return {f"pkg.logic.x_double__mutmut_{n}": code for n, code in enumerate(codes, 1)}


def test_every_mutant_killed_passes(tmp_path, capsys):
    mutants = write_meta(tmp_path, keys([1] * 10))
    assert main(mutants, 90) == 0
    assert "killed 10/10" in capsys.readouterr().out


def test_a_mutant_never_checked_fails_though_the_rate_clears(tmp_path, capsys):
    # Ten of eleven killed is over 90%, but the eleventh never ran.
    mutants = write_meta(tmp_path, keys([1] * 10 + [None]))
    assert main(mutants, 90) == 1
    assert "11 mutants found but 10 tested" in capsys.readouterr().out


def test_an_unchecked_mutant_outside_the_globs_is_not_judged(tmp_path):
    codes = keys([1] * 10)
    codes["pkg.logic.x_halve__mutmut_1"] = None
    mutants = write_meta(tmp_path, codes)
    assert main(mutants, 90, ["pkg.logic.x_double__mutmut_*"]) == 0


def test_no_mutants_fails(tmp_path):
    assert main(write_meta(tmp_path, {}), 90) == 1
