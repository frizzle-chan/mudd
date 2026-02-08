"""Integration tests for the skills progression system."""

from __future__ import annotations

import pytest

from mudd.cogs.speech import SPEECH_XP_PER_MESSAGE
from mudd.commands import AttackCommand, LookCommand, UseCommand
from mudd.models import RoomEntityInstance
from mudd.models.skills import UserSkill
from mudd.observers.skills import AGILITY_XP_PER_MOVE
from mudd.skills.registry import SKILL_COUNT, Skill
from mudd.skills.xp import MAX_XP, xp_for_level
from tests.helpers import act, autocomplete, create_test_user, move

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_agility_xp_grant(test_db, clean_user_state):
    """UserSkill.grant_xp correctly grants Agility XP and persists it."""
    user = await create_test_user(test_db, room_id="foyer")

    # Check initial agility XP
    skill_before = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill_before.xp == 0
    assert skill_before.level == 1

    # Grant agility XP (same amount as movement would grant)
    result = await UserSkill.grant_xp(test_db, user.id, Skill.AGILITY, 28)
    assert result.old_xp == 0
    assert result.new_xp == 28
    assert result.old_level == 1
    assert result.new_level == 1
    assert result.leveled_up is False

    # Verify persisted
    skill_after = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill_after.xp == 28
    assert skill_after.level == 1


async def test_speech_xp_grant(test_db, clean_user_state):
    """UserSkill.grant_xp correctly grants Speech XP and persists it."""
    user = await create_test_user(test_db, room_id="foyer")

    # Check initial speech XP
    skill_before = await UserSkill.get(test_db, user.id, Skill.SPEECH)
    assert skill_before.xp == 0
    assert skill_before.level == 1

    # Grant speech XP (same amount as a chat message would grant)
    result = await UserSkill.grant_xp(
        test_db, user.id, Skill.SPEECH, SPEECH_XP_PER_MESSAGE
    )
    assert result.old_xp == 0
    assert result.new_xp == SPEECH_XP_PER_MESSAGE
    assert result.old_level == 1
    assert result.new_level == 1
    assert result.leveled_up is False

    # Verify persisted
    skill_after = await UserSkill.get(test_db, user.id, Skill.SPEECH)
    assert skill_after.xp == SPEECH_XP_PER_MESSAGE
    assert skill_after.level == 1


async def test_food_grants_vitality_xp(test_db, clean_user_state):
    """Using food item with grant_xp effect grants Vitality XP via EffectsObserver."""
    user = await create_test_user(test_db, room_id="store-room")

    # Find the test apple in the room (has grant_xp("vitality", 100) in OnUse)
    apple = next(
        o
        for o in await autocomplete(test_db, user.id, "Test Apple")
        if not isinstance(o, RoomEntityInstance) and o.entity.name == "Test Apple"
    )

    # Check initial vitality XP
    skill_before = await UserSkill.get(test_db, user.id, Skill.VITALITY)
    assert skill_before.xp == 0

    # Use the apple (triggers grant_xp via template effect)
    result = await act(test_db, user.id, UseCommand(), f"entity://{apple.instance_id}")
    assert "Delicious" in result.output

    # Verify effects observed the XP grant signal
    assert result.effects.has_xp_grants
    assert result.effects.xp_grants == [("vitality", 100)]

    # SkillsObserver should have processed the XP grant during flush
    assert len(result.skills.results) == 1
    xp_result = result.skills.results[0]
    assert xp_result.skill == "vitality"
    assert xp_result.old_xp == 0
    assert xp_result.new_xp == 100
    assert xp_result.old_level == 1
    assert xp_result.new_level == 2  # 100 XP crosses level 2 boundary (83 XP)
    assert xp_result.leveled_up is True

    # Verify XP persisted in database
    skill_after = await UserSkill.get(test_db, user.id, Skill.VITALITY)
    assert skill_after.xp == 100
    assert skill_after.level == 2


