# Testing Guidelines

## Core Principles

**No mocks except for third-party APIs**: Tests must use a real PostgreSQL database, not mocked services. Only mock external dependencies like Discord API objects.

- **Use real database**: All tests that involve `EntityService`, `FocusContextService`, or database queries must use the `test_db` fixture with a real PostgreSQL instance
- **Only mock Discord**: Mock `discord.Interaction`, `discord.Member`, `discord.Channel` etc. since we cannot control Discord's API in tests. Use mock factories in `tests/mocks/discord.py`
- **Session-scoped DB**: One test database per test run, cleaned up after. Use `clean_user_state` fixture for test isolation when modifying user-mutable data

## Scenario-Driven Integration Tests

Integration tests should read like chat transcripts - each test tells a complete user story using only commands.

## Colocated Unit Tests

Pure unit tests (no DB, no `unittest.mock`) live alongside their source files using the `_unit_test.py` suffix. Test only pure logic — if a test needs mocks or patches, it belongs in integration tests instead.

```
mudd/
├── utils/
│   ├── text.py
│   ├── text_unit_test.py            # tests for text.py
│   ├── async_cached_property.py
│   └── async_cached_property_unit_test.py
├── observers/
│   ├── effects.py
│   └── effects_unit_test.py         # tests for effects.py
```

When adding a new unit test, create a `<module>_unit_test.py` file next to the source file it tests.

## Running Tests

```bash
pytest                           # Run all tests (integration + colocated unit tests)
pytest tests/integration/        # Run only integration tests
pytest mudd/                     # Run only colocated unit tests
```
