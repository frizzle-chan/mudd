"""Random selection utilities."""

import random


def weighted_choice[T](items: list[tuple[T, int]]) -> T | None:
    """Select a random item using weighted probabilities.

    Thin wrapper around random.choices() that handles the empty/zero-weight case.

    Args:
        items: List of (item, weight) tuples. Weight must be >= 0.

    Returns:
        Randomly selected item, or None if no items have positive weight.
    """
    if not items:
        return None

    population = [item for item, _ in items]
    weights = [weight for _, weight in items]

    if sum(weights) == 0:
        return None

    return random.choices(population, weights=weights, k=1)[0]
