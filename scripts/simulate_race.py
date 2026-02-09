#!/usr/bin/env -S uv run

"""Simulate horse races against the dev database for balance tuning."""

from __future__ import annotations

import argparse
import asyncio
import sys
from random import Random

import asyncpg


async def run(args: argparse.Namespace) -> int:
    # Imports here to avoid top-level side effects from mudd package
    from mudd.database import close_pool, init_database
    from mudd.loaders.horse_loader import sync_horses
    from mudd.models import Horse
    from mudd.racing.config import DEFAULT_CONFIG
    from mudd.racing.formatting import (
        format_odds_board,
        format_results,
    )
    from mudd.racing.odds import HorseStats, compute_odds
    from mudd.racing.persistence import (
        create_race,
        get_recent_results,
        update_rolling_counters,
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
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