async def test_level_up_detection(test_db, clean_user_state):
    """Granting enough XP to cross level threshold detects level-up."""
    user = await create_test_user(test_db, room_id="store-room")

    # Level 2 requires 83 XP
    result = await UserSkill.grant_xp(test_db, user.id, Skill.ATTACK, 83)
    assert result.leveled_up is True
    assert result.old_level == 1
    assert result.new_level == 2
    assert result.levels_gained == 1

    # Verify in database
    skill = await UserSkill.get(test_db, user.id, Skill.ATTACK)
    assert skill.level == 2
    assert skill.xp == 83


async def test_multiple_level_ups(test_db, clean_user_state):
    """Large XP grant can cause multiple level-ups at once."""
    user = await create_test_user(test_db, room_id="store-room")

    # Grant enough XP for level 10 (requires 1,154 XP)
    xp_for_10 = xp_for_level(10)
    result = await UserSkill.grant_xp(test_db, user.id, Skill.SPEECH, xp_for_10)
    assert result.leveled_up is True
    assert result.old_level == 1
    assert result.new_level == 10
    assert result.levels_gained == 9

    # Verify in database
    skill = await UserSkill.get(test_db, user.id, Skill.SPEECH)
    assert skill.level == 10
    assert skill.xp == xp_for_10


async def test_xp_cap_enforcement(test_db, clean_user_state):
    """XP is capped at MAX_XP (200,000,000)."""
    user = await create_test_user(test_db, room_id="store-room")

    # Grant XP close to max
    await UserSkill.grant_xp(test_db, user.id, Skill.FISHING, MAX_XP - 100)

    # Grant more than the remaining cap
    result = await UserSkill.grant_xp(test_db, user.id, Skill.FISHING, 500)
    assert result.new_xp == MAX_XP  # Capped, not MAX_XP - 100 + 500

    # Verify in database
    skill = await UserSkill.get(test_db, user.id, Skill.FISHING)
    assert skill.xp == MAX_XP
    assert skill.level == 99


async def test_total_level_calculation(test_db, clean_user_state):
    """Total level is the sum of all skill levels."""
    user = await create_test_user(test_db, room_id="store-room")

    # All skills start at level 1
    skills = await UserSkill.get_all(test_db, user.id)
    total = sum(s.level for s in skills)
    assert total == SKILL_COUNT  # 5 skills * level 1 = 5

    # Level up attack to 5 (requires 388 XP)
    await UserSkill.grant_xp(test_db, user.id, Skill.ATTACK, xp_for_level(5))

    skills = await UserSkill.get_all(test_db, user.id)
    total = sum(s.level for s in skills)
    # 4 skills at level 1 + attack at level 5 = 9
    assert total == SKILL_COUNT - 1 + 5


async def test_all_skills_initialized(test_db, clean_user_state):
    """New user gets all skills initialized at level 1."""
    user = await create_test_user(test_db, room_id="store-room")

    skills = await UserSkill.get_all(test_db, user.id)
    assert len(skills) == SKILL_COUNT

    for skill in skills:
        assert skill.level == 1
        assert skill.xp == 0
        assert skill.user_id == user.id


async def test_xp_persists_across_actions(test_db, clean_user_state):
    """XP persists in database across multiple game actions."""
    user = await create_test_user(test_db, room_id="store-room")

    # Grant some agility XP
    await UserSkill.grant_xp(test_db, user.id, Skill.AGILITY, 50)

    # Perform unrelated game actions (look at room)
    await act(test_db, user.id, LookCommand(), f"room://{user.current_room}")

    # Verify XP still there
    skill = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill.xp == 50


async def test_grant_xp_rejects_negative_amount(test_db, clean_user_state):
    """grant_xp raises ValueError for negative amounts."""
    user = await create_test_user(test_db, room_id="store-room")

    with pytest.raises(ValueError, match="XP amount must be positive"):
        await UserSkill.grant_xp(test_db, user.id, Skill.ATTACK, -10)


async def test_grant_xp_rejects_zero_amount(test_db, clean_user_state):
    """grant_xp raises ValueError for zero amount."""
    user = await create_test_user(test_db, room_id="store-room")

    with pytest.raises(ValueError, match="XP amount must be positive"):
        await UserSkill.grant_xp(test_db, user.id, Skill.ATTACK, 0)


