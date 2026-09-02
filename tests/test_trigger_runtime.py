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
from vantage.helpers import config
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
spells = app._parsers_dict['spells']
repeat = CustomTrigger(
    name='Repeat test', text='Start repeat', time='00:00:02',
    timer_type='repeating', overlay_id='timers', alert_text='Cycle active',
    timer_ending_seconds=1, timer_ending_alert='Cycle ending',
    timer_ended_alert='Cycle ended', category='Runtime')
stopwatch = CustomTrigger(
    name='Pull stopwatch', text='Start watch', time='',
    timer_type='stopwatch', overlay_id='timers', alert_text='Elapsed',
    end_text='Stop watch', category='Runtime',
    end_patterns=[{'text': 'Stop watch', 'regex': False}])
config.data['spells']['custom_timers'] = [repeat.to_list(), stopwatch.to_list()]
config.data['spells']['trigger_categories']['Runtime'] = True
spells.load_custom_timers()

stamp = datetime.datetime.now()
spells.parse(stamp, 'Start repeat')
repeat_run = spells._trigger_runs['Repeat test']
repeat_run['deadline'] = time.monotonic() + 0.5
spells._update_custom_trigger_timers()
ending_fired = repeat_run['ending_fired']
repeat_run['deadline'] = time.monotonic() - 0.1
spells._update_custom_trigger_timers()
repeated = (
    'Repeat test' in spells._trigger_runs and
    spells._trigger_runs['Repeat test']['deadline'] > time.monotonic())

spells.parse(stamp, 'Start watch')
watch_run = spells._trigger_runs['Pull stopwatch']
timer_overlay = app._notification_overlay.overlays['timers']
stopwatch_visible = any(
    entry.get('key') == 'Pull stopwatch' and
    entry.get('timer_mode') == 'stopwatch'
    for entry in timer_overlay._entries)
spells.parse(stamp, 'Stop watch')

print(json.dumps({
    'ending_fired': ending_fired,
    'repeated': repeated,
    'watch_deadline': watch_run['deadline'],
    'stopwatch_visible': stopwatch_visible,
    'stopwatch_ended': 'Pull stopwatch' not in spells._trigger_runs,
}))
app.quit()
"""


TIMER_NAME_SCRIPT = r"""
import datetime
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
spells = app._parsers_dict['spells']
triggers = [
    CustomTrigger(
        name='Shared A', text='Start shared A', time='00:01:00',
        timer_type='countdown', timer_name='Shared spawn',
        restart_behavior='restart', restart_based_on_timer_name=True,
        overlay_id='timers', category='Runtime'),
    CustomTrigger(
        name='Shared B', text='Start shared B', time='00:02:00',
        timer_type='countdown', timer_name='Shared spawn',
        restart_behavior='restart', restart_based_on_timer_name=True,
        overlay_id='timers', category='Runtime'),
    CustomTrigger(
        name='Independent A', text='Start independent A', time='00:01:00',
        timer_type='countdown', timer_name='Independent shared',
        restart_behavior='restart', restart_based_on_timer_name=False,
        overlay_id='timers', category='Runtime'),
    CustomTrigger(
        name='Independent B', text='Start independent B', time='00:02:00',
        timer_type='countdown', timer_name='Independent shared',
        restart_behavior='restart', restart_based_on_timer_name=False,
        overlay_id='timers', category='Runtime'),
]
config.data['spells']['custom_timers'] = [item.to_list() for item in triggers]
config.data['spells']['trigger_categories']['Runtime'] = True
spells.load_custom_timers()
stamp = datetime.datetime.now()

spells.parse(stamp, 'Start shared A')
first_shared = next(
    run for run in spells._trigger_runs.values()
    if run['name'] == 'Shared spawn')
first_owner = first_shared['trigger'].name
spells.parse(stamp, 'Start shared B')
shared_runs = [
    run for run in spells._trigger_runs.values()
    if run['name'] == 'Shared spawn']

spells.parse(stamp, 'Start independent A')
spells.parse(stamp, 'Start independent B')
independent_runs = [
    run for run in spells._trigger_runs.values()
    if run['name'] == 'Independent shared']
custom_target = spells._spell_container.get_spell_target_by_name('__custom__')
independent_bars = [
    widget for widget in custom_target.spell_widgets()
    if widget.spell.name == 'Independent shared']
timer_overlay = app._notification_overlay.overlays['timers']
independent_overlay_rows = [
    entry for entry in timer_overlay._entries
    if entry.get('title') == 'Independent shared']

print(json.dumps({
    'first_owner': first_owner,
    'shared_count': len(shared_runs),
    'shared_owner': shared_runs[0]['trigger'].name,
    'shared_duration': shared_runs[0]['duration'],
    'independent_count': len(independent_runs),
    'independent_bars': len(independent_bars),
    'independent_overlay_rows': len(independent_overlay_rows),
    'independent_keys': sorted(run['key'] for run in independent_runs),
}))
app.quit()
"""


def test_trigger_runtime_supports_ending_repeating_stopwatch_and_early_end(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "ending_fired": True,
        "repeated": True,
        "watch_deadline": None,
        "stopwatch_visible": True,
        "stopwatch_ended": True,
    }


def test_trigger_runtime_matches_optional_timer_name_scope_without_merging_independent_runs(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", TIMER_NAME_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "first_owner": "Shared A",
        "shared_count": 1,
        "shared_owner": "Shared B",
        "shared_duration": 120.0,
        "independent_count": 2,
        "independent_bars": 2,
        "independent_overlay_rows": 2,
        "independent_keys": ["Independent A", "Independent B"],
    }
