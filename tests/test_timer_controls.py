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
    previous = config.data['timers']['compact']
    config.data['timers']['compact'] = False
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
    assert row.controls.size() == TimerRow.CONTROLS_SIZE
    assert row.minimumHeight() == TimerRow.DETAILED_MINIMUM_HEIGHT
    assert row.volume.property("IntegratedRocker") is True
    assert row.volume.parentWidget() is row.controls
    row.close()
    row.deleteLater()
    app.processEvents()
    config.data['timers']['compact'] = previous


def test_compact_timer_controls_cannot_be_compressed_below_their_buttons():
    app = _app()
    previous = config.data['timers']['compact']
    config.data['timers']['compact'] = True
    try:
        row = TimerRow(SpawnTimerState("Crystal Eyes", 1970), _Owner())
        # Reproduce a panel trying to squeeze its timer rows while being
        # shortened. The row must enforce enough space for the full segmented
        # control instead of painting it under the following card.
        row.resize(510, 30)
        row.show()
        app.processEvents()

        assert row.height() >= TimerRow.COMPACT_MINIMUM_HEIGHT
        assert row.controls.height() == TimerRow.CONTROLS_SIZE.height()
        previous_right = -1
        for index in range(row.controls.layout().count()):
            control = row.controls.layout().itemAt(index).widget()
            assert control.geometry().bottom() < row.controls.height()
            assert control.geometry().left() > previous_right
            previous_right = control.geometry().right()
        assert previous_right < row.controls.width()
        assert row.controls.geometry().bottom() < row.height()
        row.close()
        row.deleteLater()
        app.processEvents()
    finally:
        config.data['timers']['compact'] = previous


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
