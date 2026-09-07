import math
import os
from pathlib import Path
import json
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from vantage.helpers.responsive import ResponsiveActionBar
from vantage.helpers.scaled_dialog import UniformScaleDialog


ROOT = Path(__file__).resolve().parents[1]

READABILITY_SCRIPT = r"""
import json
from PySide6.QtGui import QPalette
from vantage.helpers.application import VantageApp
from vantage.parsers.market import WikiItemCard
from vantage.parsers.timers import TimerEditDialog

app = VantageApp([])
dialogs = {
    'settings': app._settings,
    'item': WikiItemCard({'n': 'Manastone'}),
    'timer': TimerEditDialog(),
}
result = {}
for name, dialog in dialogs.items():
    design = dialog._dialog_design_size
    dialog.resize(1, 1)
    dialog.show()
    app.processEvents()
    result[name] = {
        'design': [design.width(), design.height()],
        'minimum': [dialog.minimumWidth(), dialog.minimumHeight()],
        'actual': [dialog.width(), dialog.height()],
        'scale': dialog.uniform_scale,
    }
    dialog.close()
checklist = app._parsers_dict['quests']._checklist
checklist.show()
app.processEvents()
result['quest_checklist_palette'] = {
    'window': checklist.palette().color(QPalette.ColorRole.Window).name(),
    'text': checklist.palette().color(QPalette.ColorRole.WindowText).name(),
}
checklist.close()
print(json.dumps(result))
app.quit()
"""


def test_concrete_scaled_dialogs_cannot_shrink_below_readable_floor(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', READABILITY_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    for name in ('settings', 'item', 'timer'):
        dialog = result[name]
        required_width = math.ceil(
            dialog['design'][0] * UniformScaleDialog.MIN_READABLE_SCALE)
        required_height = math.ceil(
            dialog['design'][1] * UniformScaleDialog.MIN_READABLE_SCALE)
        assert dialog['minimum'][0] >= required_width
        assert dialog['minimum'][1] >= required_height
        assert dialog['actual'][0] >= required_width
        assert dialog['actual'][1] >= required_height
        assert dialog['scale'] >= UniformScaleDialog.MIN_READABLE_SCALE - .02

    palette = result['quest_checklist_palette']
    assert palette['window'] == '#0c0e11'
    assert palette['text'] == '#e8e6e1'


def test_queued_responsive_reflow_is_safe_after_rapid_close():
    app = QApplication.instance() or QApplication([])
    parent = ResponsiveActionBar(80)
    for label in ("One", "Two", "Three"):
        parent.addWidget(QPushButton(label))
    parent.show()
    parent.close()
    parent.deleteLater()
    # Executes every queued zero-delay reflow after the native widgets close.
    for _ in range(3):
        app.processEvents()
