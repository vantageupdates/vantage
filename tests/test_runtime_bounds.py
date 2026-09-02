import datetime

from vantage.helpers.combat import CombatTracker


def _at(second):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=second)


def test_long_session_collections_remain_bounded():
    """A full raid/EC session must not grow memory without a hard ceiling."""
    tracker = CombatTracker(max_history=25)

    for index in range(20_250):
        tracker.ingest(_at(index), f"Trader tells you, 'message {index}'")
    for index in range(2_250):
        tracker.ingest(
            _at(30_000 + index),
            f"--You have looted Fine Steel Sword {index}.--")
    for index in range(3_250):
        tracker.ingest(
            _at(40_000 + index),
            "Your faction standing with Claws of Veeshan got better.")

    tracker.set_diagnostics_enabled(True)
    for index in range(5_250):
        tracker.ingest(
            _at(50_000 + index), f"Unmatched raid damage line {index}")

    for index in range(40):
        target = f"training dummy {index}"
        tracker.ingest(
            _at(60_000 + index * 2),
            f"You hit {target} for 10 points of damage.")
        tracker.ingest(
            _at(60_001 + index * 2), f"You have slain {target}!")

    assert len(tracker.chat) == tracker.chat.maxlen == 20_000
    assert len(tracker.loot) == tracker.loot.maxlen == 2_000
    assert len(tracker.faction) == tracker.faction.maxlen == 3_000
    assert len(tracker.diagnostics) == tracker.diagnostics.maxlen == 5_000
    assert len(tracker.completed) == tracker.completed.maxlen == 25
    assert not tracker.active
