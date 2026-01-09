#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Generate a Mermaid diagram of room connections from a recfile."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def get_rooms(recfile: Path) -> dict[str, str]:
    """Extract room IDs and descriptions from recfile."""
    result = subprocess.run(
        ["recsel", "-t", "Room", "-p", "Id,Description", str(recfile)],
        capture_output=True,
        text=True,
        check=True,
    )

    rooms: dict[str, str] = {}
    current_id: str | None = None
    current_desc_lines: list[str] = []

    for line in result.stdout.splitlines():
        if line.startswith("Id: "):
            if current_id is not None:
                rooms[current_id] = "\n".join(current_desc_lines)
            current_id = line[4:]
            current_desc_lines = []
        elif line.startswith("Description: "):
            current_desc_lines.append(line[13:])
        elif line.startswith("+ "):
            current_desc_lines.append(line[2:])
        elif line == "+":
            current_desc_lines.append("")

    if current_id is not None:
        rooms[current_id] = "\n".join(current_desc_lines)

    return rooms


def find_connections(rooms: dict[str, str]) -> set[tuple[str, str]]:
    """Find room connections from #channel-name patterns in descriptions."""
    edges: set[tuple[str, str]] = set()
    channel_pattern = re.compile(r"#([a-z0-9-]+)")

    for room_id, description in rooms.items():
        for match in channel_pattern.finditer(description):
            target = match.group(1)
            if target in rooms:
                edges.add((room_id, target))

    return edges


def bfs_distances(edges: set[tuple[str, str]], start: str) -> dict[str, int]:
    """Calculate distances from start node using BFS."""
    from collections import deque

    # Build adjacency list
    adj: dict[str, set[str]] = {}
    for src, dst in edges:
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)

    distances: dict[str, int] = {start: 0}
    queue = deque([start])

    while queue:
        node = queue.popleft()
        for neighbor in adj.get(node, []):
            if neighbor not in distances:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)

    return distances


def generate_mermaid(edges: set[tuple[str, str]], entrance: str = "foyer") -> str:
    """Generate Mermaid graph syntax from edges."""
    lines = [
        "---",
        "config:",
        "    layout: elk",
        "---",
        "graph LR",
        f'    {entrance}@{{ shape: stadium, label: "{entrance} (entrance)" }}',
    ]

    # Calculate distances from entrance
    dist = bfs_distances(edges, entrance)

    # Count connections per node to identify leaves
    degree: dict[str, int] = {}
    for src, dst in edges:
        degree[src] = degree.get(src, 0) + 1
        degree[dst] = degree.get(dst, 0) + 1

    bidirectional: set[tuple[str, str]] = set()
    oneway: set[tuple[str, str]] = set()

    for src, dst in edges:
        if (dst, src) in edges:
            # Put leaf nodes on the right, or closer node on left
            if degree.get(dst, 0) == 2 and degree.get(src, 0) > 2:
                bidirectional.add((src, dst))
            elif degree.get(src, 0) == 2 and degree.get(dst, 0) > 2:
                bidirectional.add((dst, src))
            elif dist.get(src, 999) <= dist.get(dst, 999):
                bidirectional.add((src, dst))
            else:
                bidirectional.add((dst, src))
        else:
            oneway.add((src, dst))

    # Sort by distance of closer node, then by names
    def edge_sort_key(edge: tuple[str, str]) -> tuple[int, int, str, str]:
        src, dst = edge
        return (
            min(dist.get(src, 999), dist.get(dst, 999)),
            max(dist.get(src, 999), dist.get(dst, 999)),
            src,
            dst,
        )

    for src, dst in sorted(bidirectional, key=edge_sort_key):
        lines.append(f"    {src} <--> {dst}")
    for src, dst in sorted(oneway, key=edge_sort_key):
        lines.append(f"    {src} --> {dst}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Mermaid diagram of room connections."
    )
    parser.add_argument("recfile", type=Path, help="Path to the recfile")
    args = parser.parse_args()

    if not args.recfile.exists():
        print(f"Error: {args.recfile} not found", file=sys.stderr)
        sys.exit(1)

    rooms = get_rooms(args.recfile)
    edges = find_connections(rooms)
    mermaid = generate_mermaid(edges)
    print(mermaid)


if __name__ == "__main__":
    main()
