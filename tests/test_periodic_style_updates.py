"""Recurring countdown updates must not rebuild unchanged Qt styles."""
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from vantage.helpers import config
from vantage.helpers.notification_overlay import NotificationOverlayManager
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.parsers.quickbar import QuickBar
from vantage.parsers.spells import SpellWidget
from vantage.parsers.timers import TimerRow
from vantage.parsers.maps.mapclasses import SpawnPoint


class _Control:
    def __init__(self):
        self.properties = {}
        self.polishes = 0

    def property(self, name):
        return self.properties.get(name)

    def setProperty(self, name, value):
        self.properties[name] = value

    def style(self):
        return None

    def setStyle(self, _style):
        self.polishes += 1

    def setValue(self, value):
        self.value = value

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tooltip = text

    def setAccessibleDescription(self, text):
        self.description = text


def test_spell_phase_styles_change_once_not_on_every_countdown_tick():
    progress = _Control()
    row = SimpleNamespace(progress=progress)
    for _ in range(20):
        SpellWidget._set_progress_state(
            row, Warning=False, Critical=False, Pulse=False)
    assert progress.polishes == 1
    SpellWidget._set_progress_state(row, Warning=True, Critical=False, Pulse=False)
    assert progress.polishes == 2
    SpellWidget._set_progress_state(row, Warning=True, Critical=False, Pulse=False)
    assert progress.polishes == 2
    SpellWidget._set_progress_state(row, Critical=True, Pulse=True)
    assert progress.polishes == 3
    SpellWidget._set_progress_state(row, Faded=True, Pulse=False)
    assert progress.polishes == 4


def test_quickbar_tick_keeps_values_current_without_repolishing_each_sample():
    bar = SimpleNamespace(
        tick_progress=_Control(), tick_countdown=_Control(), _window_targets={})
    for remaining in (5.0, 4.9, 4.8):
        QuickBar._server_tick_update(bar, SimpleNamespace(
            synced=True, pulse=False, remaining=remaining, progress=.5))
    assert bar.tick_progress.polishes == 1
    assert bar.tick_countdown.text == '4.8'
    assert bar.tick_progress.value == 500
    QuickBar._server_tick_update(bar, SimpleNamespace(synced=True, pulse=True))
    assert bar.tick_progress.polishes == 2
    assert bar.tick_countdown.text == 'TICK'
    QuickBar._server_tick_update(bar, SimpleNamespace(synced=False, pulse=False))
    assert bar.tick_progress.polishes == 3


def test_timer_phase_repolishes_only_when_the_phase_changes(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, 'data', {})
    config.verify_settings()
    owner = SimpleNamespace(
        announce=lambda *_: None, state_changed=lambda: None,
        edit_timer=lambda *_: None, clone_timer=lambda *_: None,
        delete_timer=lambda *_: None)
    timer = SpawnTimerState('Synthetic timer', 60)
    row = TimerRow(timer, owner)
    calls = []
    original = row.phase_label.setStyle
    monkeypatch.setattr(row.phase_label, 'setStyle', lambda style: (
        calls.append(True), original(style)))
    for _ in range(5):
        row.refresh()
    assert calls == []
    row._restart()
    row.refresh()
    assert len(calls) == 1
    row.refresh()
    assert len(calls) == 1
    assert row.time_label.text() != '--:--'
    row.close()


def test_overlay_styles_are_cached_but_fade_and_settings_still_apply(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, 'data', {'general': {'notification_overlays':
        config.normalize_notification_overlays({})}})
    monkeypatch.setattr(config, 'save', lambda: None)
    manager = NotificationOverlayManager()
    try:
        overlay = manager.overlays['alerts']
        calls = []
        original = overlay.card.setStyleSheet
        monkeypatch.setattr(overlay.card, 'setStyleSheet', lambda text: (
            calls.append(text), original(text)))
        for _ in range(5):
            overlay._apply_appearance(False)
        assert calls == []
        overlay._apply_appearance(True)
        assert len(calls) == 1
        overlay._apply_appearance(True)
        assert len(calls) == 1
        config.data['general']['notification_overlays']['alerts']['font_size'] = 16
        overlay._apply_appearance(True)
        assert len(calls) == 2
        assert '16pt' in overlay.card.styleSheet()
    finally:
        manager.close()


def test_restarting_map_pin_keeps_one_owned_refresh_timer(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    original = SpawnPoint._update

    def tracked_update(pin):
        calls.append(pin)
        original(pin)

    monkeypatch.setattr(SpawnPoint, '_update', tracked_update)
    pin = SpawnPoint(length=60)
    try:
        for _ in range(20):
            pin.start()
        assert len(calls) == 20
        assert pin.timer.isSingleShot()
        assert pin.timer.isActive()
        QTest.qWait(1150)
        # A slow CI host may deliver a late tick, but must never deliver the
        # twenty independent callback chains the old restart path scheduled.
        assert 21 <= len(calls) <= 22
        pin.stop()
        assert not pin.timer.isActive()
    finally:
        pin.timer.stop()
