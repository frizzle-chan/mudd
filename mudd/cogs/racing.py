"""Racing cog — triggers horse races and posts results to Discord."""

from __future__ import annotations

import datetime as dt
import logging
import random
from io import BytesIO

import asyncpg
import discord
from discord.ext import commands, tasks

from mudd.models.horse import Horse
from mudd.observers import RoomChannelCache
from mudd.racing import (
    AnnouncementHorse,
    HorseStats,
    RaceHorse,
    compute_odds,
    profile_from_bytes,
    render_announcement,
    render_frame,
    render_race_gif,
    simulate_race,
    sprite_from_bytes,
)
from mudd.racing.formatting import (
    format_form,
    format_results,
    format_star_rating,
)
from mudd.racing.persistence import (
    PendingMessage,
    RaceMessageInput,
    create_race,
    create_race_messages,
    delete_message,
    fetch_pending_messages,
    finish_race,
    get_recent_results,
    get_remaining_message_count,
    has_active_race,
    set_race_thread,
    update_rolling_counters,
)
from mudd.racing.rendering import fallback_sprite, sample_frames
from mudd.racing.simulation import BurstType

logger = logging.getLogger(__name__)

# Role required to trigger races
HORSE_ROLE_NAME = "horse"

# Room where races can be triggered
RACE_TRACK_ROOM = "race-track"

# Total sampled frames for GIF rendering (25 ticks: 0-24)
GIF_RENDER_FRAMES = 24

# Frame batches for animated GIFs: indices into the sampled frames
FRAME_BATCHES = [
    list(range(0, 6)),
    list(range(6, 12)),
    list(range(12, 18)),
    list(range(18, 24)),
]


def _generate_commentary(
    horse_names: list[str],
    result_events: list[tuple[int, int, str]],
    frame_batch_index: int,
) -> str:
    """Generate commentary text for a batch of race frames.

    Args:
        horse_names: Names aligned with horse indices.
        result_events: List of (tick, horse_index, burst_type) from the race.
        frame_batch_index: Which batch (0-3) this is for.

    Returns:
        Commentary string for this section of the race.
    """
    # Phase descriptions
    phase_intros = [
        "The early running!",
        "Into the middle of the race!",
        "The final stretch!",
        "They're at the wire!",
    ]

    lines = [phase_intros[frame_batch_index]]

    # Find notable events for this batch
    for _tick, horse_idx, burst_type in result_events:
        name = horse_names[horse_idx] if horse_idx < len(horse_names) else "A horse"
        if burst_type == BurstType.SURGE:
            lines.append(f"**{name}** surges forward!")
        elif burst_type == BurstType.STUMBLE:
            lines.append(f"**{name}** stumbles!")

    if len(lines) == 1:
        # No events — add generic commentary
        fillers = [
            "The pack is tightly bunched!",
            "Jockeys are pushing hard!",
            "It's anyone's race!",
            "The crowd is on their feet!",
        ]
        lines.append(fillers[frame_batch_index])

    return "\n".join(lines)


def _generate_announcement_flavor(
    horses: list[Horse],
    forms: dict[str, list[int]],
) -> str:
    """Generate 1-2 lines of flavor text for the race announcement.

    Examines recent form for winning/losing streaks and picks callout
    lines accordingly, plus optional generic atmosphere text.
    """
    streak_lines: list[str] = []

    for h in horses:
        results = forms.get(h.id, [])
        if len(results) < 2:
            continue

        # Winning streak: 2+ consecutive 1st-place finishes (newest first)
        win_count = 0
        for pos in results:
            if pos == 1:
                win_count += 1
            else:
                break
        if win_count >= 2:
            streak_lines.append(
                random.choice(
                    [
                        f"**{h.name}** is on a {win_count}-race winning streak!",
                        f"**{h.name}** has been red hot lately!",
                    ]
                )
            )
            continue

        # Losing streak: 2+ consecutive finishes outside top 3
        loss_count = 0
        for pos in results:
            if pos > 3:
                loss_count += 1
            else:
                break
        if loss_count >= 2:
            streak_lines.append(
                random.choice(
                    [
                        f"**{h.name}** is looking to bounce back after a rough patch",
                        f"**{h.name}** has been struggling for form lately",
                    ]
                )
            )

    generic_lines = [
        "The crowd is buzzing with anticipation!",
        "It's a beautiful day at the track!",
        "The jockeys are warming up in the paddock.",
        "Punters are studying the form guide...",
    ]

    lines: list[str] = []
    if streak_lines:
        lines.append(random.choice(streak_lines))
        if random.random() < 0.5:
            lines.append(random.choice(generic_lines))
    else:
        lines = random.sample(generic_lines, k=random.randint(1, 2))

    return "\n".join(lines)