async def test_cumulative_xp_from_multiple_actions(test_db, clean_user_state):
    """XP accumulates correctly across multiple interactions."""
    user = await create_test_user(test_db, room_id="store-room")

    # Grant agility XP twice
    await UserSkill.grant_xp(test_db, user.id, Skill.AGILITY, 28)
    await UserSkill.grant_xp(test_db, user.id, Skill.AGILITY, 28)

    skill = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill.xp == 56


async def test_level_boundary_exact(test_db, clean_user_state):
    """Granting exactly the XP needed for a level lands on the boundary."""
    user = await create_test_user(test_db, room_id="store-room")

    # Level 2 boundary is exactly 83 XP
    result = await UserSkill.grant_xp(test_db, user.id, Skill.VITALITY, 83)
    assert result.new_level == 2
    assert result.new_xp == 83
    assert result.leveled_up is True

    # One less than level 3 boundary (174 XP)
    xp_for_3 = xp_for_level(3)
    remaining = xp_for_3 - 83 - 1
    result = await UserSkill.grant_xp(test_db, user.id, Skill.VITALITY, remaining)
    assert result.new_level == 2
    assert result.leveled_up is False

    # Now add 1 more to hit level 3
    result = await UserSkill.grant_xp(test_db, user.id, Skill.VITALITY, 1)
    assert result.new_level == 3
    assert result.leveled_up is True


async def test_movement_grants_agility_xp(test_db, clean_user_state):
    """Moving to a new room grants agility XP via the full observer chain."""
    user = await create_test_user(test_db, room_id="foyer")

    # Verify no agility XP before moving
    skill_before = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill_before.xp == 0
    assert skill_before.level == 1

    # Move to a different room
    move_result = await move(test_db, user.id, "store-room")

    # SkillsObserver should have processed the agility XP grant
    assert len(move_result.skills.results) == 1
    xp_result = move_result.skills.results[0]
    assert xp_result.skill == Skill.AGILITY
    assert xp_result.old_xp == 0
    assert xp_result.new_xp == AGILITY_XP_PER_MOVE
    assert xp_result.old_level == 1

    # Verify agility XP persisted in the database
    skill_after = await UserSkill.get(test_db, user.id, Skill.AGILITY)
    assert skill_after.xp == AGILITY_XP_PER_MOVE
    assert skill_after.level == 1


async def test_attack_destroy_grants_attack_xp(test_db, clean_user_state):
    """Destroying an entity via attack grants Attack XP via template effect."""
    user = await create_test_user(test_db, room_id="store-room")

    # Find the test target dummy in the room (has grant_xp + destroy on attack)
    dummy = next(
        o
        for o in await autocomplete(test_db, user.id, "Test Target Dummy")
        if not isinstance(o, RoomEntityInstance)
        and o.entity.name == "Test Target Dummy"
    )

    # Check initial attack XP
    skill_before = await UserSkill.get(test_db, user.id, Skill.ATTACK)
    assert skill_before.xp == 0
    assert skill_before.level == 1

    # Attack the dummy (triggers grant_xp("attack", 25) + destroy via template)
    result = await act(
        test_db, user.id, AttackCommand(), f"entity://{dummy.instance_id}"
    )
    assert "smash" in result.output.lower()

    # Verify effects observed the XP grant signal from template
    assert result.effects.has_xp_grants
    assert result.effects.xp_grants == [("attack", 25)]

    # SkillsObserver should have processed the XP grant during flush
    assert len(result.skills.results) == 1
    xp_result = result.skills.results[0]
    assert xp_result.skill == Skill.ATTACK
    assert xp_result.old_xp == 0
    assert xp_result.new_xp == 25
    assert xp_result.old_level == 1
    assert xp_result.new_level == 1  # 25 XP doesn't cross level 2 boundary (83 XP)
    assert xp_result.leveled_up is False

    # Verify XP persisted in database
    skill_after = await UserSkill.get(test_db, user.id, Skill.ATTACK)
    assert skill_after.xp == 25
    assert skill_after.level == 1
