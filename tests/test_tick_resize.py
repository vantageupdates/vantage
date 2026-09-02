import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
tick = app._parsers_dict['tick']
tick._set_collapsed(False)
tick.show()
tick.resize(195, 48)
app.processEvents()
app.processEvents()

controls = (tick.mode, tick.auto, tick.sync_button, tick.clear_button)
inside = []
for control in controls:
    top = control.mapTo(tick._surface, control.rect().topLeft())
    bottom = control.mapTo(tick._surface, control.rect().bottomRight())
    inside.append(
        top.x() >= 0 and top.y() >= 0 and
        bottom.x() < tick._surface.width() and
        bottom.y() < tick._surface.height())

print(json.dumps({
    'size': [tick.width(), tick.height()],
    'minimum_height': tick.minimumHeight(),
    'inside': inside,
}))
app.quit()
"""


def test_tick_rejects_a_height_that_would_cut_its_controls(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['size'][0] == 195
    assert result['size'][1] >= 106
    assert result['minimum_height'] == 48
    assert all(result['inside'])
