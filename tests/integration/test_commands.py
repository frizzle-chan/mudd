"""End-to-end tests for entity template rendering."""

import pytest

from mudd.commands import LookCommand
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.room import Room
from mudd.models.user import User
from mudd.observers import EffectsObserver
from mudd.scene import Scene

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestCommands:
    """Validates all entity templates render without errors."""

    async def test_look_command(self, test_client, clean_user_state):
        """Every entity with on_look handler should render successfully."""
        pool = test_client.pool

        # Get all entity instances from rooms
        rows = await pool.fetch("""
            SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                   ei.container_entity_id, r.*
            FROM entity_instances ei
            CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
            WHERE ei.room IS NOT NULL
        """)

        instances = [
            EntityInstance._from_row(row, ResolvedEntity._from_row(row), pool)
            for row in rows
        ]

        # Create test user
        user_id = 999999
        await pool.execute(
            "INSERT INTO users (id, current_room) VALUES ($1, 'foyer')",
            user_id,
        )
        user = await User.get(pool, user_id)
        assert user is not None

        errors: list[str] = []
        look_cmd = LookCommand()

        for instance in instances:
            # Skip entities without on_look handler
            if instance.entity.on_look is None:
                continue

            # Skip entities without a room
            if instance.room_id is None:
                continue

            try:
                # Get room for scene
                room = await Room.get(pool, instance.room_id)
                if not room:
                    continue

                # Build scene with effects observer
                effects = EffectsObserver()
                scene = Scene(user=user, room=room, _pool=pool).with_observers(effects)

                # Execute look command
                result = await look_cmd.execute(scene, instance)

                if not result.output:
                    errors.append(f"{instance.entity.id}: Empty output")
            except Exception as e:
                errors.append(f"{instance.entity.id}: {type(e).__name__}: {e}")

        assert not errors, "Template rendering errors:\n" + "\n".join(errors)
