import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import os

from vantage.helpers import config
from vantage.helpers.application import (
    UPDATE_BUSY_RETRY_MS, UPDATE_HEARTBEAT_MS, UPDATE_INITIAL_DELAY_MS,
    UPDATE_RETRY_MS, VantageApp)

config.data['general']['startup_window_state'] = 'normal'
config.data['general']['update_check'] = True
os.environ['VANTAGE_UPDATED_FROM'] = '1.44.44'
app = VantageApp([])
bar = app._parsers_dict['quickbar']
button = bar._buttons['updates']

initial = {
    'active': app._update_heartbeat.isActive(),
    'interval': app._update_heartbeat.interval(),
    'tooltip': button.toolTip(),
    'update_toast_visible': app._update_toast.isVisible(),
    'rail_text': bar.notification_rail._label.text(),
    'rail_pending': list(bar.notification_rail._pending),
}

app._update_heartbeat.stop()
app._update_controller.check = lambda: False
app._update_heartbeat_tick()
busy = app._update_heartbeat.interval()

app._update_check_started()
checking = {
    'state': button.property('UpdateState'),
    'name': button.accessibleName(),
    'tooltip': button.toolTip(),
}

app._update_check_failed('temporary GitHub failure')
retrying = {
    'state': button.property('UpdateState'),
    'name': button.accessibleName(),
    'interval': app._update_heartbeat.interval(),
}

app._update_check_finished(None, 'Up to date')
healthy = {
    'state': button.property('UpdateState'),
    'interval': app._update_heartbeat.interval(),
}

print(json.dumps({
    'initial': initial,
    'busy': busy,
    'checking': checking,
    'retrying': retrying,
    'healthy': healthy,
    'constants': [
        UPDATE_INITIAL_DELAY_MS, UPDATE_BUSY_RETRY_MS,
        UPDATE_RETRY_MS, UPDATE_HEARTBEAT_MS],
}))
app._update_heartbeat.stop()
app.quit()
"""


def test_update_heartbeat_starts_fast_retries_and_updates_quickbar(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['constants'] == [3000, 15000, 60000, 600000]
    assert result['initial']['active'] is True
    assert result['initial']['interval'] == 3000
    assert 'every 10 minutes' in result['initial']['tooltip']
    assert result['initial']['update_toast_visible'] is False
    update_message = 'Vantage updated · 1.44.44 → 1.44.46'
    assert update_message in (
        [result['initial']['rail_text']] + result['initial']['rail_pending'])
    assert result['busy'] == 15000
    assert result['checking'] == {
        'state': 'checking',
        'name': 'Checking for Vantage updates',
        'tooltip': 'Checking GitHub for a verified Vantage update…',
    }
    assert result['retrying'] == {
        'state': 'retrying',
        'name': 'Update check will retry automatically',
        'interval': 60000,
    }
    assert result['healthy'] == {
        'state': 'idle',
        'interval': 600000,
    }
