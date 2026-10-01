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

| Deployable | Package | What it is |
|---|---|---|
| `agg-player` | `player/agg` | The wallet (functional: pure `guard`/`validate`/`compute` in `logic.py`), plus the `PlayerUpcaster` on the same server |
| `agg-table` | `table/agg` | Seats, shoe, rounds, dealer and settlement (object-oriented; house rules in `rules.py`) |
| `pmg-buy-in` | `pmg_buy_in` | The buy-in process manager: holds the seat, then the money, then confirms and spends, undoing either half |
| `saga-player-table` | `player/saga_table` | A top-up request becomes AddChips at the table; a refusal is compensated by the wallet |
| `saga-table-player` | `table/saga_player` | Settlement facts (chips added, cash-outs), round history and loyalty, each a saga of its own |
| `projector-player-table-ledger` | `prj_ledger` | The money ledger over both domains and `LedgerQueryService` |

All live under `src/angzarr_blackjack/`. `cards.py` holds the deterministic
shoe (SplitMix64 + Fisher–Yates, exactly as `cards.proto` pins it) and hand
values.

Each component implements the handler interface the angzarr CLI generates from
the protos with angzarr-client-python's codegen templates
(`src/angzarr_blackjack/_gen`, not committed) and is registered on the router
binding `angzarr_client.router`; framework protos come from
`angzarr_client.proto`. `_runtime/` hosts each component behind its framework
gRPC service; commands, rejections, undo, facts and `Replay` all dispatch
through the binding, and handlers read the cover they are handling from their
context (`cctx.cover`, a `PageContext`, or `angzarr_client.router.current_cover()`).

## Setup

The CLI is built from a source checkout; angzarr-client is not released yet,
so `client-setup` checks out angzarr-client-python at the pinned revision
(`.deps/angzarr-client-python`) and builds its framework protos and router
library, and the project depends on that checkout:

```bash
export ANGZARR_CLI_SRC=../../angzarr-cli/main
just -f justfile.container ci-setup     # cli-build, client-setup, install
```

## Tests

```bash
just test                  # native unit tests + every in-process scenario
just test-unit             # pytest: exact rejection codes, golden shoes, L1/L2 properties
just test-example-unit     # behave: blackjack + blackjack-framework scenarios
just acceptance-dry-run    # every cluster scenario parses and resolves its steps
just mutation-test         # mutmut, 90% kill gate
```

The in-process tier (`unit_steps/`) runs every component on one router; its
`World` plays the coordinators in memory. Undefined or pending steps fail the
run. Entity roots are `uuid5(NAMESPACE_OID, "<kind>:<label>")`.

## Cluster

```bash
just up                         # kind cluster, secrets, postgres/rabbitmq, skaffold run
just test-example-acceptance    # required cluster scenarios
just demo-session 5             # a basic-strategy player plays five rounds
just down
```

The acceptance tier reads `PLAYER_URL` (default `localhost:31320`),
`TABLE_URL` (`localhost:31321`) and `LEDGER_URL` (`localhost:31325`), and
watches the event bus (`AMQP_URL`, or `secret/angzarr-mq` through a
port-forward). Scenarios tagged `@needs-core-X-NNN` wait on a framework fix
and are excluded from the required run.

## License

BSD-3-Clause
