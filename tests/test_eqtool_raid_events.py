import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
import time

from vantage.helpers.application import VantageApp
from vantage.helpers.encounter_events import RING_WAR_SCHEDULE_SOURCE

app = VantageApp([])
timers = app._parsers_dict['timers']
now = datetime.datetime.now().replace(microsecond=0)
alerts = []
app.show_overlay_notification = lambda title, message, **kwargs: alerts.append(
    [title, message, kwargs.get('overlay_id')])

timers.parse(now, 'Dain Frostreaver IV engages Mindflux!')
timers.parse(
    now, 'You feel you should get somewhere safe as soon as possible.')
timers.parse(
    now, 'Seneschal Aldikar shouts, TROOPS, TAKE YOUR POSITIONS!')
schedule = [
    timer for timer in timers._states.values()
    if timer.source == RING_WAR_SCHEDULE_SOURCE]
first_id = schedule[0].timer_id
first_values = [schedule[0].name, schedule[0].respawn_seconds,
                timers._rows[first_id].phase_label.text()]
all_tooltips = all(
    timers._rows[timer.timer_id].toolTip()
    and timers._rows[timer.timer_id].progress.toolTip()
    for timer in schedule)
schedule[0].deadline = time.time() - 1
timers._tick()
print(json.dumps({
    'startup_alerts': alerts[:3],
    'due_alert': alerts[-1],
    'count': len(schedule),
    'after_due_count': len([
        timer for timer in timers._states.values()
        if timer.source == RING_WAR_SCHEDULE_SOURCE]),
    'first_removed': first_id not in timers._states,
    'first': first_values,
    'last': [schedule[-1].name, schedule[-1].respawn_seconds],
    'all_running': all(timer.running for timer in schedule),
    'all_tooltips': all_tooltips,
}))
app.quit()
"""


def test_raid_events_create_exact_local_overlays_and_schedule(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['startup_alerts'] == [
        ['Vantage', 'Mindflux FTE Dain Frostreaver IV', 'timers'],
        ['Vantage', 'Server quake detected from the EQ log', 'timers'],
        ['Vantage', 'Ring War schedule started · 24 milestones', 'timers'],
    ]
    assert result['due_alert'] == [
        'Vantage', 'Ring War · Wave 1 · Round 1: due now', 'timers']
    assert result['count'] == 24
    assert result['after_due_count'] == 23
    assert result['first_removed'] is True
    assert result['first'] == [
        'Ring War · Wave 1 · Round 1', 210, 'EVENT']
    assert result['last'] == [
        'Ring War · Wave 3 · Break', 5319]
    assert result['all_running'] is True
    assert result['all_tooltips'] is True
