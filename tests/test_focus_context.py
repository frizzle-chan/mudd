"""Tests for FocusContextService.

Tests:
1. get_focus returns None when no focus exists
2. set_focus creates focus record
3. get_focus returns focus after set_focus
4. get_focus returns None for stale focus (different room)
5. get_focus returns None and clears expired focus (>5 minutes old)
6. clear_focus removes focus record
7. clear_focus returns on_close template when reason is 'close'
8. clear_focus returns None for other reasons
9. update_focus_timestamp updates timestamp
10. is_entity_in_focus returns True for focused entity
11. is_entity_in_focus returns True for entity in focused container
12. is_entity_in_focus returns False for unrelated entity
13. get_focused_contents returns focused entity and contents
14. get_focused_contents returns empty list when no focus
15. Singleton pattern tests
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from mudd.services.entity_loader import sync_entities
from mudd.services.focus_context import (
    FOCUS_TIMEOUT_MINUTES,
    FocusContextService,
    get_focus_context_service,
    init_focus_context_service,
    is_focus_context_service_initialized,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def focus_db(test_db, world_file):
    """Sync entities to test database for focus tests."""
    await sync_entities(test_db, world_file)
    yield test_db


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(focus_db):
    """Create FocusContextService with patched get_pool."""
    import mudd.services.focus_context as focus_module

    original_get_pool = focus_module.get_pool

    async def mock_get_pool():
        return focus_db

    focus_module.get_pool = mock_get_pool  # type: ignore[assignment]
    service = FocusContextService()
    yield service
    focus_module.get_pool = original_get_pool


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_user(focus_db):
    """Create a test user for all tests in this module."""
    user_id = 123456789
    await focus_db.execute(
        "INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
    )
    yield user_id


async def set_focus_directly(pool, user_id: int, room: str, entity_id: str):
    """Helper to set focus directly in database, replacing any existing focus."""
    await pool.execute("DELETE FROM user_focus WHERE user_id = $1", user_id)
    await pool.execute(
        """
        INSERT INTO user_focus (user_id, room, entity_id, updated_at)
        VALUES ($1, $2, $3, now())
        """,
        user_id,
        room,
        entity_id,
    )


async def set_focus_with_time(
    pool, user_id: int, room: str, entity_id: str, updated_at: datetime
):
    """Helper to set focus with specific timestamp."""
    await pool.execute("DELETE FROM user_focus WHERE user_id = $1", user_id)
    await pool.execute(
        """
        INSERT INTO user_focus (user_id, room, entity_id, updated_at)
        VALUES ($1, $2, $3, $4)
        """,
        user_id,
        room,
        entity_id,
        updated_at,
    )


async def clear_focus_directly(pool, user_id: int):
    """Helper to clear focus directly in database."""
    await pool.execute("DELETE FROM user_focus WHERE user_id = $1", user_id)


class TestGetFocus:
    """Test get_focus method."""

    async def test_get_focus_returns_none_when_no_focus(
        self, service, test_user, focus_db
    ):
        """get_focus returns None when user has no focus."""
        await clear_focus_directly(focus_db, test_user)
        focus = await service.get_focus(test_user, "library")
        assert focus is None

    async def test_get_focus_returns_focus_after_set(
        self, service, test_user, focus_db
    ):
        """get_focus returns FocusContext after set_focus."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        focus = await service.get_focus(test_user, "library")
        assert focus is not None
        assert focus.user_id == test_user
        assert focus.room == "library"
        assert focus.entity_id == "library_records"

    async def test_get_focus_returns_none_for_different_room(
        self, service, test_user, focus_db
    ):
        """get_focus returns None when focus is in different room."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        # Query focus from foyer - should return None
        focus = await service.get_focus(test_user, "foyer")
        assert focus is None

    async def test_get_focus_clears_expired_focus(self, service, test_user, focus_db):
        """get_focus returns None and clears focus older than timeout."""
        expired_time = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES + 1)
        await set_focus_with_time(
            focus_db, test_user, "library", "library_records", expired_time
        )

        # get_focus should return None and delete the expired record
        focus = await service.get_focus(test_user, "library")
        assert focus is None

        # Verify the record was deleted
        row = await focus_db.fetchrow(
            "SELECT * FROM user_focus WHERE user_id = $1", test_user
        )
        assert row is None


class TestSetFocus:
    """Test set_focus method."""

    async def test_set_focus_creates_record(self, service, test_user, focus_db):
        """set_focus creates a new focus record."""
        await clear_focus_directly(focus_db, test_user)

        from mudd.services.entity import ResolvedEntity

        entity = ResolvedEntity(
            id="library_records",
            name="Wooden Chest",
            description_short=None,
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open="You open the chest.",
            on_close="You close the chest.",
            contents_visible=False,
            focus_mode="container",
            spawn_mode="none",
        )

        result = await service.set_focus(test_user, "library", entity)

        # set_focus returns None (no extra message for opening)
        assert result is None

        # Verify record was created
        row = await focus_db.fetchrow(
            "SELECT * FROM user_focus WHERE user_id = $1", test_user
        )
        assert row is not None
        assert row["room"] == "library"
        assert row["entity_id"] == "library_records"

    async def test_set_focus_updates_existing_record(
        self, service, test_user, focus_db
    ):
        """set_focus updates existing focus using ON CONFLICT."""
        from mudd.services.entity import ResolvedEntity

        # Set initial focus
        await set_focus_directly(focus_db, test_user, "foyer", "foyer_table")

        # Set new focus
        entity = ResolvedEntity(
            id="library_records",
            name="Wooden Chest",
            description_short=None,
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=False,
            focus_mode="container",
            spawn_mode="none",
        )
        await service.set_focus(test_user, "library", entity)

        # Verify only one record exists and it's updated
        rows = await focus_db.fetch(
            "SELECT * FROM user_focus WHERE user_id = $1", test_user
        )
        assert len(rows) == 1
        assert rows[0]["room"] == "library"
        assert rows[0]["entity_id"] == "library_records"


class TestClearFocus:
    """Test clear_focus method."""

    async def test_clear_focus_removes_record(self, service, test_user, focus_db):
        """clear_focus removes focus record."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        result = await service.clear_focus(test_user, reason="interaction")

        # Should return None for non-close reason
        assert result is None

        # Verify record was deleted
        row = await focus_db.fetchrow(
            "SELECT * FROM user_focus WHERE user_id = $1", test_user
        )
        assert row is None

    async def test_clear_focus_returns_on_close_template(
        self, service, test_user, focus_db
    ):
        """clear_focus returns on_close template when reason is 'close'."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        result = await service.clear_focus(test_user, reason="close")

        # Should return the on_close template (inherited from chest prototype)
        assert result is not None
        assert "close" in result.lower() or "chest" in result.lower()

    async def test_clear_focus_returns_none_for_movement(
        self, service, test_user, focus_db
    ):
        """clear_focus returns None when reason is 'movement'."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        result = await service.clear_focus(test_user, reason="movement")

        assert result is None

    async def test_clear_focus_returns_none_when_no_focus(
        self, service, test_user, focus_db
    ):
        """clear_focus returns None when user has no focus."""
        await clear_focus_directly(focus_db, test_user)
        result = await service.clear_focus(test_user, reason="close")
        assert result is None


