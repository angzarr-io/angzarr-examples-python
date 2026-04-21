# Cluster Tournament Acceptance — E2E Walkthrough

A step-by-step trace of `cluster_tournament.feature` running against the kind
cluster: every command, every coordinator hop, every aggregate handler, every
emitted event, and every saga that fires.

Feature file:
`angzarr-project/features/example/acceptance/cluster_tournament.feature`

Step definitions:
`tests/example/acceptance/steps/{tournament,table,player,common,cluster}_steps.py`

Aggregate handlers:
`tournament/agg/handlers.py`, `table/agg/handlers/table.py`,
`hand/agg/handlers/hand.py`, `player/agg/handlers.py`,
`reservation/agg/handlers.py`

---

## Cluster topology

`just up` lays out per-domain `<domain>-aggregate` deployments, each pod a
two-container pair: a Python business-logic container that owns the proto
handlers and an `angzarr-aggregate` Rust sidecar that owns the gRPC surface,
event store (Postgres), and AMQP publish.

| Domain        | NodePort        | Container path                          | Service path                                                       |
| ------------- | --------------- | --------------------------------------- | ------------------------------------------------------------------ |
| `player`      | `localhost:31320` | `player-aggregate` → `poker-python-player`           | `/angzarr_client.proto.angzarr.CommandHandlerCoordinatorService/HandleCommand` |
| `table`       | `localhost:31321` | `table-aggregate` → `poker-python-table`             | …same…                                                             |
| `hand`        | `localhost:31322` | `hand-aggregate` → `poker-python-hand`               | …same…                                                             |
| `tournament`  | `localhost:31323` | `tournament-aggregate` → `poker-python-tournament`   | …same…                                                             |
| `reservation` | `localhost:31324` | `reservation-aggregate` → `poker-python-reservation` | …same…                                                             |

Sagas (deployed):

- `saga-table-hand`: subscribes to `table` AMQP topic — translates
  `HandStarted` → `DealCards` (dispatched to `hand`).
- `saga-table-player`: subscribes to `table` AMQP topic — translates
  `HandEnded` → `ReleaseFunds` (per-player commands to `player`).

Process manager (deployed):

- `pmg-reservation-pm`: subscribes to `reservation`, `table`, `tournament`
  topics. Drives the buy-in / rebuy / registration reservation chain. Not
  exercised by these tournament scenarios — the tests send
  `EnrollPlayer` / `ProcessRebuy` straight to the tournament coordinator and
  bypass the reservation flow (see notes on each step below).

The Python `CommandClient` (`tests/command_client.py`) maps each domain to
the corresponding `*_URL` env var; with the URLs set above it routes each
`send_command(domain, ...)` to the right NodePort.

---

## Wire-level shape of every command

The client wraps each command in this envelope before it leaves the test:

```
CommandRequest {
  command: CommandBook {
    cover: Cover { domain, root: UUID, correlation_id }
    pages: [ CommandPage { header: PageHeader{sequence}, command: Any } ]
  }
  sync_mode: <see policy below>
}
```

The Rust sidecar deserializes, validates the command book against per-pod
limits, executes the handler with retry on conflicts, persists the resulting
event(s) to Postgres, publishes them to the per-domain AMQP exchange/topic,
and replies with `CommandResponse` (the events that just got persisted).

Sagas consume from AMQP via the saga sidecar and dispatch translated
commands back through `CommandHandlerCoordinatorService` on the destination
domain.

### Sync-mode policy

`GrpcClient.send_command` defaults to **`SYNC_MODE_ASYNC`** (fire-and-forget)
for all game-state commands. Per-root sequencing in the coordinator still
serializes commands against an aggregate, so the next command on the same
root sees the prior write — the client just doesn't wait for downstream
sagas/projectors/PMs to complete before returning. Cross-root coordination
(table → saga → hand) is observed by sleeping in the
`Then within N seconds` step and by the next command failing if the saga
hadn't fired.

**`SYNC_MODE_SIMPLE`** is reserved for **financial commands** — currently
only `DepositFunds` (in `_deposit_funds`, `player_steps.py:47`) and the
`DepositFunds(0)` reachability ping (`cluster_steps.py:_ping_player`).
SIMPLE blocks until the write is durable so the test can rely on the new
balance / coordinator state without polling. When the reservation chain
is exercised end-to-end, `WithdrawFunds`, `ReserveFunds`,
`DeductReservedFunds`, `ReleaseFunds`, and the reservation-domain
`Initiate*` / `Confirm*` / `Release*` commands should opt into SIMPLE the
same way.

