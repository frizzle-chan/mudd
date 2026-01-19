#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "asyncpg",
#     "python-dotenv",
# ]
# ///
"""Benchmark autocomplete performance.

Measures:
- get_autocomplete_entities() latency
- focus_service.get_focus() latency
- get_focus_aware_autocomplete_entities() end-to-end latency

Run before and after optimization to quantify improvement.
"""

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mudd.matching.entity_matcher import (
    get_autocomplete_entities,
    get_focus_aware_autocomplete_entities,
)
from mudd.services.entity import EntityService
from mudd.services.focus_context import FocusContextService


async def benchmark_function(name: str, func, iterations: int = 20) -> dict:
    """Run a function multiple times and collect timing statistics."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await func()
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        times.append(elapsed)

    return {
        "name": name,
        "iterations": iterations,
        "min_ms": min(times),
        "max_ms": max(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
        "first_ms": times[0],
        "second_ms": times[1] if len(times) > 1 else None,
    }


def print_results(results: dict) -> None:
    """Pretty print benchmark results."""
    print(f"\n{results['name']}")
    print("-" * 50)
    print(f"  Iterations: {results['iterations']}")
    print(f"  First call (cold): {results['first_ms']:.2f}ms")
    if results["second_ms"] is not None:
        print(f"  Second call (warm): {results['second_ms']:.2f}ms")
    print(f"  Min: {results['min_ms']:.2f}ms")
    print(f"  Max: {results['max_ms']:.2f}ms")
    print(f"  Mean: {results['mean_ms']:.2f}ms")
    print(f"  Median: {results['median_ms']:.2f}ms")
    print(f"  Stdev: {results['stdev_ms']:.2f}ms")


async def main() -> int:
    """Run autocomplete benchmarks."""
    load_dotenv()

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://mudd:mudd@db:5432/mudd",
    )

    print("Connecting to database...")
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=5)
    if pool is None:
        print("Failed to create database pool", file=sys.stderr)
        return 1

    # Get a room with entities from the database
    row = await pool.fetchrow(
        """
        SELECT DISTINCT room FROM entity_instances
        WHERE room IS NOT NULL
        LIMIT 1
        """
    )
    if not row:
        print("No rooms with entities found in database", file=sys.stderr)
        await pool.close()
        return 1

    room = row["room"]
    print(f"Using room: {room}")

    # Create services
    entity_service = EntityService(pool)
    focus_service = FocusContextService(pool)

    # Use a fake user ID that won't have focus state
    user_id = 999999999

    print("\n" + "=" * 60)
    print("AUTOCOMPLETE BENCHMARKS")
    print("=" * 60)

    # Benchmark 1: get_autocomplete_entities (cold cache)
    entity_service.invalidate_cache()
    results1 = await benchmark_function(
        "get_autocomplete_entities() [cold then warm cache]",
        lambda: get_autocomplete_entities(entity_service, room),
    )
    print_results(results1)

    # Benchmark 2: focus_service.get_focus()
    results2 = await benchmark_function(
        "focus_service.get_focus() [no focus exists]",
        lambda: focus_service.get_focus(user_id, room),
    )
    print_results(results2)

    # Benchmark 3: get_focus_aware_autocomplete_entities (cold cache)
    entity_service.invalidate_cache()
    results3 = await benchmark_function(
        "get_focus_aware_autocomplete_entities() [cold then warm cache]",
        lambda: get_focus_aware_autocomplete_entities(
            entity_service, focus_service, user_id, room
        ),
    )
    print_results(results3)

    # Benchmark 4: get_focus_aware_autocomplete_entities (warm cache only)
    # First call to warm up, then measure
    await get_focus_aware_autocomplete_entities(
        entity_service, focus_service, user_id, room
    )
    results4 = await benchmark_function(
        "get_focus_aware_autocomplete_entities() [warm cache only]",
        lambda: get_focus_aware_autocomplete_entities(
            entity_service, focus_service, user_id, room
        ),
    )
    print_results(results4)

    # Benchmark 5: Test with cached autocomplete choices (if available)
    if hasattr(entity_service, "get_cached_autocomplete_choices"):
        print("\n[OPTIMIZED PATH AVAILABLE]")
        entity_service.invalidate_cache()
        results5 = await benchmark_function(
            "get_cached_autocomplete_choices() [cold then warm]",
            lambda: entity_service.get_cached_autocomplete_choices(room),
        )
        print_results(results5)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Room tested: {room}")
    print(f"Focus check overhead: ~{results2['mean_ms']:.2f}ms")
    print(f"Full autocomplete (warm): ~{results4['mean_ms']:.2f}ms")

    if hasattr(entity_service, "get_cached_autocomplete_choices"):
        print(f"Cached autocomplete: ~{results5['mean_ms']:.2f}ms")  # type: ignore
        speedup = results4["mean_ms"] / results5["mean_ms"]  # type: ignore
        print(f"Speedup: {speedup:.1f}x")

    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
