# Angzarr blackjack example (Python)

A small blackjack table built on the [angzarr](https://angzarr.io/) CQRS/ES
framework. Python is the structural template the Go, Java, C#, C++ and Rust
examples mirror. The specification — protos, house rules and scenarios —
lives in the `angzarr-project` submodule:

- protos: `angzarr-project/proto/io/angzarr/examples/v1/`
- house rules AHR-1..13 and ledger invariants L1..L4:
  `angzarr-project/features/example/blackjack/RULES.md`
- scenarios: `features/example/blackjack/` (rules),
  `blackjack-framework/` (framework concepts, in process) and
  `blackjack-acceptance/` (deployed cluster)

## Components

This branch carries only the **stage-1 slice** of the example, on the spec at
`angzarr-project` 541cadc: `CreateTable` records `TableCreated` and the first
`ShoeShuffled`.

| Deployable | Package | What it is |
|---|---|---|
| `agg-table` | `table/agg` | Creating a table and shuffling its first shoe; the configuration rule (AHR-1) is in `rules.py` |

All live under `src/angzarr_blackjack/`. `cards.py` holds the deterministic
shoe (SplitMix64 + Fisher–Yates, exactly as `cards.proto` pins it) and the
card notation the scenarios use.

The in-process tier runs table creation (EU-1440..1442) and the golden shoe
vectors (EU-1520..1525); every other scenario in the submodule is skipped.

### Waiting on blackjack rulings R1-R4

The rest of the example waits on the open rulings in
`angzarr-project/docs/design/blackjack-latest-proto-rulings.md` (R1 top-up
compensation, R2 buy-in refusals into pmg-buy-in, R3 saga-injected facts, R4
cascade replies). It is not ported or stubbed here; its last version is
`feat/blackjack` 8647b82:

- the wallet `agg-player` and its upcaster, `pmg-buy-in`,
  `saga-player-table`, `saga-table-player` and
  `projector-player-table-ledger`;
- the table's seats, chips, bets, rounds and settlement (the
  `TableAggregateHandler` methods other than `create_table` and the
  `TableCreated` / `ShoeShuffled` appliers; a command for them fails as an
  internal error), and the hand-value and round rules;
- the in-process steps for every scenario outside the slice, and the
  cluster acceptance tier (`acceptance_steps/`, `just
  test-example-acceptance`, `just acceptance-dry-run`, `just
  acceptance-local`, `just demo-session` and CI's acceptance job).

## Setup

The CLI is built from a source checkout. angzarr-client is pinned to a git
revision (`pyproject.toml`); installing it builds its router library, so
`cargo` must be on PATH:

```bash
export ANGZARR_CLI_SRC=../../angzarr-cli/main
just -f justfile.container ci-setup     # cli-build, proto-gen, uv sync
```

Each deployable's `main.register(host)` adds its component to an
angzarr-client `ComponentHost`, which serves it over gRPC; `main()` runs that
host on `$PORT`. The host refuses to start without the build's
`rules_version`, and `main()` does not give one yet, so `just run agg-table`
stops with `MISSING_RULES_VERSION` until a version source is chosen.

## Tests

```bash
just test                  # native unit tests + the stage-1 scenarios
just test-unit             # pytest: exact rejection codes, golden shoes, the table through the router
just test-example-unit     # behave: EU-1440..1442 and EU-1520..1525
just mutation-test         # mutmut, 90% kill gate
```

The in-process tier (`unit_steps/`) runs every component on one router; its
`World` plays the coordinator in memory. Undefined or pending steps fail the
run. Entity roots are `uuid5(NAMESPACE_OID, "<kind>:<label>")`.

## Cluster

```bash
just up                         # kind cluster, secrets, postgres/rabbitmq, skaffold run
just down
```

`just core-images` then `just deploy-apps-local` deploy against the
coordinators and chart of a core checkout (`ANGZARR_CORE_SRC`, default
`../../core/main`; skaffold profile `local-core`). The cluster acceptance
tier waits on the rulings above.

## License

BSD-3-Clause
