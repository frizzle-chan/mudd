# Testing Guidelines

## Core Principles

**No mocks except for third-party APIs**: Tests must use a real PostgreSQL database, not mocked services. Only mock external dependencies like Discord API objects.

- **Use real database**: All tests that involve `EntityService`, `FocusContextService`, or database queries must use the `test_db` fixture with a real PostgreSQL instance
- **Only mock Discord**: Mock `discord.Interaction`, `discord.Member`, `discord.Channel` etc. since we cannot control Discord's API in tests. Use mock factories in `tests/mocks/discord.py`
- **Session-scoped DB**: One test database per test run, cleaned up after. Use `clean_user_state` fixture for test isolation when modifying user-mutable data

## RoomChannelCache Stub

The `RoomChannelCache` is coupled to Discord API (channel/category lookups), so tests use `StubRoomChannelCache`:

- Cogs accept `RoomChannelCache` for room<->channel mappings
- Production: `RoomChannelCache` (real Discord operations)
- Tests: `StubRoomChannelCache` (in-memory, populated from mock guild)
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

## Test Fixtures in Store Room

The `store-room` contains test fixtures with predictable strings for integration tests. These entities are in the `storeroom_box` container:

| Entity | Purpose | Test Strings |
|--------|---------|--------------|
| `test_orb` | Testing OnLook, OnTouch, OnAttack | `TEST_LOOK_RESPONSE`, `TEST_TOUCH_RESPONSE`, `TEST_ATTACK_RESPONSE` |
| `test_gadget` | Testing OnUse, OnTake | `TEST_USE_RESPONSE`, `TEST_TAKE_RESPONSE` |
| `test_lockbox` | Testing OnOpen, OnClose | `TEST_OPEN_RESPONSE`, `TEST_CLOSE_RESPONSE` |
| `test_record` | Testing effects.broadcast() | `TEST_EPHEMERAL_RESPONSE`, `TEST_BROADCAST_RESPONSE` |

### Example: Using Test Fixtures

```python
async def test_broadcast_functionality(self, test_client):
    user = await test_client.create_user(user_id=123, room="store-room")
    # Open the container to access fixtures
    await test_client.interact(user, action="open", target="Cardboard Box")
    # Use the test record
    response, broadcasts = await test_client.interact_with_broadcasts(
        user, action="use", target="Test Record"
    )
    assert "TEST_EPHEMERAL_RESPONSE" in response
    assert "TEST_BROADCAST_RESPONSE" in broadcasts[0]
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
