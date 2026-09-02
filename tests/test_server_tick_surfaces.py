import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config

config.data['general']['startup_window_state'] = 'normal'
config.data['tick']['toggled'] = True
app = VantageApp([])
tick = app._parsers_dict['tick']
app._parsers_dict['quickbar']._trigger('tick')
app.processEvents()
tick.sync_now()

tick._set_collapsed(True)
app.processEvents()
rolled = {
    'header_visible': tick.header_tick.isVisible(),
    'header_text': tick.header_countdown.text(),
    'header_progress': tick.header_progress.value(),
    'main_progress': tick.progress.value(),
    'tray_text': app._tray_tick_text,
    'tray_dynamic': app._tick_tray_icon_key is not None,
    'tooltip': app._system_tray.toolTip(),
}

tick._set_collapsed(False)
app.processEvents()
expanded = {
    'header_visible': tick.header_tick.isVisible(),
    'tray_text': app._tray_tick_text,
    'tray_dynamic': app._tick_tray_icon_key is not None,
}

tick._minimize_to_tray()
app.processEvents()
hidden = {
    'visible': tick.isVisible(),
    'tray_text': app._tray_tick_text,
    'tray_dynamic': app._tick_tray_icon_key is not None,
    'cached_icons': len(app._tick_tray_icon_cache),
}

print(json.dumps({'rolled': rolled, 'expanded': expanded, 'hidden': hidden}))
app.quit()
"""


def test_tick_moves_to_header_and_windows_tray_when_compact(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], env=env, cwd=ROOT,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['rolled']['header_visible'] is True
    assert result['rolled']['header_text'] == 'TICK'
    assert result['rolled']['header_progress'] == \
        result['rolled']['main_progress'] == 1000
    assert result['rolled']['tray_dynamic'] is True
    assert result['rolled']['tray_text'] == 'Server Tick NOW'
    assert 'Server Tick NOW' in result['rolled']['tooltip']

    assert result['expanded'] == {
        'header_visible': False,
        'tray_text': '',
        'tray_dynamic': False,
    }
    assert result['hidden']['visible'] is False
    assert result['hidden']['tray_dynamic'] is True
    assert result['hidden']['tray_text'] == 'Server Tick NOW'
    assert result['hidden']['cached_icons'] >= 1
