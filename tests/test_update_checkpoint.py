import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp

app = VantageApp([])
spells = app._parsers_dict['spells']
config.data['spells']['use_casting_window'] = False
now = datetime.datetime.now().replace(microsecond=0)
spells.parse(now, 'You begin casting Clarity II.')
spells.parse(
    now + datetime.timedelta(seconds=4),
    'A soft breeze slips through your mind.')

# Do not wait for the normal 200 ms debounce: an update clicked immediately
# after a cast must still write the exact live row before starting another EXE.
app.checkpoint_for_update()
with open(config._filename, encoding='utf-8') as source:
    saved = json.load(source)
rows = saved['spells']['active_timer_state']
print(json.dumps({
    'count': len(rows),
    'spell': rows[0]['spell']['name'],
    'target': rows[0]['target'],
    'deadline_is_future': rows[0]['deadline'] > 0,
}))
app.quit()
"""


def test_update_checkpoint_preserves_a_just_cast_buff(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        'count': 1,
        'spell': 'clarity ii',
        'target': '__you__',
        'deadline_is_future': True,
    }
