import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


STARTUP_SCRIPT = r"""
import json
import os
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from vantage.helpers.application import VantageApp
from vantage.helpers import config

state = os.environ['QA_STARTUP_STATE']
config.data['general']['startup_window_state'] = state
app = VantageApp([])
timers = app._parsers_dict['timers']
quickbar = app._parsers_dict['quickbar']
result = {
    'visible': sum(parser.isVisible() for parser in app._parsers),
    'quickbar_visible': quickbar.isVisible(),
    'quickbar_toggled': quickbar._toggled,
    'timers_visible': timers.isVisible(),
    'timers_toggled': timers._toggled,
    'timers_rolled': timers._collapsed,
    'timers_uniform': (
        timers._scale_view is not None and timers._scale_proxy is not None),
    'taskbar_tools': all(
        bool(parser.windowFlags() & Qt.WindowType.Tool)
        for parser in app._parsers),
    'settings_lazy': app._settings_instance is None,
    'mobile_lazy': app._mobile_share_instance is None,
}
quickbar._trigger('timers')
QTest.qWait(30)
result['timers_visible_after_click'] = timers.isVisible()
result['timers_toggled_after_click'] = timers._toggled
timers.setGeometry(123, 77, 444, 333)
QTest.qWait(30)
result['window_size'] = [timers.width(), timers.height()]
result['surface_size'] = [timers._surface.width(), timers._surface.height()]
QTest.qWait(520)
result['saved_geometry'] = config.data['timers']['geometry']
print(json.dumps(result))
app.quit()
"""


@pytest.mark.parametrize(
    'state', ('rolled', 'minimized', 'normal'),
)
def test_quickbar_is_the_only_startup_window(tmp_path, state):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / state)
    env['QA_STARTUP_STATE'] = state
    completed = subprocess.run(
        [sys.executable, '-c', STARTUP_SCRIPT], env=env,
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['visible'] == 1
    assert result['quickbar_visible'] is True
    assert result['quickbar_toggled'] is True
    assert result['timers_visible'] is False
    assert result['timers_toggled'] is False
    assert result['timers_rolled'] is False
    assert result['timers_uniform'] is True
    assert result['taskbar_tools'] is True
    assert result['settings_lazy'] is True
    assert result['mobile_lazy'] is True
    assert result['timers_visible_after_click'] is True
    assert result['timers_toggled_after_click'] is True
    assert result['saved_geometry'] == [
        123, 77, *result['window_size']]
    assert result['surface_size'][0] == 520
    expected_logical_height = round(
        result['window_size'][1] /
        (result['window_size'][0] / 520))
    assert result['surface_size'][1] == expected_logical_height
