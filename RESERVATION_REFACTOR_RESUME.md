# Resume — Outstanding Work

Everything that's shipped is elided. This file only tracks what's left.

## Standalone purge — leftover dust

Core purge shipped. `test-coverage/main/src/standalone/`,
`standalone_integration/` tests, `*.standalone.yaml`, `StandaloneConfig`
/ `ResolvedStandaloneConfig` / `GatewayConfig` / `RegistrationConfig`,
`bin-standalone` bacon jobs, `build-standalone` just recipes,
`poker_game.feature` + `sync_modes.feature`, and terraform
`standalone = bool` field (renamed to `entry_point`) are all gone.
Canonical `angzarr-project/site/` docs scrubbed; `core/main/docs/docs/`
and `test-coverage/main/docs/docs/` mirrors scrubbed via agents
(running at time of resume write — verify complete).

Dust still on the floor:
- Per-language sibling `angzarr-project/` submodule copies
  (`client-cpp`, `client-csharp`, `client-go`, `client-java`,
  `client-python`, `client-rust`, `examples-*`) — still carry their
  own `features/acceptance/poker_game.feature` +
  `sync_modes.feature` and various doc copies. They'll resync when
  their submodule pointer bumps to canonical; leaving for now. The
  `examples-python/angzarr-project/` copy (and its
  `angzarr-client-python/angzarr-project/` twin) were cleaned up —
  see below.
- `.test.rs` comment noise (process, transport, dlq, bus/ipc,
  proto_reflect) — ~8 internal test-file doc comments still say
  "standalone" as historical description. Low priority.
- `core/main/docs/plans/cli-implementation.md` — historical planning
  doc mentions standalone. Skipped.
- `test-coverage/main/.tasks.md` has `[x]` completed-history entries
  referencing the removed code. Left as historical record.

## Rust `Option<&str>` edition plumbing (Task 2 v2)

Storage is already SQL NULL (v1 shipped). Remaining is
code-aesthetic: make the Rust API genuinely optional so `""` isn't
acting as sentinel.

Attempted 2026-04-20 — scope was under-counted. Partial edits to
`SourceInfo` + `EventStore` trait + `storage/helpers` produced ~40
E0053 trait-signature mismatches across the impls (I reverted to a
clean tree). Realistic scope:

- **Seven** `EventStore` impls, not five: `postgres`, `sqlite`,
  `nats`, `immudb`, `mock`, `bigtable`, `dynamo`. Each has ~10
  trait-method signatures + internal bridge logic to propagate
  `Option<&str>` through query builders.
- Each backend handles main-timeline differently today: PG uses
  `edition_to_db()` empty→NULL mapping; SQLite/ImmuDB/BigTable/Dynamo
  use `.eq(DEFAULT_EDITION)` with `"angzarr"` literal — these backends
  need either a bridge (`edition.unwrap_or(DEFAULT_EDITION)` at method
  top) or internal query-builder migration to `IS NULL` predicates.
- `InstrumentedEventStore` wraps ~15 edition-carrying methods in
  `src/advice/instrumented.rs` — mirror of the trait changes.
- `AggregateContext` trait + impls: 5 methods × N impls, each with
  internal `load_prior_events` → `EventStore::get_from` call
  translation.
- Call sites do the right thing already (`cover.edition()` returns
  `Option<&str>`) but currently `.unwrap_or_default().to_string()` to
  satisfy the `&str` API. Refactor simplifies them.
- Tests in `storage/helpers/tests.rs`, `bus/nats/config.rs` has its
  own `DEFAULT_EDITION`, `proto_ext/edition.rs` EditionExt trait needs
  its `is_main_timeline()` method signature updated.
- `client-rust/main/src/proto_ext/constants.rs` has
  `DEFAULT_EDITION = ""` (inverted!) — separate untangling.
- Python `angzarr_client/helpers.py` has its own logic.

Realistic estimate: 600–900 lines across ~30 files. Best done in a
dedicated session with a plan that commits each backend as its own
reviewable change.

## Projector extraction completion

Core is clean of `prj-*` path deps. But the sibling library crates
have no runnable form. For each of `prj-log`, `prj-event`,
`prj-cloudevents`:

- `src/bin/angzarr-prj-<name>.rs` — minimal tonic server (env-var
  port, add the service that the lib already exposes, no angzarr-core
  Config/transport/bootstrap dep).
- `[[bin]]` entry in the sibling's `Cargo.toml`.
- `Containerfile` — rust base → build bin → distroless runtime.
- `skaffold.yaml` or equivalent in each sibling.
- Kind values helm entry when/if you actually want them deployed
  (currently the cluster runs without them).

Only execute this if you need projectors actually running in a pod.

## Unit-test harness gaps (Task 3 analysis)

Shipped 2026-04-20. Final counts (targeted files):

- **hand.feature** — 100/100. Added duplicate-indices guard to
  `RequestDraw`.
- **process_manager.feature** — 42/42. Step defs now dispatch via
  `on_*` (ReservationPM methods); scenarios retargeted to the
  `reservation` domain for confirm/release commands; process-event
  short-name lookup fixed (was splitting on wrong delimiter). The
  `HandFlowPM on_hand_complete emits EndHand` scenario was removed
  — that flow lives in `TableSyncCompleteSaga` and is exercised by
  saga.feature.
- **saga.feature** — 21/21. Step def regexes accept the full
  `angzarr_client.proto.examples.X` qualifier; added step defs for
  `EndHand command has N results` and
  `EndHand command result N has winning_hand populated`; added
  `winners with winning_hand:` given; fixed
  `TableSyncCompleteSaga` to propagate `winning_hand` from
  `PotWinner` onto `PotResult`.
