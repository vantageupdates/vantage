import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
    QLineEdit, QWidget)

from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.helpers.overlay_editor import OverlayManagerDialog
from vantage.helpers.threat_settings import ThreatSettingsDialog
from vantage.parsers.combat import CombatExportOptionsDialog
from vantage.parsers.timers import TimerEditDialog


def rect(widget):
    value = widget.geometry()
    return [value.x(), value.y(), value.width(), value.height()]


def scale_down(dialog, width, height, anchor):
    dialog.show()
    app.processEvents()
    before = rect(anchor)
    dialog.resize(width, height)
    app.processEvents()
    return {
        'window': [dialog.width(), dialog.height()],
        'surface': [dialog.scaled_surface.width(), dialog.scaled_surface.height()],
        'scale': round(dialog.uniform_scale, 3),
        'logical_unchanged': rect(anchor) == before,
    }


def click_scaled(dialog, child):
    logical = child.mapTo(dialog.scaled_surface, child.rect().center())
    scene = dialog._dialog_proxy.mapToScene(QPointF(logical))
    viewport = dialog._dialog_view.mapFromScene(scene)
    QTest.mouseClick(
        dialog._dialog_view.viewport(), Qt.MouseButton.LeftButton,
        pos=viewport)


app = VantageApp([])
combat = app._parsers_dict['combat']
timer = TimerEditDialog(parent=app._parsers_dict['timers'])
output = CombatExportOptionsDialog(combat._output_options(), combat)
threat = ThreatSettingsDialog(config.data['combat']['threat'], combat)
overlays = OverlayManagerDialog(app._notification_overlay, combat)

results = {
    'timer': scale_down(timer, 250, 210, timer.name),
    'output': scale_down(output, 270, 260, output.output_channel),
    'threat': scale_down(threat, 280, 240, threat.main_rate),
    'overlays': scale_down(overlays, 415, 285, overlays.name),
}

click_scaled(timer, timer.name)
QTest.keyClicks(timer._dialog_view.viewport(), 'Quillmane')
app.processEvents()
results['timer_text'] = timer.name.text()

interactive = (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QLineEdit)
results['timer_missing_tooltips'] = [
    widget.accessibleName() or widget.objectName() or type(widget).__name__
    for widget in timer.scaled_surface.findChildren(QWidget)
    if isinstance(widget, interactive) and widget.isVisibleTo(timer.scaled_surface)
    and not widget.toolTip().strip()]

print(json.dumps(results))
for dialog in (timer, output, threat, overlays):
    dialog.close()
app.quit()
"""


def test_priority_dialogs_scale_as_fixed_miniatures_with_live_controls(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["timer_text"] == "Quillmane"
    assert result["timer_missing_tooltips"] == []
    for name in ("timer", "output", "threat", "overlays"):
        assert result[name]["scale"] <= 0.51
        assert result[name]["logical_unchanged"] is True
    assert result["timer"]["surface"] == [500, 420]
    assert result["output"]["surface"] == [540, 486]
    assert result["threat"]["surface"] == [560, 590]
    assert result["overlays"]["surface"] == [830, 570]
