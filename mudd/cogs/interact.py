"""Interact command for entity interactions."""

import logging
import random
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.matching.verb_matcher import match_verb
from mudd.services.currency import HOUSE_ACCOUNT_ID, TransferError
from mudd.services.entity import ResolvedEntity
from mudd.services.entity_resolution import ResolutionError
from mudd.services.inventory import DropTarget
from mudd.services.rendering import RenderingService, TemplateRenderError
from mudd.services.trigger_effects import TriggerEffects
from mudd.types import UserContext, VerbAction
from mudd.utils.text import indefinite_article

if TYPE_CHECKING:
    from mudd.services.currency import CurrencyService
    from mudd.services.entity import EntityService
    from mudd.services.entity_resolution import EntityResolutionService
    from mudd.services.inventory import InventoryService
    from mudd.services.visibility import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        entity_service: "EntityService",
        entity_resolution: "EntityResolutionService",
        visibility_service: "VisibilityServiceProtocol",
        inventory_service: "InventoryService",
        pool: asyncpg.Pool,
        rendering_service: RenderingService,
        currency_service: "CurrencyService",
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.entity_resolution = entity_resolution
        self.visibility_service = visibility_service
        self._inventory = inventory_service
        self.pool = pool
        self._rendering = rendering_service
        self._currency = currency_service

    async def target_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for target parameter.

        Uses unified EntityResolutionService for all contexts:
        1. Inventory thread: Shows thread's item (and contents if container)
        2. "i." prefix: Searches user's inventory
        3. Default: Searches room entities with focus handling
        """
        try:
            # Build context and get choices using unified API
            ctx = await self.entity_resolution.build_context(interaction, current)
            return await self.entity_resolution.get_autocomplete_choices(ctx, current)

        except asyncpg.PostgresError:
            logger.exception("Database error in target autocomplete")
            return []
        except Exception:
            logger.exception("Unexpected error in target autocomplete")
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
        user_id = interaction.user.id

        # Match verb first to determine context
        action_type = await match_verb(self.pool, action)

        if action_type is None:
            await interaction.response.send_message(
                "You can't do that.", ephemeral=True
            )
            return

        # For drop actions, force inventory context by prefixing "i."
        # This ensures the target is resolved from inventory
        context_query = target
        if action_type == VerbAction.ON_DROP and not target.startswith("i."):
            context_query = f"i.{target}"

        # Build context for resolution
        ctx = await self.entity_resolution.build_context(interaction, context_query)
        room = ctx.room

        if not room:
            await interaction.response.send_message(
                "You can't interact with anything here.", ephemeral=True
            )
            return

        # Resolve target using unified API
        result = await self.entity_resolution.resolve_target(ctx, target)

        if isinstance(result, ResolutionError):
            if result.error_type == "ambiguous":
                await interaction.response.send_message(result.message, ephemeral=True)
            else:
                await interaction.response.send_message(result.message, ephemeral=True)
            return

        # Successfully resolved entity
        matched_instance = result.instance
        entity = matched_instance.entity
        source = result.source  # "room", "inventory", or "container"

        # Skip focus manipulation for inventory actions - they don't affect room focus
        is_inventory_source = source in ("inventory", "container")
        if not is_inventory_source and action_type != VerbAction.ON_DROP:
            # Check if target is in current focus (to decide whether to clear focus)
            is_in_focus = await self.entity_resolution.is_entity_in_focus(
                user_id, room, entity.id
            )

            if is_in_focus:
                # Update timestamp to prevent timeout when interacting with focus
                await self.entity_resolution.update_focus_timestamp(user_id)
            else:
                # Clear focus when interacting with entity not in current focus
                await self.entity_resolution.clear_focus(user_id, reason="interaction")

        # Get handler text based on action
        handler_text = _get_handler_text(entity, action_type)

        if handler_text is None:
            await interaction.response.send_message("Nothing happens.", ephemeral=True)
            return

        # Fetch container contents for template (regardless of contents_visible)
        # For inventory items, check inventory container contents
        if is_inventory_source:
            container_contents = (
                await self.entity_resolution._get_inventory_container_contents(
                    user_id, entity.id
                )
            )
        else:
            container_contents = await self.entity_service.get_container_contents(
                entity.id, room
            )
        contents_str = self._rendering.build_contents_string(container_contents)

        # Create user context for template
        user_context = UserContext(
            name=interaction.user.display_name,
            mention=interaction.user.mention,
        )

        # For drop actions, look up focused container for template context
        container: ResolvedEntity | None = None
        if action_type == VerbAction.ON_DROP:
            focus = await self.entity_resolution.get_focus(user_id, room)
            if focus and focus.focus_mode == "container":
                container = await self.entity_service.get_entity(focus.entity_id)

        # Fetch balance for wallet entities
        balance_str = ""
        if entity.id == "wallet":
            balance = await self._currency.get_balance(user_id)
            if balance is not None:
                balance_str = f"¥{balance:,}"

        # Render template with entity and user context
        effects: TriggerEffects
        try:
            output, effects = self._rendering.render_with_effects(
                handler_text, entity, user_context, contents_str, container, balance_str
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
            await self.entity_resolution.set_focus(user_id, room, entity)
        elif action_type == VerbAction.ON_CLOSE:
            # Clear focus when explicitly closing
            # Get close message (template) before clearing
            close_template = await self.entity_resolution.clear_focus(
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
                interaction, entity, matched_instance.instance_id, room, output, effects
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

        # Execute cleanup operations (thread deletions, etc.)
        await self._execute_cleanups(interaction, effects)

        # Handle entity destruction (before grants so spawning pool can respawn)
        if effects.has_destroy:
            await self._handle_destroy(interaction.guild, matched_instance.instance_id)

        # Execute broadcast side effects (public messages to user's current room)
        # Look up room from DB since interaction may come from inventory thread
        guild = interaction.guild
        if guild is not None:
            user_room = await self.pool.fetchval(
                "SELECT current_room FROM users WHERE id = $1",
                interaction.user.id,
            )
            room_channel = discord.utils.get(guild.text_channels, name=user_room)

            if room_channel is not None:
                for broadcast_msg in effects.broadcasts:
                    await room_channel.send(broadcast_msg)

                # Process grant_random effects
                for grant_random_effect in effects.grant_randoms:
                    await self._handle_grant_random(
                        interaction, grant_random_effect.tag, room_channel
                    )

                # Process grant effects
                for grant_effect in effects.grants:
                    await self._handle_grant(
                        interaction, grant_effect.entity_id, room_channel
                    )

                # Process dispense effect
                if effects.has_dispense:
                    await self._handle_dispense(
                        interaction, matched_instance.entity, room_channel
                    )

        # Process currency grants (outside room_channel check - doesn't need channel)
        if guild is not None:
            for currency_grant in effects.currency_grants:
                await self._handle_currency_grant(
                    guild, interaction.user.id, currency_grant.amount
                )

    async def _handle_pickup(
        self,
        interaction: Interaction,
        entity: ResolvedEntity,
        instance_id: UUID,
        room: str,
        template_output: str,
        effects: TriggerEffects,
    ) -> str | None:
        """Handle item pickup based on effects.pickup() call.

        Args:
            interaction: Discord interaction
            entity: The entity being taken (unused, kept for signature)
            instance_id: UUID of the entity instance
            room: Current room name
            template_output: The rendered on_take template output
            effects: TriggerEffects from template rendering

        Returns:
            Modified output string if pickup happened, None if pickup() not called
        """
        if not effects.has_pickup:
            return None

        guild = interaction.guild
        if guild is None:
            return "You can't take items outside a server."

        result = await self._inventory.add_to_inventory(
            guild, interaction.user.id, instance_id, source_room=room
        )
        if not result.success:
            return result.error or "The item is no longer there."

        self.entity_resolution.invalidate_cache()
        return template_output

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
        if not effects.has_drop:
            return None

        guild = interaction.guild
        if guild is None:
            return "You can't drop items outside a server."

        user_id = interaction.user.id

        # Check for focus context to determine drop target
        focus = await self.entity_resolution.get_focus(user_id, room)
        container_entity_id: str | None = None

        if focus and focus.focus_mode == "container":
            container_entity_id = focus.entity_id
        else:
            # Dropping to floor - check clutter limit
            clutter_count = await self.pool.fetchval(
                """SELECT COUNT(*) FROM entity_instances
                WHERE room = $1 AND player_dropped = TRUE
                AND container_entity_id IS NULL""",
                room,
            )
            if clutter_count >= 5:
                return "The floor is too cluttered. Pick something up first."

        target = DropTarget(room=room, container_entity_id=container_entity_id)
        result = await self._inventory.remove_from_inventory(
            guild, user_id, instance_id, entity.id, target
        )
        if not result.success:
            return result.error or "You no longer have that item."

        # Queue thread deletion to run after response is sent
        effects.queue_thread_deletion(instance_id, guild.id)

        self.entity_resolution.invalidate_cache()
        return None

    async def _handle_grant_random(
        self,
        interaction: Interaction,
        tag: str,
        channel: discord.TextChannel,
    ) -> None:
        """Handle granting a random item from a tag.

        Uses EntityService for weighted random selection, creates an instance
        in the user's inventory, and broadcasts the result.

        Args:
            interaction: Discord interaction
            tag: Tag to filter entities by
            channel: Channel to broadcast to
        """
        guild = interaction.guild
        if guild is None:
            return

        # Select random entity by tag with weighted rarity
        entity = await self.entity_service.get_random_entity_by_tag(tag)
        if entity is None:
            logger.warning("No entities found for grant_random with tag '%s'", tag)
            return

        result = await self._inventory.grant_item(guild, interaction.user.id, entity.id)
        if not result.success:
            logger.warning("Grant random failed: %s", result.error)
            return

        # Broadcast the granted item to the channel
        user_name = interaction.user.display_name
        await channel.send(f"**{user_name}** picks up a *{entity.display_name}*.")

    async def _handle_grant(
        self,
        interaction: Interaction,
        entity_id: str,
        channel: discord.TextChannel,
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

        result = await self._inventory.grant_item(guild, interaction.user.id, entity_id)
        if not result.success:
            logger.warning("Grant failed: %s", result.error)

    async def _execute_cleanups(
        self, interaction: Interaction, effects: TriggerEffects
    ) -> None:
        """Execute cleanup operations after response sent.

        Runs deferred operations like thread deletions that must happen
        after the interaction response to avoid "Unknown Channel" errors.

        Args:
            interaction: Discord interaction
            effects: TriggerEffects containing queued cleanup operations
        """
        guild = interaction.guild
        if guild is None:
            return

        for cleanup in effects.cleanups:
            if cleanup.operation_type == "delete_thread":
                deleted = await self._inventory.delete_item_thread(
                    guild, cleanup.instance_id
                )
                if not deleted:
                    logger.warning(
                        "Failed to delete thread for instance %s",
                        cleanup.instance_id,
                    )

    async def _handle_destroy(
        self, guild: discord.Guild | None, instance_id: UUID
    ) -> bool:
        """Delete an entity instance and its inventory thread.

        Args:
            guild: Discord guild (needed for thread deletion)
            instance_id: UUID of the entity instance to destroy

        Returns:
            True if the instance was deleted, False otherwise
        """
        if guild is None:
            return False

        deleted = await self._inventory.destroy_instance(guild, instance_id)
        if deleted:
            self.entity_resolution.invalidate_cache()
        return deleted

    async def _handle_dispense(
        self,
        interaction: Interaction,
        container_entity: ResolvedEntity,
        channel: discord.TextChannel,
    ) -> None:
        """Handle dispensing an item from a container to the user.

        Queries the container's contents and picks one randomly, then
        moves it to the user's inventory. Charges 10 yen to use.

        Args:
            interaction: Discord interaction
            container_entity: The container entity dispensing items
            channel: Channel to broadcast result to
        """
        # Charge 10 yen to use the slot machine
        transfer_result = await self._currency.transfer(
            interaction.user.id,
            HOUSE_ACCOUNT_ID,
            10,
            "Slot machine usage fee",
        )

        if not transfer_result.success:
            # Handle insufficient funds or other errors
            if transfer_result.error == TransferError.INSUFFICIENT_BALANCE:
                user_name = interaction.user.display_name
                await channel.send(
                    f"**{user_name}** doesn't have enough yen to use "
                    f"the slot machine. (Cost: ¥10)"
                )
            else:
                user_name = interaction.user.display_name
                await channel.send(
                    f"**{user_name}** can't use the slot machine right now."
                )
            return

        # Query container contents (items inside this container in the room)
        user_room = await self.pool.fetchval(
            "SELECT current_room FROM users WHERE id = $1",
            interaction.user.id,
        )
        if user_room is None:
            return

        # Get items inside the container
        contents = await self.pool.fetch(
            """SELECT ei.id, ei.entity_id
            FROM entity_instances ei
            WHERE ei.container_entity_id = $1 AND ei.room = $2""",
            container_entity.id,
            user_room,
        )

        if not contents:
            # Container is empty
            await channel.send("The slot machine is waiting to be refilled.")
            return

        # Pick one randomly
        item_row = random.choice(contents)
        item_instance_id = item_row["id"]
        item_entity_id = item_row["entity_id"]

        # Get the entity for display name
        item_entity = await self.entity_service.get_entity(item_entity_id)
        if item_entity is None:
            logger.error("Entity %s not found for dispense", item_entity_id)
            return

        guild = interaction.guild
        if guild is None:
            return

        result = await self._inventory.add_to_inventory(
            guild, interaction.user.id, item_instance_id
        )
        if result.success:
            self.entity_resolution.invalidate_cache()
            user_name = interaction.user.display_name
            article = indefinite_article(item_entity.display_name)
            name = item_entity.display_name
            await channel.send(f"**{user_name}** got {article} *{name}*!")

    async def _handle_currency_grant(
        self,
        guild: discord.Guild,
        user_id: int,
        amount: int,
    ) -> None:
        """Grant currency to user from house account.

        Args:
            guild: Discord guild
            user_id: Discord user ID to grant currency to
            amount: Amount of yen to grant
        """
        # Transfer from house account (user_id=0)
        result = await self._currency.transfer(
            sender_id=0,
            recipient_id=user_id,
            amount=amount,
            memo="Item pickup",
        )

        if not result.success:
            logger.warning(f"Currency grant failed for user {user_id}: {result.error}")
            return

        # Update wallet thread with new balance
        balance_str = f"\u00a5{result.recipient_new_balance:,}"
        await self._update_wallet_thread(
            guild, user_id, balance_str, f"\U0001f4b0 Found \u00a5{amount:,}"
        )

    async def _update_wallet_thread(
        self,
        guild: discord.Guild,
        user_id: int,
        balance_str: str,
        notification: str,
    ) -> None:
        """Update a user's wallet thread description and post a notification.

        Args:
            guild: Discord guild
            user_id: User whose wallet to update
            balance_str: Formatted balance string (e.g., "\\u00a51,000")
            notification: Notification message to post
        """
        try:
            # Get wallet instance ID from currency account
            wallet_instance_id = await self._currency.get_wallet_instance_id(user_id)
            if wallet_instance_id is None:
                logger.warning(f"No wallet instance found for user {user_id}")
                return

            # Get entity instance to find thread ID
            wallet_instance = await self.entity_service.get_entity_instance(
                UUID(wallet_instance_id)
            )
            if wallet_instance is None:
                logger.warning(f"Wallet instance {wallet_instance_id} not found")
                return

            # Get thread ID from database
            row = await self.pool.fetchrow(
                """
                SELECT discord_thread_id, discord_description_msg_id
                FROM entity_instances WHERE id = $1
                """,
                wallet_instance_id,
            )
            if row is None or row["discord_thread_id"] is None:
                logger.warning(f"No thread for wallet instance {wallet_instance_id}")
                return

            thread_id = row["discord_thread_id"]
            msg_id = row["discord_description_msg_id"]

            # Get thread
            thread = guild.get_thread(thread_id)
            if thread is None:
                logger.warning(f"Thread {thread_id} not found in guild")
                return

            # Render new description with updated balance
            new_description = await self._rendering.render_entity_on_look(
                wallet_instance,
                self.entity_service,
                None,  # room is None for inventory items
                balance_str,
                include_heading=False,  # Thread title shows the item name
            )

            # Update thread description message
            if msg_id:
                try:
                    message = await thread.fetch_message(msg_id)
                    await message.edit(content=new_description)
                except discord.NotFound:
                    logger.warning(f"Description message {msg_id} not found")
                except discord.HTTPException as e:
                    logger.error(f"Failed to update wallet description: {e}")

            # Post notification
            try:
                await thread.send(notification)
            except discord.HTTPException as e:
                logger.error(f"Failed to post wallet notification: {e}")

        except Exception:
            logger.exception(f"Failed to update wallet thread for user {user_id}")


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
