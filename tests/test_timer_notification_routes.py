import time
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.helpers.notification_routes import NotificationDeliveryResult
from vantage.parsers import timers as timers_module
from vantage.parsers.timers import SpawnTimers, TimerEditDialog


def test_timer_sound_inheritance_off_and_override_round_trip():
    for value in (None, '', 'builtin:portal-ping'):
        timer = SpawnTimerState('Frenzy', 30, sound_path=value)
        assert SpawnTimerState.from_dict(timer.to_dict()).sound_path == value


def test_timer_tick_passes_explicit_three_state_override_to_dispatcher(monkeypatch):
    app = QApplication.instance() or QApplication([])
    captured = []
    monkeypatch.setattr(
        app, 'notify_event',
        lambda route, message, **kwargs: captured.append(
            (route, kwargs.get('sound_override'))),
        raising=False)

    class Host:
        def __init__(self, timer):
            self._states = {timer.timer_id: timer}
            self._rows = {timer.timer_id: SimpleNamespace(refresh=lambda: None)}
        def announce(self, _message):
            pass
        def _remove_timer(self, timer_id):
            self._states.pop(timer_id, None)
        def _save(self):
            pass

    for value in (None, '', 'builtin:portal-ping'):
        timer = SpawnTimerState(
            'Frenzy', 30, smart=False, sound_path=value,
            running=True, phase='respawn', deadline=time.time() - 1)
        SpawnTimers._tick(Host(timer))
    assert captured == [
        ('smart_timer', None), ('smart_timer', ''),
        ('smart_timer', 'builtin:portal-ping')]


def test_timer_editor_tests_inherited_off_and_override_truthfully(monkeypatch):
    config.verify_settings()
    app = QApplication.instance() or QApplication([])
    calls = []
    announcements = []

    def notify(route, message, **kwargs):
        calls.append((route, kwargs))
        override = kwargs.get('sound_override')
        if override is None:
            return NotificationDeliveryResult(route, 'voice', 'played', True)
        if override == '':
            return NotificationDeliveryResult(route, 'off', 'off', False)
        return NotificationDeliveryResult(route, 'sound', 'played', True)

    monkeypatch.setattr(app, 'notify_event', notify, raising=False)
    monkeypatch.setattr(
        timers_module.QAccessible, 'updateAccessibility',
        lambda event: announcements.append(event))
    dialog = TimerEditDialog()

    dialog.sound.setCurrentIndex(0)
    dialog._test_notification()
    assert calls[-1][0] == 'smart_timer'
    assert calls[-1][1]['sound_override'] is None
    assert calls[-1][1]['allow_hidden'] is True
    assert dialog.sound_test_status.text() == 'Test status · voice played'

    dialog.sound.setCurrentIndex(dialog.sound.findData(''))
    dialog._test_notification()
    assert calls[-1][1]['sound_override'] == ''
    assert 'Off' in dialog.sound_test_status.text()

    dialog.sound.setCurrentIndex(dialog.sound.findData('builtin:portal-ping'))
    dialog._test_notification()
    assert calls[-1][1]['sound_override'] == 'builtin:portal-ping'
    assert dialog.sound_test_status.text() == 'Test status · sound played'
    assert dialog.sound_test_status.accessibleName()
    assert dialog.sound_test_status.toolTip()
    assert len(announcements) == 3
    dialog.close()
