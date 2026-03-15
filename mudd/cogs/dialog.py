"""Dialog interaction handler for NPC dialog button clicks."""

from __future__ import annotations

import asyncio
import logging

import asyncpg
import discord
from discord.ext import commands

from mudd.loaders.dialog_loader import get_dialog
from mudd.models.dialog import DialogSession
from mudd.observers.dialog import DialogView

logger = logging.getLogger(__name__)


class Dialog(commands.Cog):
    """Handles dialog button interactions for NPC conversations."""

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self._pool = pool

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Handle dialog button clicks."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if not custom_id.startswith("dialog:"):
            return

        parts = custom_id.split(":", 2)
        if len(parts) != 3:
            return

        _, dialog_id, node_id = parts

        # Validate session ownership
        session = await DialogSession.get(self._pool, interaction.user.id)
        if session is None or session.dialog_id != dialog_id:
            await interaction.response.send_message(
                "This dialog is not yours or has expired.",
                ephemeral=True,
            )
            return

        # Load dialog tree and node
        tree = get_dialog(dialog_id)
        if tree is None:
            await interaction.response.send_message(
                "Dialog not found.",
                ephemeral=True,
            )
            return

        node = tree.nodes.get(node_id)
        if node is None:
            await interaction.response.send_message(
                "Dialog node not found.",
                ephemeral=True,
            )
            return

        # Disable buttons on the clicked message
        if interaction.message:
            disabled_view = discord.ui.View()
            for action_row in interaction.message.components:
                if not isinstance(action_row, discord.ActionRow):
                    continue
                for component in action_row.children:
                    if not isinstance(component, discord.Button):
                        continue
                    btn = discord.ui.Button(
                        label=component.label or "?",
                        custom_id=(component.custom_id or "") + ":disabled",
                        style=component.style or discord.ButtonStyle.secondary,
                        disabled=True,
                    )
                    disabled_view.add_item(btn)
            try:
                await interaction.message.edit(view=disabled_view)
            except discord.HTTPException:
                logger.warning(
                    "Failed to disable buttons on message %d",
                    interaction.message.id,
                )

        node_text = node.text.strip()

        if node.end:
            # End node: send final text, clean up session + thread in background
            await interaction.response.send_message(node_text)
            deleted = await DialogSession.delete(self._pool, interaction.user.id)
            channel = interaction.channel
            if deleted and isinstance(channel, discord.Thread):

                async def cleanup_thread(thread: discord.Thread) -> None:
                    await asyncio.sleep(3)
                    try:
                        await thread.delete()
                    except discord.HTTPException:
                        logger.warning("Failed to delete dialog thread")

                asyncio.create_task(cleanup_thread(channel))
        else:
            # Build view with option buttons
            view = DialogView(dialog_id, node.options)
            await interaction.response.send_message(node_text, view=view)
