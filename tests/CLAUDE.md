# Testing Guidelines

## Core Principles

**No mocks except for third-party APIs**: Tests must use a real PostgreSQL database, not mocked services. Only mock external dependencies like Discord API objects.

- **Use real database**: All tests that involve `EntityService`, `FocusContextService`, or database queries must use the `test_db` fixture with a real PostgreSQL instance
- **Only mock Discord**: Mock `discord.Interaction`, `discord.Member`, `discord.Channel` etc. since we cannot control Discord's API in tests. Use mock factories in `tests/mocks/discord.py`
- **Session-scoped DB**: One test database per test run, cleaned up after. Use `clean_user_state` fixture for test isolation when modifying user-mutable data

## VisibilityService Protocol

The `VisibilityService` is tightly coupled to Discord API (permissions, channels), so tests use `StubVisibilityService` which implements the same protocol interface (`VisibilityServiceProtocol`):

- Cogs accept `VisibilityServiceProtocol` type hint
- Production: `VisibilityService` (real Discord operations)
- Tests: `StubVisibilityService` (in-memory, no Discord)
- See `tests/mocks/discord.py` for the stub implementation

## Scenario-Driven Integration Tests

Integration tests should read like chat transcripts - each test tells a complete user story using only commands.

### Key Guidelines

- **Use commands only**: Tests should use `test_client.look()`, `test_client.interact()`, etc. - not direct DB calls like `set_focus()`
- **Verify state**: Use `test_client.get_focus()` only for assertions, not for setting up test state
- **Complete stories**: Each test should tell a complete user journey, not test isolated features

### Example: Good (Scenario-Driven)

```python
async def test_user_discovers_records(self, test_client):
    user = await test_client.create_user(room="library")

    # User opens the chest - establishes focus
    response = await test_client.interact(user, action="open", target="Wooden Chest")

    # User examines a record inside
    response = await test_client.look(user, at="WLFGRL")
    assert "Machine Girl" in response
```

### Example: Bad (Direct DB Manipulation)

```python
async def test_look_at_contained_entity(self, test_client):
    user = await test_client.create_user(room="library")
    await test_client.set_focus(user, "library_records")  # Don't do this!
    response = await test_client.look(user, at="WLFGRL")
```

### Exception: Time-Dependent Tests

Direct DB manipulation is acceptable when testing time-based behavior (like focus timeout) since we cannot simulate time passing:

```python
async def test_stale_focus_cleared_on_get(self, test_client):
    # Set focus with old timestamp directly in DB
    # This is a valid exception because we cannot simulate time passing
    expired_time = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES + 1)
    await test_client.pool.execute(
        "INSERT INTO user_focus ... VALUES ($1, $2, $3, $4)",
        user.id, "library", "library_records", expired_time,
    )
```

## Directory Structure

```
tests/
├── conftest.py            # Session-scoped DB fixture
├── harness.py             # TestClient for command-based testing
├── mocks/                 # Discord mock factories (only mock Discord API)
├── unit/                  # Pure unit tests (no DB)
├── loaders/               # Data loading tests (.rec parsing)
└── integration/           # Scenario-driven tests
    ├── test_scenarios.py  # Main workflow scenarios
    └── test_*.py          # Edge case tests
```

## Running Tests

```bash
pytest tests/                    # Run all tests
pytest tests/integration/        # Run only integration tests
pytest tests/unit/               # Run only unit tests
pytest tests/integration/test_scenarios.py -v  # Run scenarios with verbose output
```
