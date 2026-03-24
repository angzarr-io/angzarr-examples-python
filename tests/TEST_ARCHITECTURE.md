# Test Architecture Plan

## Goal

Unified test helpers that power both unit tests and BDD/Gherkin tests, reducing duplication and ensuring consistent behavior verification.

## Python Structure

```
examples-python/main/
├── tests/
│   ├── helpers/                    # Shared test utilities
│   │   ├── __init__.py            # Re-exports all helpers
│   │   ├── proto_helpers.py       # pack/unpack, make_event_book, uuid_for
│   │   ├── builders.py            # Fluent state/event builders
│   │   ├── assertions.py          # assert_event_type, assert_rejected
│   │   └── executors.py           # execute_command, apply_events
│   │
│   ├── features/                   # BDD feature files
│   │   ├── player.feature
│   │   ├── table.feature
│   │   ├── hand.feature
│   │   ├── buy_in.feature
│   │   ├── registration.feature
│   │   ├── rebuy.feature
│   │   └── cascade.feature        # Compensation/rollback scenarios
│   │
│   ├── steps/                      # BDD step definitions (use helpers)
│   │   ├── common_steps.py        # Shared Given/When/Then
│   │   ├── player_steps.py
│   │   ├── table_steps.py
│   │   ├── hand_steps.py
│   │   └── orchestration_steps.py
│   │
│   ├── unit/                       # Unit tests (use helpers)
│   │   ├── test_player.py
│   │   ├── test_table.py
│   │   ├── test_hand.py
│   │   ├── test_saga.py
│   │   └── test_compensation.py
│   │
│   └── conftest.py                 # pytest fixtures
│
├── player/agg/test_handlers.py     # In-module unit tests (use helpers)
├── table/agg/handlers/test_*.py
├── hand/agg/handlers/test_*.py
├── buy_in/pmg/test_handlers.py
├── rebuy/pmg/test_handlers.py
└── registration/pmg/test_handlers.py
```

## Helper Modules

### proto_helpers.py
```python
# Core proto manipulation
uuid_for(seed: str) -> bytes
currency(amount: int) -> Currency
pack_event(event: Message) -> Any
unpack_event(any_pb: Any, cls: type[T]) -> T
make_event_book(domain, root, events) -> EventBook
make_command_book(domain, root, command) -> CommandBook
```

### builders.py
```python
# Fluent builders for test state
class PlayerStateBuilder:
    def with_bankroll(amount) -> Self
    def with_reserved(amount, table_root) -> Self
    def registered() -> Self
    def build() -> PlayerState

class EventBookBuilder:
    def with_domain(domain) -> Self
    def with_root(root) -> Self
    def with_event(event) -> Self
    def build() -> EventBook
```

### assertions.py
```python
# Semantic test assertions
def assert_event_type(result: EventBook, expected_type: str) -> None
def assert_event_field(result: EventBook, field: str, expected: Any) -> None
def assert_command_rejected(exc: Exception, code: str) -> None
def assert_state_equals(state, expected: dict) -> None
```

### executors.py
```python
# Command execution helpers
def execute_command(handler, cmd, state, seq=0) -> EventBook | Exception
def apply_events(state, events: list) -> State
def rebuild_state(event_book: EventBook, state_cls) -> State
```

## BDD Step Definitions Pattern

```python
# steps/player_steps.py
from tests.helpers import PlayerStateBuilder, execute_command, assert_event_type

@given("a registered player with bankroll {amount:d}")
def step_impl(context, amount):
    context.player_state = (
        PlayerStateBuilder()
        .registered()
        .with_bankroll(amount)
        .build()
    )

@when("the player deposits {amount:d}")
def step_impl(context, amount):
    cmd = DepositFunds(amount=currency(amount))
    context.result = execute_command(handle_deposit, cmd, context.player_state)

@then("the result is a FundsDeposited event")
def step_impl(context):
    assert_event_type(context.result, "FundsDeposited")
```

## Unit Test Pattern

```python
# tests/unit/test_player.py
from tests.helpers import PlayerStateBuilder, execute_command, assert_event_type

class TestDepositFunds:
    def test_deposit_increases_bankroll(self):
        state = PlayerStateBuilder().registered().with_bankroll(1000).build()
        cmd = DepositFunds(amount=currency(500))

        result = execute_command(handle_deposit, cmd, state)

        assert_event_type(result, "FundsDeposited")
        assert_event_field(result, "new_balance.amount", 1500)
```

## Coverage Targets

| Domain | Unit Tests | BDD Scenarios |
|--------|------------|---------------|
| Player | 35+ | 17 (match Rust) |
| Table | 46+ | 21 (match Rust) |
| Hand | 119+ | 48 (match Rust) |
| Buy-in PM | 15+ | 7 |
| Registration PM | 13+ | 5 |
| Rebuy PM | 14+ | 6 |
| Saga | 10+ | 9 (match Rust) |
| Cascade | 10+ | 5 |
| **Total** | **262+** | **118** |
