"""Racing cog — triggers horse races and posts results to Discord."""

from __future__ import annotations

import datetime as dt
import logging
import random
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from mudd.bot import MuddBot

from mudd.models.bet import MIN_BET
from mudd.models.horse import Horse
from mudd.models.race import RaceStatus
from mudd.observers import RoomChannelCache
from mudd.racing import (
    AnnouncementHorse,
    RaceHorse,
    compute_odds,
    profile_from_bytes,
    render_announcement,
    render_frame,
    render_race_gif,
    render_winner,
    simulate_race,
    sprite_from_bytes,
)
from mudd.racing.config import DEFAULT_CONFIG, RACE_TRACK_ROOM, RaceConfig
from mudd.racing.formatting import (
    format_form,
    format_results,
    format_star_rating,
)
from mudd.racing.odds import HorseOdds
from mudd.racing.persistence import (
    MessageType,
    PendingMessage,
    PollAnswer,
    PollConfig,
    RaceMessageInput,
    create_race,
    create_race_messages,
    delete_message,
    fetch_pending_messages,
    finish_race,
    get_poll_message_id,
    get_race_thread_id,
    get_recent_results,
    get_remaining_message_count,
    get_scheduled_event_id,
    has_active_race,
    set_poll_message_id,
    set_race_thread,
    set_scheduled_event_id,
    transition_to_running,
    update_rolling_counters,
)
from mudd.racing.rendering import fallback_sprite, sample_frames
from mudd.racing.simulation import BurstType, RaceResult
from mudd.utils.discord import fetch_thread

logger = logging.getLogger(__name__)

# Role required to trigger races
HORSE_ROLE_NAME = "horse"

# Discord polls support at most 10 answers
MAX_HORSES = 10


def _announcement_time(config: RaceConfig) -> dt.time:
    """Compute the daily announcement time from race config.

    Subtracts ``pre_race_minutes`` from the race start time to get the
    time the scheduler should fire.
    """
    tz = ZoneInfo(config.race_timezone)
    # Use a dummy date to do proper time arithmetic (handles hour rollover)
    race_dt = dt.datetime(2000, 1, 1, config.race_hour, config.race_minute, tzinfo=tz)
    announce_dt = race_dt - dt.timedelta(minutes=config.pre_race_minutes)
    return announce_dt.timetz()


DAILY_RACE_EVENT_NAME = "Daily Horse Race"

RACE_EVENT_DESCRIPTION = (
    "Daily horse race at the track!\n\n"
    "**How to get there from the Foyer:**\n"
    "`/move gallery` -> `/move courtyard` -> `/move race-track`\n\n"
    "Head to #race-track to watch the race!"
)


def _generate_commentary(
    horse_names: list[str],
    result_events: list[tuple[int, int, str]],
    frame_batch_index: int,
    num_batches: int,
) -> str:
    """Generate commentary text for a batch of race frames.

    Args:
        horse_names: Names aligned with horse indices.
        result_events: List of (tick, horse_index, burst_type) from the race.
        frame_batch_index: Which batch this is for (0-indexed).
        num_batches: Total number of GIF batches in this race.

    Returns:
        Commentary string for this section of the race.
    """
    # Select phase-appropriate intro based on race progress
    if frame_batch_index == 0:
        intro = "The early running!"
    elif frame_batch_index == num_batches - 1:
        intro = "They're at the wire!"
    else:
        progress = frame_batch_index / (num_batches - 1)
        if progress < 0.35:
            intro = random.choice(
                [
                    "The early running!",
                    "The pack is finding its rhythm!",
                ]
            )
        elif progress <= 0.7:
            intro = random.choice(
                [
                    "Into the middle of the race!",
                    "The jockeys are settling in!",
                ]
            )
        else:
            intro = random.choice(
                [
                    "The final stretch!",
                    "They're turning for home!",
                ]
            )

    lines = [intro]

    # Deduplicate by horse — keep latest event per horse
    seen: dict[int, tuple[int, int, str]] = {}
    for event in result_events:
        seen[event[1]] = event
    deduped = sorted(seen.values(), key=lambda e: e[0])

    # Cap at 3 most recent events
    result_events = deduped[-3:]

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
        lines.append(random.choice(fillers))

    return "\n".join(lines)


