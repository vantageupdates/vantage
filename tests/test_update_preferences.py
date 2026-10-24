"""Update preferences are exercised only with disposable synthetic profiles."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('warning_seconds', [0, 30, 40, 75, 600])
def test_explicit_fade_warning_survives_settings_verification_and_reload(
        monkeypatch, tmp_path, warning_seconds):
    from vantage.helpers import config

    monkeypatch.setattr(config, 'data', {
        'spells': {'fade_warning_seconds': warning_seconds}})
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'settings.json'))
    config.verify_settings()
    config.save()
    config.load(config._filename)
    config.verify_settings()

    assert config.data['spells']['fade_warning_seconds'] == warning_seconds


def test_missing_fade_warning_keeps_current_default(monkeypatch):
    from vantage.helpers import config

    monkeypatch.setattr(config, 'data', {})
    config.verify_settings()

    assert config.data['spells']['fade_warning_seconds'] == 40


@pytest.mark.parametrize('changed_section', [
    'general', 'maps', 'quickbar', 'spells', 'timers', 'future_preferences'])
def test_full_checkpoint_rejects_preference_loss_even_with_identical_countdowns(
        monkeypatch, tmp_path, changed_section):
    from vantage.helpers import config

    snapshot = {
        'general': {'master_volume': 63},
        'maps': {'geometry': [25, 35, 337, 293], 'scale': .23},
        'quickbar': {'opacity': 71, 'show_support': False},
        'spells': {'active_timer_state': [{'deadline': 123456}],
                   'fade_warning_seconds': 30},
        'timers': {'items': [{'name': 'Synthetic timer', 'deadline': 123456}],
                   'volume': 37},
        'future_preferences': {'nested': {'custom': ['keep', 12]}},
    }
    monkeypatch.setattr(config, 'data', copy.deepcopy(snapshot))
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'settings.json'))
    config.save()
    spells = snapshot['spells']['active_timer_state']
    timers = snapshot['timers']['items']
    assert config.verify_update_checkpoint(spells, timers, snapshot)

    # Model a faulty save that retains countdowns but silently drops a setting.
    key = next(key for key in config.data[changed_section]
               if key not in ('active_timer_state', 'items'))
    config.data[changed_section].pop(key)
    config.save()

    assert config.verify_update_checkpoint(spells, timers) is True
    assert config.verify_update_checkpoint(spells, timers, snapshot) is False


def test_full_checkpoint_compares_json_representation(monkeypatch, tmp_path):
    from vantage.helpers import config

    snapshot = {'spells': {'active_timer_state': []}, 'timers': {'items': []},
                'extension': {7: ('custom', 19)}}
    monkeypatch.setattr(config, 'data', snapshot)
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'settings.json'))
    config.save()

    assert config.verify_update_checkpoint([], [], copy.deepcopy(snapshot))


@pytest.mark.parametrize('replacement', [0, 0.0])
def test_full_checkpoint_rejects_changed_preference_type(
        monkeypatch, tmp_path, replacement):
    from vantage.helpers import config

    snapshot = {'spells': {'active_timer_state': []}, 'timers': {'items': []},
                'quickbar': {'show_header': False}}
    monkeypatch.setattr(config, 'data', copy.deepcopy(snapshot))
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'settings.json'))
    config.data['quickbar']['show_header'] = replacement
    config.save()

    assert config.verify_update_checkpoint([], [], snapshot) is False


def test_app_checkpoint_refuses_preference_loss_and_resumes_live_state(
        monkeypatch, tmp_path):
    from vantage.helpers import application, config

    monkeypatch.setattr(config, 'data', {
        'spells': {'active_timer_state': []}, 'timers': {'items': []},
        'general': {'master_volume': 63}})
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(application, 'write_spell_handoff', lambda _rows: None)
    saves = []
    original_save = config.save

    def incomplete_save():
        saves.append(True)
        config.data['general']['master_volume'] = 100
        original_save()

    monkeypatch.setattr(config, 'save', incomplete_save)
    resumed = []
    spells = SimpleNamespace(
        begin_update_handoff=lambda: [],
        cancel_update_handoff=lambda: resumed.append(True))
    host = SimpleNamespace(_parsers=[], _parsers_dict={'spells': spells})

    assert application.VantageApp.checkpoint_for_update(host) is False
    assert saves == [True]
    assert resumed == [True]


# The shared fixture installs the no-network/no-audio/no-game hooks, but always
# creates a fresh profile. Restore the explicit test directory AFTER those
# hooks, then load the saved profile so the second process tests a true restart.
PROCESS_SETUP = r"""
import copy
import datetime
import json
import os
from pathlib import Path
import sys
import time

profile = Path(os.environ['VANTAGE_DATA_DIR'])
updated_from = os.environ.get('VANTAGE_UPDATED_FROM', '')
sys.path.insert(0, str(Path.cwd() / 'tests'))
from native_audit_fixture import isolate
isolate()
os.environ['VANTAGE_DATA_DIR'] = str(profile)
if updated_from:
    os.environ['VANTAGE_UPDATED_FROM'] = updated_from
