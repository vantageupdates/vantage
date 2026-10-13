"""Trigger parity checks through isolated, real log-reader dispatch."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from vantage.helpers import config
from vantage.parsers.spells import (
    CustomTrigger, _trigger_captures, _trigger_ender_matches_run,
    render_trigger_text)


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import datetime
import json
from native_audit_fixture import isolate

isolate()
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers import spells as sm
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
spells = app._parsers_dict['spells']
settings = config.data['spells']
settings.update(use_custom_triggers=True, use_item_triggers=False)
settings['trigger_categories']['Parity'] = True
stamp = datetime.datetime.now()
clock = [100.0]
sm.time.monotonic = lambda: clock[0]
notices, audio = [], []
app._queue_quickbar_notice = lambda text, **kwargs: notices.append(text)
sm.speak_text = lambda text, *args, **kwargs: audio.append((text, kwargs))

def load(**changes):
    for key in list(spells._trigger_runs):
        spells._end_trigger_run(key)
    values = dict(
        name='Parity', text='Start {target}', time='00:01:00',
        timer_type='countdown', timer_name='Target {target}',
        category='Parity', overlay_id='timers', delivery='off',
        end_text='End all', match_cooldown_seconds=0)
    values.update(changes)
    settings['custom_timers'] = [CustomTrigger(**values).to_list()]
    spells.load_custom_timers()
    notices.clear()
    audio.clear()
    return spells._custom_timers[0][2]

def dispatch(text, character='Alice', server='Green'):
    app._parse((stamp, text, character, server))

def snapshot():
    return sorted((run['character'], run['server'], run['name'])
                  for run in spells._trigger_runs.values())

results = {}
try:
    for mode in ('restart', 'keep', 'new'):
        load(restart_behavior=mode)
        dispatch('Start First')
        dispatch('Start Second', 'Bob')
        dispatch('Start Third', 'Alice', 'Blue')
        results[mode + '_profiles'] = snapshot()
        dispatch('Start Fourth')
        results[mode + '_same_profile'] = snapshot()
        dispatch('End all', 'Alice', 'Blue')
        results[mode + '_end_blue'] = snapshot()
        results[mode + '_active_keys'] = sorted(
            spells._custom_timers[0][2].active_names) == sorted(spells._trigger_runs)

    load(restart_based_on_timer_name=True, timer_name='Shared')
    other = CustomTrigger(
        name='Other definition', text='Other start', time='00:02:00',
        timer_type='countdown', timer_name='Shared',
        restart_based_on_timer_name=True, category='Parity',
        overlay_id='timers', delivery='off', match_cooldown_seconds=0)
    settings['custom_timers'].append(other.to_list())
    spells.load_custom_timers()
    dispatch('Start First')
    dispatch('Start Second', 'Bob')
    dispatch('Other start')
    results['timer_name_owners'] = sorted(
        (run['character'], run['trigger'].name, run['duration'])
        for run in spells._trigger_runs.values())

    trigger = load(
        timer_type='none', alert_text='{c} #{COUNTER}',
        match_cooldown_seconds=5, counter_reset_seconds=10)
    dispatch('Start First')
    dispatch('Start First', 'Bob')
    dispatch('Start First', 'Alice', 'Blue')
    dispatch('Start First')  # duplicate only in Alice/Green
    clock[0] = 106.0
    dispatch('Start Second')
    clock[0] = 112.0
    dispatch('Start Second', 'Bob')  # Bob's own reset interval elapsed
    results['counter_notices'] = list(notices)

    for captured in ('named', 'numeric', 'unrelated'):
        raw = captured == 'numeric'
        trigger = load(
            text=r'^Start (.+)$' if raw else 'Start {target}', regex=raw,
            restart_behavior='new', timer_name='Target ${1}' if raw else 'Target {target}',
            end_patterns=[{'text': r'^End (.+)$' if raw else (
                'End {other}' if captured == 'unrelated' else 'End {target}'),
                'regex': raw}, {'text': 'End all', 'regex': False}])
        dispatch('Start Goblin A')
        dispatch('Start Goblin B')
        # A saved-definition reload must retain each live run's captures.
        spells.load_custom_timers()
        dispatch('End Goblin A')
        results[captured + '_end'] = snapshot()
        target = spells._spell_container.get_spell_target_by_name('__custom__')
        results[captured + '_row_count'] = len(target.spell_widgets()) if target else 0
        results[captured + '_overlay_count'] = len(
            [entry for entry in app._notification_overlay.overlays['timers']._entries
             if entry.get('title', '').startswith('Target Goblin')])
        dispatch('End all')
        results[captured + '_stop_all'] = not spells._trigger_runs

    load(
        time='00:00:10', timer_ending_seconds=2,
        timer_ending_alert='Ending ${target} {c} #{COUNTER}',
        timer_ended_alert='Ended ${target} {c} #{COUNTER}',
        timer_ending_delivery='tts', timer_ending_tts='Speak ${target}',
        timer_ended_delivery='tts', timer_ended_tts='Done ${target}',
        audio_muted=True)
    dispatch('Start Goblin A')
    dispatch('Start Goblin B', 'Bob')
    for run in spells._trigger_runs.values():
        run['deadline'] = clock[0] + 1
    notices.clear()
    spells._update_custom_trigger_timers()
    results['muted_ending'] = list(notices)
    for run in spells._trigger_runs.values():
        run['deadline'] = clock[0] - 1
    spells._update_custom_trigger_timers()
    results['muted_phases'] = list(notices)
    results['muted_audio'] = audio
    results['phase_cleanup'] = not spells._trigger_runs and not any(
        entry.get('key') for entry in app._notification_overlay.overlays['timers']._entries)
    print('PARITY_JSON=' + json.dumps(results))
finally:
    app.quit()
'''


@pytest.fixture(scope='module')
def dispatch_results():
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=False, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    return json.loads(next(line.removeprefix('PARITY_JSON=')
                           for line in completed.stdout.splitlines()
                           if line.startswith('PARITY_JSON=')))


@pytest.mark.parametrize('mode', ['restart', 'keep', 'new'])
def test_real_dispatch_isolates_timer_runs_by_character_and_server(dispatch_results, mode):
    suffix = ' #1' if mode == 'new' else ''
    assert dispatch_results[mode + '_profiles'] == [
        ['Alice', 'Blue', 'Target Third' + suffix],
        ['Alice', 'Green', 'Target First' + suffix],
        ['Bob', 'Green', 'Target Second' + suffix]]
    green = ('First' if mode == 'keep' else 'Fourth')
    expected = [
        ['Alice', 'Green', 'Target ' + green],
        ['Bob', 'Green', 'Target Second']]
    if mode == 'new':
        expected = [
            ['Alice', 'Green', 'Target First #1'],
            ['Alice', 'Green', 'Target Fourth #2'],
            ['Bob', 'Green', 'Target Second #1']]
    assert dispatch_results[mode + '_end_blue'] == expected
    assert dispatch_results[mode + '_active_keys']


def test_timer_name_restart_remains_cross_definition_within_the_same_profile(dispatch_results):
    assert dispatch_results['timer_name_owners'] == [
        ['Alice', 'Other definition', 120.0], ['Bob', 'Parity', 60.0]]


def test_cooldown_counter_and_counter_reset_are_profile_specific(dispatch_results):
    assert dispatch_results['counter_notices'] == [
        'Alice #1', 'Bob #1', 'Alice #1', 'Alice #2', 'Bob #1']


@pytest.mark.parametrize('captured', ['named', 'numeric'])
def test_early_end_correlates_original_captures_after_reload(dispatch_results, captured):
    assert dispatch_results[captured + '_end'] == [
        ['Alice', 'Green', 'Target Goblin B #2']]
    assert dispatch_results[captured + '_row_count'] == 1
    assert dispatch_results[captured + '_overlay_count'] == 1
    assert dispatch_results[captured + '_stop_all']


def test_unrelated_captured_ender_is_conservative_but_capture_free_stops_all(dispatch_results):
    assert len(dispatch_results['unrelated_end']) == 2
    assert dispatch_results['unrelated_stop_all']


def test_muted_timers_keep_original_phase_text_and_cleanup_each_profile(dispatch_results):
    assert dispatch_results['muted_ending'] == [
        'Ending Goblin A Alice #1', 'Ending Goblin B Bob #1']
    assert dispatch_results['muted_phases'] == [
        'Ending Goblin A Alice #1', 'Ending Goblin B Bob #1',
        'Ended Goblin A Alice #1', 'Ended Goblin B Bob #1']
    assert not dispatch_results['muted_audio']
    assert dispatch_results['phase_cleanup']


@pytest.mark.parametrize('capture', ['Goblin', '$2', '${other}', '{c}'])
def test_named_dollar_capture_rendering_is_a_single_pass(monkeypatch, capture):
    monkeypatch.setattr(config, 'data', {'sharing': {'player_name': 'Alice'}})
    trigger = CustomTrigger()
    trigger.counter = 3
    match = re.match(r'(?P<target>.+)\|(?P<other>.+)', capture + '|second')
    assert render_trigger_text(
        '${target} / {target} / ${1} / $1 / {c} / {COUNTER}', match, trigger
    ) == f'{capture} / {capture} / {capture} / {capture} / Alice / 3'


@pytest.mark.parametrize('pattern,text,expected', [
    (r'(?P<target>.+)', 'goblin a', True),
    (r'(?P<target>.+)', 'Goblin B', False),
    (r'(?P<other>.+)', 'Goblin A', False),
    (r'(?P<c>\w+) (?P<other>.+)', 'Alice Goblin A', False),
    (r'(?P<c>\w+)', 'Alice', True),
    (r'(?P<c>\w+)', 'Bob', False),
    (r'End(?: (?P<target>.+))?', 'End', False),
    (r'End all', 'End all', True),
])
def test_early_end_requires_shared_identity_and_resolved_optional_captures(pattern, text, expected):
    start = re.match(r'(?P<target>.+)', 'Goblin A')
    run = {'character': 'Alice', 'captures': _trigger_captures(start)}
    assert _trigger_ender_matches_run(run, re.match(pattern, text)) is expected


def test_named_captures_match_by_name_even_when_regex_group_order_changes():
    start = re.match(r'(?P<target>.+) (?P<spell>\w+)', 'Goblin A Root')
    end = re.match(r'(?P<spell>\w+) (?P<target>.+)', 'Root Goblin A')
    assert _trigger_ender_matches_run({'captures': _trigger_captures(start)}, end)


@pytest.mark.parametrize('message', [
    'Your spell is interrupted.', 'Your spell fizzles!'])
def test_capture_free_start_accepts_structural_regex_ending_groups(message):
    start = re.match(r'^You begin casting Complete Heal\.$',
                     'You begin casting Complete Heal.')
    end = re.match(r'^Your spell (is interrupted\.|fizzles!)$', message)
    assert _trigger_ender_matches_run(
        {'character': 'Alice', 'captures': _trigger_captures(start)}, end)


def test_capture_free_start_does_not_claim_unmatched_named_target():
    end = re.match(r'^End (?P<target>.+)$', 'End Goblin A')
    assert not _trigger_ender_matches_run({'character': 'Alice', 'captures': {}}, end)