- **poker_game.feature** + **sync_modes.feature** — removed. Their
  coverage belonged to the deleted standalone-mode code path and
  they had no value in the PM-driven layout. Deleted from both
  `angzarr-project/features/example/unit/` and the
  `angzarr-client-python/angzarr-project/` twin.
- **table.feature** — 65/65. `@when` player-id regex relaxed from
  `[^"]+` to `[^"]*` on SeatPlayer and AddRebuyChips steps.
- **tournament.feature** — 55/55. ~40 step defs added (aggregate-
  state assertions, additional given-seeds, rebuild-state step).
  Handler fixes: propagate `hand_root` on `PlayerEliminated`, set
  `total_registrations` on `RegistrationClosed`, populate
  `chips_added` from `rebuy_config.rebuy_chips` on `RebuyProcessed`,
  guard OpenRegistration against running tournaments, guard
  PauseTournament against already-paused, distinct denial reasons
  from `can_rebuy` (not enabled / window closed / max reached), and
  seed a default level-1 `BlindLevel` when `TournamentCreated`
  carries no structure.

Shipped in a follow-up pass:

- **player.feature** EU-0252/EU-0253 — added a
  `I handle a JoinTable rejection notification for table "X"` step def
  that invokes the rejection handler with a synthesized
  `RejectionNotification`, and updated
  `handle_table_join_rejected` + the `@rejected` method on
  `PlayerAggregate` to always emit a `FundsReleased` event (amount 0
  when no matching reservation) rather than returning `None`, so a
  compensation record is always produced. 82/82.

- **projector.feature** 31/31 — rebuilt `prj-output/main.py`'s
  `OutputProjector` as a dual-mode class: it keeps the
  `@projector(name=..., domains=[...])` + `@handles` decorators used
  by the Router, but gains a plain constructor
  (`output_fn`, `show_timestamps`), `set_player_name`,
  `handle_event(EventPage)` and `handle_event_book(EventBook)` methods
  that dispatch via a table built from the decorated handlers. Added
  formatting for every event covered by scenarios (currency
  `$1,234`, card-pair lists, blinds, action verbs, community phases,
  unknown-event fallback, timestamp toggle).

## Open design decisions → shipped

**`ReserveFunds` keying**: renamed `table_root` → `key` on
`ReserveFunds` / `FundsReserved` / `ReleaseFunds` / `FundsReleased`
to match `DeductReservedFunds` / `FundsDeducted`. Regenerated both
the canonical `angzarr-project/proto/` and the sibling
`angzarr-client-python/angzarr-project/proto/` via `buf generate`
(works locally after all). Updated callers in `player/agg/`,
`reservation/pmg/handlers.py`, `sagas/hand_results_saga.py`, and the
test step defs. Kept the aggregate's error messages talking about
"table" so feature scenarios' exact-match assertions stay green.

While regenerating I discovered the canonical proto had drifted out
of sync with the runtime code: `DeductReservedFunds`, `FundsDeducted`,
and `player_root` fields on the Initiate*/Requested/Confirmed/Released
lifecycle messages across buy_in/rebuy/registration were missing
from the .proto sources but present in (stale) pb2 outputs. Added
them back so the protos are a complete source of truth for the pb2s.

## Final unit-feature tally

11/11 feature files green, 479/479 scenarios, 0 errors:

- hand.feature 100/100, process_manager.feature 42/42,
  saga.feature 21/21, table.feature 65/65,
  tournament.feature 55/55, player.feature 82/82,
  projector.feature 31/31, plus betting_round, game_rules,
  orchestration, and raise_tracking features all clean.

## Open design decisions

- **`ReserveFunds` keying**: the proto field is still
  `bytes table_root`; tournament-registration flows repurpose that
  slot as `tournament_root` (semantically misleading but works
  without a proto change). `DeductReservedFunds`/`FundsDeducted`
  already use the cleaner `key` field. Pick one and align.

## Known gotchas (carried forward)

- **Buf cache**: re-running `buf generate` outside the container hits
  symbol conflicts with venv `grpc_tools`. Must use the container.
- **Sibling imports in PM**: `reservation/pmg/main.py` does
  `from handlers import ReservationPM`. Its Containerfile stage sets
  `WORKDIR /app/reservation/pmg` and `CMD ["python", "main.py"]`
  (NOT `python -m`).
- **QueryClient endpoint**: `reservation/agg/main.py` and
  `reservation/pmg/main.py` both read `QUERY_ENDPOINT`. For PMs wired
  via the angzarr sidecar it's `ANGZARR_PORT`; query may need a
  separate var.
- **Kind secret drift after rotation**: after `just seed-secrets &&
  just deploy-infra`, delete `angzarr-db-0` and `angzarr-mq-0` pods so
  they re-initialize, then rollout-restart every application deployment
  so env picks up the new passwords.
- **Acceptance baseline**: 5/5 green — preserve.

## Quick checks for the next session

```bash
cd /home/babbitt/workspace/angzarr/examples-python/main

kubectl get pods -n angzarr | grep reservation

PLAYER_URL=localhost:31320 TABLE_URL=localhost:31321 \
HAND_URL=localhost:31322 RESERVATION_URL=localhost:31324 \
    just test-example-acceptance

kubectl exec -n angzarr angzarr-db-0 -- psql -U angzarr -d angzarr \
    -c "SELECT COUNT(*) FROM events WHERE edition IS NULL;
        SELECT COUNT(*) FROM events WHERE edition IS NOT NULL;"
```