profile.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.helpers.update_handoff import spell_handoff_path
from vantage.parsers.spells import Spell

config._filename = str(profile / 'vantage.config.json')

PANEL_NAMES = (
    'maps', 'spells', 'boats', 'tick', 'timers', 'vitals', 'combat',
    'random_parser', 'heals', 'market', 'opendkp', 'zones', 'quests',
    'items_notes', 'log_searcher', 'vantage_ui', 'quickbar')

PREFERENCE_KEYS = {
    'general': ('startup_window_state', 'master_volume', 'audio_muted',
                'notification_position', 'notification_overlays',
                'table_column_widths', 'reduce_motion'),
    'quickbar': ('orientation', 'show_header', 'show_server_tick',
                 'show_notification_ticker', 'show_support', 'show_zones'),
    'maps': ('scale', 'last_zone', 'auto_follow', 'show_grid', 'show_poi',
             'show_mouse_location', 'show_location_hud', 'use_z_layers',
             'line_width', 'color'),
    'spells': ('fade_warning_seconds', 'fade_voice_warning_seconds',
               'fade_sound_volume', 'fade_sound_path', 'fade_sound_overrides',
               'fade_sound_muted', 'sounds_when_hidden', 'audio_profiles',
               'custom_timers', 'trigger_categories'),
    'timers': ('volume', 'sounds_when_hidden', 'auto_from_log', 'compact',
               'instances', 'view_zone', 'watch_timer_ids', 'keyword_rules'),
    'sounds': ('starting_delivery', 'routes'),
}

def preferences():
    result = {
        section: {key: copy.deepcopy(config.data[section][key]) for key in keys}
        for section, keys in PREFERENCE_KEYS.items()}
    result['panels'] = {
        name: {key: copy.deepcopy(config.data[name][key]) for key in (
            'geometry', 'opacity', 'auto_hide_menu', 'always_on_top',
            'frameless', 'collapsed')}
        for name in PANEL_NAMES}
    result['extension'] = copy.deepcopy(config.data['future_preferences'])
    return result

def rendered(app):
    return {
        'panels': {
            name: [panel.x(), panel.y(), panel.width(), panel.height()]
            for name in PANEL_NAMES
            for panel in (app._parsers_dict[name],)},
        'opacities': {
            name: app._parsers_dict[name]._window_opacity
            for name in PANEL_NAMES},
        'overlays': {
            key: [overlay.x(), overlay.y(), overlay.width(), overlay.height()]
            for key, overlay in app._notification_overlay.overlays.items()},
        'map_scale': app._parsers_dict['maps']._map._scale,
        'map_zone': app._parsers_dict['maps']._map._data.zone,
    }
"""


SAVE_PROCESS = PROCESS_SETUP + r"""
config.data['general'].update({
    'startup_window_state': 'normal', 'master_volume': 63,
    'notification_position': 'bottom_left',
    'table_column_widths': {'synthetic-table': [77, 123, 211]},
    'notification_overlays': {
        'custom_update_overlay': {
            'label': 'Synthetic update overlay', 'type': 'timer',
            'geometry': [35, 42, 381, 123], 'font_size': 13,
            'background_opacity': 81, 'faded_background_opacity': 35,
            'contrast_opacity_version': 1, 'show_timer_bar': True,
            'default_position': 'bottom_left', 'text_fade_seconds': 23}}})
config.data['maps'].update({
    'last_zone': 'east commonlands', 'scale': .23,
    'auto_follow': False, 'show_grid': False, 'show_poi': False,
    'show_mouse_location': False, 'show_location_hud': False,
    'use_z_layers': True, 'line_width': 3, 'color': '#123456'})
config.data['quickbar'].update({
    'show_header': False, 'show_server_tick': False,
    'show_notification_ticker': False, 'show_support': False,
    'show_zones': False})
config.data['spells'].update({
    'fade_warning_seconds': 30, 'fade_voice_warning_seconds': 11,
    'fade_sound_volume': 37, 'fade_sound_path': 'builtin:crystal-ping',
    'fade_sound_overrides': {'Synthetic ward': 'builtin:soft-tick'},
    'fade_sound_muted': ['Synthetic silence'], 'sounds_when_hidden': False,
    'audio_profiles': {'auditcleric@p1999green': {
        'character': 'AuditCleric', 'server': 'P1999Green',
        'voice_name': 'Synthetic voice', 'voice_speed': -2, 'volume': 43}}})
config.data['timers'].update({
    'volume': 29, 'sounds_when_hidden': False, 'auto_from_log': False,
    'compact': True, 'view_zone': 'East Commonlands'})
config.data['sounds']['starting_delivery'] = 'voice'
config.data['sounds']['routes']['spell_fading'].update({
    'enabled': False, 'volume': 37, 'sound': 'builtin:crystal-ping'})
config.data['future_preferences'] = {
    'unknown_nested_key': {'value': ['retained', 23, False]}}
