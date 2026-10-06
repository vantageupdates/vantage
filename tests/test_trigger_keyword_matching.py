"""Literal keyword matching through real parser methods, with all I/O stubbed."""

import copy
import datetime
import json
from collections import deque
from types import MethodType, SimpleNamespace

import pytest

from vantage.helpers import config
from vantage.helpers import settings as settings_module
from vantage.parsers import spells as sm
from vantage.parsers.spells import (
    CustomTrigger, Spells, compile_trigger_pattern, dynamic_timer_seconds,
    match_trigger_pattern, render_trigger_text)


def match(trigger, line, character='Alpha'):
    pattern = compile_trigger_pattern(
        trigger.text, character=character, raw_regex=trigger.regex,
        match_mode=trigger.match_mode)
    return match_trigger_pattern(
        pattern, line, match_mode=trigger.match_mode, raw_regex=trigger.regex)


@pytest.mark.parametrize('line,expected', [
    ('the tangrin', True),
    ('THE TANGRIN roars!', True),
    ('You target The Tangrin.', True),
    ("Raid says, 'the tangrin arrived.'", True),
    ('Look: the tangrin', True),
    ('the tangrinspawn', True),  # Literal substring, not a word-boundary mode.
    ('tangrin', False),
    ('the tangr', False),
    ('the  tangrin', False),
    ('a different creature roars', False),
])
def test_contains_literal_phrase_anywhere_and_case_insensitive(line, expected):
    trigger = CustomTrigger(text=' \t the tangrin \n ', match_mode='contains')
    result = match(trigger, line)
    assert bool(result) is expected
    if result:
        assert result.group().casefold() == 'the tangrin'
        assert result.groups() == () and result.groupdict() == {}


@pytest.mark.parametrize('phrase,line,expected', [
    ('{Actor}', 'prefix {ACTOR} suffix', True),
    ('{Actor}', 'prefix Tangrin suffix', False),
    ('{c}', 'prefix Alpha suffix', False),
    ('*', 'prefix * suffix', True),
    ('*', 'prefix anything suffix', False),
    ('[the]+ tangrin.*', 'prefix [THE]+ Tangrin.* suffix', True),
    ('[the]+ tangrin.*', 'the tangrin roars', False),
    ('$' + '{1}', 'prefix $' + '{1}' + ' suffix', True),
])
def test_contains_never_interprets_tokens_wildcards_or_regex(phrase, line, expected):
    trigger = CustomTrigger(text=phrase, match_mode='contains')
    assert bool(match(trigger, line)) is expected


@pytest.mark.parametrize('phrase', ['', ' ', '\n\t', None])
def test_empty_contains_phrase_never_matches(phrase):
    pattern = compile_trigger_pattern(phrase, match_mode='contains')
    for line in ('', 'the tangrin', 'anything else'):
        assert not match_trigger_pattern(pattern, line, match_mode='contains')


@pytest.mark.parametrize('mode', ['full', 'contains'])
@pytest.mark.parametrize('pattern,line,expected', [
    (r'^a (.+) roars$', 'a Tangrin roars', True),
    (r'^a (.+) roars$', 'prefix a Tangrin roars', False),
    (r'^a (.+) roars$', 'a Tangrin roars suffix', False),
    ('Tangrin', 'Tangrin suffix', True),
    ('Tangrin', 'prefix Tangrin', False),  # Retain regex .match, not .search.
])
def test_explicit_regex_retains_prior_matching_regardless_of_saved_mode(
        mode, pattern, line, expected):
    trigger = CustomTrigger(text=pattern, regex=True, match_mode=mode)
    result = match(trigger, line)
    assert bool(result) is expected
    if result and result.groups():
        assert result.group(1) == 'Tangrin'


def test_full_friendly_pattern_keeps_tokens_wildcards_and_anchors():
    trigger = CustomTrigger(text='{Actor} marks {Actor} *.', match_mode='full')
    result = match(trigger, 'Goblin marks Goblin with fire.')
    assert result.groupdict() == {'Actor': 'Goblin'}
    assert not match(trigger, 'Goblin marks Wolf with fire.')
    assert not match(trigger, 'prefix Goblin marks Goblin with fire.')
    assert not match(trigger, 'Goblin marks Goblin with fire. suffix')
    trigger.text = '{c} waits {ts}'
    result = match(trigger, 'Alpha waits 1:02:03.5')
    assert result and dynamic_timer_seconds(result) == 3723.5
    assert not match(trigger, 'Beta waits 1:02:03.5')
    trigger.runtime_character = 'Alpha'
    assert render_trigger_text('$1', result, trigger) == '1:02:03.5'


