"""Monitoring changes gate future delivery without changing timer state."""
import datetime
from types import MethodType, SimpleNamespace

import pytest

from vantage.helpers import config
from vantage.helpers.trigger_groups import set_group_enabled
from vantage.parsers import spells as sm
from vantage.parsers.spells import CustomTrigger, Spells, SpellWidget


@pytest.fixture
def runtime(monkeypatch):
    settings = {
        'use_custom_triggers': True, 'use_item_triggers': False,
        'custom_timers': [], 'trigger_categories': {'Runtime': True},
        'fade_sound_volume': 37, 'fade_sound_enabled': True,
        'fade_sound_muted': [], 'fade_sound_overrides': {},
    }
    monkeypatch.setattr(config, 'data', {
        'spells': settings, 'sharing': {'player_name': 'Alpha'},
        'general': {'notification_overlays': {
            'timers': {'enabled': True, 'type': 'timer'}}},
        'sounds': {'routes': {'spell_fading': {'delivery': 'voice'}}},
    })
    clock = [100.0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    notices, overlays, audio, dismissed, rows, removals, fades = (
        [], [], [], [], [], [], [])
    host = SimpleNamespace(
        _queue_quickbar_notice=lambda text, **kwargs: notices.append(text),
        show_overlay_notification=lambda *args, **kwargs:
            overlays.append((args, kwargs)),
        dismiss_overlay_timer=lambda key: dismissed.append(key),
    )
    monkeypatch.setattr(sm, 'QApplication', SimpleNamespace(instance=lambda: host))
    monkeypatch.setattr(sm, 'play_alert',
                        lambda *args, **kwargs: audio.append(('sound', args, kwargs)))
    monkeypatch.setattr(sm, 'speak_text',
                        lambda *args, **kwargs: audio.append(('tts', args, kwargs)))
    owner = SimpleNamespace(
        _trigger_runs={}, _trigger_compile_errors={}, _custom_timers=[],
        _active_character='Beta', _active_server='Green', _current_zone='Plane',
        _spell_trigger=None, _zoning=None,
        _sync_character_context=lambda: None,
        _consume_charm_activity=lambda *_args: None,
        _consume_cross_log_self_landing=lambda *_args: False,
        _boat_server_name=lambda: '',
        _boat_toggle=SimpleNamespace(isChecked=lambda: False),
        _spell_container=SimpleNamespace(
            add_spell=lambda *args: rows.append(args),
            end_custom_timer=lambda *args, **kwargs: removals.append((args, kwargs)),
            mark_worn_off=lambda *args, **kwargs: fades.append((args, kwargs))),
        _record_trigger_match=lambda *_args, **_kwargs: None,
        _custom_trigger_has_audio=Spells._custom_trigger_has_audio,
        _trigger_text_color=Spells._trigger_text_color,
    )
    for name in (
            '_start_trigger_run', '_trigger_run_keys', '_end_trigger_run',
            '_show_trigger_run_overlay', '_fire_trigger_stage',
            '_deliver_custom_trigger_audio', '_update_custom_trigger_timers',
            '_line_has_custom_audio', 'load_custom_timers', 'parse'):
        setattr(owner, name, MethodType(getattr(Spells, name), owner))
    host._parsers_dict = {'spells': owner}

    def start(**changes):
        values = dict(
            name='Timer', text='Begin timer', time='00:00:10',
            category='Runtime', profile='Alpha', overlay_id='timers',
            timer_type='countdown', timer_visible_seconds=4,
            timer_ending_seconds=2, alert_text='Active {c}',
            timer_ending_alert='Ending {c}', timer_ended_alert='Ended {c}',
            delivery='sound', sound_path='builtin:crystal-ping',
            timer_ending_delivery='sound',
            timer_ending_sound='builtin:crystal-ping',
            timer_ended_delivery='tts', timer_ended_tts='Ended {c}',
            end_text='Stop timer')
        values.update(changes)
        trigger = CustomTrigger(**values)
        trigger.runtime_character = 'Alpha'
        trigger.active_names = ['Timer']
        match = sm.compile_trigger_pattern(trigger.text).match('Begin timer')
        owner._start_trigger_run(
            trigger, 'Timer', 'Timer', 10.0, match, datetime.datetime.now())
        return owner._trigger_runs['Timer']

    return SimpleNamespace(
        owner=owner, host=host, settings=settings, clock=clock, start=start,
        notices=notices, overlays=overlays, audio=audio, dismissed=dismissed,
        rows=rows, removals=removals, fades=fades)


def disable(runtime, run, mode):
    trigger = run['trigger']
    if mode == 'global':
        runtime.settings['use_custom_triggers'] = False
    elif mode == 'individual':
        trigger.enabled = False
    elif mode == 'group':
        set_group_enabled(runtime.settings, 'Runtime', False)
    elif mode == 'character_group':
        set_group_enabled(runtime.settings, 'Runtime', False, 'Alpha')
    elif mode == 'definition_profile':
        trigger.profile = 'Beta'
    else:
        runtime.owner.load_custom_timers()


@pytest.mark.parametrize('mode', [
    'global', 'individual', 'group', 'character_group',
    'definition_profile', 'orphan'])
@pytest.mark.parametrize('timer_type', ['countdown', 'repeating'])
def test_monitoring_off_suppresses_future_delivery_and_keeps_timer_progress(
        runtime, mode, timer_type):
    run = runtime.start(timer_type=timer_type)
    trigger = run['trigger']
    old_row = object()
    runtime.rows.append(old_row)
    disable(runtime, run, mode)
    assert runtime.owner._deliver_custom_trigger_audio(
        trigger, 'basic', trigger.sound_path, '', False, 'Test', 'Alpha') == ''
    for stage in ('ending', 'ended'):
        runtime.owner._fire_trigger_stage(run, stage)
    runtime.owner._show_trigger_run_overlay(run)
    runtime.clock[0] = 107.0
    runtime.owner._update_custom_trigger_timers()
    assert run['visible'] is True
    assert run['deadline'] == 110.0
    assert runtime.rows == [old_row]
    runtime.clock[0] = 108.0
    runtime.owner._update_custom_trigger_timers()
    assert run['ending_fired'] is True
    assert run['deadline'] == 110.0
    runtime.clock[0] = 111.0
    runtime.owner._update_custom_trigger_timers()
    assert not runtime.notices and not runtime.overlays and not runtime.audio
    assert runtime.rows[0] is old_row
    if timer_type == 'repeating':
        assert runtime.owner._trigger_runs['Timer'] is run
        assert run['deadline'] == 121.0
        assert len(runtime.rows) == 2
    else:
        assert 'Timer' not in runtime.owner._trigger_runs


@pytest.mark.parametrize('stage', ['ending', 'ended'])
@pytest.mark.parametrize('muted', [False, True])
def test_audio_off_keeps_written_timer_stage(runtime, stage, muted):
    run = runtime.start(
        timer_ending_delivery='off', timer_ended_delivery='off',
        audio_muted=muted)
    runtime.owner._fire_trigger_stage(run, stage)
    assert runtime.notices == [f'{stage.title()} Alpha']
    assert len(runtime.overlays) == 1
    assert not runtime.audio


@pytest.mark.parametrize('mode', ['global', 'individual', 'character_group'])
def test_off_then_on_preserves_pending_timeline_and_original_character(runtime, mode):
    run = runtime.start()
    trigger = run['trigger']
    trigger.counter = 7
    snapshot = dict(run)
    disable(runtime, run, mode)
    if mode == 'character_group':
        set_group_enabled(runtime.settings, 'Runtime', True, 'Beta')
    runtime.clock[0] = 105.0
    runtime.owner._update_custom_trigger_timers()
    assert run == snapshot
    assert trigger.counter == 7
    assert not runtime.notices and not runtime.overlays and not runtime.audio
    if mode == 'global':
        runtime.settings['use_custom_triggers'] = True
    elif mode == 'individual':
        trigger.enabled = True
    else:
        set_group_enabled(runtime.settings, 'Runtime', True, 'Alpha')
        set_group_enabled(runtime.settings, 'Runtime', False, 'Beta')
    assert runtime.owner._active_character == 'Beta'
    runtime.clock[0] = 107.0
    runtime.owner._update_custom_trigger_timers()
    assert len(runtime.overlays) == 1
    assert runtime.overlays[0][1]['character'] == 'Alpha'
    assert (run['started'], run['deadline'], run['ending_text'], trigger.counter) == (
        100.0, 110.0, 'Ending Alpha', 7)
    runtime.clock[0] = 108.0
    runtime.owner._update_custom_trigger_timers()
    runtime.clock[0] = 109.0
    runtime.owner._update_custom_trigger_timers()
    assert runtime.notices == ['Ending Alpha']
    runtime.clock[0] = 110.0
    runtime.owner._update_custom_trigger_timers()
    assert runtime.notices == ['Ending Alpha', 'Ended Alpha']
    assert [event[0] for event in runtime.audio] == ['sound', 'tts']
    assert all(event[2]['character'] == 'Alpha' for event in runtime.audio)
    assert 'Timer' not in runtime.owner._trigger_runs


def test_enabling_after_off_phase_does_not_replay_consumed_phase(runtime):
    run = runtime.start()
    runtime.settings['use_custom_triggers'] = False
    runtime.clock[0] = 108.0
    runtime.owner._update_custom_trigger_timers()
    assert run['ending_fired'] is True and run['visible'] is True
    assert run['deadline'] == 110.0
    assert not runtime.notices and not runtime.overlays and not runtime.audio
    runtime.settings['use_custom_triggers'] = True
    runtime.clock[0] = 109.0
    runtime.owner._update_custom_trigger_timers()
    assert not runtime.notices and not runtime.overlays and not runtime.audio
    runtime.clock[0] = 110.0
    runtime.owner._update_custom_trigger_timers()
    assert runtime.notices == ['Ended Alpha']
    assert [event[0] for event in runtime.audio] == ['tts']


def test_reload_updates_monitoring_without_replacing_running_state(runtime):
    run = runtime.start()
    running = run['trigger']
    running.counter = 7
    snapshot = {key: value for key, value in run.items() if key != 'trigger'}
    saved = CustomTrigger(*running.to_list())
    saved.enabled, saved.category, saved.profile = False, 'Raid/Kael', 'Beta'
    saved.time = '00:09:00'
    runtime.settings['custom_timers'] = [saved.to_list()]
    runtime.owner.load_custom_timers()
    assert run['trigger'] is running
    assert (running.enabled, running.category, running.profile) == (
        False, 'Raid/Kael', 'Beta')
    assert running.counter == 7 and running.active_names == ['Timer']
    assert {key: value for key, value in run.items() if key != 'trigger'} == snapshot
    runtime.settings['custom_timers'] = []
    runtime.owner.load_custom_timers()
    assert not running.enabled
    assert runtime.owner._trigger_runs['Timer'] is run
    assert run['deadline'] == snapshot['deadline']


def test_save_reload_early_end_resolves_original_running_definition(runtime):
    run = runtime.start()
    running = run['trigger']
    runtime.settings['custom_timers'] = [running.to_list()]
    runtime.owner.load_custom_timers()
    current = runtime.owner._custom_timers[0][2]
    assert current is not running
    runtime.owner._active_character = 'Alpha'
    runtime.owner.parse(datetime.datetime.now(), 'Stop timer')
    assert 'Timer' not in runtime.owner._trigger_runs
    assert runtime.removals[0][1]['runtime_key'] == 'Timer'
    assert runtime.dismissed == ['Timer']


@pytest.mark.parametrize('mode', [
    'global', 'individual', 'group', 'character_group',
    'definition_profile', 'other_character', 'captured_character', 'zone'])
def test_early_end_does_not_cancel_disabled_or_other_character_run(runtime, mode):
    run = runtime.start()
    saved = CustomTrigger(*run['trigger'].to_list())
    runtime.owner._active_character = 'Alpha'
    text = 'Stop timer'
    if mode == 'individual':
        saved.enabled = False
    elif mode == 'definition_profile':
        saved.profile = 'Beta'
    elif mode == 'captured_character':
        saved.end_patterns = [{'text': 'Stop {c}', 'regex': False}]
        text = 'Stop Beta'
    elif mode == 'zone':
        saved.zone = 'Other zone'
    elif mode == 'other_character':
        runtime.owner._active_character = 'Beta'
    runtime.settings['custom_timers'] = [saved.to_list()]
    runtime.owner.load_custom_timers()
    if mode in ('global', 'group', 'character_group'):
        disable(runtime, run, mode)
    runtime.owner.parse(datetime.datetime.now(), text)
    assert runtime.owner._trigger_runs['Timer'] is run
    assert run['deadline'] == 110.0
    assert not runtime.removals
    assert len(runtime.fades) == 1


def test_global_off_does_not_claim_normal_buff_fade_audio(runtime):
    run = runtime.start()
    trigger = run['trigger']
    runtime.owner._active_character = 'Alpha'
    runtime.settings['custom_timers'] = [trigger.to_list()]
    runtime.owner.load_custom_timers()
    assert runtime.owner._line_has_custom_audio('Begin timer')
    runtime.settings['use_custom_triggers'] = False
    assert not runtime.owner._line_has_custom_audio('Begin timer')
    runtime.owner.parse(datetime.datetime.now(), 'Begin timer')
    assert len(runtime.fades) == 1
    assert runtime.owner._trigger_runs['Timer'] is run


@pytest.mark.parametrize('target_name,force,expected', [
    ('__custom__', False, 0), ('__custom__', True, 1), ('__you__', False, 1)])
def test_custom_fade_monitoring_gate_preserves_normal_buffs_and_explicit_tests(
        runtime, monkeypatch, target_name, force, expected):
    runtime.start()
    runtime.settings['use_custom_triggers'] = False
    target_type = type('Target', (), {})
    monkeypatch.setattr(sm, 'SpellTarget', target_type)
    target = target_type()
    target.name = target_name
    events = []
    def notify(*args, **kwargs):
        events.append((args, kwargs))
        return SimpleNamespace(state='played', delivery='voice', reason='')
    runtime.host.notify_event = notify
    widget = SimpleNamespace(
        spell=SimpleNamespace(name='Timer', runtime_key='Timer'),
        runtime_character='Alpha', runtime_server='Green',
        parentWidget=lambda: target, _warning_played=False,
        _fade_voice_text=lambda *_args: 'Timer fading',
        _fade_voice_dedupe_key=lambda *_args: 'generation',
        _queue_fading_notice=lambda text: runtime.notices.append(text))
    SpellWidget._play_fade_alert(widget, force=force)
    assert len(events) == expected
    if target_name == '__custom__' and not force:
        assert not runtime.notices