for index, name in enumerate(PANEL_NAMES):
    config.data[name].update({
        'geometry': [20 + index * 7, 25 + index * 5, 390, 280],
        'opacity': 61 + index, 'auto_hide_menu': bool(index % 2),
        'always_on_top': False, 'collapsed': False})
config.verify_settings()
config.save()

app = VantageApp([])
QTest.qWait(600)
# Named replica presets store their resulting geometry. Exercise the same
# operation used by the panel context menu before the update checkpoint.
app._parsers_dict['spells']._set_replica_scale(.75)
app._parsers_dict['timers']._set_replica_scale(.50)
app._parsers_dict['quickbar']._set_replica_scale(.75)

container = app._parsers_dict['spells']._spell_container
buff = Spell(
    name='Synthetic ward', runtime_key='synthetic-ward',
    duration_seconds=7200, duration=1200, duration_formula=0, type=1)
container.add_spell(
    buff, datetime.datetime.now(), '__you__', 'AuditCleric', 'P1999Green')
timer = SpawnTimerState(
    name='Synthetic camp', timer_id='syntheticcamp',
    respawn_seconds=5400, kill_seconds=47, warning_seconds=19,
    zone='East Commonlands', color='#5A80B0', volume=27,
    sound_path='builtin:soft-tick', delivery='off')
timer.start()
app._parsers_dict['timers']._register_timer(timer)
QTest.qWait(600)
expected_rendered = rendered(app)
assert expected_rendered['map_scale'] == .23
assert app.checkpoint_for_update()
expected = preferences()
before_shutdown = copy.deepcopy(config.data)
QTimer.singleShot(0, app.exit_for_verified_update)
QTimer.singleShot(5000, app.quit)
app.exec()
persisted = json.loads(Path(config._filename).read_text(encoding='utf-8'))
print(json.dumps({
    'expected': expected, 'after_shutdown': preferences(),
    'rendered': expected_rendered,
    'snapshot': before_shutdown, 'persisted': persisted,
    'handoff_exists': spell_handoff_path().exists(),
}))
"""


RESTORE_PROCESS = PROCESS_SETUP + r"""
config.load(config._filename)
config.verify_settings()
app = VantageApp([])
QTest.qWait(700)
rows = app._parsers_dict['spells']._spell_container.snapshot_runtime_state()
timer_rows = [timer.to_dict()
              for timer in app._parsers_dict['timers']._states.values()]
print(json.dumps({
    'preferences': preferences(), 'rendered': rendered(app),
    'spells': rows, 'timers': timer_rows,
    'handoff_consumed': not spell_handoff_path().exists(),
    'now': time.time(),
}))
app.quit()
"""


def _run(script, profile, *, updated_from=''):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(profile)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for key in ('VANTAGE_UPDATED_FROM', 'VANTAGE_OPEN_UI_AFTER_UPDATE',
                'VANTAGE_UPDATE_ERROR'):
        env.pop(key, None)
    if updated_from:
        env['VANTAGE_UPDATED_FROM'] = updated_from
    result = subprocess.run(
        [sys.executable, '-B', '-c', script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _assert_same_tree(actual, expected, path='preferences'):
    """Report only the differing preference instead of a complete profile."""
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            _assert_same_tree(actual[key], value, f'{path}.{key}')
    else:
        assert actual == expected, path


def test_update_shutdown_and_fresh_process_keep_custom_preferences_and_timers(
        tmp_path):
    profile = tmp_path / 'synthetic-profile'
    saved = _run(SAVE_PROCESS, profile)
    restored = _run(RESTORE_PROCESS, profile, updated_from='1.44.140')

    assert saved['handoff_exists'] is True
    _assert_same_tree(saved['after_shutdown'], saved['expected'])
    _assert_same_tree(restored['preferences'], saved['expected'])
    _assert_same_tree(restored['rendered'], saved['rendered'], 'rendered')
    assert restored['handoff_consumed'] is True
    assert len(restored['spells']) == 1
    assert restored['spells'][0]['spell']['name'] == 'Synthetic ward'
    # Spell widgets restore a whole-second remaining duration, so their next
    # snapshot can round the absolute deadline up by less than one second.
    assert restored['spells'][0]['deadline'] == pytest.approx(
        saved['snapshot']['spells']['active_timer_state'][0]['deadline'],
        abs=1.1, rel=0)
    assert 0 < restored['spells'][0]['deadline'] - restored['now'] < 7200
    assert restored['timers'] == saved['snapshot']['timers']['items']
    assert 0 < restored['timers'][0]['deadline'] - restored['now'] < 5400
    # The orderly shutdown journal may advance; the remainder of the complete
    # durable configuration must still match the verified update snapshot.
    saved['snapshot']['timers'].pop('last_session_closed_at', None)
    saved['persisted']['timers'].pop('last_session_closed_at', None)
    _assert_same_tree(saved['persisted'], saved['snapshot'], 'checkpoint')
