#!/usr/bin/env -S uv run

"""Simulate horse races against the dev database for balance tuning."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from random import Random

import asyncpg


async def run(args: argparse.Namespace) -> int:
    # Imports here to avoid top-level side effects from mudd package
    from mudd.database import close_pool, init_database
    from mudd.loaders.horse_loader import sync_horses
    from mudd.models import Horse
    from mudd.racing.config import DEFAULT_CONFIG
    from mudd.racing.formatting import (
        format_form,
        format_odds_board,
        format_results,
        format_star_rating,
    )
    from mudd.racing.odds import HorseStats, compute_odds
    from mudd.racing.persistence import (
        create_race,
        get_recent_results,
        update_rolling_counters,
    )
    from mudd.racing.rendering import (
        AnnouncementHorse,
        RaceHorse,
        fallback_sprite,
        profile_from_bytes,
        render_announcement,
        render_frame,
        render_race_gif,
        sample_frames,
        sprite_from_bytes,
    )
    from mudd.racing.simulation import BurstType, simulate_race

    pool: asyncpg.Pool = await init_database()

    try:
        # Sync horses from recfiles
        await sync_horses(pool)

        # Load active horses
        horses = await Horse.get_all_active(pool)
        if len(horses) < 2:
            print(
                f"Need at least 2 active horses, found {len(horses)}", file=sys.stderr
            )
            return 1

        rng = Random(args.seed) if args.seed is not None else Random()
        config = DEFAULT_CONFIG

        # Track aggregate stats for multi-race summary
        win_counts: dict[str, int] = {h.id: 0 for h in horses}
        place_counts: dict[str, int] = {h.id: 0 for h in horses}

        for race_num in range(1, args.count + 1):
            print(f"\n=== Race #{race_num} ===\n")

            # Build HorseStats from models
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
            names = {h.id: h.name for h in horses}

            # Fetch recent results for form display
            horse_ids = [h.id for h in horses]
            forms = await get_recent_results(pool, horse_ids)

            # Compute odds
            odds = compute_odds(stats, config)

            # Print odds board
            print(format_odds_board(odds, forms, names))
            print()

            # Simulate race
            result = simulate_race(stats, rng=rng, config=config)

            # Print verbose per-tick progress if requested
            if args.verbose:
                print("  Tick progress:")
                for tick in range(1, config.num_ticks + 1):
                    frame = result.snapshots[tick]
                    positions = "  ".join(
                        f"{names[result.horse_ids[i]]:>8}={frame[i]:.3f}"
                        for i in range(len(horses))
                    )
                    # Check for burst events on this tick
                    tick_events = [e for e in result.events if e.tick == tick]
                    event_str = ""
                    if tick_events:
                        event_str = "  " + ", ".join(
                            f"{names[result.horse_ids[e.horse_index]]} {e.burst_type}"
                            for e in tick_events
                        )
                    print(f"  [{tick:>2}] {positions}{event_str}")
                print()

            # Print results
            horse_names = [names[hid] for hid in result.horse_ids]
            print("Results:")
            print(format_results(result.finishing_order, horse_names, odds))

            # Event summary
            surges = sum(1 for e in result.events if e.burst_type == BurstType.SURGE)
            stumbles = sum(
                1 for e in result.events if e.burst_type == BurstType.STUMBLE
            )
            print(f"\nEvents: {surges} surges, {stumbles} stumbles")

            # Render all thread images to directory
            if args.render:
                render_dir = Path(args.render)
                if args.count > 1:
                    render_dir = render_dir / f"race_{race_num}"
                render_dir.mkdir(parents=True, exist_ok=True)

                race_horses = [
                    RaceHorse(
                        name=names[h.id],
                        sprite=(
                            sprite_from_bytes(h.race_image)
                            if h.race_image
                            else fallback_sprite(i)
                        ),
                    )
                    for i, h in enumerate(horses)
                ]

                # Announcement image
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
                form_strings = [format_form(forms.get(h.id, [])) for h in horses]
                star_strings = [format_star_rating(o.star_rating) for o in odds]
                announcement_data = render_announcement(
                    announcement_horses,
                    [o.displayed_payout for o in odds],
                    form_strings,
                    star_strings,
                    race_number=race_num,
                )
                (render_dir / "announcement.png").write_bytes(announcement_data)

                # Race GIF batches
                gif_render_frames = 24
                frame_batches = [
                    list(range(0, 6)),
                    list(range(6, 12)),
                    list(range(12, 18)),
                    list(range(18, 24)),
                ]
                for batch_idx, batch in enumerate(frame_batches):
                    gif_data = render_race_gif(
                        race_horses,
                        result,
                        batch,
                        render_frames=gif_render_frames,
                    )
                    path = render_dir / f"race_part{batch_idx + 1}.gif"
                    path.write_bytes(gif_data)

                # Photo finish (last sampled frame as static PNG)
                sampled_ticks = sample_frames(result.snapshots, gif_render_frames)
                last_tick = sampled_ticks[gif_render_frames]
                finish_img = render_frame(
                    race_horses,
                    result.snapshots[last_tick],
                    [e for e in result.events if e.tick == last_tick],
                    last_tick,
                    gif_render_frames,
                    gif_render_frames + 1,
                )
                finish_img.save(render_dir / "photo_finish.png")

                # Victory image
                winner_horse = horses[result.finishing_order[0]]
                if winner_horse.victory_image:
                    (render_dir / "winner.png").write_bytes(winner_horse.victory_image)

                print(f"Rendered to {render_dir}/")

            # Track aggregate stats
            for rank, idx in enumerate(result.finishing_order):
                hid = result.horse_ids[idx]
                if rank == 0:
                    win_counts[hid] += 1
                if rank < 3:
                    place_counts[hid] += 1

            # Persist if not dry-run
            if not args.dry_run:
                race_id = await create_race(pool, result, odds)
                await update_rolling_counters(pool, config.rolling_window)
                print(f"Saved as race #{race_id}")

                # Reload horses to pick up updated counters
                horses = await Horse.get_all_active(pool)
            else:
                print("(dry run — not saved)")

        # Multi-race summary
        if args.count > 1:
            print(f"\n=== {args.count} Race Summary ===\n")

            # Compute expected percentages from final odds
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
            final_odds = compute_odds(stats, config)
            expected = {o.horse_id: o.true_probability * 100 for o in final_odds}

            header = (
                f"  {'Horse':<12} {'Expected%':>10}"
                f" {'Actual%':>9} {'Wins':>6} {'Places':>8}"
            )
            separator = "  " + "─" * 50
            print(header)
            print(separator)
            for h in horses:
                actual_pct = win_counts[h.id] / args.count * 100
                print(
                    f"  {h.name:<12} {expected[h.id]:>9.1f}% {actual_pct:>8.1f}%"
                    f" {win_counts[h.id]:>6} {place_counts[h.id]:>8}"
                )

    finally:
        await close_pool()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate horse races")
    parser.add_argument(
        "--count", type=int, default=1, help="Number of races to simulate"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate without persisting"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show per-tick detail"
    )
    parser.add_argument(
        "--render", type=str, default=None, help="Save all race images to DIR"
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
