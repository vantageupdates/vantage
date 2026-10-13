"""Regression coverage for encounter routing, boundaries, and saved selections."""

import datetime

import pytest

from vantage.helpers.combat import CombatTracker
from vantage.helpers.combat_archive import CombatArchive


def at(seconds):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=seconds)


def completed_fight(offset=0, incoming_only=False):
    tracker = CombatTracker()
    first = (
        "a goblin hits You for 10 points of damage." if incoming_only else
        "You slash a goblin for 10 points of damage.")
    tracker.ingest(at(offset), first)
    tracker.ingest(at(offset + 5), "a goblin hits You for 7 points of damage.")
    tracker.ingest(at(offset + 6), "You have slain a goblin!")
    return tracker.last()


def test_incoming_damage_finds_opponent_among_all_active_fights():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You slash a goblin for 10 points of damage.")
    tracker.ingest(at(1), "You slash an orc for 20 points of damage.")
    tracker.ingest(at(2), "a goblin hits Alice for 7 points of damage.")

    assert set(tracker.active) == {"a goblin", "an orc"}
    goblin = tracker.active["a goblin"]
    assert goblin.total_damage == 10
    assert goblin.tanks["Alice"].damage == 7
    assert tracker.session_tanks["Alice"].damage == 7
    assert set(tracker.session_attackers) == {"You"}
    assert tracker.active["an orc"].total_damage == 20


def test_group_defense_finds_opponent_among_all_active_fights():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You slash a goblin for 10 points of damage.")
    tracker.ingest(at(1), "You slash an orc for 20 points of damage.")
    tracker.ingest(at(2), "a goblin tries to hit Alice, but Alice dodges!")

    assert tracker.active["a goblin"].tanks["Alice"].dodges == 1
    assert tracker.session_tanks["Alice"].dodges == 1
    assert "Alice" not in tracker.active["an orc"].tanks


@pytest.mark.parametrize("incoming", [False, True])
def test_damage_after_timeout_starts_a_new_same_named_fight(incoming):
    tracker = CombatTracker(timeout=12)
    line = (
        "a bat hits You for 10 points of damage." if incoming else
        "You hit a bat for 10 points of damage.")
    tracker.ingest(at(0), line)
    first = tracker.current()
    tracker.ingest(at(60), line)

    assert list(tracker.completed) == [first]
    assert tracker.current() is not first
    assert first.started_at == first.last_at == at(0)
    assert tracker.current().started_at == tracker.current().last_at == at(60)
    assert first.duration == tracker.current().duration == 1
    assert tracker.drain_completed() == [first]
    assert tracker.drain_completed() == []
    if incoming:
        assert first.tanks["You"].damage == 10
        assert tracker.current().tanks["You"].damage == 10
        assert tracker.session_tanks["You"].damage == 20
    else:
        assert first.total_damage == tracker.current().total_damage == 10
        assert tracker.session_attackers["You"].damage == 20


def test_damage_at_timeout_boundary_remains_in_same_fight():
    tracker = CombatTracker(timeout=12)
    tracker.ingest(at(0), "You hit a bat for 10 points of damage.")
    first = tracker.current()
    tracker.ingest(at(12), "You hit a bat for 20 points of damage.")

    assert tracker.current() is first
    assert first.total_damage == 30
    assert not tracker.completed


def test_late_death_can_still_finalize_the_active_fight():
    tracker = CombatTracker(timeout=12)
    tracker.ingest(at(0), "You hit a bat for 10 points of damage.")
    tracker.ingest(at(60), "You have slain a bat!")

    assert tracker.current() is None
    assert tracker.last().killed is True
    assert tracker.last().last_at == at(60)
    assert tracker.last().duration == 1
    assert [event.kind for event in tracker.last().events] == ["Damage", "Kill"]
    assert tracker.drain_completed() == [tracker.last()]


def test_exact_slain_name_wins_over_a_more_recent_partial_match():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a goblin for 10 points of damage.")
    tracker.ingest(at(1), "You hit a goblin wizard for 20 points of damage.")
    tracker.ingest(at(2), "You have slain A Goblin!")

    assert tracker.last().target == "a goblin"
    assert tracker.last().killed is True
    assert set(tracker.active) == {"a goblin wizard"}
    assert tracker.current().total_damage == 20


def test_ambiguous_partial_slain_name_does_not_finalize_an_arbitrary_fight():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a goblin warrior for 10 points of damage.")
    tracker.ingest(at(1), "You hit a goblin wizard for 20 points of damage.")

    assert tracker.finalize_target("a goblin", at(2), killed=True) is None
    assert len(tracker.active) == 2
    assert not tracker.completed


def test_unambiguous_partial_slain_name_still_matches():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a goblin warrior for 10 points of damage.")

    assert tracker.finalize_target("goblin warrior", at(2), killed=True)
    assert tracker.last().target == "a goblin warrior"


@pytest.mark.parametrize("incoming_only", [False, True])
def test_single_fight_selection_preserves_incoming_damage_duration(incoming_only):
    fight = completed_fight(incoming_only=incoming_only)
    selected = CombatTracker().combine([fight])

    assert fight.duration == 6
    assert selected.duration == fight.duration
    assert selected.damage_started_at == fight.damage_started_at == at(0)
    assert selected.damage_last_at == fight.damage_last_at == at(5)
    assert selected.dps == fight.dps
    assert selected.your_dps == fight.your_dps
    assert selected.tanks["You"].damage == fight.tanks["You"].damage


def test_combining_fights_keeps_existing_elapsed_gap_policy():
    first, second = completed_fight(), completed_fight(60)
    selected = CombatTracker().combine([first, second])

    assert selected.duration == 66
    assert selected.dps == 20 / 66


@pytest.mark.parametrize(
    "profiles, expected",
    [
        ([("Alice", "Green"), ("Alice", "Green")], ("Alice", "Green")),
        ([("Alice", "Green"), ("Bob", "Green")], ("", "")),
        ([("Alice", "Green"), ("Alice", "Blue")], ("", "")),
        ([("Alice", "Green"), ("", "")], ("", "")),
    ],
)
def test_archive_replacement_preserves_only_homogeneous_profiles(
        tmp_path, profiles, expected):
    path = tmp_path / "combat.sqlite"
    archive = CombatArchive(path)
    try:
        archive_ids = [
            archive.append(completed_fight(index * 60), *profile)
            for index, profile in enumerate(profiles)]
        selected = CombatTracker().combine(archive.load(archive_ids))
        replacement_ids = archive.replace_selected(archive_ids, [selected])
        assert len(replacement_ids) == 1
        assert archive.count() == 1
    finally:
        archive.close()

    reopened = CombatArchive(path)
    try:
        restored = reopened.load_all()[0]
        summary = reopened.summaries()[0]
        assert (restored.archive_character, restored.archive_server) == expected
        assert (summary.character, summary.server) == expected
        assert restored.total_damage == summary.total_damage == 20
        assert restored.duration == summary.duration == 66
        assert restored.damage_started_at == at(0)
        assert restored.damage_last_at == at(65)
    finally:
        reopened.close()
