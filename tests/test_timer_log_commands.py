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
stamp = datetime.datetime.now()
timers.parse(stamp, "You say, 'StartTimer-30-Invis_Check'")
first = next(
    timer for timer in timers._states.values()
    if timer.source == 'Log command')
first_id = first.timer_id
timers.parse(
    stamp + datetime.timedelta(seconds=1),
    "You tell yourself, 'PigTimer-45-Invis_Check'")
second = timers._states[first_id]
timers._zone_changed("Velketor's Labyrinth")
timers.parse(
    stamp + datetime.timedelta(seconds=2),
    "You say, 'StartTimer-60-Root_Check'")
timers._zone_changed("Kael Drakkel")
timers.parse(
    stamp + datetime.timedelta(seconds=3),
    "You say, 'StartTimer-60-Root_Check'")
zoned = [
    timer for timer in timers._states.values()
    if timer.source == 'Log command' and timer.name == 'Root Check']
timers.zone_filter.setCurrentIndex(
    timers.zone_filter.findData("Velketor's Labyrinth"))
app.processEvents()
print(json.dumps({
    'name': second.name,
    'duration': second.respawn_seconds,
    'source': second.source,
    'running': second.running,
    'same_timer': len([
        timer for timer in timers._states.values()
        if timer.source == 'Log command' and
        timer.name == 'Invis Check']) == 1,
    'tooltip': bool(timers._rows[first_id].progress.toolTip()),
    'zoned_count': len(zoned),
    'zones': sorted(timer.zone for timer in zoned),
    'visible_root_zones': sorted(
        timer.zone for timer in zoned
        if not timers._rows[timer.timer_id].isHidden()),
    'zone_filter_tooltip': bool(timers.zone_filter.toolTip()),
}))
app.quit()
"""


def test_log_timer_command_creates_and_restarts_one_visible_timer(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'name': 'Invis Check',
        'duration': 45,
        'source': 'Log command',
        'running': True,
        'same_timer': True,
        'tooltip': True,
        'zoned_count': 2,
        'zones': ["Kael Drakkel", "Velketor's Labyrinth"],
        'visible_root_zones': ["Velketor's Labyrinth"],
        'zone_filter_tooltip': True,
    }