class TestUpdateFocusTimestamp:
    """Test update_focus_timestamp method."""

    async def test_update_focus_timestamp_updates_time(
        self, service, test_user, focus_db
    ):
        """update_focus_timestamp updates the timestamp."""
        old_time = datetime.now(UTC) - timedelta(minutes=3)
        await set_focus_with_time(
            focus_db, test_user, "library", "library_records", old_time
        )

        await service.update_focus_timestamp(test_user)

        # Verify timestamp was updated
        row = await focus_db.fetchrow(
            "SELECT * FROM user_focus WHERE user_id = $1", test_user
        )
        assert row is not None
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        # Should be much more recent than old_time
        assert updated_at > old_time


class TestIsEntityInFocus:
    """Test is_entity_in_focus method."""

    async def test_is_entity_in_focus_returns_true_for_focused_entity(
        self, service, test_user, focus_db
    ):
        """is_entity_in_focus returns True for the focused entity."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        result = await service.is_entity_in_focus(
            test_user, "library", "library_records"
        )
        assert result is True

    async def test_is_entity_in_focus_returns_true_for_contained_entity(
        self, service, test_user, focus_db
    ):
        """is_entity_in_focus returns True for entity inside focused container."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        # Check if the record inside the chest is in focus
        # (record_machine_girl has container_id = library_records in mansion.rec)
        result = await service.is_entity_in_focus(
            test_user, "library", "record_machine_girl"
        )
        assert result is True

    async def test_is_entity_in_focus_returns_false_for_unrelated_entity(
        self, service, test_user, focus_db
    ):
        """is_entity_in_focus returns False for unrelated entity."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        result = await service.is_entity_in_focus(test_user, "library", "foyer_table")
        assert result is False

    async def test_is_entity_in_focus_returns_false_when_no_focus(
        self, service, test_user, focus_db
    ):
        """is_entity_in_focus returns False when user has no focus."""
        await clear_focus_directly(focus_db, test_user)
        result = await service.is_entity_in_focus(
            test_user, "library", "library_records"
        )
        assert result is False


class TestGetFocusedContents:
    """Test get_focused_contents method."""

    async def test_get_focused_contents_includes_focused_entity(
        self, service, test_user, focus_db
    ):
        """get_focused_contents includes the focused entity itself."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        contents = await service.get_focused_contents(test_user, "library")
        assert "library_records" in contents

    async def test_get_focused_contents_includes_container_contents(
        self, service, test_user, focus_db
    ):
        """get_focused_contents includes entities inside focused container."""
        await set_focus_directly(focus_db, test_user, "library", "library_records")

        contents = await service.get_focused_contents(test_user, "library")

        # Should include the chest and its contents
        assert "library_records" in contents
        assert "record_machine_girl" in contents

    async def test_get_focused_contents_returns_empty_when_no_focus(
        self, service, test_user, focus_db
    ):
        """get_focused_contents returns empty list when no focus."""
        await clear_focus_directly(focus_db, test_user)
        contents = await service.get_focused_contents(test_user, "library")
        assert contents == []


