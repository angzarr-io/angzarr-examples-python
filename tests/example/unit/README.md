# tests/example/unit — Python step defs for unit-example tier

Implements the scenarios in
[`angzarr-project/features/example/unit/`](../../../angzarr-project/features/example/unit/)
using behave.

## What's here

- `environment.py` — behave `before_scenario` hook resetting per-scenario
  context
- `steps/` — step definitions, one file per aggregate/component:
  - `hand_steps.py`, `player_steps.py`, `table_steps.py` — aggregate handlers
  - `saga_steps.py`, `process_manager_steps.py`, `projector_steps.py` —
    cross-domain components
  - `orchestration_steps.py` — BuyIn / Registration / Rebuy orchestrators
  - `merge_strategy_steps.py`, `fact_flow_steps.py` — scenario support
  - `common_steps.py` — shared phrasings used across multiple files

## Style

Direct handler invocation. In-memory state. Synchronous.

- Scenarios construct state via builders / event replay (`apply_events`)
- Commands dispatched by invoking `handler(cmd, state)` directly
- Assertions inspect the returned `EventBook`, `state` struct, or emitted
  commands
- No `CommandClient`, no running sidecar, no `within N seconds`

If an assertion needs the real router or live cross-domain propagation, the
scenario belongs in [`../acceptance/`](../acceptance/), not here.

## Running

```bash
# From examples-python/main/
just test-example-unit
```

Behind the scenes:

```bash
uv run behave angzarr-project/features/example/unit/ \
  --steps-dir tests/example/unit/steps \
  --environment-file tests/example/unit/environment.py \
  --tags="~@wip"
```

Feature files are read directly from the `angzarr-project/` git submodule —
no symlinks, no copies.

## Adding a scenario

1. **First**: add the scenario in
   [`angzarr-project/features/example/unit/<file>.feature`](../../../angzarr-project/features/example/unit/),
   allocate the next `@EU-NNNN` ID (see [the tier README](../../../angzarr-project/features/example/unit/README.md))
2. Land the angzarr-project PR
3. Bump the submodule pointer here (`git -C angzarr-project checkout <sha>`)
4. Implement the step defs (add/extend in the matching `*_steps.py`)
5. Verify: `just test-example-unit`

Between steps 2 and 4, CI runs red on the new scenario — this is by design
(see the three-tier model's [root README](../../../angzarr-project/features/README.md)).
