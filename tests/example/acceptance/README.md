# tests/example/acceptance — Python step defs for acceptance-example tier

Implements the scenarios in
[`angzarr-project/features/example/acceptance/`](../../../angzarr-project/features/example/acceptance/)
using behave.

## What's here

- `environment.py` — creates the `CommandClient` (in-process or gRPC) in
  `before_all`, resets per-scenario state in `before_scenario`
- `steps/` — step definitions:
  - `player_steps.py`, `table_steps.py`, `hand_steps.py` — domain-level flow
  - `sync_steps.py` — ASYNC/SIMPLE/CASCADE mode assertions + CascadeErrorMode
  - `common_steps.py` — shared phrasings, `pack_command`, retry helpers
  - `__init__.py` — marks the dir as a package for relative imports

## Style

Live stack via the `CommandClient` abstraction. Two backends, same step defs:

| Backend | Activated by | Use case |
|---------|-----|----------|
| `InProcessClient` | default | Dev loop; fast; no network |
| `GrpcClient` | `PLAYER_URL=<host:port>` set | Live sidecars (standalone/kind/cluster) |

The backend is chosen in `environment.py`'s `before_all` — step defs never
import the concrete client class.

**Async assertions.** Use `within N seconds` (typically 2–5s) to observe
cross-domain saga propagation. See
[STEP_VOCABULARY.md §4](../../../angzarr-project/features/STEP_VOCABULARY.md).

## Running

```bash
# From examples-python/main/

# Default: InProcessClient
just test-example-acceptance

# Against a live sidecar
PLAYER_URL=localhost:1310 just test-example-acceptance
```

Behind the scenes:

```bash
PLAYER_URL="${PLAYER_URL:-}" uv run behave angzarr-project/features/example/acceptance/ \
  --steps-dir tests/example/acceptance/steps \
  --environment-file tests/example/acceptance/environment.py \
  --tags="~@wip"
```

Feature files read directly from the `angzarr-project/` submodule — no
symlinks.

## CI

`.github/workflows/ci.yml` runs this tier against a kind cluster with
port-forwards for `player-aggregate`, `table-aggregate`, `hand-aggregate`.
`PLAYER_URL`/`TABLE_URL`/`HAND_URL` are set to `localhost:131N`.

## Adding a scenario

1. Add the scenario in
   [`angzarr-project/features/example/acceptance/<file>.feature`](../../../angzarr-project/features/example/acceptance/),
   allocate the next `@EA-NNNN` ID
2. Decide whether it needs to pass in both InProcess and gRPC backends —
   usually yes. Avoid backend-specific assumptions (e.g. don't assume DB
   persistence across commands)
3. Land the angzarr-project PR
4. Bump the submodule pointer here
5. Implement the step defs
6. Verify in both modes: `just test-example-acceptance` and
   `PLAYER_URL=localhost:1310 just test-example-acceptance` (after bringing
   up standalone or kind)
