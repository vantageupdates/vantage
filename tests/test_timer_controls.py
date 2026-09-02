import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from vantage.helpers import config
from vantage.helpers.spawn_timer import PHASE_IDLE, PHASE_RESPAWN, SpawnTimerState
from vantage.parsers.timers import TimerRow


class _Owner:
    def __init__(self):
        self.messages = []
        self.changes = 0

    def announce(self, message):
        self.messages.append(message)

    def state_changed(self):
        self.changes += 1

    def edit_timer(self, _timer_id):
        pass

    def delete_timer(self, _timer_id):
        pass


def _app():
    if 'timers' not in config.data:
        config.data = {}
        config.verify_settings()
    return QApplication.instance() or QApplication([])


def test_restart_runs_immediately_and_clear_is_a_separate_action():
    app = _app()
    timer = SpawnTimerState("Crystal Fang", 1970)
    owner = _Owner()
    row = TimerRow(timer, owner)
    app.processEvents()

    row._restart()
    assert timer.phase == PHASE_RESPAWN
    assert timer.running is True
    assert timer.deadline is not None

    row._clear()
    assert timer.phase == PHASE_IDLE
    assert timer.running is False
    assert timer.deadline is None
    assert "restarted" in owner.messages[0]
    assert "cleared" in owner.messages[1]


def test_every_timer_button_has_an_authored_tooltip():
    app = _app()
    row = TimerRow(SpawnTimerState("Crystal Fang", 1970), _Owner())
    app.processEvents()
    buttons = row.findChildren(QPushButton)

    assert len(buttons) >= 7
    assert all(button.toolTip().strip() for button in buttons)
    assert "Restart" in row.restart_button.accessibleName()
    assert "READY" in row.clear_button.toolTip()