`SYNC_MODE_CASCADE` is used by a small number of explicit overrides in
`hand_steps.py` / `sync_steps.py` to test multi-aggregate atomicity
semantics — out of scope for `cluster_tournament.feature`.

---

## Scenario EA-0006 — Two-player tournament completes after one hand

Lines 33–63 of `cluster_tournament.feature`. Setup creates Alice + Bob,
buys them into a table, opens registration, enrolls them, starts the
tournament, plays one hand, eliminates Bob, completes with Alice as winner.

### Step 1 — `Given registered players with bankroll: …`

Driven by `tests/example/acceptance/steps/player_steps.py:71`. For each row
in the table the harness does **two** commands per player:

#### 1a — `RegisterPlayer` → `player-aggregate`

- Client packs `player.RegisterPlayer{display_name="Alice", email, player_type=HUMAN}`.
- Coordinator: `player-aggregate-debug` NodePort `:31320`.
- Handler: `handle_register_player` (`player/agg/handlers.py:59`).
  - Guard rejects if player already exists.
  - Validates `display_name` and `email`.
- Emits: **`PlayerRegistered{display_name, email, player_type, registered_at}`**.
- Persisted to Postgres, published to AMQP topic `player`. No saga listens.
- **Sync mode: `ASYNC`** (identity, not financial).

#### 1b — `DepositFunds` → `player-aggregate`

- Client packs `player.DepositFunds{amount=Currency{2000, "USD"}}`.
- Same coordinator. Handler `handle_deposit_funds` (`player/agg/handlers.py:103`).
  - Validates amount > 0.
  - Computes `new_balance = state.bankroll + amount`.
- **Sync mode: `SIMPLE`** — financial.
- Emits: **`FundsDeposited{amount, new_balance, deposited_at}`**.
- Aggregate's `apply_*` updates state.bankroll → 2000.

Repeat for Bob. After this step both player aggregates exist with
bankroll = 2000.

### Step 2 — `Given a tournament "Spring" …`

`tournament_steps.py:82`. Sends `tournament.CreateTournament{name="Spring",
game_variant=TEXAS_HOLDEM, buy_in=500, starting_stack=1500, max_players=9,
min_players=2}` to **`tournament-aggregate`** (NodePort `:31323`).

- Handler: `handle_create_tournament` (`tournament/agg/handlers.py:297`).
  - Rejects if tournament already exists.
  - Validates name non-empty, buy_in/starting_stack/min_players ≥ 2,
    `min_players ≤ max_players`.
- Emits: **`TournamentCreated{name, game_variant, buy_in, starting_stack,
  max_players, min_players, blind_structure, created_at}`**.
- Applier sets `status = TOURNAMENT_CREATED`, `current_level = 1`,
  `total_prize_pool = 0`, no registered players.
- **Sync mode: `ASYNC`** — game state.

### Step 3 — `When I create a Texas Hold'em table "Spring-1" with blinds 5/10`

`table_steps.py:267 → _create_table` (`table_steps.py:30`). Sends
`table.CreateTable{table_name="Spring-1", game_variant=TEXAS_HOLDEM,
small_blind=5, big_blind=10, min_buy_in=10, max_buy_in=10000,
max_players=9, action_timeout_seconds=30}` to **`table-aggregate`**
(NodePort `:31321`).

- Handler: `handle_create_table` (`table/agg/handlers/table.py:333`).
  - Rejects on duplicate, validates blinds, buy-in bounds, player range.
- Emits: **`TableCreated{table_name, game_variant, small_blind, big_blind,
  min_buy_in, max_buy_in, max_players, created_at}`**.
- Applier initializes `_TableState` with empty `seats`, `status="open"`.
- **Sync mode: `ASYNC`** — game state.

### Steps 4 & 5 — `player "<X>" joins table "Spring-1" at seat <i> with buy-in 1500`

Two commands, one per player. `_join_table` (`table_steps.py:66`) sends
`table.JoinTable{player_root=<Alice's UUID>, preferred_seat=0, buy_in_amount=1500}`
(then again with seat=1 for Bob) to `table-aggregate`.

