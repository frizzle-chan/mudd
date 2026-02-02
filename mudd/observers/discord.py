"""Discord reconciler that syncs Discord state with model changes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    import asyncpg

    from mudd.services.inventory import InventoryService
    from mudd.services.rendering import RenderingService

from mudd.events import (
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
)
from mudd.models.entity import EntityInstance

logger = logging.getLogger(__name__)


class DiscordReconciler:
    """Observes model changes and reconciles Discord state.

    Handles Discord thread management when entities change state:
    - "picked_up": Creates inventory thread for the item
    - "dropped": Deletes inventory thread
    - "destroyed": Deletes inventory thread

    The reconciler implements the Observer protocol: notify() is sync
    and queues notifications for async processing. Call flush() after
    sending the response to execute queued Discord operations.

    Usage:
        reconciler = DiscordReconciler(bot, pool, inventory_service, rendering_service)
        instance = instance.with_observers(reconciler)
        new_instance = await instance.move_to_inventory(user)
        await interaction.response.send_message(...)
        await reconciler.flush()  # Execute Discord operations after response
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        inventory_service: InventoryService,
        rendering_service: RenderingService,
    ) -> None:
        """Initialize the Discord reconciler.

        Args:
            bot: Discord bot client
            pool: Database connection pool
            inventory_service: Service for inventory thread management
            rendering_service: Service for rendering entity descriptions
        """
        self.bot = bot
        self.pool = pool
        self.inventory_service = inventory_service
        self.rendering_service = rendering_service
        self._pending: list[tuple[EntityInstance, str]] = []

    def notify(self, event: GameEvent) -> None:
        """Receive notification (sync). Queue for async processing.

        This method is called synchronously by EntityInstance._notify().
        It queues the event for later async processing via flush().

        Args:
            event: The game event to process
        """
        match event:
            case EntityPickedUpEvent(instance=instance):
                self._pending.append((instance, "picked_up"))
            case EntityDroppedEvent(instance=instance):
                self._pending.append((instance, "dropped"))
            case EntityDestroyedEvent(instance=instance):
                self._pending.append((instance, "destroyed"))
            # Ignore template signals - they're handled by EffectsObserver

    async def flush(self) -> None:
        """Process queued notifications. Call after response sent.

        Processes all pending events and clears the queue. Safe to call
        multiple times; subsequent calls are no-ops if queue is empty.
        """
        pending = self._pending
        self._pending = []

        for instance, event in pending:
            await self._handle_entity_event(instance, event)

    async def _handle_entity_event(self, instance: EntityInstance, event: str) -> None:
        """Handle a single entity event.

        Args:
            instance: The entity instance that changed
            event: The event name
        """
        if not self.bot.guilds:
            logger.warning("No guilds available, skipping Discord reconciliation")
            return

        guild = self.bot.guilds[0]  # Single-guild bot

        match event:
            case "picked_up":
                await self._create_inventory_thread(guild, instance)
            case "dropped" | "destroyed":
                await self._delete_inventory_thread(guild, instance)

    async def _create_inventory_thread(
        self, guild: discord.Guild, instance: EntityInstance
    ) -> None:
        """Create inventory thread for a picked-up item.

        Args:
            guild: Discord guild
            instance: The entity instance that was picked up
        """
        if instance.owner_id is None:
            return

        # Fetch balance for template context
        balance = await self.pool.fetchval(
            "SELECT balance FROM currency_accounts WHERE user_id = $1",
            instance.owner_id,
        )
        balance_str = f"\u00a5{balance:,}" if balance else "\u00a50"

        # Render description
        description = await self.rendering_service.render_entity_on_look_v2(
            instance, balance_str
        )

        await self.inventory_service.create_item_thread_v2(guild, instance, description)

    async def _delete_inventory_thread(
        self, guild: discord.Guild, instance: EntityInstance
    ) -> None:
        """Delete inventory thread for a dropped/destroyed item.

        Args:
            guild: Discord guild
            instance: The entity instance that was dropped or destroyed
        """
        await self.inventory_service.delete_item_thread_v2(guild, instance)
