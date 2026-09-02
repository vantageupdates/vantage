import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QHelpEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.parsers.timers import TimerEditDialog


def panel_tooltip(panel, control):
    logical = control.mapTo(panel._surface, control.rect().center())
    scene = panel._scale_proxy.mapToScene(QPointF(logical))
    point = panel._scale_view.mapFromScene(scene)
    event = QHelpEvent(
        QEvent.Type.ToolTip, point,
        panel._scale_view.viewport().mapToGlobal(point))
    QToolTip.hideText()
    QApplication.sendEvent(panel._scale_view.viewport(), event)
    app.processEvents()
    return QToolTip.text()


def panel_hover_tooltip(panel, control):
    logical = control.mapTo(panel._surface, control.rect().center())
    scene = panel._scale_proxy.mapToScene(QPointF(logical))
    point = panel._scale_view.mapFromScene(scene)
    viewport = panel._scale_view.viewport()
    global_point = viewport.mapToGlobal(point)
    event = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), QPointF(global_point),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)
    app.processEvents()
    return panel._scale_view.viewport().toolTip()


def dialog_tooltip(dialog, control):
    logical = control.mapTo(dialog.scaled_surface, control.rect().center())
    scene = dialog._dialog_proxy.mapToScene(QPointF(logical))
    point = dialog._dialog_view.mapFromScene(scene)
    event = QHelpEvent(
        QEvent.Type.ToolTip, point,
        dialog._dialog_view.viewport().mapToGlobal(point))
    QToolTip.hideText()
    QApplication.sendEvent(dialog._dialog_view.viewport(), event)
    app.processEvents()
    return QToolTip.text()


app = VantageApp([])
timers = app._parsers_dict['timers']
if timers._collapsed:
    timers._set_collapsed(False)
timers._auto_hide_menu = False
timers._set_header_revealed(True)
timer = SpawnTimerState('Tooltip test', 1200, kill_seconds=90, volume=42)
timers._states[timer.timer_id] = timer
timers._add_row(timer)
row = timers._rows[timer.timer_id]
timers.resize(timers.minimumSize())
timers.show()
app.processEvents()

editor = TimerEditDialog(timer)
editor.resize(editor.minimumSize())
editor.show()
app.processEvents()

settings = app._settings
settings.resize(settings.minimumSize())
settings.show()
app.processEvents()
archive_enabled = settings.scaled_surface.findChild(
    QWidget, 'general:log_archive_enabled')
archive_size = settings.scaled_surface.findChild(
    QWidget, 'general:log_archive_size_mb')

print(json.dumps({
    'panel_button': panel_tooltip(timers, row.play_button),
    'panel_button_expected': row.play_button.toolTip(),
    'panel_spinbox': panel_tooltip(timers, row.volume),
    'panel_spinbox_expected': row.volume.toolTip(),
    'inner_timer_hover': panel_hover_tooltip(timers, row.restart_button),
    'inner_timer_hover_expected': row.restart_button.toolTip(),
    'header_hover': panel_hover_tooltip(timers, timers._roll_button),
    'header_hover_expected': timers._roll_button.toolTip(),
    'dialog_lineedit': dialog_tooltip(editor, editor.respawn),
    'dialog_lineedit_expected': editor.respawn.toolTip(),
    'dialog_spinbox': dialog_tooltip(editor, editor.warning),
    'dialog_spinbox_expected': editor.warning.toolTip(),
    'settings_checkbox': dialog_tooltip(settings, archive_enabled),
    'settings_checkbox_expected': archive_enabled.toolTip(),
    'settings_spinbox': dialog_tooltip(settings, archive_size),
    'settings_spinbox_expected': archive_size.toolTip(),
}))

settings.close()
editor.close()
timers.close()
app.quit()
"""


def test_scaled_surfaces_forward_real_tooltip_events(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['panel_button'] == result['panel_button_expected']
    assert result['panel_spinbox'] == result['panel_spinbox_expected']
    assert result['inner_timer_hover'] == result['inner_timer_hover_expected']
    assert result['header_hover'] == result['header_hover_expected']
    assert result['dialog_lineedit'] == result['dialog_lineedit_expected']
    assert result['dialog_spinbox'] == result['dialog_spinbox_expected']
    assert result['settings_checkbox'] == result['settings_checkbox_expected']
    assert result['settings_spinbox'] == result['settings_spinbox_expected']
