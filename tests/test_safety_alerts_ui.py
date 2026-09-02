import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
timers = app._parsers_dict['timers']
alerts = []
app.show_overlay_notification = lambda title, message, **kwargs: alerts.append({
    'title': title, 'message': message,
    'overlay': kwargs.get('overlay_id'),
    'color': kwargs.get('text_color')})
app.is_everquest_foreground = lambda: False
now = datetime.datetime(2026, 1, 1)

timers.parse(now, 'a frost giant hits You for 72 points of damage.')
timers.parse(
    now + datetime.timedelta(seconds=1),
    'a frost giant hits You for 72 points of damage.')
timers.parse(
    now + datetime.timedelta(seconds=6),
    'a frost giant tries to kick You, but misses!')

app.is_everquest_foreground = lambda: True
timers.parse(
    now + datetime.timedelta(seconds=12),
    'a frost giant hits You for 72 points of damage.')

for second in (20, 40, 60, 80):
    timers.parse(
        now + datetime.timedelta(seconds=second),
        'You have been slain by a frost giant!')

print(json.dumps({
    'alerts': alerts,
    'status': timers.status.text(),
    'death_count': len(timers._safety.deaths),
}))
app.quit()
"""


def test_safety_alerts_use_movable_overlay_and_never_control_game(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['alerts'] == [
        {
            'title': 'Vantage · Safety',
            'message': 'AFK · You are being attacked by a frost giant',
            'overlay': 'alerts', 'color': '#E08372'},
        {
            'title': 'Vantage · Safety',
            'message': 'AFK · You are being attacked by a frost giant',
            'overlay': 'alerts', 'color': '#E08372'},
        {
            'title': 'Vantage · Safety',
            'message': 'DEATH LOOP · 4 deaths in 120 seconds with no player activity',
            'overlay': 'alerts', 'color': '#E08372'},
    ]
    assert result['status'].startswith('DEATH LOOP · 4 deaths')
    assert result['death_count'] == 4

