"""Integration tests for the UserInventoryForum model."""

from __future__ import annotations

import pytest

from mudd.models.inventory_forum import UserInventoryForum
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio(loop_scope="session")

USER_A = 811_001
USER_B = 811_002


@pytest.fixture
async def clean_forum_users(test_db):
    """Delete only the users this module creates.

    Deliberately not `clean_user_state`: that fixture re-runs `sync_entities`,
    which reassigns world instance IDs and perturbs the capped autocomplete
    ordering that `test_scenarios.py` asserts on. These tests touch no world
    entities, so scoping cleanup to their own rows keeps them isolated without
    disturbing anything else. The forum rows go with the users via
    `ON DELETE CASCADE`.
    """
    yield
    await test_db.execute(
        "DELETE FROM users WHERE id = ANY($1::bigint[])",
        [
            USER_A,
            USER_B,
        ],
    )


async def test_get_owners_by_forum_id_empty(test_db, clean_forum_users):
    """No registered forums yields an empty mapping, not an error."""
    assert await UserInventoryForum.get_owners_by_forum_id(test_db) == {}


async def test_get_owners_by_forum_id_maps_forum_to_user(test_db, clean_forum_users):
    """Every registered forum maps back to the user that owns it."""
    await create_test_user(test_db, user_id=USER_A)
    await create_test_user(test_db, user_id=USER_B)
    await UserInventoryForum.create_or_update(test_db, USER_A, 901, 800)
    await UserInventoryForum.create_or_update(test_db, USER_B, 902, 800)

    owners = await UserInventoryForum.get_owners_by_forum_id(test_db)

    assert owners == {901: USER_A, 902: USER_B}
    # Callers derive the registered-forum-ID set from the keys.
    assert set(owners) == {901, 902}


async def test_get_owners_by_forum_id_reflects_reregistration(
    test_db, clean_forum_users
):
    """create_or_update replaces a user's forum rather than adding a second."""
    await create_test_user(test_db, user_id=USER_A)
    await UserInventoryForum.create_or_update(test_db, USER_A, 901, 800)
    await UserInventoryForum.create_or_update(test_db, USER_A, 999, 800)

    assert await UserInventoryForum.get_owners_by_forum_id(test_db) == {999: USER_A}
