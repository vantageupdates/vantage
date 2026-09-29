import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers.spells import spell_fade_alert_phase


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import copy
import datetime
import json

from vantage.helpers import config
from vantage.helpers import application as application_module
from vantage.helpers.application import VantageApp

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
config.data['sounds']['routes']['spell_fading']['delivery'] = 'voice'

played = []
def fake_play(path, volume, *args, **kwargs):
    played.append({
        'path': path,
        'source': kwargs.get('source', ''),
        'channel': kwargs.get('channel', ''),
    })
    app.audio_started(
        kwargs.get('source', ''), path, volume, kwargs.get('channel', ''),
        kwargs.get('visual_registered', False))
    return True
application_module.play_alert = fake_play

spoken = []
def fake_speak(text, volume, **kwargs):
    spoken.append({
        'text': text,
        'source': kwargs.get('source', ''),
        'channel': kwargs.get('channel', ''),
        'dedupe_key': kwargs.get('dedupe_key', ''),
    })
    return True
application_module.speak_text = fake_speak

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

# The same row speaks once only when it reaches the final five seconds.
widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=5)
widget._update()
final_notice = app._quickbar_notice
spoken_after_final = list(spoken)
widget._update()
spoken_after_final_refresh = len(spoken)

# Sound-only routes and explicit WAV overrides deliver once at the early
# threshold and do not replay at five seconds.
config.data['sounds']['routes']['spell_fading']['delivery'] = 'sound'
played.clear()
spoken.clear()
widget._play_fade_alert(notice='Sound route early', phase='early')
widget._play_fade_alert(notice='Sound route final', phase='final')
sound_route = {'played': list(played), 'spoken': list(spoken)}
config.data['sounds']['routes']['spell_fading']['delivery'] = 'voice'
config.data['spells']['fade_sound_overrides'][
    widget.spell.name] = 'builtin:crystal-ping'
played.clear()
spoken.clear()
widget._play_fade_alert(notice='Custom WAV early', phase='early')
widget._play_fade_alert(notice='Custom WAV final', phase='final')
custom_route = {'played': list(played), 'spoken': list(spoken)}
config.data['spells']['fade_sound_overrides'].clear()

real_notify = app.notify_event
delivered = []
app.notify_event = lambda route, text, **kwargs: (
    delivered.append({'route': route, 'text': text, **kwargs}) or True)
widget._play_fade_alert(notice=widget._fading_notice(30))

# A short/restored row enters its warning window during construction.  It
# must wait until QLayout attaches the SpellTarget so the first voice names
# the actual recipient and its durable claim reaches the container.
delivered.clear()
short_spell = copy.copy(spells.spell_book['Fetter'])
short_spell.name = 'Short Ward'
short_spell.runtime_key = 'short ward'
short_spell.duration_seconds = 5
short_spell.duration = 1
spells._spell_container.add_spell(
    short_spell, datetime.datetime.now(), '__you__',
    'Spiritflux', 'P1999Green')
short_target = spells._spell_container.get_spell_target_by_name('__you__')
short_widget = short_target.spell_widget('short ward')
before_attached_refresh = len(delivered)
short_widget._update()
short_delivery = delivered[-1]
app.notify_event = real_notify

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
    'final_notice': final_notice,
    'spoken_after_final': spoken_after_final,
    'spoken_after_final_refresh': spoken_after_final_refresh,
    'sound_route': sound_route,
    'custom_route': custom_route,
    'delivered': [short_delivery],
    'before_attached_refresh': before_attached_refresh,
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
        'source': 'Spell fading · ' + first['notice'],
        'channel': 'spells',
    }]
    assert result['played_after_second_refresh'] == 1
    assert result['final_notice'].startswith('Fetter fading soon · ')
    assert result['final_notice'].endswith('5s')
    assert result['spoken_after_final'] == [{
        'text': 'Fetter fading on a crystalline devourer',
        'source': 'Spell fading · ' + result['final_notice'],
        'channel': 'spells',
        'dedupe_key': result['spoken_after_final'][0]['dedupe_key'],
    }]
    assert result['spoken_after_final'][0]['dedupe_key'].endswith('|final')
    assert result['spoken_after_final_refresh'] == 1
    assert len(result['sound_route']['played']) == 1
    assert result['sound_route']['played'][0]['path'] == 'builtin:soft-tick'
    assert result['sound_route']['spoken'] == []
    assert len(result['custom_route']['played']) == 1
    assert result['custom_route']['played'][0]['path'] == \
        'builtin:crystal-ping'
    assert result['custom_route']['spoken'] == []
    delivered = result['delivered'][0]
    assert result['before_attached_refresh'] == 0
    assert delivered['route'] == 'spell_fading'
    assert delivered['text'].startswith('Short Ward fading soon · ')
    assert delivered['voice_text'] == \
        'Short Ward fading on Spiritflux'
    assert '30s' not in delivered['voice_text']
    assert delivered['voice_dedupe_key'].startswith(
        'spell_fading|P1999Green|Spiritflux|__you__|')
    assert delivered['voice_dedupe_key'].endswith('|final')
    assert delivered.get('delivery_override') is None
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


def test_spell_fade_phase_boundaries_keep_configured_early_threshold():
    assert spell_fade_alert_phase(41, 40) == ''
    assert spell_fade_alert_phase(40, 40) == 'early'
    assert spell_fade_alert_phase(30, 40) == 'early'
    assert spell_fade_alert_phase(29, 40) == 'early'
    assert spell_fade_alert_phase(6, 40) == 'early'
    assert spell_fade_alert_phase(5, 40) == 'final'
    assert spell_fade_alert_phase(1, 40) == 'final'
    assert spell_fade_alert_phase(0, 40) == ''