@pytest.mark.parametrize('value', [None, '', 'invalid', True, [], {}, 12])
def test_invalid_match_mode_defaults_to_full(value):
    trigger = CustomTrigger(text='the tangrin', match_mode=value)
    assert trigger.match_mode == 'full'
    assert trigger.to_list()[49] == 'full'
    assert match(trigger, 'THE TANGRIN')
    assert not match(trigger, 'prefix the tangrin suffix')


@pytest.mark.parametrize('old_length', [3, 8, 34, 46, 48, 49])
def test_appended_field_keeps_missing_legacy_modes_full(old_length):
    current = CustomTrigger(
        name='Legacy', text='the tangrin', delivery='tts', tts_text='Alert',
        audio_muted=True, match_mode='contains').to_list()
    assert len(current) == 50 and current[49] == 'contains'
    restored = CustomTrigger(*current[:old_length])
    assert restored.match_mode == 'full'
    assert len(restored.to_list()) == 50
    if old_length == 49:
        assert restored.to_list()[:49] == current[:49]
        assert restored.audio_muted is True
    assert not match(restored, 'prefix the tangrin suffix')
    assert CustomTrigger(*current).match_mode == 'contains'


def test_precise_builtin_system_alerts_remain_full_and_anchored():
    names = {
        'Target too far', 'Target out of range', 'Cannot see target',
        'No target selected', 'Spell not recovered', 'Insufficient mana',
    }
    definitions = [CustomTrigger(*row) for row in config.BASIC_ALERTS
                   if row[0] in names]
    assert {trigger.name for trigger in definitions} == names
    for trigger in definitions:
        assert trigger.match_mode == 'full' and trigger.regex is True
        line = {
            'Target too far': 'Your target is too far away, get closer!',
            'Target out of range': 'Your target is out of range, get closer!',
            'Cannot see target': "You can't see your target from here.",
            'No target selected': 'You must first select a target for this spell!',
            'Spell not recovered': "You haven't recovered yet...",
            'Insufficient mana': 'Insufficient Mana to cast this spell!',
        }[trigger.name]
        assert match(trigger, line)
        for wrapped in ('Prefix ' + line, line + ' suffix',
                        'Player says, "' + line + '"'):
            assert not match(trigger, wrapped)


