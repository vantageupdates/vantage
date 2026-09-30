import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import copy
import datetime
import json

from vantage.helpers import config
from vantage.helpers import application as application_module
from vantage.helpers.application import VantageApp
from vantage.helpers.settings import SettingsWindow

config.data['general']['startup_window_state'] = 'normal'
config.data['general']['audio_muted'] = False
config.data['general']['master_volume'] = 100
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['fade_sound_path'] = 'builtin:soft-tick'
config.data['spells']['fade_sound_muted'] = []
config.data['spells']['fade_warning_seconds'] = 40
app = VantageApp([])
spells = app._parsers_dict['spells']
spells._toggled = True
spells.show()
app.processEvents()

played = []
spoken = []
events = []

def fake_play(path, volume, *args, **kwargs):
    played.append({
        'path': path,
        'source': kwargs.get('source', ''),
        'channel': kwargs.get('channel', ''),
    })
    return True

def fake_speak(text, volume, **kwargs):
    spoken.append({
        'text': text,
        'source': kwargs.get('source', ''),
        'channel': kwargs.get('channel', ''),
        'dedupe_key': kwargs.get('dedupe_key', ''),
    })
    return True

application_module.play_alert = fake_play
application_module.speak_text = fake_speak
real_notify = app.notify_event

def recording_notify(route, text, **kwargs):
    events.append({
        'route': route,
        'text': text,
        'delivery_override': kwargs.get('delivery_override'),
        'sound_override': kwargs.get('sound_override'),
        'voice_text': kwargs.get('voice_text'),
        'dedupe_key': kwargs.get('voice_dedupe_key'),
    })
    return real_notify(route, text, **kwargs)

app.notify_event = recording_notify

def scenario(name, initial_delivery, final_delivery=None, override='',
             final_tick=False, muted=False, master_volume=100):
    config.data['general']['audio_muted'] = bool(muted)
    config.data['general']['master_volume'] = int(master_volume)
    for route in ('spell_fading', 'spell_worn_off'):
        config.data['sounds']['routes'][route]['delivery'] = initial_delivery
    config.data['spells']['fade_sound_overrides'] = (
        {name: override} if override else {})
    spell = copy.copy(spells.spell_book['Fetter'])
    spell.name = name
    spell.runtime_key = name.casefold()
    target_name = 'a fade test target ' + name.casefold()
    spells._spell_container.add_spell(
        spell, datetime.datetime.now(), target_name,
        'Spiritflux', 'P1999Green')
    target = spells._spell_container.get_spell_target_by_name(target_name)
    widget = target.spell_widget(name.casefold())
    widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=29)
    widget._warning_played = False
    widget._final_warning_played = False
    played.clear()
    spoken.clear()
    events.clear()

    widget._update()
    if final_delivery is not None:
        for route in ('spell_fading', 'spell_worn_off'):
            config.data['sounds']['routes'][route]['delivery'] = final_delivery
    if final_tick:
        widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=5)
        widget._update()
    widget.mark_faded(datetime.datetime.now(), play_sound=True)
    return {
        'played': list(played),
        'spoken': list(spoken),
        'events': list(events),
        'early_claimed': widget._warning_played,
        'final_claimed': widget._final_warning_played,
    }

results = {
    'voice': scenario('Voice Ward', 'voice'),
    'sound': scenario('Sound Ward', 'sound'),
    'custom': scenario(
        'Custom Ward', 'voice', override='builtin:crystal-ping'),
    'off': scenario('Off Ward', 'off'),
    'final_then_worn': scenario('Final Ward', 'voice', final_tick=True),
    'voice_to_sound': scenario('Voice To Sound', 'voice', 'sound'),
    'voice_to_off': scenario('Voice To Off', 'voice', 'off'),
    'sound_to_voice': scenario('Sound To Voice', 'sound', 'voice'),
    'muted': scenario('Muted Ward', 'voice', muted=True),
    'zero_volume': scenario(
        'Zero Volume Ward', 'voice', master_volume=0),
}
settings_window = SettingsWindow('Buffs & Triggers')
fade_enabled = settings_window.fade_alerts_enabled
fade_warning = settings_window.fade_warning_seconds
results['settings'] = {
    'enabled_name': fade_enabled.accessibleName(),
    'enabled_description': fade_enabled.accessibleDescription(),
    'warning_name': fade_warning.accessibleName(),
    'warning_description': fade_warning.accessibleDescription(),
}
print(json.dumps(results))
settings_window.close()
app.quit()
"""


def test_spell_fade_two_phase_delivery_matrix_and_worn_off_claims(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    voice = result['voice']
    assert [item['path'] for item in voice['played']] == [
        'builtin:soft-tick']
    assert [item['text'] for item in voice['spoken']] == [
        'Voice Ward worn off on a fade test target voice ward']
    assert [item['route'] for item in voice['events']] == [
        'spell_fading', 'spell_worn_off']
    assert voice['events'][0]['text'].startswith(
        'Voice Ward fading soon · A Fade Test Target Voice Ward · 29s')
    assert voice['events'][1]['text'] == (
        'Voice Ward worn off · A Fade Test Target Voice Ward')
    assert voice['early_claimed'] is True
    assert voice['final_claimed'] is True

    assert [item['path'] for item in result['sound']['played']] == [
        'builtin:soft-tick']
    assert result['sound']['spoken'] == []
    assert [item['path'] for item in result['custom']['played']] == [
        'builtin:crystal-ping']
    assert result['custom']['spoken'] == []
    assert result['off']['played'] == []
    assert result['off']['spoken'] == []

    final_then_worn = result['final_then_worn']
    assert [item['path'] for item in final_then_worn['played']] == [
        'builtin:soft-tick']
    assert [item['text'] for item in final_then_worn['spoken']] == [
        'Final Ward fading on a fade test target final ward']
    assert [item['route'] for item in final_then_worn['events']] == [
        'spell_fading', 'spell_fading']
    assert final_then_worn['events'][-1]['text'].endswith('· 5s')

    assert result['voice_to_sound']['spoken'] == []
    assert result['voice_to_off']['spoken'] == []
    assert [item['text'] for item in result['sound_to_voice']['spoken']] == [
        'Sound To Voice worn off on a fade test target sound to voice']
    for blocked in ('muted', 'zero_volume'):
        assert result[blocked]['played'] == []
        assert result[blocked]['spoken'] == []
        assert [item['route'] for item in result[blocked]['events']] == [
            'spell_fading', 'spell_worn_off']
    settings = result['settings']
    assert settings['enabled_name'] == 'Enable fading alerts'
    assert settings['enabled_description'].startswith(
        'At the configured warning time, play one short sound cue')
    assert settings['warning_name'] == 'Warn before fading'
    assert 'early sound cue begin' in settings['warning_description']
    assert 'speech uses the separate spoken stop' in \
        settings['warning_description']