def _generate_announcement_flavor(
    horses: list[Horse],
    forms: dict[str, list[int]],
) -> str:
    """Generate 1-2 lines of flavor text for the race announcement.

    Examines recent form for winning/losing streaks and picks callout
    lines accordingly, plus optional generic atmosphere text.
    """
    debut_lines: list[str] = []
    streak_lines: list[str] = []

    for h in horses:
        results = forms.get(h.id, [])

        if not results and h.recent_races == 0:
            debut_lines.append(
                random.choice(
                    [
                        f"**{h.name}** makes their racing debut today!",
                        f"All eyes on **{h.name}** — a first-time starter!",
                        f"**{h.name}** steps onto the track for the very first time!",
                    ]
                )
            )
            continue

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

    lines: list[str] = debut_lines.copy()
    if streak_lines:
        lines.append(random.choice(streak_lines))
        if random.random() < 0.5:
            lines.append(random.choice(generic_lines))
    else:
        lines.extend(random.sample(generic_lines, k=random.randint(1, 2)))

    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _RaceImages:
    """Pre-rendered image assets for a race."""

    gif_batches: list[bytes]
    starting_gate: bytes
    photo_finish: bytes


def _build_race_horses(
    horses: list[Horse],
) -> tuple[list[RaceHorse], list[AnnouncementHorse]]:
    """Convert Horse models to RaceHorse and AnnouncementHorse lists."""
    race_horses = [
        RaceHorse(
            name=h.name,
            sprite=(
                sprite_from_bytes(h.race_image) if h.race_image else fallback_sprite(i)
            ),
        )
        for i, h in enumerate(horses)
    ]
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
    return race_horses, announcement_horses


def _render_race_images(
    race_horses: list[RaceHorse],
    result: RaceResult,
    config: RaceConfig,
) -> _RaceImages:
    """Render GIF batches, starting gate, and photo finish images."""
    total_frames = config.total_render_frames
    gif_batches: list[bytes] = []
    for batch in config.frame_batches:
        gif_data = render_race_gif(
            race_horses,
            result,
            batch,
            render_frames=total_frames,
        )
        gif_batches.append(gif_data)

    # Starting gate (all horses at starting positions)
    starting_frame = render_frame(
        race_horses,
        result.snapshots[0],
        [],
        0,
        0,
        total_frames + 1,
    )
    starting_buf = BytesIO()
    starting_frame.save(starting_buf, format="PNG")

    # Photo finish (last sampled frame as static PNG)
    sampled_ticks = sample_frames(result.snapshots, total_frames)
    last_tick = sampled_ticks[total_frames]
    finish_frame = render_frame(
        race_horses,
        result.snapshots[last_tick],
        [e for e in result.events if e.tick == last_tick],
        last_tick,
        total_frames,
        total_frames + 1,
    )
    finish_buf = BytesIO()
    finish_frame.save(finish_buf, format="PNG")

    return _RaceImages(
        gif_batches=gif_batches,
        starting_gate=starting_buf.getvalue(),
        photo_finish=finish_buf.getvalue(),
    )