- Handler: `handle_join_table` (`table/agg/handlers/table.py:383`).
  - Rejects: table missing, no `player_root`, player already seated, table
    full, buy-in out of [min_buy_in, max_buy_in], requested seat occupied.
  - Picks `seat_position` from `preferred_seat` if free.
- Emits: **`PlayerJoined{player_root, seat_position, buy_in_amount, stack, joined_at}`**.
- **Sync mode: `ASYNC`** — game state. (In the full reservation chain the
  buy-in debit rides SIMPLE; the direct JoinTable exercised here doesn't
  touch the player bankroll.)

> Note: in the real product, JoinTable would be PM-orchestrated through a
> reservation against the player aggregate's bankroll (see
> `pmg-reservation-pm`). The acceptance test takes the direct command path
> on the table aggregate to keep the scenario focused on tournament
> mechanics.

After both joins: table has two seated players, Alice at position 0,
Bob at position 1. Each has stack=1500 in the table-side state. Player
aggregate bankrolls are unchanged (no reservation chain ran).

### Step 6 — `And I open registration on tournament "Spring"`

`tournament_steps.py:138`. Sends `tournament.OpenRegistration{}` to
`tournament-aggregate`.

- Handler: `handle_open_registration` (`tournament/agg/handlers.py:347`).
  - Rejects if tournament missing, already running, or already open.
- Emits: **`RegistrationOpened{opened_at}`**.
- Applier sets `status = TOURNAMENT_REGISTRATION_OPEN`.
- **Sync mode: `ASYNC`** — game state.

### Steps 7 & 8 — `player "<X>" registers for tournament "Spring"`

`tournament_steps.py:147`. The docstring acknowledges the test
short-circuits the reservation chain: it sends
`tournament.EnrollPlayer{player_root, reservation_id=<fresh UUID>}`
**directly** to `tournament-aggregate` rather than going through
`InitiateTournamentRegistration` on the player aggregate (which would
fan out: player → reservation → pmg-reservation-pm → tournament).

- Handler: `handle_enroll_player` (`tournament/agg/handlers.py:400`).
  - Rejects if no `player_root`, registration not open, tournament full,
    or player already registered (rejection path emits
    `TournamentEnrollmentRejected` rather than throwing).
  - Sets `fee_paid = self.buy_in` (500), `starting_stack = 1500`.
- Emits: **`TournamentPlayerEnrolled{player_root, reservation_id, fee_paid,
  starting_stack, registration_number, enrolled_at}`**.
- Applier records the registration in
  `state.registered_players[player_root_hex]`,
  `total_prize_pool += 500`, `players_remaining = len(registered_players)`.
- **Sync mode: `ASYNC`** — tournament-state command. The funds-side
  `ReserveFunds` / `DeductReservedFunds` legs of the *real* reservation
  chain would ride SIMPLE; the direct EnrollPlayer here doesn't touch
  the player aggregate.

After both enrollments: registered = {Alice, Bob}, total_prize_pool = 1000,
players_remaining = 2.

### Step 9 — `Then tournament "Spring" has 2 registered players`

`tournament_steps.py:311`. Test-side assertion only — checks
`context.tournaments["Spring"]["registered"]`, the locally tracked set
mirroring the commands the harness has issued. Same for
`total_prize_pool 1000` (`tournament_steps.py:342`).

### Step 10 — `When I start tournament "Spring"`

`tournament_steps.py:180`. Sends `tournament.StartTournament{}` to
`tournament-aggregate`.

- Handler: `handle_start_tournament` (`tournament/agg/handlers.py:627`).
  - Rejects if tournament missing, registration not open, fewer than
    `min_players` registered.
- Emits: **`TournamentStarted{total_players=2, total_prize_pool=1000, started_at}`**.
- Applier sets `status = TOURNAMENT_RUNNING`.
- **Sync mode: `ASYNC`** — game state.

### Step 11 — `And a hand starts at table "Spring-1"` (this is where a saga fires)

`table_steps.py:310 → _start_hand` (`table_steps.py:97`). Sends
`table.StartHand{}` to `table-aggregate`.

