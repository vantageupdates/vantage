import time
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.spawn_timer import SpawnTimerState, TimerEvent
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


def test_timer_event_sound_tts_and_off_are_exclusive_and_profile_aware(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    notified, spoken = [], []

    def notify(route, message, **kwargs):
        notified.append((route, message, kwargs))
        delivery = str(kwargs.get("delivery_override") or "sound")
        return NotificationDeliveryResult(route, delivery, "played", True)

    monkeypatch.setattr(app, "notify_event", notify, raising=False)
    monkeypatch.setattr(
        timers_module, "speak_text",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    host = SimpleNamespace(
        _active_character="Mindflux", _active_server="Green")
    event = TimerEvent("warning", "one", "Frenzy", "Frenzy: spawn in 9 s")

    sound = SpawnTimerState(
        "Frenzy", 30, zone="Lower Guk", delivery="sound",
        sound_path="builtin:portal-ping", volume=41)
    SpawnTimers._deliver_timer_event(
        host, sound, event, event.message, "smart_timer", 1)
    assert notified[-1][2]["delivery_override"] == "sound"
    assert notified[-1][2]["sound_override"] == "builtin:portal-ping"
    assert spoken == []

    voice = SpawnTimerState(
        "Frenzy", 30, zone="Lower Guk", delivery="tts",
        tts_text="{timer} {state} in {zone}", tts_voice="Narrator",
        tts_pitch=-5, volume=53)
    SpawnTimers._deliver_timer_event(
        host, voice, event, event.message, "smart_timer", 1)
    assert notified[-1][2]["delivery_override"] == "off"
    assert spoken[-1][0][:2] == (
        "Frenzy ending soon in Lower Guk", 53)
    assert spoken[-1][1]["voice_name"] == "Narrator"
    assert spoken[-1][1]["pitch"] == -5
    assert spoken[-1][1]["character"] == "Mindflux"
    assert spoken[-1][1]["server"] == "Green"
    assert spoken[-1][1]["channel"] == "timers"
    assert spoken[-1][1]["allow_hidden"] is False

    silent = SpawnTimerState("Frenzy", 30, delivery="off")
    before = len(spoken)
    SpawnTimers._deliver_timer_event(
        host, silent, event, event.message, "smart_timer", 1)
    assert notified[-1][2]["delivery_override"] == "off"
    assert len(spoken) == before


def test_timer_editor_exposes_compact_accessible_tts_controls(monkeypatch):
    config.verify_settings()
    app = QApplication.instance() or QApplication([])
    spoken = []
    monkeypatch.setattr(
        timers_module, "speech_voice_names", lambda: ["Voice One"])
    monkeypatch.setattr(
        timers_module, "speak_text",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    timer = SpawnTimerState(
        "Port cycle", 600, zone="North Karana", delivery="tts",
        tts_text="{timer}: {state} · {zone}", tts_voice="Voice One",
        tts_pitch=4, volume=47)
    dialog = TimerEditDialog(timer)
    dialog.show()
    app.processEvents()

    assert [dialog.delivery.itemData(index)
            for index in range(dialog.delivery.count())] == [
                "legacy", "sound", "tts", "off"]
    assert dialog.delivery.currentData() == "tts"
    assert dialog.delivery.accessibleName() == "Timer notification delivery"
    assert dialog.tts_text.accessibleName() == "Timer speech message"
    assert "{timer}" in dialog.tts_text.toolTip()
    assert dialog.tts_voice.accessibleName() == "Timer Windows voice"
    assert dialog.tts_voice.currentData() == "Voice One"
    assert dialog.tts_voice.itemData(0) == ""
    assert dialog.tts_voice.itemText(0).startswith("Vantage Command")
    assert "calm installed Windows voice" in \
        dialog.tts_voice.accessibleDescription()
    assert dialog.tts_pitch.accessibleName() == "Timer speech pitch"
    assert dialog.tts_pitch.value() == 4
    assert dialog.tts_text.isEnabled() and not dialog.sound.isEnabled()

    dialog._test_notification()
    assert spoken[-1][0][:2] == (
        "Port cycle: ready · North Karana", 47)
    assert dialog.sound_test_status.text() == "Test status · tts played"
    assert dialog.sound_test_status.accessibleName() == \
        "Test status · tts played"
    assert "Latest timer notification test result" in \
        dialog.sound_test_status.accessibleDescription()

    host = dialog._form_scroll.widget()
    rows = [
        dialog.death_mob_panel, dialog.color_preview, dialog.delivery,
        dialog._sound_panel, dialog._tts_panel, dialog.volume]
    rects = [QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())
             for widget in rows]
    assert all(before.bottom() < after.top()
               for before, after in zip(rects, rects[1:]))
    assert rects[-1].bottom() < host.height()
    assert dialog._form_scroll.verticalScrollBar().maximum() > 0
    assert dialog._death_mob_label.buddy() is dialog.death_mob_picker
    assert dialog._sound_panel_label.buddy() is dialog.sound
    assert dialog._tts_panel_label.buddy() is dialog.tts_text

    dialog.delivery.setCurrentIndex(dialog.delivery.findData("sound"))
    app.processEvents()
    assert dialog.sound.isEnabled() and not dialog.tts_text.isEnabled()
    dialog.delivery.setCurrentIndex(dialog.delivery.findData("tts"))
    dialog.apply(timer)
    assert timer.delivery == "tts"
    assert timer.tts_text == "{timer}: {state} · {zone}"
    assert timer.tts_voice == "Voice One"
    assert timer.tts_pitch == 4 and timer.volume == 47
    dialog.close()
