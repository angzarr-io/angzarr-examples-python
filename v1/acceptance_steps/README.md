# acceptance_steps/ — Python step defs for acceptance-example tier

Implements the scenarios in
[`angzarr-project/features/example/acceptance/`](../angzarr-project/features/example/acceptance/)
using behave.

## Layout

Behave's `--stage acceptance` resolves two siblings at the repo root
(`examples-python/main/`), via walk-up from the submodule's feature files:

- [`acceptance_environment.py`](../acceptance_environment.py) — builds the
  `CommandClient` (gRPC) in `before_all`, resets per-scenario state in
  `before_scenario`
- `acceptance_steps/` (this directory) — step definitions:
  - `player_steps.py`, `table_steps.py`, `hand_steps.py` — domain-level flow
  - `tournament_steps.py`, `reservation_steps.py`, `cluster_steps.py` —
    cluster-only coordination
  - `sync_steps.py` — ASYNC/SIMPLE/CASCADE mode assertions + CascadeErrorMode
  - `common_steps.py` — shared phrasings, `pack_command`, retry helpers

## Style

Live stack via the `CommandClient` — a gRPC client that routes commands by
domain to running coordinators. Step defs never construct aggregates or
call handler functions directly; every command goes over the wire.

| Target | `PLAYER_URL` example | Use case |
|---|---|---|
| Standalone | `localhost:1310` after `docker-compose up` | Local cluster validation |
| kind | `localhost:1310` after port-forward | CI `kind` jobs |
| Remote cluster | `<ingress>:<port>` | Pre-release against real cluster |

If `PLAYER_URL` is unset, the client defaults to `localhost:1310`.

**Async assertions.** Use `within N seconds` (typically 2–5s) to observe
cross-domain saga propagation. See
[STEP_VOCABULARY.md §4](../angzarr-project/features/STEP_VOCABULARY.md).

## Running

```bash
# From examples-python/main/ — requires a running coordinator
PLAYER_URL=localhost:1310 just test-example-acceptance
```

Behind the scenes:

```bash
PLAYER_URL="${PLAYER_URL:-localhost:1310}" uv run behave --stage acceptance \
  angzarr-project/features/example/acceptance/ --tags="~@wip"
```

Feature files read directly from the `angzarr-project/` submodule — no
symlinks, no copies.

## CI

`.github/workflows/ci.yml` runs this tier against a kind cluster with
port-forwards for `player-aggregate`, `table-aggregate`, `hand-aggregate`.
`PLAYER_URL`/`TABLE_URL`/`HAND_URL` are set to `localhost:131N`.

## Adding a scenario

1. Add the scenario in
   [`angzarr-project/features/example/acceptance/<file>.feature`](../angzarr-project/features/example/acceptance/),
   allocate the next `@EA-NNNN` ID
2. Land the angzarr-project PR
3. Bump the submodule pointer here (`just bump-angzarr-project`)
4. Implement the step defs in the matching `*_steps.py`
5. Verify against a live cluster:
   `PLAYER_URL=localhost:1310 just test-example-acceptance` (after bringing
   up standalone or kind)