class Racing(commands.Cog):
    """Horse racing integration — triggers races and posts to Discord."""

    def __init__(
        self,
        bot: commands.Bot,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._room_cache = room_cache

    async def cog_load(self) -> None:
        self.race_poster.start()

    async def cog_unload(self) -> None:
        self.race_poster.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for !horse command in the race-track channel."""
        if message.author.bot or message.guild is None:
            return

        if message.content.strip().lower() != "!horse":
            return

        # Must be in the race-track room
        room_id = self._room_cache.get_room_for_channel(message.channel.id)
        if room_id != RACE_TRACK_ROOM:
            return

        # Must have the "horse" role
        member = message.author
        if not isinstance(member, discord.Member):
            return
        has_role = any(r.name.lower() == HORSE_ROLE_NAME for r in member.roles)
        if not has_role:
            return

        # Acknowledge the command
        await message.add_reaction("\U0001f40e")

        # Check for active race
        if await has_active_race(self._pool):
            await message.reply("A race is already in progress!")
            return

        try:
            await self._prepare_race(message.channel)
        except Exception:
            logger.exception("Failed to prepare race")
            await message.reply("Something went wrong preparing the race.")

    async def _prepare_race(self, channel: discord.abc.Messageable) -> None:
        """Pre-compute an entire race and enqueue messages for posting."""
        pool = self._pool

        # 1. Load active horses
        horses = await Horse.get_all_active(pool)
        if len(horses) < 2:
            if isinstance(channel, discord.TextChannel):
                await channel.send("Not enough horses to race! Need at least 2.")
            return

        # 2. Build HorseStats and compute odds
        stats = [
            HorseStats(
                horse_id=h.id,
                speed=h.speed,
                stamina=h.stamina,
                consistency=h.consistency,
                luck=h.luck,
                recent_races=h.recent_races,
                recent_wins=h.recent_wins,
                recent_places=h.recent_places,
            )
            for h in horses
        ]
        odds = compute_odds(stats)
        horse_ids = [h.id for h in horses]
        forms = await get_recent_results(pool, horse_ids)
        # 3. Simulate race
        result = simulate_race(stats)

        # 4. Render announcement image
        announcement_horses = [
            AnnouncementHorse(
                horse_id=h.id,
                name=h.name,
                profile=(
                    profile_from_bytes(h.profile_image)
                    if h.profile_image
                    else fallback_sprite(i).resize((64, 64))
                ),
            )
            for i, h in enumerate(horses)
        ]
        announcement_odds = [o.displayed_payout for o in odds]
        announcement_forms = [format_form(forms.get(h.id, [])) for h in horses]
        announcement_stars = [format_star_rating(o.star_rating) for o in odds]

        announcement_image = render_announcement(
            announcement_horses,
            announcement_odds,
            announcement_forms,
            announcement_stars,
            race_number=0,  # Will be replaced with actual race_id after insert
        )

        # 5. Render race GIFs
        race_horses = [
            RaceHorse(
                name=h.name,
                sprite=(
                    sprite_from_bytes(h.race_image)
                    if h.race_image
                    else fallback_sprite(i)
                ),
            )
            for i, h in enumerate(horses)
        ]

        gif_batches: list[bytes] = []
        for batch in FRAME_BATCHES:
            gif_data = render_race_gif(
                race_horses,
                result,
                batch,
                render_frames=GIF_RENDER_FRAMES,
            )
            gif_batches.append(gif_data)

        # 5b. Render starting gate image (all horses at starting positions)
        starting_frame = render_frame(
            race_horses,
            result.snapshots[0],
            [],
            0,
            0,
            GIF_RENDER_FRAMES + 1,
        )
        starting_buf = BytesIO()
        starting_frame.save(starting_buf, format="PNG")
        starting_gate_data = starting_buf.getvalue()

        # 5c. Render photo finish (last sampled frame as static PNG)
        sampled_ticks = sample_frames(result.snapshots, GIF_RENDER_FRAMES)
        last_tick = sampled_ticks[GIF_RENDER_FRAMES]
        finish_frame = render_frame(
            race_horses,
            result.snapshots[last_tick],
            [e for e in result.events if e.tick == last_tick],
            last_tick,
            GIF_RENDER_FRAMES,
            GIF_RENDER_FRAMES + 1,
        )
        finish_buf = BytesIO()
        finish_frame.save(finish_buf, format="PNG")
        photo_finish_data = finish_buf.getvalue()

        # 6. Get winner's victory image
        winner_idx = result.finishing_order[0]
        winner_horse = horses[winner_idx]
        victory_image = winner_horse.victory_image

        # 8. Build results text
        horse_names = [h.name for h in horses]
        results_text = format_results(result.finishing_order, horse_names, odds)
        winner_name = horse_names[winner_idx]

        # 9. Generate commentary for each GIF batch
        # Collect events per batch by mapping tick ranges to batches
        batch_events: list[list[tuple[int, int, str]]] = [[] for _ in FRAME_BATCHES]
        for event in result.events:
            for batch_idx, batch_indices in enumerate(FRAME_BATCHES):
                batch_tick_range = [sampled_ticks[i] for i in batch_indices]
                min_tick = min(batch_tick_range)
                max_tick = max(batch_tick_range)
                if min_tick <= event.tick <= max_tick:
                    batch_events[batch_idx].append(
                        (event.tick, event.horse_index, event.burst_type)
                    )
                    break

        commentaries = [
            _generate_commentary(horse_names, batch_events[i], i)
            for i in range(len(FRAME_BATCHES))
        ]

        # 10. Compute timestamps
        now = dt.datetime.now(dt.UTC)
        race_start_ts = int((now + dt.timedelta(seconds=45)).timestamp())
        flavor = _generate_announcement_flavor(horses, forms)
        announcement_text = (
            f"Today's race is set to begin <t:{race_start_ts}:R>\n\n{flavor}"
        )
        channel_id = getattr(channel, "id", 0)

        messages: list[RaceMessageInput] = []

        # Seq 0: Announcement (channel message)
        messages.append(
            RaceMessageInput(
                sequence=0,
                message_type="announcement",
                content=announcement_text,
                image_data=announcement_image,
                image_name="announcement.png",
                post_at=now,
            )
        )

        # Seq 1: Betting prompt (thread)
        messages.append(
            RaceMessageInput(
                sequence=1,
                message_type="thread",
                content="Place your bets! (Betting coming soon...)",
                image_data=None,
                image_name=None,
                post_at=now + dt.timedelta(seconds=3),
            )
        )

        # Seq 2-4: Starting sequence, staggered leading up to race start
        messages.append(
            RaceMessageInput(
                sequence=2,
                message_type="thread",
                content="Riders up!",
                image_data=None,
                image_name=None,
                post_at=now + dt.timedelta(seconds=20),
            )
        )
        messages.append(
            RaceMessageInput(
                sequence=3,
                message_type="thread",
                content="They're approaching the starting gate...",
                image_data=None,
                image_name=None,
                post_at=now + dt.timedelta(seconds=25),
            )
        )
        messages.append(
            RaceMessageInput(
                sequence=4,
                message_type="thread",
                content="They're all in the gate...",
                image_data=starting_gate_data,
                image_name="starting_gate.png",
                post_at=now + dt.timedelta(seconds=30),
            )
        )

        # Seq 5-8: Race progress (GIFs + commentary)
        # First batch merges with "And they're off!" at race start time
        race_frames = zip(gif_batches, commentaries, strict=True)
        for i, (gif_data, commentary) in enumerate(race_frames):
            if i == 0:
                content = f"And they're off!\n\n{commentary}"
                offset = dt.timedelta(seconds=45)
            else:
                content = commentary
                offset = dt.timedelta(seconds=45 + i * 15)
            messages.append(
                RaceMessageInput(
                    sequence=5 + i,
                    message_type="thread",
                    content=content,
                    image_data=gif_data,
                    image_name=f"race_part{i + 1}.gif",
                    post_at=now + offset,
                )
            )

        # Seq 9: Photo finish (last frame as static image)
        messages.append(
            RaceMessageInput(
                sequence=9,
                message_type="thread",
                content="Photo finish!",
                image_data=photo_finish_data,
                image_name="photo_finish.png",
                post_at=now + dt.timedelta(seconds=105),
            )
        )

        # Seq 10: Results + winner
        messages.append(
            RaceMessageInput(
                sequence=10,
                message_type="thread",
                content=f"**{winner_name} wins!**\n```\n{results_text}\n```",
                image_data=victory_image,
                image_name="winner.png" if victory_image else None,
                post_at=now + dt.timedelta(seconds=115),
            )
        )

        # 11. Persist race and messages
        race_id = await create_race(
            pool, result, odds, status="running", channel_id=channel_id
        )

        # Update announcement with actual race number by re-rendering
        announcement_image_final = render_announcement(
            announcement_horses,
            announcement_odds,
            announcement_forms,
            announcement_stars,
            race_number=race_id,
        )
        messages[0] = RaceMessageInput(
            sequence=0,
            message_type="announcement",
            content=announcement_text,
            image_data=announcement_image_final,
            image_name="announcement.png",
            post_at=now,
        )

        await create_race_messages(pool, race_id, messages)
        await update_rolling_counters(pool)

        logger.info("Race #%d prepared with %d messages", race_id, len(messages))

    @tasks.loop(seconds=10)
    async def race_poster(self) -> None:
        """Poll for pending race messages and post them to Discord."""
        try:
            await self._post_pending_messages()
        except Exception:
            logger.exception("Error in race poster loop")

    @race_poster.before_loop
    async def before_race_poster(self) -> None:
        await self.bot.wait_until_ready()

    async def _post_pending_messages(self) -> None:
        """Fetch and post all due race messages."""
        pending = await fetch_pending_messages(self._pool)
        if not pending:
            return

        # Track which races had messages posted
        races_with_posts: set[int] = set()
        # Thread IDs created during this batch — the fetched rows
        # have thread_id=NULL for messages queried before the
        # announcement created the thread.
        batch_threads: dict[int, int] = {}

        for msg in pending:
            try:
                thread_id = await self._post_single_message(msg, batch_threads)
                if thread_id is not None:
                    batch_threads[msg.race_id] = thread_id
                await delete_message(self._pool, msg.id)
                races_with_posts.add(msg.race_id)
            except Exception:
                logger.exception(
                    "Failed to post race message %d (race %d, seq %d)",
                    msg.id,
                    msg.race_id,
                    msg.sequence,
                )

        # Check if any races are now complete
        for race_id in races_with_posts:
            remaining = await get_remaining_message_count(self._pool, race_id)
            if remaining == 0:
                await finish_race(self._pool, race_id)
                logger.info(
                    "Race #%d finished — all messages posted",
                    race_id,
                )

    async def _post_single_message(
        self,
        msg: PendingMessage,
        batch_threads: dict[int, int],
    ) -> int | None:
        """Post a single race message to Discord.

        Returns:
            The new thread ID if an announcement created one,
            otherwise None.
        """
        # Build send kwargs — only include file if present so
        # the type checker sees a matching overload.
        kwargs: dict[str, object] = {"content": msg.content}
        if msg.image_data and msg.image_name:
            kwargs["file"] = discord.File(
                BytesIO(msg.image_data), filename=msg.image_name
            )

        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild is None:
            logger.warning("No guild available for race message")
            return None

        if msg.message_type == "announcement":
            return await self._post_announcement(msg, kwargs, guild)

        if msg.message_type == "thread":
            await self._post_to_thread(msg, kwargs, guild, batch_threads)

        return None

    async def _post_announcement(
        self,
        msg: PendingMessage,
        kwargs: dict[str, object],
        guild: discord.Guild,
    ) -> int | None:
        """Post announcement to channel and create thread.

        Returns the new thread ID.
        """
        if msg.channel_id is None:
            logger.warning("No channel_id for announcement message %d", msg.id)
            return None

        channel = guild.get_channel(msg.channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "Channel %d not found for race %d",
                msg.channel_id,
                msg.race_id,
            )
            return None

        sent = await channel.send(**kwargs)  # type: ignore[arg-type]

        thread = await sent.create_thread(name=f"Race #{msg.race_id}")
        await set_race_thread(self._pool, msg.race_id, thread.id)
        logger.info(
            "Created thread %d for race #%d",
            thread.id,
            msg.race_id,
        )
        return thread.id

    async def _post_to_thread(
        self,
        msg: PendingMessage,
        kwargs: dict[str, object],
        guild: discord.Guild,
        batch_threads: dict[int, int],
    ) -> None:
        """Post a message to the race's thread."""
        # Use in-memory thread ID from this batch if the fetched
        # row predates thread creation.
        thread_id = msg.thread_id or batch_threads.get(msg.race_id)
        if thread_id is None:
            logger.warning(
                "No thread_id for race %d, seq %d — will retry next cycle",
                msg.race_id,
                msg.sequence,
            )
            raise _ThreadNotReady

        thread = guild.get_thread(thread_id)
        if thread is None:
            try:
                thread = await guild.fetch_channel(thread_id)
            except discord.NotFound:
                logger.warning(
                    "Thread %d not found for race %d",
                    thread_id,
                    msg.race_id,
                )
                return

        if isinstance(thread, discord.Thread):
            await thread.send(**kwargs)  # type: ignore[arg-type]


class _ThreadNotReady(Exception):
    """Thread message can't post because thread isn't created."""
