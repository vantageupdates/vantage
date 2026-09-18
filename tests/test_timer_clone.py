import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_ACCESSIBILITY", "0")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from vantage.helpers.spawn_timer import PHASE_IDLE, SpawnTimerState
from vantage.parsers import timers as timers_module
from vantage.parsers.timers import (
    SpawnTimers, TimerEditDialog, clone_timer_configuration)


def _app():
    return QApplication.instance() or QApplication([])


def _active_timer():
    timer = SpawnTimerState(
        "Kennel Master", 1_970, kill_seconds=75, warning_seconds=45,
        color="#657A96", smart=False, zone="Chardok",
        death_mobs=["Kennel Master Al`ele", "chokidai kennel guard"],
        sound_path="builtin:danger-double", volume=63, delivery="tts",
        tts_text="{timer} {state}", tts_voice="Adjutant", tts_pitch=-2,
        source="Imported raid sheet", automatic=True)
    timer.start(100)
    timer.cycles = 4
    timer.warning_sent = True
    return timer


def test_clone_configuration_is_deep_and_runtime_identity_is_fresh():
    original = _active_timer()
    clone = clone_timer_configuration(original)

    for field in timers_module.TIMER_CLONE_CONFIGURATION_FIELDS:
        assert getattr(clone, field) == getattr(original, field)
    assert clone.timer_id != original.timer_id
    assert clone.phase == PHASE_IDLE
    assert clone.running is False
    assert clone.phase_started_at is None
    assert clone.deadline is None
    assert clone.paused_remaining is None
    assert clone.cycles == 0
    assert clone.warning_sent is False

    clone.death_mobs.append("another placeholder")
    assert "another placeholder" not in original.death_mobs


def test_clone_dialog_requires_name_or_death_trigger_change(monkeypatch):
    _app()
    original = _active_timer()
    candidate = clone_timer_configuration(original)
    dialog = TimerEditDialog(candidate, clone_source=original)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, title, message: warnings.append((title, message)))

    assert dialog._clone_has_required_change() is False
    assert dialog._validate() is False
    assert warnings and warnings[-1][0] == "Change Required"
    assert "different timer name" in warnings[-1][1]
    assert "original timer will not be changed" in warnings[-1][1]
    assert dialog.clone_notice.isVisible() is False  # dialog is not shown
    assert dialog.clone_notice.accessibleName() == \
        "Clone timer change required"
    assert "original is never overwritten" in \
        dialog.clone_notice.accessibleDescription()

    dialog.name.setText("Kennel Master · East room")
    assert dialog._clone_has_required_change() is True
    assert dialog._validate() is True
    dialog.close()


class _Controller:
    def __init__(self, timer):
        self._is_primary = True
        self._controller = self
        self._states = {timer.timer_id: timer}
        self._views = [self]
        self._settings = {"watch_timer_ids": [timer.timer_id]}
        self.refreshes = 0
        self.changes = []
        self.messages = []

    def _view_settings(self):
        return self._settings

    def _register_timer(self, timer):
        self._states[timer.timer_id] = timer
        return timer

    def _refresh_all_view_filters(self):
        self.refreshes += 1

    def state_changed(self, layout_changed=False):
        self.changes.append(layout_changed)

    def announce(self, message):
        self.messages.append(message)


def test_successful_clone_registers_new_timer_and_copies_watch(monkeypatch):
    original = _active_timer()
    before = copy.deepcopy(original.to_dict())
    controller = _Controller(original)

    class AcceptedCloneDialog:
        def __init__(self, candidate, _parent, clone_source=None):
            assert clone_source is original
            self.candidate = candidate

        def exec(self):
            return True

        def apply(self, candidate):
            candidate.name = "Kennel Master · East room"
            candidate.death_mobs.append("chokidai wardog")
            return candidate

    monkeypatch.setattr(timers_module, "TimerEditDialog", AcceptedCloneDialog)
    clone = SpawnTimers.clone_timer(controller, original.timer_id)

    assert clone is not None
    assert clone.timer_id != original.timer_id
    assert controller._states[original.timer_id] is original
    assert controller._states[clone.timer_id] is clone
    assert original.to_dict() == before
    assert clone.phase == PHASE_IDLE and clone.running is False
    assert controller._settings["watch_timer_ids"] == [
        original.timer_id, clone.timer_id]
    assert controller.refreshes == 1
    assert controller.changes == [True]
    assert controller.messages == [
        "CLONED · Kennel Master → Kennel Master · East room · new READY timer"]


def test_cancelled_clone_leaves_original_and_controller_untouched(monkeypatch):
    original = _active_timer()
    before = copy.deepcopy(original.to_dict())
    controller = _Controller(original)

    class CancelledCloneDialog:
        def __init__(self, candidate, _parent, clone_source=None):
            candidate.name = "Unsaved change"
            candidate.death_mobs.clear()

        def exec(self):
            return False

    monkeypatch.setattr(timers_module, "TimerEditDialog", CancelledCloneDialog)
    result = SpawnTimers.clone_timer(controller, original.timer_id)

    assert result is None
    assert list(controller._states) == [original.timer_id]
    assert original.to_dict() == before
    assert controller._settings["watch_timer_ids"] == [original.timer_id]
    assert controller.refreshes == 0
    assert controller.changes == []
    assert controller.messages == []
