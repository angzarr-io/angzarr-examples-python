"""mutation_scope: the mutant name globs a push's changed paths carry."""

from __future__ import annotations

import textwrap

import pytest

from mutation_scope import scope

CONFIG = """
[tool.mutmut]
paths_to_mutate = ["src/"]
do_not_mutate = ["src/pkg/_gen/*", "*/main.py", "*/__init__.py"]
"""

LOGIC = "def double(x):\n    return x * 2\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository holding a project at ``app/`` and one at its root."""
    monkeypatch.chdir(tmp_path)

    def write(path: str, text: str) -> None:
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(textwrap.dedent(text))

    for project in ("app/", ""):
        write(project + "pyproject.toml", CONFIG)
        write(project + "src/pkg/logic.py", LOGIC)
        write(project + "src/pkg/main.py", LOGIC)
        write(project + "src/pkg/__init__.py", LOGIC)
        write(project + "src/pkg/_gen/wire.py", LOGIC)
        write(project + "src/pkg/sub/rules.py", LOGIC)
        write(project + "src/pkg/constants.py", "LIMIT = 7\nNAMES = ('a', 'b')\n")
    return write


def test_a_changed_module_with_mutants_is_named(repo):
    assert scope("app", ["app/src/pkg/logic.py", "app/src/pkg/sub/rules.py"]) == [
        "pkg.logic.*",
        "pkg.sub.rules.*",
    ]


def test_the_root_project_is_named_by_its_own_paths(repo):
    assert scope(".", ["src/pkg/logic.py", "app/src/pkg/logic.py"]) == ["pkg.logic.*"]


def test_a_module_named_twice_is_named_once(repo):
    assert scope("app", ["app/src/pkg/logic.py", "app/src/pkg/logic.py"]) == [
        "pkg.logic.*"
    ]


@pytest.mark.parametrize(
    "path",
    [
        "app/src/pkg/main.py",  # do_not_mutate
        "app/src/pkg/__init__.py",  # do_not_mutate
        "app/src/pkg/_gen/wire.py",  # do_not_mutate
        "app/tests/test_logic.py",  # not under paths_to_mutate
        "app/README.md",  # not Python
        "other/src/pkg/logic.py",  # another project
    ],
)
def test_a_path_mutmut_does_not_mutate_names_nothing(repo, path):
    assert scope("app", [path]) == []


def test_a_mutated_module_with_nothing_to_mutate_names_nothing(repo):
    """mutmut refuses a name glob matching no mutant ("nothing matches"), so
    a module it mutates but finds no mutant in is no mutant of the push."""
    assert scope("app", ["app/src/pkg/constants.py"]) == []


def test_a_deleted_module_names_nothing(repo):
    assert scope("app", ["app/src/pkg/gone.py"]) == []
