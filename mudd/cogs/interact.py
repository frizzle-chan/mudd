"""Interact command for entity interactions."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.matching.entity_matcher import match_entity_by_prefix
from mudd.matching.verb_matcher import match_verb
from mudd.services.entity import RARITY_WEIGHTS, ResolvedEntity
from mudd.services.rendering import RenderingService, TemplateRenderError
from mudd.services.trigger_effects import TriggerEffects
from mudd.types import UserContext, VerbAction
from mudd.utils.random import weighted_choice

if TYPE_CHECKING:
    from mudd.services.entity import EntityService
    from mudd.services.inventory import InventoryService
    from mudd.services.player_context import PlayerContextService
    from mudd.services.visibility import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        entity_service: "EntityService",
        player_context: "PlayerContextService",
        visibility_service: "VisibilityServiceProtocol",
        inventory_service: "InventoryService",
        pool: asyncpg.Pool,
        rendering_service: RenderingService,
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.player_context = player_context
        self.visibility_service = visibility_service
        self._inventory = inventory_service
        self.pool = pool
        self._rendering = rendering_service

    async def target_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for target parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), prioritizes focused contents with
        "[Container Name]" prefix.
        """
        try:
            await self.visibility_service.wait_for_startup()

            room = getattr(interaction.channel, "name", None)
            if not room:
                return []

            # Get autocomplete choices with text filtering
            choices = await self.player_context.get_visible_entities(
                room, interaction.user.id, query=current
            )

            # Return as Discord choices (limit 25 per Discord API)
            return [
                app_commands.Choice(
                    name=c.display_name,
                    value=c.instance.entity.name,  # Use actual name for matching
                )
                for c in choices
            ][:25]
        except asyncpg.PostgresError:
            logger.exception(
                "Database error in target autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []
        except Exception:
            logger.exception(
                "Unexpected error in target autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="interact", description="Interact with things")
    @app_commands.describe(
        action="Action to perform (e.g., smash, touch, take)",
        target="Thing to interact with",
    )
    @app_commands.rename(target="with")
    @app_commands.autocomplete(target=target_autocomplete)
    async def interact(self, interaction: Interaction, target: str, action: str):
        """Interact with an entity using a verb."""
        await self.visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)
        if not room:
            await interaction.response.send_message(
                "You can't interact with anything here.", ephemeral=True
            )
            return

        user_id = interaction.user.id

        # Match verb first to determine entity source (room vs inventory)
        action_type = await match_verb(self.pool, action)

        if action_type is None:
            await interaction.response.send_message(
                "You can't do that.", ephemeral=True
            )
            return

        # For drop actions, look up entity from user's inventory
        if action_type == VerbAction.ON_DROP:
            all_entities = await self.entity_service.get_user_inventory(user_id)
            not_found_msg = f"You don't have '{target}'."
        else:
            # Uses get_room_entities (not get_autocomplete_entities) intentionally:
            # players can interact with hidden container contents if they know the name
            all_entities = await self.entity_service.get_room_entities(room)
            not_found_msg = f"You don't see '{target}' here."

        # Resolve target to entity
        match_result = match_entity_by_prefix(target, all_entities)

        if match_result.is_empty():
            await interaction.response.send_message(not_found_msg, ephemeral=True)
            return

        if match_result.is_ambiguous():
            names = [m.instance.entity.name for m in match_result.matches]
            names_list = ", ".join(f"*{name}*" for name in names)
            await interaction.response.send_message(
                f"Which one? {names_list}", ephemeral=True
            )
            return

        # Unique match
        matched_instance = match_result.matches[0].instance
        entity = matched_instance.entity

        # Check if target is in current focus (to decide whether to clear focus)
        is_in_focus = await self.player_context.is_entity_in_focus(
            user_id, room, entity.id
        )

        if is_in_focus:
            # Update timestamp to prevent timeout when interacting with focused content
            await self.player_context.update_focus_timestamp(user_id)
        else:
            # Clear focus when interacting with entity not in current focus
            await self.player_context.clear_focus(user_id, reason="interaction")

        # Get handler text based on action
        handler_text = _get_handler_text(entity, action_type)

        if handler_text is None:
            await interaction.response.send_message("Nothing happens.", ephemeral=True)
            return

        # Fetch container contents for template (regardless of contents_visible)
        container_contents = await self.entity_service.get_container_contents(
            entity.id, room
        )
        contents_str = self._rendering.build_contents_string(container_contents)

        # Create user context for template
        user_context = UserContext(
            name=interaction.user.display_name,
            mention=interaction.user.mention,
        )

        # Render template with entity and user context
        effects: TriggerEffects
        try:
            output, effects = self._rendering.render_with_effects(
                handler_text, entity, user_context, contents_str
            )
        except TemplateRenderError:
            logger.warning(
                "Template error rendering '%s' handler for entity '%s'",
                action_type.value,
                entity.id,
                exc_info=True,
            )
            output = f"*{entity.name}* responds, but something went wrong."
            effects = TriggerEffects()

        # Handle focus changes based on action type
        if action_type == VerbAction.ON_OPEN and entity.focus_mode != "none":
            # Establish focus when opening a focusable entity (e.g., container)
            await self.player_context.set_focus(user_id, room, entity)
        elif action_type == VerbAction.ON_CLOSE:
            # Clear focus when explicitly closing
            # Get close message (template) before clearing
            close_template = await self.player_context.clear_focus(
                user_id, reason="close"
            )
            if close_template:
                # Render the close template and append
                try:
                    close_output = self._rendering.render(close_template, entity, "")
                    output = f"{output}\n\n{close_output}"
                except TemplateRenderError:
                    logger.warning(
                        "Template error rendering on_close for entity '%s'",
                        entity.id,
                        exc_info=True,
                    )
                    output = f"{output}\n\nYou step away from the *{entity.name}*."

        # Handle item pickup for ON_TAKE action
        if action_type == VerbAction.ON_TAKE:
            pickup_result = await self._handle_pickup(
                interaction, entity, matched_instance.instance_id, room, output
            )
            if pickup_result is not None:
                # pickup_result is either a modified output or an error message
                output = pickup_result

        # Handle item drop for ON_DROP action
        if action_type == VerbAction.ON_DROP:
            drop_result = await self._handle_drop(
                interaction, entity, matched_instance.instance_id, room, effects
            )
            if drop_result is not None:
                output = drop_result

        await interaction.response.send_message(output, ephemeral=True)

        # Execute broadcast side effects (public messages to channel)
        channel = interaction.channel
        if channel is not None and hasattr(channel, "send"):
            for broadcast_msg in effects.broadcasts:
                await channel.send(broadcast_msg)  # type: ignore[union-attr]

            # Process grant_random effects
            for grant_random_effect in effects.grant_randoms:
                await self._handle_grant_random(
                    interaction, grant_random_effect.tag, channel
                )

            # Process grant effects
            for grant_effect in effects.grants:
                await self._handle_grant(interaction, grant_effect.entity_id, channel)

    async def _handle_pickup(
        self,
        interaction: Interaction,
        entity: ResolvedEntity,
        instance_id: UUID,
        room: str,
        template_output: str,
    ) -> str | None:
        """Handle item pickup based on spawn_mode.

        Args:
            interaction: Discord interaction
            entity: The entity being taken
            instance_id: UUID of the entity instance
            room: Current room name
            template_output: The rendered on_take template output

        Returns:
            Modified output string if pickup happened, None if spawn_mode=none
        """
        if entity.spawn_mode == "none":
            # Entity can't be taken - template already has the response
            return None

        user_id = interaction.user.id
        guild = interaction.guild
        if guild is None:
            return "You can't take items outside a server."

        if entity.spawn_mode == "clone":
            # Quest item - check if user already has this entity type
            existing = await self.pool.fetchval(
                """SELECT id FROM entity_instances
                WHERE owner_id = $1 AND entity_id = $2""",
                user_id,
                entity.id,
            )
            if existing:
                return "You already have this item."

            # Create a new instance in the user's inventory
            new_instance_id = await self.pool.fetchval(
                """INSERT INTO entity_instances (entity_id, owner_id)
                VALUES ($1, $2) RETURNING id""",
                entity.id,
                user_id,
            )
            if new_instance_id is None:
                logger.error("Failed to create clone instance for %s", entity.id)
                return "Something went wrong picking up the item."

            # Create Discord thread for the item
            thread = await self._inventory.create_item_thread(
                guild, user_id, new_instance_id, entity.display_name, template_output
            )
            if thread is None:
                logger.warning("Failed to create thread for cloned item %s", entity.id)
                # Item is still in inventory, just no Discord thread

            return template_output

        elif entity.spawn_mode == "move":
            # Move the existing instance to the user's inventory
            result = await self.pool.execute(
                """UPDATE entity_instances
                SET room = NULL, owner_id = $1, player_dropped = FALSE
                WHERE id = $2 AND room = $3""",
                user_id,
                instance_id,
                room,
            )
            if result == "UPDATE 0":
                return "The item is no longer there."

            # Create Discord thread for the item
            thread = await self._inventory.create_item_thread(
                guild, user_id, instance_id, entity.display_name, template_output
            )
            if thread is None:
                logger.warning("Failed to create thread for moved item %s", entity.id)
                # Item is still in inventory, just no Discord thread

            return template_output

        return None

    async def _handle_drop(
        self,
        interaction: Interaction,
        entity: ResolvedEntity,
        instance_id: UUID,
        room: str,
        effects: TriggerEffects,
    ) -> str | None:
        """Handle item drop from inventory to room.

        Args:
            interaction: Discord interaction
            entity: The entity being dropped
            instance_id: UUID of the entity instance
            room: Current room name to drop into
            effects: TriggerEffects from template rendering

        Returns:
            Error message if drop failed, None if successful
        """
        # Check if template called effects.drop()
        if not effects.has_drop:
            # Template didn't call drop() - item stays in inventory
            return None

        guild = interaction.guild
        if guild is None:
            return "You can't drop items outside a server."

        # Check floor clutter limit (5 player-dropped items per room)
        clutter_count = await self.pool.fetchval(
            """SELECT COUNT(*) FROM entity_instances
            WHERE room = $1 AND player_dropped = TRUE""",
            room,
        )
        if clutter_count >= 5:
            return "The floor is too cluttered. Pick something up first."

        # Move instance from inventory to room
        result = await self.pool.execute(
            """UPDATE entity_instances
            SET room = $1, owner_id = NULL, player_dropped = TRUE
            WHERE id = $2 AND owner_id = $3""",
            room,
            instance_id,
            interaction.user.id,
        )
        if result == "UPDATE 0":
            return "You no longer have that item."

        # Delete Discord inventory thread
        deleted = await self._inventory.delete_item_thread(guild, instance_id)
        if not deleted:
            logger.warning("Failed to delete thread for dropped item %s", entity.id)

        return None

    async def _handle_grant_random(
        self,
        interaction: Interaction,
        tag: str,
        channel: object,
    ) -> None:
        """Handle granting a random item from a tag.

        Queries entities matching the tag (excluding quest rarity),
        does weighted random selection, creates an instance in the
        user's inventory, and broadcasts the result.

        Args:
            interaction: Discord interaction
            tag: Tag to filter entities by
            channel: Channel to broadcast to
        """
        guild = interaction.guild
        if guild is None:
            return

        # Query entities matching the tag (excluding quest rarity)
        candidates = await self.pool.fetch(
            """
            SELECT DISTINCT e.id, e.name, e.rarity
            FROM entities e
            JOIN entity_tags et ON e.id = et.entity_id
            WHERE et.tag = $1 AND e.rarity != 'quest'
            """,
            tag,
        )

        if not candidates:
            logger.warning("No entities found for grant_random with tag '%s'", tag)
            return

        # Build list of (data, weight) for weighted selection
        items = [
            (
                (candidate["id"], candidate["name"], candidate["rarity"]),
                RARITY_WEIGHTS.get(candidate["rarity"], 0),
            )
            for candidate in candidates
        ]

        selected = weighted_choice(items)
        if selected is None:
            logger.warning("No weighted candidates for grant_random with tag '%s'", tag)
            return

        entity_id, name, rarity = selected

        # Create instance in user's inventory
        user_id = interaction.user.id
        new_instance_id = await self.pool.fetchval(
            """INSERT INTO entity_instances (entity_id, owner_id)
            VALUES ($1, $2) RETURNING id""",
            entity_id,
            user_id,
        )
        if new_instance_id is None:
            logger.error("Failed to create grant_random instance for %s", entity_id)
            return

        # Get display_name via resolve_entity for proper formatting
        resolved = await self.pool.fetchrow(
            "SELECT * FROM resolve_entity($1)", entity_id
        )
        display_name = resolved["display_name"] if resolved else name

        # Create Discord thread for the item
        thread = await self._inventory.create_item_thread(
            guild,
            user_id,
            new_instance_id,
            display_name,
            f"You received a **{display_name}**!",
        )
        if thread is None:
            logger.warning(
                "Failed to create thread for grant_random item %s", entity_id
            )

        # Broadcast the granted item to the channel
        user_name = interaction.user.display_name
        await channel.send(f"**{user_name}** picks up a *{display_name}*.")  # type: ignore[union-attr]

    async def _handle_grant(
        self,
        interaction: Interaction,
        entity_id: str,
        channel: object,
    ) -> None:
        """Handle granting a specific item to the user.

        Creates a new instance of the entity in the user's inventory
        and creates a Discord thread for it.

        Args:
            interaction: Discord interaction
            entity_id: ID of the entity to grant
            channel: Channel (unused, kept for consistency with grant_random)
        """
        guild = interaction.guild
        if guild is None:
            return

        user_id = interaction.user.id

        # Verify entity exists and get display_name
        resolved = await self.pool.fetchrow(
            "SELECT * FROM resolve_entity($1)", entity_id
        )
        if resolved is None:
            logger.warning("Entity '%s' not found for grant()", entity_id)
            return

        display_name = resolved["display_name"]

        # Create instance in user's inventory
        new_instance_id = await self.pool.fetchval(
            """INSERT INTO entity_instances (entity_id, owner_id)
            VALUES ($1, $2) RETURNING id""",
            entity_id,
            user_id,
        )
        if new_instance_id is None:
            logger.error("Failed to create grant instance for %s", entity_id)
            return

        # Create Discord thread for the item
        thread = await self._inventory.create_item_thread(
            guild,
            user_id,
            new_instance_id,
            display_name,
            f"You received a **{display_name}**!",
        )
        if thread is None:
            logger.warning("Failed to create thread for granted item %s", entity_id)


def _get_handler_text(entity: ResolvedEntity, action: VerbAction) -> str | None:
    """Get handler text from entity based on action.

    Args:
        entity: The resolved entity
        action: The verb action (on_look, on_attack, etc.)

    Returns:
        Handler text or None if no handler defined
    """
    handler_map = {
        VerbAction.ON_LOOK: entity.on_look,
        VerbAction.ON_TOUCH: entity.on_touch,
        VerbAction.ON_ATTACK: entity.on_attack,
        VerbAction.ON_USE: entity.on_use,
        VerbAction.ON_TAKE: entity.on_take,
        VerbAction.ON_OPEN: entity.on_open,
        VerbAction.ON_CLOSE: entity.on_close,
        VerbAction.ON_DROP: entity.on_drop,
    }
    return handler_map.get(action)
