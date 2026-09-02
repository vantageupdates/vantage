import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])

def audit(panel):
    controls = []
    for control_type in (QAbstractButton, QAbstractSpinBox, QComboBox):
        for control in panel._parser_menu_area.findChildren(control_type):
            if not control.isVisible():
                continue
            top_left = control.mapTo(panel._menu, control.rect().topLeft())
            controls.append((control.objectName() or control_type.__name__,
                             QRect(top_left, control.size())))
    overlaps = []
    for index, (first_name, first_rect) in enumerate(controls):
        for second_name, second_rect in controls[index + 1:]:
            if first_rect.intersects(second_rect):
                overlaps.append([first_name, second_name])
    return {
        'height': panel._menu.sizeHint().height(),
        'overlaps': overlaps,
    }

result = {}
for name, panel in app._parsers_dict.items():
    panel._set_collapsed(False)
    panel.resize(panel._design_size)
    panel._set_header_revealed(True)
    panel.show()
    app.processEvents()
    normal = audit(panel)
    panel._set_collapsed(True)
    app.processEvents()
    result[name] = {'normal': normal, 'rolled': audit(panel)}

print(json.dumps(result))
app.quit()
"""


def test_parser_headers_are_compact_and_controls_never_overlap(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result
    for states in result.values():
        for state in states.values():
            assert state['height'] <= 22
            assert state['overlaps'] == []