def _build_message_queue(
    result: RaceResult,
    odds: list[HorseOdds],
    horses: list[Horse],
    forms: dict[str, list[int]],
    images: _RaceImages,
    channel_id: int,
    config: RaceConfig,
    *,
    announcement_time: dt.datetime,
    race_start_time: dt.datetime,
) -> list[RaceMessageInput]:
    """Construct the full list of RaceMessageInputs with timings and commentary.

    All timestamps are anchored to ``announcement_time`` (when the announcement
    posts) and ``race_start_time`` (when GIFs begin).  A ``RACE_START`` sentinel
    message is inserted 30 s before ``race_start_time`` to trigger the
    ``announcing`` -> ``running`` status transition.
    """
    horse_names = [h.name for h in horses]
    winner_idx = result.finishing_order[0]
    winner_name = horse_names[winner_idx]
    results_text = format_results(result.finishing_order, horse_names, odds)
    raw_victory = horses[winner_idx].victory_image
    victory_image = (
        render_winner(raw_victory, winner_name, race_number=0) if raw_victory else None
    )

    # Generate commentary per GIF batch
    total_frames = config.total_render_frames
    frame_batches = config.frame_batches
    num_batches = config.num_gifs
    sampled_ticks = sample_frames(result.snapshots, total_frames)
    batch_events: list[list[tuple[int, int, str]]] = [[] for _ in frame_batches]
    for event in result.events:
        for batch_idx, batch_indices in enumerate(frame_batches):
            batch_tick_range = [sampled_ticks[i] for i in batch_indices]
            min_tick = min(batch_tick_range)
            max_tick = max(batch_tick_range)
            if min_tick <= event.tick <= max_tick:
                batch_events[batch_idx].append(
                    (event.tick, event.horse_index, event.burst_type)
                )
                break

    commentaries = [
        _generate_commentary(horse_names, batch_events[i], i, num_batches)
        for i in range(num_batches)
    ]

    race_start_ts = int(race_start_time.timestamp())
    flavor = _generate_announcement_flavor(horses, forms)
    announcement_text = (
        "# Race #{race_number}\n"
        f"Today's race is set to begin <t:{race_start_ts}:R>\n\n{flavor}"
    )

    # Render announcement with placeholder race number (re-rendered after insert)
    announcement_horses_for_img = [
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
        announcement_horses_for_img,
        announcement_odds,
        announcement_forms,
        announcement_stars,
        race_number=0,
    )

    messages: list[RaceMessageInput] = []

    # Seq 0: Announcement (channel message)
    messages.append(
        RaceMessageInput(
            sequence=0,
            message_type=MessageType.ANNOUNCEMENT,
            content=announcement_text,
            image_data=announcement_image,
            image_name="announcement.png",
            post_at=announcement_time,
        )
    )

    # Seq 1: Poll — "Favorite horse?"
    # Duration must survive from open until race finish, rounded up to
    # the next hour (Discord minimum is 1 h).
    poll_open = announcement_time + dt.timedelta(seconds=3)
    race_end = race_start_time + dt.timedelta(
        seconds=num_batches * config.gif_interval_seconds + 10
    )
    poll_seconds = int((race_end - poll_open).total_seconds())
    poll_duration_hours = max(1, -(-poll_seconds // 3600))
    poll_answers = [
        PollAnswer(text=h.name, emoji=f"{i}\u20e3") for i, h in enumerate(horses)
    ]
    messages.append(
        RaceMessageInput(
            sequence=1,
            message_type=MessageType.POLL,
            content=None,
            image_data=None,
            image_name=None,
            post_at=poll_open,
            poll=PollConfig(
                question="Favorite horse?",
                answers=poll_answers,
                duration_hours=poll_duration_hours,
            ),
        )
    )

    # Seq 2: RACE_START sentinel — triggers announcing -> running + event start
    messages.append(
        RaceMessageInput(
            sequence=2,
            message_type=MessageType.RACE_START,
            content=None,
            image_data=None,
            image_name=None,
            post_at=race_start_time - dt.timedelta(seconds=30),
        )
    )

    # Seq 3: Betting instructions (between POLL and RACE_START)
    messages.append(
        RaceMessageInput(
            sequence=3,
            message_type=MessageType.THREAD,
            content=(
                "## Place your bets!\n"
                f"• minimum bet is **¤{MIN_BET}**\n"
                "• `/bet <horse> <amount>` to place a bet\n"
                "• `/bet <horse> 0` to cancel a bet\n"
                "• You can bet on multiple horses\n"
                "• Betting closes when the race starts!"
            ),
            image_data=None,
            image_name=None,
            post_at=announcement_time + dt.timedelta(seconds=5),
        )
    )

    # Seq 4: "Betting is closed!" — 2 seconds after RACE_START
    messages.append(
        RaceMessageInput(
            sequence=4,
            message_type=MessageType.THREAD,
            content="### Betting is closed!\nGood luck!",
            image_data=None,
            image_name=None,
            post_at=race_start_time - dt.timedelta(seconds=28),
        )
    )

    # Seq 5-7: Starting sequence
    messages.append(
        RaceMessageInput(
            sequence=5,
            message_type=MessageType.THREAD,
            content="Riders up!",
            image_data=None,
            image_name=None,
            post_at=race_start_time - dt.timedelta(seconds=30),
        )
    )
    messages.append(
        RaceMessageInput(
            sequence=6,
            message_type=MessageType.THREAD,
            content="They're approaching the starting gate...",
            image_data=None,
            image_name=None,
            post_at=race_start_time - dt.timedelta(seconds=25),
        )
    )
    messages.append(
        RaceMessageInput(
            sequence=7,
            message_type=MessageType.THREAD,
            content="They're all in the gate...",
            image_data=images.starting_gate,
            image_name="starting_gate.png",
            post_at=race_start_time - dt.timedelta(seconds=20),
        )
    )

    # Race progress (GIFs + commentary)
    gif_interval = config.gif_interval_seconds
    seq = 8
    race_frames = zip(images.gif_batches, commentaries, strict=True)
    for i, (gif_data, commentary) in enumerate(race_frames):
        content = f"## And they're off!\n\n{commentary}" if i == 0 else commentary
        messages.append(
            RaceMessageInput(
                sequence=seq,
                message_type=MessageType.THREAD,
                content=content,
                image_data=gif_data,
                image_name=f"race_part{i + 1}.gif",
                post_at=race_start_time + dt.timedelta(seconds=i * gif_interval),
            )
        )
        seq += 1

    # Photo finish
    photo_finish_offset = num_batches * gif_interval
    messages.append(
        RaceMessageInput(
            sequence=seq,
            message_type=MessageType.THREAD,
            content="Photo finish!",
            image_data=images.photo_finish,
            image_name="photo_finish.png",
            post_at=race_start_time + dt.timedelta(seconds=photo_finish_offset),
        )
    )

    # Results + winner
    messages.append(
        RaceMessageInput(
            sequence=seq + 1,
            message_type=MessageType.THREAD,
            content=f"## {winner_name} wins!\n```\n{results_text}\n```",
            image_data=victory_image,
            image_name="winner.png" if victory_image else None,
            post_at=race_start_time + dt.timedelta(seconds=photo_finish_offset + 10),
        )
    )

    return messages


class Racing(commands.Cog):
    """Horse racing integration — triggers races and posts to Discord."""

    bot: MuddBot

    def __init__(
        self,
        bot: MuddBot,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._room_cache = room_cache

    async def cog_load(self) -> None:
        self.race_poster.start()
        self.daily_race_scheduler.start()

    async def cog_unload(self) -> None:
        self.race_poster.cancel()
        self.daily_race_scheduler.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for !horse command in the race-track channel."""
        if message.author.bot or message.guild is None:
            return

        if message.guild.id != self.bot.guild_id:
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
        """Pre-compute an ad-hoc race and enqueue messages for posting."""
        pool = self._pool

        # 1. Load active horses (capped at MAX_HORSES for Discord poll limit)
        horses = await Horse.get_all_active(pool)
        if len(horses) < 2:
            if isinstance(channel, discord.TextChannel):
                await channel.send("Not enough horses to race! Need at least 2.")
            return
        if len(horses) > MAX_HORSES:
            horses = random.sample(horses, MAX_HORSES)

        # 2. Build HorseStats, compute odds, simulate
        config = DEFAULT_CONFIG
        stats = [h.to_stats() for h in horses]
        odds = compute_odds(stats)
        horse_ids = [h.id for h in horses]
        forms = await get_recent_results(pool, horse_ids)
        result = simulate_race(stats)

        # 3. Build visual assets
        race_horses, announcement_horses = _build_race_horses(horses)
        images = _render_race_images(race_horses, result, config)

        # 4. Build message queue with ad-hoc timing
        now = dt.datetime.now(dt.UTC)
        channel_id = getattr(channel, "id", 0)
        messages = _build_message_queue(
            result,
            odds,
            horses,
            forms,
            images,
            channel_id,
            config,
            announcement_time=now,
            race_start_time=now + dt.timedelta(minutes=2),
        )

        # 5. Persist and finalize images with actual race_id
        winner_idx = result.finishing_order[0]
        winner_info = (horses[winner_idx].victory_image, horses[winner_idx].name)
        race_id = await self._persist_race(
            pool,
            result,
            odds,
            messages,
            announcement_horses,
            forms,
            channel_id,
            winner_info,
        )

        # 6. Create Discord scheduled event (best-effort)
        race_start = now + dt.timedelta(seconds=45)
        race_duration = config.race_duration_minutes * 60
        await self._create_discord_event(
            race_id,
            f"Horse Race #{race_id}",
            race_start,
            race_start + dt.timedelta(seconds=race_duration + 30),
        )

    async def _prepare_scheduled_race(self) -> None:
        """Pre-compute a daily scheduled race and enqueue messages."""
        pool = self._pool
        config = DEFAULT_CONFIG
        tz = ZoneInfo(config.race_timezone)

        # 1. Load active horses (capped at MAX_HORSES for Discord poll limit)
        horses = await Horse.get_all_active(pool)
        if len(horses) < 2:
            logger.warning(
                "Not enough horses for scheduled race (have %d, need 2)",
                len(horses),
            )
            return
        if len(horses) > MAX_HORSES:
            horses = random.sample(horses, MAX_HORSES)

        # 2. Build HorseStats, compute odds, simulate
        stats = [h.to_stats() for h in horses]
        odds = compute_odds(stats)
        horse_ids = [h.id for h in horses]
        forms = await get_recent_results(pool, horse_ids)
        result = simulate_race(stats)

        # 3. Build visual assets
        race_horses, announcement_horses = _build_race_horses(horses)
        images = _render_race_images(race_horses, result, config)

        # 4. Compute timing anchors
        now = dt.datetime.now(dt.UTC)
        today_local = now.astimezone(tz)
        race_start_time = today_local.replace(
            hour=config.race_hour,
            minute=config.race_minute,
            second=0,
            microsecond=0,
        ).astimezone(dt.UTC)

        # 5. Get channel_id from room cache
        channel_id = self._room_cache.get_channel_for_room(RACE_TRACK_ROOM)
        if channel_id is None:
            logger.warning(
                "No channel found for %s — skipping scheduled race",
                RACE_TRACK_ROOM,
            )
            return

        # 6. Build message queue with scheduled timing
        messages = _build_message_queue(
            result,
            odds,
            horses,
            forms,
            images,
            channel_id,
            config,
            announcement_time=now,
            race_start_time=race_start_time,
        )

        # 7. Persist (default status is ANNOUNCING)
        winner_idx = result.finishing_order[0]
        winner_info = (horses[winner_idx].victory_image, horses[winner_idx].name)
        await self._persist_race(
            pool,
            result,
            odds,
            messages,
            announcement_horses,
            forms,
            channel_id,
            winner_info,
        )

    async def _persist_race(
        self,
        pool: asyncpg.Pool,
        result: RaceResult,
        odds: list[HorseOdds],
        messages: list[RaceMessageInput],
        announcement_horses: list[AnnouncementHorse],
        forms: dict[str, list[int]],
        channel_id: int,
        winner_info: tuple[bytes | None, str],
        *,
        status: RaceStatus = RaceStatus.ANNOUNCING,
    ) -> int:
        """Insert race, re-render images with actual race_id, insert messages."""
        race_id = await create_race(
            pool, result, odds, status=status, channel_id=channel_id
        )

        # Re-render announcement image with actual race number
        announcement_odds = [o.displayed_payout for o in odds]
        announcement_forms = [
            format_form(forms.get(h.horse_id, [])) for h in announcement_horses
        ]
        announcement_stars = [format_star_rating(o.star_rating) for o in odds]
        announcement_image_final = render_announcement(
            announcement_horses,
            announcement_odds,
            announcement_forms,
            announcement_stars,
            race_number=race_id,
        )
        first = messages[0]
        messages[0] = RaceMessageInput(
            sequence=first.sequence,
            message_type=first.message_type,
            content=(
                first.content.replace("{race_number}", str(race_id))
                if first.content
                else first.content
            ),
            image_data=announcement_image_final,
            image_name=first.image_name,
            post_at=first.post_at,
        )

        # Re-render winner image with actual race number
        raw_victory, winner_name = winner_info
        if raw_victory:
            winner_image_final = render_winner(
                raw_victory, winner_name, race_number=race_id
            )
            last = messages[-1]
            messages[-1] = RaceMessageInput(
                sequence=last.sequence,
                message_type=last.message_type,
                content=last.content,
                image_data=winner_image_final,
                image_name=last.image_name,
                post_at=last.post_at,
            )

        await create_race_messages(pool, race_id, messages)
        await update_rolling_counters(pool)

        logger.info("Race #%d prepared with %d messages", race_id, len(messages))
        return race_id

    @tasks.loop(time=_announcement_time(DEFAULT_CONFIG))
    async def daily_race_scheduler(self) -> None:
        """Fire once per day to prepare the daily scheduled race."""
        try:
            if await has_active_race(self._pool):
                logger.warning("Skipping daily race — active race exists")
                return
            await self._prepare_scheduled_race()
        except Exception:
            logger.exception("Error in daily race scheduler")

    @daily_race_scheduler.before_loop
    async def before_daily_race_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    # -- Discord scheduled event helpers ----------------------------------

    async def _create_discord_event(
        self,
        race_id: int,
        name: str,
        start_time: dt.datetime,
        end_time: dt.datetime,
    ) -> None:
        """Create a Discord scheduled event for the race (best-effort)."""
        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            return
        try:
            event = await guild.create_scheduled_event(
                name=name,
                start_time=start_time,
                end_time=end_time,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location="#race-track",
                description=RACE_EVENT_DESCRIPTION,
            )
            await set_scheduled_event_id(self._pool, race_id, event.id)
            logger.info("Created Discord event %d for race #%d", event.id, race_id)
        except Exception:
            logger.exception("Failed to create Discord event for race #%d", race_id)

    async def _start_discord_event(self, race_id: int) -> None:
        """Start the Discord scheduled event for a race (best-effort)."""
        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            return
        event_id = await get_scheduled_event_id(self._pool, race_id)
        if event_id is None:
            return
        try:
            event = await guild.fetch_scheduled_event(event_id)
            if event.status == discord.EventStatus.active:
                logger.debug("Discord event %d already active", event_id)
                return
            await event.start()
            logger.info("Started Discord event %d for race #%d", event_id, race_id)
        except ValueError:
            logger.info(
                "Discord event %d for race #%d already running", event_id, race_id
            )
        except Exception:
            logger.exception("Failed to start Discord event for race #%d", race_id)

    async def _end_discord_event(self, race_id: int) -> None:
        """End the Discord scheduled event for a race (best-effort)."""
        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            return
        event_id = await get_scheduled_event_id(self._pool, race_id)
        if event_id is None:
            return
        try:
            event = await guild.fetch_scheduled_event(event_id)
            if event.status == discord.EventStatus.active:
                await event.end()
                logger.info("Ended Discord event %d for race #%d", event_id, race_id)
            else:
                logger.info(
                    "Discord event %d for race #%d already %s",
                    event_id,
                    race_id,
                    event.status.name,
                )
        except ValueError:
            logger.info("Discord event %d for race #%d not endable", event_id, race_id)
        except Exception:
            logger.exception("Failed to end Discord event for race #%d", race_id)

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
                posted, thread_id = await self._post_single_message(msg, batch_threads)
                if thread_id is not None:
                    batch_threads[msg.race_id] = thread_id
                if posted:
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
                await self._resolve_and_post_payouts(race_id)
                await self._end_poll(race_id)
                await self._end_discord_event(race_id)
                logger.info(
                    "Race #%d finished — all messages posted",
                    race_id,
                )

    async def _post_single_message(
        self,
        msg: PendingMessage,
        batch_threads: dict[int, int],
    ) -> tuple[bool, int | None]:
        """Post a single race message to Discord.

        Returns:
            (posted, thread_id) — posted is True if the message was sent
            successfully (and should be deleted from the queue). thread_id
            is set when an announcement created a new thread.
        """
        # RACE_START sentinel — no Discord message, just state transition
        if msg.message_type == MessageType.RACE_START:
            await transition_to_running(self._pool, msg.race_id)
            await self._start_discord_event(msg.race_id)
            logger.info("Race #%d transitioned to running", msg.race_id)
            return True, None

        # Build send kwargs — only include file if present so
        # the type checker sees a matching overload.
        kwargs: dict[str, object] = {"content": msg.content}
        if msg.image_data and msg.image_name:
            kwargs["file"] = discord.File(
                BytesIO(msg.image_data), filename=msg.image_name
            )

        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            logger.warning("No guild available for race message")
            return False, None

        if msg.message_type == MessageType.ANNOUNCEMENT:
            thread_id = await self._post_announcement(msg, kwargs, guild)
            return True, thread_id

        if msg.message_type == MessageType.POLL:
            posted = await self._post_poll(msg, guild, batch_threads)
            return posted, None

        if msg.message_type == MessageType.THREAD:
            posted = await self._post_to_thread(msg, kwargs, guild, batch_threads)
            return posted, None

        return False, None

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
    ) -> bool:
        """Post a message to the race's thread.

        Returns True if the message was posted, False if the thread
        isn't available yet (will retry next cycle).
        """
        # Use in-memory thread ID from this batch if the fetched
        # row predates thread creation.
        thread_id = msg.thread_id or batch_threads.get(msg.race_id)
        if thread_id is None:
            logger.warning(
                "No thread_id for race %d, seq %d — will retry next cycle",
                msg.race_id,
                msg.sequence,
            )
            return False

        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            logger.warning(
                "Thread %d not found for race %d",
                thread_id,
                msg.race_id,
            )
            return True  # Don't retry — thread is gone

        await thread.send(**kwargs)  # type: ignore[arg-type]
        return True

    async def _post_poll(
        self,
        msg: PendingMessage,
        guild: discord.Guild,
        batch_threads: dict[int, int],
    ) -> bool:
        """Post a Discord poll to the race's thread.

        Returns True if the poll was posted, False if the thread
        isn't available yet (will retry next cycle).
        """
        thread_id = msg.thread_id or batch_threads.get(msg.race_id)
        if thread_id is None:
            logger.warning(
                "No thread_id for poll in race %d — will retry next cycle",
                msg.race_id,
            )
            return False

        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            logger.warning(
                "Thread %d not found for race %d poll",
                thread_id,
                msg.race_id,
            )
            return True  # Don't retry — thread is gone

        poll_config = msg.poll or PollConfig(question="Favorite horse?")

        poll = discord.Poll(
            question=poll_config.question,
            duration=dt.timedelta(hours=poll_config.duration_hours),
            multiple=False,
        )
        for answer in poll_config.answers:
            poll.add_answer(text=answer.text, emoji=answer.emoji)

        sent = await thread.send(poll=poll)
        await set_poll_message_id(self._pool, msg.race_id, sent.id)
        logger.info("Posted poll (message %d) for race #%d", sent.id, msg.race_id)
        return True

    async def _resolve_and_post_payouts(self, race_id: int) -> None:
        """Delegate payout resolution to the Betting cog."""
        from mudd.cogs.betting import Betting

        betting_cog = self.bot.get_cog(Betting.__cog_name__)
        if isinstance(betting_cog, Betting):
            await betting_cog.resolve_and_post_payouts(race_id)
        else:
            logger.warning(
                "Betting cog not loaded — cannot resolve payouts for race #%d",
                race_id,
            )

    async def _end_poll(self, race_id: int) -> None:
        """End the Discord poll for a race (best-effort)."""
        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            return
        poll_msg_id = await get_poll_message_id(self._pool, race_id)
        if poll_msg_id is None:
            return
        thread_id = await get_race_thread_id(self._pool, race_id)
        if thread_id is None:
            return
        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            return
        try:
            message = await thread.fetch_message(poll_msg_id)
            await message.end_poll()
            logger.info("Ended poll for race #%d", race_id)
        except Exception:
            logger.exception("Failed to end poll for race #%d", race_id)
