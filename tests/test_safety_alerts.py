import datetime

from vantage.helpers.safety_alerts import SafetyAlertState


def _at(second):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=second)


def test_afk_attack_requires_incoming_target_no_focus_and_cooldown():
    state = SafetyAlertState()

    first = state.ingest(
        _at(0), "a frost giant hits You for 72 points of damage.", False)
    assert [(event.kind, event.attacker) for event in first] == [
        ("afk_attacked", "a frost giant")]
    assert state.ingest(
        _at(2), "a frost giant tries to kick You, but misses!", False) == ()
    assert state.ingest(
        _at(6), "a frost giant hits You for 72 points of damage.", True) == ()
    assert state.ingest(
        _at(7), "You hit a frost giant for 20 points of damage.", False) == ()
    assert state.ingest(
        _at(8), "a frost giant hits Alice for 72 points of damage.", False) == ()


def test_death_loop_matches_four_in_120s_and_resets_on_player_activity():
    state = SafetyAlertState(4, 120)
    for second in (0, 30, 60):
        assert state.ingest(
            _at(second), "You have been slain by a frost giant!", True) == ()
    alert = state.ingest(_at(90), "You died.", True)
    assert len(alert) == 1
    assert alert[0].kind == "death_loop"
    assert alert[0].death_count == 4

    state.ingest(_at(91), "You begin casting Gate.", True)
    assert len(state.deaths) == 0
    for second in (100, 110, 120):
        state.ingest(_at(second), "You died.", True)
    state.ingest(_at(121), "You auction, 'Still here'", True)
    assert len(state.deaths) == 0


def test_death_loop_window_and_storage_are_bounded():
    state = SafetyAlertState(4, 30)
    for second in range(50):
        state.ingest(_at(second), "You died.", True)
    assert len(state.deaths) <= state.deaths.maxlen == 20
    state.ingest(_at(100), "an ordinary line", True)
    assert len(state.deaths) == 0

