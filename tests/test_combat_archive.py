import datetime

from vantage.helpers.combat import CombatTracker
from vantage.helpers.combat_archive import CombatArchive


def at(seconds):
    return datetime.datetime(2026, 1, 1, 10, 0) + datetime.timedelta(
        seconds=seconds)


def completed_fight(target="a goblin", offset=0):
    tracker = CombatTracker(max_history=1)
    tracker.ingest(
        at(offset), f"Alice slashes {target} for 20 points of damage.")
    tracker.ingest(
        at(offset + 1), f"You hit {target} for 12 points of damage.")
    tracker.ingest(
        at(offset + 2), f"{target} hits Alice for 7 points of damage.")
    tracker.ingest(at(offset + 3), f"You have slain {target}!")
    return tracker.last()


def test_combat_archive_restores_every_attacker_and_parsed_stat(tmp_path):
    path = tmp_path / "combat.sqlite"
    archive = CombatArchive(path)
    fight = completed_fight()

    archive_id = archive.append(fight, "Mindflux", "Green")
    assert archive_id
    assert archive.append(fight, "Mindflux", "Green") == archive_id
    assert archive.count() == 1
    archive.close()

    reopened = CombatArchive(path)
    restored = reopened.load_all()[0]
    assert restored.target == "a goblin"
    assert restored.killed is True
    assert restored.archive_character == "Mindflux"
    assert restored.archive_server == "Green"
    assert set(restored.attackers) == {"Alice", "You"}
    assert restored.attackers["Alice"].damage == 20
    assert restored.attackers["You"].damage == 12
    assert restored.tanks["Alice"].damage == 7
    assert restored.events
    reopened.close()


def test_combat_completion_delivery_keeps_every_fight_while_memory_is_bounded():
    tracker = CombatTracker(max_history=1)
    for index, target in enumerate(("a bat", "a rat", "a spider")):
        tracker.ingest(
            at(index * 10), f"You hit {target} for 5 points of damage.")
        tracker.ingest(
            at(index * 10 + 1), f"You have slain {target}!")

    assert [fight.target for fight in tracker.completed] == ["a spider"]
    assert [fight.target for fight in tracker.drain_completed()] == [
        "a bat", "a rat", "a spider"]
    assert tracker.drain_completed() == []


def test_combat_archive_selected_delete_and_replace_all(tmp_path):
    archive = CombatArchive(tmp_path / "combat.sqlite")
    first = completed_fight("a bat", 0)
    second = completed_fight("a rat", 10)
    archive.append(first)
    archive.append(second)
    assert archive.count() == 2
    summaries = archive.summaries()
    assert [summary.target for summary in summaries] == ["a rat", "a bat"]
    assert summaries[0].total_damage == 32
    assert summaries[0].player_count == 2
    assert [fight.target for fight in archive.load_recent(1)] == ["a rat"]

    assert archive.delete([first.archive_id]) is True
    assert [fight.target for fight in archive.load_all()] == ["a rat"]
    assert archive.replace_all((first, second)) is True
    assert [fight.target for fight in archive.load_all()] == [
        "a rat", "a bat"]
    archive.close()
