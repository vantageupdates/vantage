import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton

from vantage.helpers import config
from vantage.helpers.spawn_timer import PHASE_IDLE, PHASE_RESPAWN, SpawnTimerState
from vantage.parsers.timers import (
    SPAWN_TIMER_WINDOW_STYLE, TimerProgressBar, TimerRow)


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


def test_timer_row_uses_border_light_crisp_controls():
    app = _app()
    row = TimerRow(SpawnTimerState("Crystal Fang", 1970), _Owner())
    row.resize(510, row.sizeHint().height())
    row.show()
    app.processEvents()

    assert "QFrame#SpawnTimerRow" in SPAWN_TIMER_WINDOW_STYLE
    assert "background: transparent;\n        border: none;" in \
        SPAWN_TIMER_WINDOW_STYLE
    assert isinstance(row.progress, TimerProgressBar)
    assert row.progress.height() == 9
    assert "border: none" in row.progress.styleSheet()
    assert row.progress.accent == row.timer.color.upper()
    assert all(
        button.property("TimerRowAction") is True
        for button in row.findChildren(QPushButton))
    assert all(
        button.iconSize() == QSize(16, 16)
        for button in row.findChildren(QPushButton))
    assert row.controls.layout().spacing() == 0
    assert row.controls.width() == 242
    assert row.volume.property("IntegratedRocker") is True
    assert row.volume.parentWidget() is row.controls
    row.close()
    row.deleteLater()
    app.processEvents()


def test_timer_row_and_progress_render_at_fractional_scale():
    app = _app()
    timer = SpawnTimerState("Fractional scale", 1800)
    timer.start()
    row = TimerRow(timer, _Owner())
    row.resize(510, row.sizeHint().height())
    row.progress.setValue(62)
    row.show()
    app.processEvents()

    image = QImage(360, 90, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#00000000"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(0.70, 0.70)
    row.render(painter, QPoint())
    painter.end()

    assert not image.isNull()
    assert image.width() == 360
    assert any(
        QColor(image.pixel(x, 30)).alpha() > 0
        for x in range(5, image.width() - 5))
    row.close()
    row.deleteLater()
    app.processEvents()