- Handler: `handle_start_hand` (`table/agg/handlers/table.py:466`).
  - Rejects if table missing, hand already in progress, or fewer than
    2 active players.
  - Computes deterministic `hand_root = sha256("angzarr.poker.hand.<table_id>.<hand_number>")[:16]`.
  - Picks dealer position, derives small/big-blind positions
    (heads-up: SB = dealer).
  - Snapshots the active seats into `SeatSnapshot`s.
- Emits: **`HandStarted{hand_root, hand_number=1, dealer_position,
  small_blind_position, big_blind_position, game_variant, small_blind=5,
  big_blind=10, active_players=[…], started_at}`**.
- Sidecar publishes to AMQP topic `table`.
- **Sync mode: `ASYNC`** — game state. Returns as soon as the table
  aggregate persists `HandStarted`; the saga-driven `DealCards` runs
  out-of-band (observed by the next step's wait window).

**`saga-table-hand` (`table/saga-hand/main.py:46`) consumes `HandStarted`.**

- Handler: `TableHandSaga.handle_hand_started` (`table/saga-hand/main.py:50`).
  - Builds `hand.PlayerInHand{player_root, position, stack}` for each
    active seat.
  - Emits a `CommandBook` targeting domain=`hand`, root=`event.hand_root`:
    `hand.DealCards{table_root=<hand_root>, hand_number=1, game_variant,
    dealer_position, small_blind=5, big_blind=10, players=[…]}`.

The angzarr-saga sidecar dispatches `DealCards` over gRPC to
**`hand-aggregate`** (NodePort `:31322`).

- Handler: `handle_deal_cards` (`hand/agg/handlers/hand.py:389`).
  - Rejects if hand already dealt, no players, fewer than 2 players.
  - Calls `get_game_rules(TEXAS_HOLDEM).deal_hole_cards()` (random unless
    `deck_seed` set — saga doesn't pass one in this test).
- Emits: **`CardsDealt{table_root, hand_number=1, game_variant,
  dealer_position, dealt_at, player_cards=[…], players=[…]}`**.
- **Sync mode**: whatever the saga sidecar uses for its dispatch — the
  command originates from the saga, not from the test client. The test
  doesn't observe `DealCards` directly; the implicit assertion is that
  Step 13's `AwardPot` would fail if `CardsDealt` hadn't landed.

### Step 12 — `Then within 5 seconds: | table | HandStarted | / | hand | CardsDealt |`

`common_steps.py:127`. Sleep for `min(5, 0.1)` seconds — i.e., 100 ms — and
move on. The actual assertion is implicit: subsequent steps that send
commands to the same hand_root would fail if the saga had not produced
`CardsDealt` (because the hand wouldn't exist for AwardPot to act on).

### Step 13 — `When the hand at table "Spring-1" is fast-forwarded with "Alice" winning the pot`

`tournament_steps.py:256`. Sends `hand.AwardPot{awards=[PotAward{player_root=<Alice>,
amount=15, pot_type="main"}]}` to `hand-aggregate`. This skips PostBlind /
PlayerAction / DealCommunityCards / RevealCards entirely — the test only
needs a hand to "complete" so the tournament-side eliminate has something
to attribute to.

- Handler: `handle_award_pot` (`hand/agg/handlers/hand.py:766`).
  - Rejects if hand not dealt, already complete, no awards, winner not in
    hand, folded player.
  - Snaps award amounts to current pot total (still 0 here since no blinds
    posted) and builds `PotWinner{}` records.
- Emits **two** events in one transaction:
  - **`PotAwarded{winners=[PotWinner{player_root=Alice, amount, pot_type}], awarded_at}`**.
  - **`HandComplete{table_root, hand_number=1, winners, final_stacks, completed_at}`**.
- **Sync mode: `ASYNC`** — game state. (When `saga-hand-player` is
  deployed, the resulting `DepositFunds` it dispatches to credit pot
  winners is the financial leg and would ride SIMPLE on the saga's
  outbound dispatch.)

> What does **not** happen here: `saga-hand-table` (`hand/saga-table/main.py`,
> would translate `HandComplete` → `EndHand` on the table) and
> `saga-hand-player` (`hand/saga-player/main.py`, would translate
> `PotAwarded` → `DepositFunds` on the player) **exist in code but are not
> deployed by `values.yaml`**. So the table never sees `EndHand` and the
> player aggregate's bankroll isn't credited — fine for this test because
> the next step targets the tournament directly.

### Step 14 — `And I eliminate player "Bob" from tournament "Spring"`

`tournament_steps.py:221`. Sends
`tournament.EliminatePlayer{player_root=<Bob>, hand_root=<context.current_hand_root>}`
to `tournament-aggregate`. (`current_hand_root` is the test-side UUID
generated when StartHand was issued — note it's **not** the deterministic
`hand_root` derived by the table aggregate; the elimination event simply
records whatever hand_root the test passes.)

- Handler: `handle_eliminate_player` (`tournament/agg/handlers.py:545`).
  - Rejects if tournament missing, not running, missing player_root, or
    player not registered.
  - `finish_position = self.players_remaining` (= 2 at the moment Bob
    is eliminated).
- Emits: **`PlayerEliminated{player_root=<Bob>, hand_root, finish_position=2,
  payout=0, eliminated_at}`**.
- Applier removes Bob from `state.registered_players`,
  `players_remaining = 1`.
- **Sync mode: `ASYNC`** — game state. Note `payout=0`: when payouts are
  wired up the resulting `DepositFunds` to the busted-out player would
  be the financial leg and ride SIMPLE.

### Step 15 — `Then tournament "Spring" has players_remaining 1`

Local assertion (`tournament_steps.py:322`).

### Step 16 — `When I complete tournament "Spring" with winner "Alice"`

`tournament_steps.py:241`. Sends
`tournament.CompleteTournament{winner_root=<Alice>}` to `tournament-aggregate`.

- Handler: `handle_complete_tournament` (`tournament/agg/handlers.py:656`).
  - Rejects if tournament missing, already completed, or not in
    Running/Paused.
- Emits: **`TournamentCompleted{winner_root=<Alice>,
  total_prize_pool=1000, completed_at}`**.
- Applier sets `status = TOURNAMENT_COMPLETED`.
- **Sync mode: `ASYNC`** — game state. (Once payout fan-out is wired
  the prize-pool `DepositFunds` to the winner would be the financial
  leg riding SIMPLE.)

### Steps 17 & 18 — `Then tournament "Spring" has status "Completed"` / `winner is "Alice"`

Local assertions (`tournament_steps.py:299`, `tournament_steps.py:353`).

### EA-0006 ledger summary

Per-aggregate event book at end of scenario:

- **player[Alice]**: `PlayerRegistered`, `FundsDeposited(2000)`.
- **player[Bob]**: `PlayerRegistered`, `FundsDeposited(2000)`.
- **table[Spring-1]**: `TableCreated`, `PlayerJoined(Alice@0)`,
  `PlayerJoined(Bob@1)`, `HandStarted(#1)`.
- **hand[<derived>]**: `CardsDealt`, `PotAwarded`, `HandComplete`.
- **tournament[Spring]**: `TournamentCreated`, `RegistrationOpened`,
  `TournamentPlayerEnrolled(Alice)`, `TournamentPlayerEnrolled(Bob)`,
  `TournamentStarted`, `PlayerEliminated(Bob)`, `TournamentCompleted(Alice)`.

Single saga firing across the whole scenario:
`saga-table-hand` (HandStarted → DealCards).

---

## Scenario EA-0007 — Three-player tournament with blind advance, rebuy, eliminations

Lines 71–125 of the feature. Same shape as EA-0006 with three additions
that exercise extra tournament handlers:

### Tournament created with rebuy + blind structure

`tournament_steps.py:99` packs `RebuyConfig{enabled=true, rebuy_cost=100,
rebuy_chips=1000}` and a three-level `blind_structure`. Resulting
`TournamentCreated` carries that config; the applier stashes it on
`state.rebuy_config` / `state.blind_structure`.

### Per-hand cycle (×4 hands)

Each iteration is the same `StartHand` → saga → `DealCards` → `AwardPot`
chain as EA-0006 step 11–13 but with `Majors-1` as the table.

### Between hands 1 and 2 — `AdvanceBlindLevel`

`tournament_steps.py:189`. Sends `tournament.AdvanceBlindLevel{}` to
`tournament-aggregate`.

- Handler: `handle_advance_blind_level` (`tournament/agg/handlers.py:506`).
  - Rejects if tournament missing or not running.
  - `new_level = state.current_level + 1`; pulls the corresponding
    `BlindLevel` config if present.
- Emits: **`BlindLevelAdvanced{level=2, small_blind=10, big_blind=20,
  ante=0, advanced_at}`**.
- Applier sets `state.current_level = 2`.
- **Sync mode: `ASYNC`** — game state.

### After hand 2 — `ProcessRebuy` for Charlie

`tournament_steps.py:199`. Sends
`tournament.ProcessRebuy{player_root=<Charlie>, reservation_id=<fresh UUID>}`
to `tournament-aggregate`.

- Handler: `handle_process_rebuy` (`tournament/agg/handlers.py:450`).
  - Rejects if tournament missing/not running, player missing/not
    registered, or `can_rebuy` returns false (rejection emits `RebuyDenied`).
  - Reads `rebuy_cost=100`, `chips_added=1000` from `state.rebuy_config`.
- Emits: **`RebuyProcessed{player_root=<Charlie>, rebuy_count=1,
  rebuy_cost=100, chips_added=1000, processed_at}`**.
- Applier increments `registration.rebuys_used` and adds rebuy_cost to
  `total_prize_pool` (1500 → 1600).
- **Sync mode: `ASYNC`** — tournament-state command (the financial
  rebuy-cost debit is the player-side `DeductReservedFunds` in the
  full chain, not this command).

> Same caveat as enrollment: in the product, `ProcessRebuy` is the
> tail of an `InitiateRebuy` (player) → reservation → PM →
> ProcessRebuy (tournament) chain coordinated by `pmg-reservation-pm`. The
> test sends `ProcessRebuy` directly, so the player aggregate's bankroll
> isn't actually debited 100.

### After hands 3 & 4 — two more `EliminatePlayer` commands

Same handler as EA-0006 step 14, called for Bob then Charlie.
`finish_position` reflects `players_remaining` at the time of each
elimination (3 → 2 after Bob, 2 → 1 after Charlie).

### Final `CompleteTournament` for Alice

Same as EA-0006 step 16 with `total_prize_pool=1600` recorded on
`TournamentCompleted`.

### EA-0007 saga firings

`saga-table-hand` fires once per `StartHand` — four times total. No other
sagas run for this scenario either.

---

## Why the deployed-saga set is intentionally narrow

`values.yaml` only lists `saga-table-hand` and `saga-table-player`. The
other two sagas (`saga-hand-table`, `saga-hand-player`) live in the repo
but aren't deployed because the tournament scenarios:

1. Skip betting via direct `AwardPot` — there's no real pot to settle, so
   `PotAwarded → DepositFunds` (saga-hand-player) would credit the wrong
   amount.
2. Send `EliminatePlayer` directly to the tournament — there's no need
   for `HandComplete → EndHand → HandEnded → ReleaseFunds` to reconcile
   stacks, because the test never asserts table-side seating after
   the hand.

Each scenario targets a specific lifecycle slice. Wiring the full
saga + PM chain is a separate (existing) feature in `cluster.feature`
and the unit/in-process suites.

EA-0008 (`Full-lifecycle complex tournament across every code path`) does
deploy all four sagas — see `values.yaml` and the `saga-hand-{table,player}`
build targets in `Containerfile`. It exercises a real betting hand
(PostBlind / PlayerAction / DealCommunityCards / AwardPot) against the
deterministic deck_seed `saga-table-hand` now propagates from
`event.hand_root` (`table/saga-hand/main.py`).

### Saga retry storm — root cause + fix

A real-betting cluster hand initially deadlocked the `saga-table-hand`
queue. The mechanics:

1. Saga consumes `HandStarted` from AMQP, dispatches `DealCards` →
   first attempt **succeeds**, hand persists `CardsDealt`.
2. AMQP redelivers `HandStarted` (at-least-once delivery, ack races a
   transient blip).
3. Saga handles redelivery, recomputes `destinations.sequence_for("hand")`
   → still 0 (saga is rebuilt fresh on each invocation, doesn't
   remember the prior dispatch).
4. Re-dispatched `DealCards(seq=0)` reaches the hand aggregate. The
   Python `handle_deal_cards` runs its `if self.exists` guard *before*
   the rust sidecar gets to do sequence validation, so the response
   is `FailedPrecondition: "Hand already dealt"` rather than
   `Sequence mismatch:`.
5. The framework's `is_retryable_status` (`core/main/src/utils/retry.rs`)
   used to be `matches!(status.code(), Code::FailedPrecondition)` —
   it treated **every** FailedPrecondition as a retryable sequence
   conflict. So the saga retries forever, redelivery loop, queue
   backpressures.

Fix: narrow `is_retryable_status` to message-prefix-match
`Sequence mismatch:` / `Sequence conflict:` (the only actual sequence
strings the framework emits). Business guard rejections like "Hand
already dealt" / "Player does not exist" / "Tournament is full" now
correctly become `CommandOutcome::Rejected` — saga acks once, moves on.

The cleaner long-term fix landed: saga-produced commands now use the
`AngzarrDeferredSequence` page-header variant, and the framework
implements `check_deferred_idempotency` on the destination aggregate
(`core/main/src/orchestration/aggregate/{local,grpc}/mod.rs`). On
delivery the pipeline calls `find_by_source(target_root, source.root,
source_seq)` against the event store — a hit returns the cached events
as `CommandResponse{events}` without invoking the business handler,
which makes redelivery a true no-op rather than relying on a guard
rejection. The same machinery is mirrored for external facts via
`check_external_idempotency` + `find_by_external_id`, keyed on
`external_id` from the `ExternalDeferredSequence` header.

---

## Observed event store after EA-0008

A direct read of the live cluster's `events` table after the latest
green run shows the framework idempotency landing correctly:

```
   domain    | saga_produced | total
-------------+---------------+-------
 hand        |             4 |     4
 player      |             0 |    38
 reservation |             0 |     6
 table       |             0 |    27
 tournament  |             0 |    34
```

Every event under `hand` carries `(source_domain="table", source_seq=N)`
— that's `saga-table-hand` translating `HandStarted` → `DealCards`
through the `AngzarrDeferredSequence` page header, and the destination
hand-aggregate's pipeline persisting the source provenance via the
new `persist_events(... source_info)` parameter. A redelivery of any
of those `HandStarted` events is now a `find_by_source` cache hit;
the python `handle_deal_cards` is never re-invoked.

The other domains show `saga_produced = 0` because none of the
deployed saga-driven flows targeted them in this scenario:

- **player** events are all client-driven `PlayerRegistered` /
  `FundsDeposited` / `FundsReserved` / `FundsDeducted` /
  `FundsReleased` / `FundsWithdrawn` — direct test commands, no saga
  in the path. `saga-hand-player` would tag `DepositFunds` events with
  source provenance if `PotAwarded` had been published, but see below.
- **reservation** events are 3 × `RegistrationRequested` + 2 ×
  `BuyInRequested` + 1 × `RebuyRequested` — direct `Initiate*`
  commands from the test, not produced by a saga.
- **table** and **tournament** events are all client-driven likewise.

### What the test did NOT exercise (and why)

The full betting hand in EA-0008 (`PostBlind` / `PlayerAction` /
`DealCommunityCards` / `RevealCards` / `AwardPot`) emits **0 hand
events past `CardsDealt`**. Cause: the test client's
`_send_hand_command` always sends `sequence=0`, so the second command
on a hand_root (e.g. `PostBlind` after `CardsDealt` already at seq 0)
hits `pre_validate_sequence` → `Sequence mismatch: command expects 0,
aggregate at 1`. The aggregate's saga_backoff retry loop burns
through 11 attempts, gives up, and the test step's try/except moves
on. So `PotAwarded` and `HandComplete` never get persisted, and the
deployed `saga-hand-player` / `saga-hand-table` sagas never have
triggers to consume — both of their queues stay at 0.

This is a **test-harness gap**, not a framework bug. The fix is to
have the test client read the aggregate's current sequence (or use
`AngzarrDeferredSequence` for client-issued commands too) before
sending each hand-side command. Out of scope for the current pass;
documented here so future work doesn't chase it as a framework
issue.

### Saga firings actually observed

Across all 7 passing scenarios in the run that produced the table
above, only `saga-table-hand` actually fired and produced events
(4 `CardsDealt` events). The other three deployed sagas were
correctly subscribed (RabbitMQ bindings present, queues created)
but had no triggering events to consume, for the reasons above.
