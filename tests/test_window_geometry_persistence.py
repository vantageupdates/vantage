import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SAVE_SCRIPT = r"""
import json
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp

app = VantageApp([])
sizes = {
    'maps': (333, 287),
    'spells': (231, 355),
    'tick': (173, 101),
    'timers': (417, 311),
    'combat': (463, 277),
    'heals': (431, 203),
    'market': (777, 489),
}
for index, (name, size) in enumerate(sizes.items()):
    panel = app._parsers_dict[name]
    panel._set_collapsed(False)
    panel.setGeometry(20 + index * 12, 30 + index * 9, *size)

bar = app._parsers_dict['quickbar']
bar.resize(
    round(bar._design_size.width() * .78),
    round(bar._design_size.height() * .78))
QTest.qWait(600)
app.checkpoint_for_update()
names = [*sizes, 'quickbar']
print(json.dumps({name: config.data[name]['geometry'] for name in names}))
app.quit()
"""


RESTORE_SCRIPT = r"""
import json
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

app = VantageApp([])
QTest.qWait(600)
names = [
    'maps', 'spells', 'tick', 'timers', 'combat', 'heals', 'market',
    'quickbar']

def rectangles():
    return {
        name: [
            app._parsers_dict[name].x(), app._parsers_dict[name].y(),
            app._parsers_dict[name].width(), app._parsers_dict[name].height()]
        for name in names
    }

startup = rectangles()
app.reload_ui()
QTest.qWait(600)
print(json.dumps({'startup': startup, 'reloaded': rectangles()}))
app.quit()
"""


def _run(script, profile):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(profile)
    completed = subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_every_window_and_quickbar_keep_exact_size_across_restart_and_reload(
        tmp_path):
    profile = tmp_path / 'profile'
    saved = _run(SAVE_SCRIPT, profile)
    restored = _run(RESTORE_SCRIPT, profile)
    saved_sizes = {name: rectangle[2:] for name, rectangle in saved.items()}
    startup_sizes = {
        name: rectangle[2:]
        for name, rectangle in restored['startup'].items()}
    reloaded_sizes = {
        name: rectangle[2:]
        for name, rectangle in restored['reloaded'].items()}

    # Positions may be clamped when the next run uses a smaller monitor, but
    # the user's chosen physical width and height must never be rescaled.
    assert startup_sizes == saved_sizes
    assert reloaded_sizes == saved_sizes