class TestFocusContextServiceSingleton:
    """Test singleton pattern for FocusContextService."""

    def test_get_focus_context_service_raises_before_init(self):
        """get_focus_context_service raises RuntimeError before initialization."""
        import mudd.services.focus_context as focus_module

        original_service = focus_module._service

        try:
            focus_module._service = None

            with pytest.raises(
                RuntimeError, match="FocusContextService not initialized"
            ):
                get_focus_context_service()
        finally:
            focus_module._service = original_service

    def test_init_focus_context_service_creates_singleton(self):
        """init_focus_context_service creates and returns singleton."""
        import mudd.services.focus_context as focus_module

        original_service = focus_module._service

        try:
            focus_module._service = None
            assert not is_focus_context_service_initialized()

            service = init_focus_context_service()
            assert service is not None
            assert is_focus_context_service_initialized()

            assert get_focus_context_service() is service
        finally:
            focus_module._service = original_service

    def test_is_focus_context_service_initialized_reflects_state(self):
        """is_focus_context_service_initialized returns correct state."""
        import mudd.services.focus_context as focus_module

        original_service = focus_module._service

        try:
            focus_module._service = None
            assert not is_focus_context_service_initialized()

            focus_module._service = FocusContextService()
            assert is_focus_context_service_initialized()
        finally:
            focus_module._service = original_service
