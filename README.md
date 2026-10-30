# Angzarr blackjack example (Python)

The Python side of the blackjack example built on the
[angzarr](https://angzarr.io/) CQRS/ES framework: the **player** domain
(`player/`), a Python aggregate that angzarr-embedded launches as a child
process. The blackjack table is the Rust one, in
[angzarr-examples-rust](https://github.com/angzarr-io/angzarr-examples-rust).
The specification — protos, house rules and scenarios — lives in
[angzarr-project](https://github.com/angzarr-io/angzarr-project):

- protos: `proto/io/angzarr/examples/v1/`
- house rules AHR-1..13 and ledger invariants L1..L4:
  `features/example/blackjack/RULES.md`

## The player

`player/` is its own uv project (`player/pyproject.toml`, `player/justfile`),
run on the host: uv provides Python, and installing angzarr-client (pinned to
a git revision) builds its router library, so `cargo` must be on PATH.
`angzarr scaffold python` (the Rust angzarr CLI, pinned in `player/justfile`)
wrote it and rewrites its generated files (`just --justfile player/justfile
scaffold`); `logic_impl.py`, `strategy.py` and the tests are the player's own.

```bash
just --justfile player/justfile install         # the locked environment
just --justfile player/justfile test            # pytest
just --justfile player/justfile mutation-test   # mutmut, 90% kill gate
```

## The repository root

The root holds only tooling: its own uv environment (`pyproject.toml`) with
the formatter and linter run over the player and the tests of `tools/`
(`mutation_scope.py` and `mutation_gate.py`, which the player's mutation
recipe uses). Its recipes run in the dev container (`justfile` delegates to
`justfile.container`; CI runs `just -f justfile.container ...` directly):

```bash
just install               # the root's tooling environment
just test                  # the tests of tools/
just lint                  # ruff over tools/ and the player
just fmt-fix               # ruff --fix and black over the same
just push-check origin     # pre-push: every test (root and player) of each pushed commit; red refused on main only
```

## Git hooks

lefthook (`lefthook.yml`) runs, before each commit, the submodule and secret
guards, the formatter, and every test: the root's (`just test-commit`) and the
player's (`just --justfile player/justfile test-commit`). Red tests are
allowed on a branch and never reach the default branch: committed off it,
failing tests pass with a warning; committed on it, or in a merge commit, they
fail. Before each push, `just push-check` runs every test in the pushed
commit's own tree and refuses a push to the default branch whose tests fail.
No hook runs mutation testing; CI runs it on a schedule
(`.github/workflows/mutation.yml`).

## License

BSD-3-Clause