@pytest.fixture
def runtime(monkeypatch):
    settings = {
        'use_custom_triggers': True, 'use_item_triggers': False,
        'custom_timers': [], 'trigger_categories': {'Runtime': True},
        'trigger_groups': {'Runtime': {'enabled': True}},
        'fade_sound_volume': 37,
    }
    monkeypatch.setattr(config, 'data', {
        'spells': settings, 'sharing': {'player_name': 'Alpha'},
        'general': {'notification_overlays': {
            'alerts': {'enabled': True, 'type': 'text'},
            'timers': {'enabled': True, 'type': 'timer'}}},
    })
    clock = [100.0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    notices, overlays, audio, clipboard, rows, removed, dismissed = (
        [], [], [], [], [], [], [])
    host = SimpleNamespace(
        _queue_quickbar_notice=lambda text, **kwargs: notices.append(text),
        show_overlay_notification=lambda *args, **kwargs:
            overlays.append((args, kwargs)),
        dismiss_overlay_timer=lambda key: dismissed.append(key))
    clipboard_stub = SimpleNamespace(setText=clipboard.append)
    monkeypatch.setattr(sm, 'QApplication', SimpleNamespace(
        instance=lambda: host, clipboard=lambda: clipboard_stub))
    monkeypatch.setattr(sm, 'play_alert',
                        lambda *args, **kwargs: audio.append(('sound', args, kwargs)))
    monkeypatch.setattr(sm, 'speak_text',
                        lambda *args, **kwargs: audio.append(('tts', args, kwargs)))
    owner = SimpleNamespace(
        _trigger_runs={}, _trigger_compile_errors={}, _custom_timers=[],
        _trigger_history=deque(maxlen=400), _active_character='Alpha',
        _active_server='Green', _current_zone='Plane', _spell_trigger=None,
        _zoning=None, _sync_character_context=lambda: None,
        _consume_charm_activity=lambda *_args: None,
        _consume_cross_log_self_landing=lambda *_args: False,
        _boat_server_name=lambda: '', _active_cast_level=lambda: 60,
        _boat_toggle=SimpleNamespace(isChecked=lambda: False),
        _spell_container=SimpleNamespace(
            add_spell=lambda *args: rows.append(args),
            end_custom_timer=lambda *args, **kwargs: removed.append((args, kwargs)),
            mark_worn_off=lambda *args, **kwargs: None),
        _custom_trigger_has_audio=Spells._custom_trigger_has_audio,
        _trigger_text_color=Spells._trigger_text_color)
    for name in (
            'parse', 'load_custom_timers', 'test_trigger_line',
            '_line_has_custom_audio', '_record_trigger_match',
            '_matching_trigger_runs', '_trigger_run_keys',
            '_start_trigger_run', '_end_trigger_run', '_show_trigger_run_overlay',
            '_deliver_custom_trigger_audio'):
        setattr(owner, name, MethodType(getattr(Spells, name), owner))
    host._parsers_dict = {'spells': owner}

    def load(**changes):
        values = dict(
            name='Keyword', text='the tangrin', match_mode='contains',
            category='Runtime', alert_text='Creature found', delivery='tts',
            tts_text='Creature found', overlay_id='alerts',
            match_cooldown_seconds=0)
        values.update(changes)
        settings['custom_timers'] = [CustomTrigger(**values).to_list()]
        owner.load_custom_timers()
        return owner._custom_timers[0][2]

    return SimpleNamespace(
        owner=owner, host=host, settings=settings, clock=clock, load=load,
        notices=notices, overlays=overlays, audio=audio, clipboard=clipboard,
        rows=rows, removed=removed, dismissed=dismissed)


@pytest.mark.parametrize('line,expected', [
    ('THE TANGRIN roars!', True),
    ('You target The Tangrin.', True),
    ('Look: the tangrin', True),
    ('a different creature roars', False),
    ('the  tangrin', False),
])
def test_real_runtime_audio_detection_and_dry_run_agree_without_preview_actions(
        runtime, line, expected):
    trigger = runtime.load(clipboard_text='/target Tangrin')
    before = copy.deepcopy(trigger.to_list())
    assert runtime.owner._line_has_custom_audio(line) is expected
    assert runtime.owner.test_trigger_line(
        '[Sun Oct 06 10:00:00 2026] ' + line, trigger.name) == int(expected)
    assert trigger.to_list() == before
    assert not runtime.owner._trigger_runs
    assert not runtime.audio and not runtime.clipboard
    assert not runtime.notices and not runtime.overlays and not runtime.rows
    preview = list(runtime.owner._trigger_history)
    assert len(preview) == int(expected)
    if expected:
        assert preview[0]['status'] == 'Test'
        assert preview[0]['line'].startswith('[Sun Oct 06')
    runtime.owner.parse(datetime.datetime.now(), line)
    assert trigger.counter == int(expected)
    assert len(runtime.audio) == int(expected)
    assert runtime.notices == (['Creature found'] if expected else [])
    assert runtime.clipboard == (['/target Tangrin'] if expected else [])
    assert len(runtime.overlays) == int(expected)


@pytest.mark.parametrize('gate', [
    'monitoring', 'individual', 'group', 'profile', 'zone', 'mute'])
def test_contains_mode_keeps_monitoring_scope_and_audio_mute_gates(runtime, gate):
    trigger = runtime.load()
    if gate == 'monitoring':
        runtime.settings['use_custom_triggers'] = False
    elif gate == 'individual':
        trigger.enabled = False
    elif gate == 'group':
        runtime.settings['trigger_groups']['Runtime']['enabled'] = False
    elif gate == 'profile':
        trigger.profile = 'Beta'
    elif gate == 'zone':
        trigger.zone = 'Other'
    else:
        trigger.audio_muted = True
    line = 'prefix THE TANGRIN suffix'
    assert runtime.owner._line_has_custom_audio(line) is False
    runtime.owner.parse(datetime.datetime.now(), line)
    assert not runtime.audio
    assert trigger.counter == (1 if gate == 'mute' else 0)
    if gate == 'mute':
        assert runtime.notices == ['Creature found']


def test_real_runtime_full_named_capture_resolves_existing_outputs(runtime):
    trigger = runtime.load(
        text='{Actor} is marked.', match_mode='full',
        alert_text='MARK {Actor}', tts_text='Marked {Actor}',
        clipboard_text='/target {Actor}')
    runtime.owner.parse(datetime.datetime.now(), 'Goblin is marked.')
    assert trigger.counter == 1
    assert runtime.notices == ['MARK Goblin']
    assert runtime.audio[0][1][0] == 'Marked Goblin'
    assert runtime.clipboard == ['/target Goblin']
    runtime.owner.parse(datetime.datetime.now(), 'prefix Goblin is marked. suffix')
    assert trigger.counter == 1


def test_contains_start_does_not_broaden_early_enders(runtime):
    trigger = runtime.load(
        text='start timer', time='00:00:10', timer_type='countdown',
        overlay_id='timers',
        end_patterns=[{'text': 'Stop timer', 'regex': False}])
    runtime.owner.parse(datetime.datetime.now(), 'prefix START TIMER suffix')
    run = runtime.owner._trigger_runs['Keyword']
    assert run['duration'] == 10.0 and run['deadline'] == 110.0
    runtime.owner.parse(datetime.datetime.now(), 'prefix Stop timer suffix')
    assert runtime.owner._trigger_runs['Keyword'] is run
    runtime.owner.parse(datetime.datetime.now(), 'STOP TIMER')
    assert not runtime.owner._trigger_runs
    assert runtime.removed[0][1]['runtime_key'] == 'Keyword'
    assert runtime.dismissed == ['Keyword']
    assert trigger.counter == 1


def test_contains_literal_timespan_token_uses_fixed_timer_not_dynamic(runtime):
    trigger = runtime.load(
        text='{ts}', time='00:00:10', timer_type='countdown',
        overlay_id='timers')
    assert runtime.owner.test_trigger_line('prefix {TS} suffix') == 1
    assert 'countdown · 10s' in runtime.owner._trigger_history[0]['output']
    runtime.owner.parse(datetime.datetime.now(), 'prefix {TS} suffix')
    assert runtime.owner._trigger_runs['Keyword']['duration'] == 10.0
    assert CustomTrigger(
        text='{ts}', time='00:00:00', timer_type='countdown',
        match_mode='contains').timer_type == 'none'
    dynamic = CustomTrigger(
        text='Wait {ts}', time='00:00:00', timer_type='countdown')
    assert dynamic.timer_type == 'countdown'
    result = match(dynamic, 'Wait 12.5')
    assert dynamic_timer_seconds(result) == 12.5


@pytest.mark.parametrize('mode,expected_version,expected_length', [
    ('full', 1, 49), ('contains', 2, 50)])
def test_native_share_round_trip_preserves_matching_mode_and_review(
        mode, expected_version, expected_length):
    from vantage.helpers.gina_import import (
        import_vantage_package_bytes, serialize_vantage_package)
    from vantage.helpers.trigger_sharing import (
        create_trigger_share_code, decode_trigger_share_code)
    trigger = CustomTrigger(
        name='Shared keyword', text='the tangrin', enabled=True,
        match_mode=mode, delivery='tts', tts_text='Creature found')
    content, warnings = serialize_vantage_package([trigger])
    assert [entry['code'] for entry in warnings] == (
        ['minimum-version'] if mode == 'contains' else [])
    assert all('1.44.127' in entry['message'] for entry in warnings)
    payload = json.loads(content)
    assert payload['version'] == expected_version
    assert len(payload['triggers'][0]['values']) == expected_length
    code = create_trigger_share_code(content)
    assert code.startswith('VT1:')
    batch = import_vantage_package_bytes(decode_trigger_share_code(code))
    assert len(batch) == 1 and batch[0].enabled is False
    assert batch[0].match_mode == mode
    assert batch[0].text == trigger.text and batch[0].tts_text == trigger.tts_text
    assert bool(match(batch[0], 'prefix THE TANGRIN suffix')) is (mode == 'contains')


@pytest.mark.parametrize('mode,phrase,line,regex,expected', [
    ('full', 'the tangrin', 'THE TANGRIN', False, True),
    ('full', 'the tangrin', 'prefix the tangrin suffix', False, False),
    ('contains', 'the tangrin', 'prefix THE TANGRIN suffix', False, True),
    ('contains', 'the tangrin', 'a different creature', False, False),
    ('contains', '{Actor}', 'Tangrin', False, False),
    ('contains', '{Actor}', 'prefix {ACTOR} suffix', False, True),
    ('full', '{c} roars', 'Alpha roars', False, True),
    ('full', '{c} roars', 'Beta roars', False, False),
    ('contains', '{c} roars', 'Alpha roars', False, False),
    ('contains', '{c} roars', 'prefix {C} ROARS suffix', False, True),
    ('contains', '^the tangrin$', 'prefix the tangrin suffix', True, False),
    ('contains', 'Tangrin', 'Tangrin suffix', True, True),
    ('contains', 'Tangrin', 'prefix Tangrin', True, False),
])
def test_detached_editor_preview_and_parser_dry_run_share_matching_contract(
        runtime, monkeypatch, mode, phrase, line, regex, expected):
    """Real preview method with detached controls; existing widget tests remain."""
    trigger = runtime.load(text=phrase, match_mode=mode, regex=regex)
    displayed = []
    result_control = SimpleNamespace(
        setVisible=lambda *_args: None,
        setPlainText=displayed.append,
        setAccessibleDescription=lambda *_args: None)
    preview = SimpleNamespace(
        _sample_toggle=SimpleNamespace(setChecked=lambda *_args: None),
        _sample_result=result_control,
        _sample_line=SimpleNamespace(
            text=lambda: '[Sun Oct 06 10:00:00 2026] ' + line,
            setFocus=lambda: None),
        _draft_trigger=lambda: CustomTrigger(*trigger.to_list()),
        _monitor_enabled=SimpleNamespace(isChecked=lambda: True),
        _category_enabled=SimpleNamespace(isChecked=lambda: True))
    monkeypatch.setattr(settings_module, 'QApplication',
                        SimpleNamespace(instance=lambda: runtime.host))
    before_config = copy.deepcopy(config.data)
    before_row = trigger.to_list()
    assert settings_module.CustomTriggerSettings._match_sample_line(preview) is expected
    assert runtime.owner.test_trigger_line(line, trigger.name) == int(expected)
    assert displayed
    if expected:
        assert 'No audio, timer, clipboard or overlay action was run' in displayed[-1]
    else:
        assert 'No actions were run.' in displayed[-1]
    assert config.data == before_config and trigger.to_list() == before_row
    assert not runtime.audio and not runtime.notices and not runtime.overlays
    assert not runtime.clipboard and not runtime.owner._trigger_runs


@pytest.mark.parametrize('active,configured,line,expected', [
    ('Alpha', 'Alpha', 'Beta roars', 0),
    ('Alpha', 'Alpha', 'ALPHA roars', 1),
    ('', 'Alpha', 'Beta roars', 0),
    ('', '', 'Beta roars', 1),
    ('Beta', 'Alpha', 'Beta roars', 1),
    ('Beta', 'Alpha', 'Alpha roars', 0),
])
def test_dry_run_captured_character_guard_matches_live_parse(
        runtime, active, configured, line, expected):
    trigger = runtime.load(text='{c} roars', match_mode='full')
    runtime.owner._active_character = active
    config.data['sharing']['player_name'] = configured
    assert runtime.owner.test_trigger_line(line, trigger.name) == expected
    assert trigger.counter == 0 and not runtime.audio
    assert not runtime.notices and not runtime.overlays and not runtime.clipboard
    runtime.owner.parse(datetime.datetime.now(), line)
    assert trigger.counter == expected
