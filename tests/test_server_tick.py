import pytest

from vantage.parsers.tick import ServerTickClock


def test_tick_clock_starts_unsynced():
    snapshot = ServerTickClock().snapshot(123.0)

    assert snapshot.synced is False
    assert snapshot.confidence == "unsynced"
    assert snapshot.period == pytest.approx(6.0)


def test_manual_anchor_counts_to_next_tick():
    clock = ServerTickClock()
    clock.sync(10.0, "Manual sync", "manual", "Player")

    pulse = clock.snapshot(10.1)
    later = clock.snapshot(11.0)

    assert pulse.pulse is True
    assert pulse.remaining == 0.0
    assert later.pulse is False
    assert later.remaining == pytest.approx(5.0)
    assert later.progress == pytest.approx(1 / 6)


def test_repeated_log_anchor_learns_period_without_chasing_noise():
    clock = ServerTickClock()
    clock.sync(10.0, "DoT", "locked", "a spider", "dot:spider:poison")
    clock.sync(15.9, "DoT", "locked", "a spider", "dot:spider:poison")

    assert clock.period == pytest.approx(5.972, abs=0.001)

    # A nonsensical interval still anchors the visible pulse but is not used
    # to distort the learned P99 tick duration.
    clock.sync(17.0, "DoT", "locked", "a spider", "dot:spider:poison")
    assert clock.period == pytest.approx(5.972, abs=0.001)


def test_new_target_calibration_starts_from_six_seconds():
    clock = ServerTickClock()
    clock.sync(10.0, "DoT", "locked", "a spider", "dot:spider:poison")
    clock.sync(15.9, "DoT", "locked", "a spider", "dot:spider:poison")
    assert clock.period < 6.0

    clock.sync(20.0, "DoT", "locked", "a bat", "dot:bat:poison")
    assert clock.period == pytest.approx(6.0)

