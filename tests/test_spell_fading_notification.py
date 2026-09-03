import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers import spells as spells_module

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
spells = app._parsers_dict['spells']
spells.show()
app.processEvents()
config.data['general']['audio_muted'] = False
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['fade_sound_path'] = 'builtin:soft-tick'
config.data['spells']['fade_sound_overrides'] = {}
config.data['spells']['fade_sound_muted'] = []
config.data['spells']['fade_warning_seconds'] = 40

played = []
def fake_play(path, volume, *args, **kwargs):
    played.append({
        'path': path,
        'source': kwargs.get('source', ''),
        'channel': kwargs.get('channel', ''),
    })
    app.audio_started(
        kwargs.get('source', ''), path, volume, kwargs.get('channel', ''))
    return True
spells_module.play_alert = fake_play

now = datetime.datetime.now()
spells._spell_container.add_spell(
    spells.spell_book['Fetter'], now, 'a crystalline devourer',
    'Mindflux', 'Green')
target = spells._spell_container.get_spell_target_by_name(
    'a crystalline devourer')
widget = target.spell_widget('fetter')
widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=30)
widget._warning_played = False
played.clear()
widget._update()
first = {
    'notice': app._quickbar_notice,
    'played': list(played),
    'warning_played': widget._warning_played,
}
widget._update()
played_after_second_refresh = len(played)

# The visual warning remains available even when fading audio is disabled.
config.data['spells']['fade_sound_enabled'] = False
spells._spell_container.add_spell(
    spells.spell_book['See Invisible'], now, '__you__',
    'Mindflux', 'Green')
self_target = spells._spell_container.get_spell_target_by_name('__you__')
self_widget = self_target.spell_widget('see invisible')
self_widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=25)
self_widget._warning_played = False
self_widget._update()
silent = {
    'notice': app._quickbar_notice,
    'played_count': len(played),
    'warning_played': self_widget._warning_played,
}

print(json.dumps({
    'first': first,
    'played_after_second_refresh': played_after_second_refresh,
    'silent': silent,
}))
app.quit()
"""


def test_fading_window_clicks_once_and_names_spell_target_and_time(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    first = result['first']
    assert first['notice'].startswith('Fetter fading soon · ')
    assert 'Crystalline Devourer' in first['notice']
    assert first['notice'].endswith('30s')
    assert first['warning_played'] is True
    assert first['played'] == [{
        'path': 'builtin:soft-tick',
        'source': first['notice'],
        'channel': 'spells',
    }]
    assert result['played_after_second_refresh'] == 1
    assert result['silent']['notice'].startswith(
        'See Invisible fading soon')
    assert result['silent']['played_count'] == 1
    assert result['silent']['warning_played'] is True


def test_former_default_fading_ping_migrates_to_short_click():
    original = copy.deepcopy(config.data)
    try:
        config.data = {
            'spells': {'fade_sound_path': 'builtin:crystal-ping'}}
        config.verify_settings()
        assert config.data['spells']['fade_sound_path'] == 'builtin:soft-tick'
        assert config.data['spells']['fade_click_version'] == 1

        config.data = {'spells': {
            'fade_sound_path': 'portable:sounds/my-warning.wav',
            'fade_click_version': 0,
        }}
        config.verify_settings()
        assert config.data['spells']['fade_sound_path'] == (
            'portable:sounds/my-warning.wav')
    finally:
        config.data = original
