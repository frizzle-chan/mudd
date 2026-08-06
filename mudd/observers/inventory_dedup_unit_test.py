"""Unit tests for non-destructive inventory forum dedup planning."""

from __future__ import annotations

import itertools

import pytest

from mudd.observers.inventory_dedup import ForumCandidate, plan_dedup


def candidate(id_: int, threads: int = 0, registered: bool = False) -> ForumCandidate:
    return ForumCandidate(id=id_, thread_count=threads, registered=registered)


class TestSurvivorPrecedence:
    def test_empty_input_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            plan_dedup([])

    def test_single_candidate_survives(self) -> None:
        plan = plan_dedup([candidate(10)])
        assert plan.survivor_id == 10
        assert plan.delete_ids == ()
        assert plan.keep_ids == ()

    def test_registered_beats_higher_thread_count(self) -> None:
        plan = plan_dedup(
            [
                candidate(10, threads=0, registered=True),
                candidate(20, threads=99),
            ]
        )
        assert plan.survivor_id == 10

    def test_thread_count_beats_newer_id(self) -> None:
        plan = plan_dedup([candidate(10, threads=100), candidate(20, threads=0)])
        assert plan.survivor_id == 10

    def test_newest_id_breaks_the_final_tie(self) -> None:
        plan = plan_dedup([candidate(10), candidate(30), candidate(20)])
        assert plan.survivor_id == 30

    def test_oldest_id_is_never_preferred(self) -> None:
        """The production bug: oldest was empty, newest held 100+ threads."""
        plan = plan_dedup([candidate(10, threads=0), candidate(20, threads=137)])
        assert plan.survivor_id == 20
        assert 20 not in plan.delete_ids

    def test_result_is_independent_of_input_order(self) -> None:
        candidates = [
            candidate(10, threads=5),
            candidate(20, threads=0, registered=True),
            candidate(30, threads=2),
        ]
        results = {
            plan_dedup(list(order)).survivor_id
            for order in itertools.permutations(candidates)
        }
        assert results == {20}


class TestDeletionPolicy:
    def test_empty_losers_are_deleted(self) -> None:
        plan = plan_dedup([candidate(10, threads=5), candidate(20), candidate(30)])
        assert plan.survivor_id == 10
        assert set(plan.delete_ids) == {20, 30}
        assert plan.keep_ids == ()

    def test_non_empty_losers_are_kept(self) -> None:
        plan = plan_dedup(
            [
                candidate(10, threads=0, registered=True),
                candidate(20, threads=7),
            ]
        )
        assert plan.survivor_id == 10
        assert plan.delete_ids == ()
        assert plan.keep_ids == (20,)

    def test_mixed_losers_are_split(self) -> None:
        plan = plan_dedup(
            [
                candidate(10, threads=0, registered=True),
                candidate(20, threads=7),
                candidate(30, threads=0),
            ]
        )
        assert plan.survivor_id == 10
        assert plan.delete_ids == (30,)
        assert plan.keep_ids == (20,)

    def test_survivor_never_appears_in_delete_or_keep(self) -> None:
        plan = plan_dedup(
            [candidate(10, threads=3), candidate(20), candidate(30, threads=1)]
        )
        assert plan.survivor_id not in plan.delete_ids
        assert plan.survivor_id not in plan.keep_ids

    def test_no_non_empty_forum_is_ever_deleted(self) -> None:
        """Exhaustive: across the candidate space, a forum with threads never
        lands in delete_ids."""
        space = [
            ForumCandidate(id=i, thread_count=t, registered=r)
            for i, (t, r) in enumerate(
                itertools.product([0, 1, 50], [False, True]), start=1
            )
        ]
        for size in (2, 3):
            for combo in itertools.permutations(space, size):
                # At most one forum can be registered to this user.
                if sum(1 for c in combo if c.registered) > 1:
                    continue
                plan = plan_dedup(list(combo))
                by_id = {c.id: c for c in combo}
                for deleted in plan.delete_ids:
                    assert by_id[deleted].thread_count == 0

    def test_every_loser_is_accounted_for(self) -> None:
        candidates = [candidate(10, threads=3), candidate(20), candidate(30, threads=1)]
        plan = plan_dedup(candidates)
        losers = {c.id for c in candidates if c.id != plan.survivor_id}
        assert losers == set(plan.delete_ids) | set(plan.keep_ids)
