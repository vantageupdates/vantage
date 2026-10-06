"""Mute persistence and user-selected fading stops, with isolated Qt dialogs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers import config
from vantage.parsers.spells import CustomTrigger, spell_fade_alert_phase

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('stage', ['basic', 'ending', 'ended'])
@pytest.mark.parametrize('mode', ['sound', 'tts', 'off', 'legacy'])
def test_mute_preserves_all_phase_choices(stage, mode):
    trigger = CustomTrigger(
        name='Mob is casting', sound_path='builtin:crystal-ping',
        tts_text='Casting', delivery=mode,
        timer_ending_sound='portable:sounds/custom.wav',
        timer_ending_tts='Soon', timer_ending_delivery=mode,
        timer_ended_tts='Done', timer_ended_delivery=mode)
    expected = trigger.audio_delivery(stage)
    original = trigger.to_list()
    trigger.audio_muted = True
    restored = CustomTrigger(*trigger.to_list())
    assert restored.enabled
    assert restored.audio_delivery(stage) == 'off'
    assert restored.configured_audio_delivery(stage) == expected
    assert restored.to_list()[:-1] == original[:-1]
    restored.audio_muted = False
    assert restored.to_list() == original
    assert restored.audio_delivery(stage) == expected


@pytest.mark.parametrize('stop', [1, 5, 10, 25, 60, 600])
def test_custom_spoken_fading_stop(stop):
    assert spell_fade_alert_phase(stop + 0.1, 600, stop) == (
        'early' if stop < 600 else '')
    assert spell_fade_alert_phase(stop, 600, stop) == 'final'
    assert spell_fade_alert_phase(stop - 0.1, 600, stop) == 'final'
    assert spell_fade_alert_phase(0, 600, stop) == ''
    assert spell_fade_alert_phase(stop + 1, 0, stop) == ''


def test_spoken_stop_default_and_validation():
    original = copy.deepcopy(config.data)
    try:
        config.data = {}
        config.verify_settings()
        assert config.data['spells']['fade_voice_warning_seconds'] == 5
        for raw, expected in [(25, 25), ('10', 10), (0, 1), (999, 600),
                              ('invalid', 5)]:
            config.data['spells']['fade_voice_warning_seconds'] = raw
            config.verify_settings()
            assert config.data['spells']['fade_voice_warning_seconds'] == expected
    finally:
        config.data = original


SCRIPT = r'''
import datetime
import json
import os
from pathlib import Path
from PySide6.QtWidgets import QPushButton
from vantage.helpers import config, settings as sm, application as am
from vantage.helpers.application import VantageApp
from vantage.helpers.settings import SettingsWindow, CustomTriggerSettings
from vantage.parsers.spells import CustomTrigger, Spells, Spell, compile_trigger_pattern
from types import SimpleNamespace

app = VantageApp([])
updates = []
app._signals['settings'].spell_triggers_updated.connect(lambda: updates.append(1))
def stored(name):
    return next(CustomTrigger(*row) for row in config.data['spells']['custom_timers']
                if row[0] == name)
dialog = CustomTriggerSettings()
dialog._load_from_config(selected_name='Mob is casting')
assert dialog._current_trigger == 'Mob is casting'
original = stored('Mob is casting')
parser = app._parsers_dict['spells']
running = CustomTrigger(*original.to_list())
running.timer_type = 'stopwatch'
running.timer_ending_delivery = running.timer_ended_delivery = 'tts'
parser._trigger_runs['mute-running'] = {'trigger': running, 'deadline': 12345}
dialog._trigger_audio_muted.setChecked(True)
dialog._save_trigger()
muted = stored('Mob is casting')
assert muted.audio_muted and muted.enabled
assert running.audio_muted and running.audio_delivery('ending') == 'off'
assert running.audio_delivery('ended') == 'off'
assert parser._trigger_runs['mute-running']['deadline'] == 12345
generic_audio, generic_events = [], []
am.play_alert = lambda *a, **k: generic_audio.append('beep') or True
am.speak_text = lambda *a, **k: generic_audio.append('voice') or True
config.data['general']['audio_muted'] = False
config.data['general']['master_volume'] = 100
config.data['sounds']['routes']['spell_fading']['delivery'] = 'voice'
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['sounds_when_hidden'] = True
parser._spell_container.add_spell(
    Spell(name='Owned trigger timer', runtime_key='mute-running', duration=10,
          duration_formula=11, spell_icon=14), datetime.datetime.now(), '__custom__')
timer_row = parser._spell_container.get_spell_target_by_name('__custom__').spell_widget('mute-running')
timer_row._play_fade_alert(phase='early')
timer_row._play_fade_alert(phase='final')
assert not generic_audio
parser._spell_container.add_spell(
    Spell(name='Restored named timer', runtime_key='Mob is casting', duration=10,
          duration_formula=11, spell_icon=14), datetime.datetime.now(), '__custom__')
restored_row = parser._spell_container.get_spell_target_by_name('__custom__').spell_widget('Mob is casting')
restored_row._play_fade_alert(phase='final')
assert not generic_audio
parser._spell_container.end_custom_timer('Restored named timer', runtime_key='Mob is casting')
assert muted.sound_path == original.sound_path
assert muted.tts_text == original.tts_text
assert muted.configured_audio_delivery() == original.configured_audio_delivery()
assert dialog._trigger_audio_muted.isChecked()
assert dialog._trigger_delivery.currentData() == original.configured_audio_delivery()
runtime = SimpleNamespace(_active_character='Spiritflux', _current_zone='',
    _custom_trigger_has_audio=Spells._custom_trigger_has_audio,
    _custom_timers=[(compile_trigger_pattern(muted.text, raw_regex=muted.regex), [], muted)])
assert not Spells._line_has_custom_audio(runtime, 'a goblin begins to cast a spell.')
audio, notices = [], []
sm.play_alert = lambda *a, **k: audio.append('sound') or True
sm.speak_text = lambda *a, **k: audio.append('speech') or True
app._queue_quickbar_notice = lambda *a, **k: notices.append(a)
dialog._announce_trigger_test = lambda text: text
assert 'muted' in dialog._test_trigger_action()
assert notices and not audio
assert 'muted' in dialog._test_trigger_sound(dialog._trigger_sound, 'Test')
assert not audio

capture = os.environ.get('VANTAGE_CONTROL_SCREENSHOTS')
if capture:
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(Path(capture) / 'trigger-mute.png'))
    dialog.close()
dialog._trigger_audio_muted.setChecked(False)
dialog._save_trigger()
assert not stored('Mob is casting').audio_muted
assert stored('Mob is casting').sound_path == original.sound_path
assert stored('Mob is casting').tts_text == original.tts_text
assert stored('Mob is casting').audio_delivery() == original.audio_delivery()
assert not running.audio_muted
timer_row._play_fade_alert(phase='final')
assert generic_audio == ['voice']
parser._spell_container.end_custom_timer('Owned trigger timer', runtime_key='mute-running')
parser._trigger_runs.pop('mute-running')
# Explicit Off is persisted; it does not restore the default WAV or legacy TTS.
dialog._trigger_delivery.setCurrentIndex(dialog._trigger_delivery.findData('off'))
dialog._save_trigger()
assert stored('Mob is casting').audio_delivery() == 'off'

# Sounds edits apply in Sounds, locate the trigger by name after list reordering,
# and do not overwrite current settings when a stale dialog has no dirty edit.
test = CustomTrigger(name='Auction custom', text='WTS', sound_path='builtin:crystal-ping',
                     tts_text='Should not fall through', delivery='legacy')
config.data['spells']['custom_timers'].append(test.to_list())
sounds = SettingsWindow('Sounds')
combo = next(combo for _, field, combo in sounds._trigger_sound_routes
             if combo._trigger_name == test.name and field == 4)
combo.setCurrentIndex(combo.findData(''))
config.data['spells']['custom_timers'].reverse()
mute = dict(sounds._trigger_audio_mutes)['Mob is casting']
mute.setChecked(True)
mob_combo = next(combo for _, field, combo in sounds._trigger_sound_routes
                 if combo._trigger_name == 'Mob is casting' and field == 4)
buttons = [route['test'] for route in sounds._trigger_audio_routes
           if route['name'] == 'Mob is casting' and route['stage'] == 'basic'
           and route['test'].accessibleName().startswith('Test Mob is casting')]
assert buttons
buttons[0].click()
assert not audio
for key, delivery, _ in sounds._notification_route_widgets:
    if key in ('market_sale', 'opendkp_auction'):
        assert delivery.findData('off') >= 0
        delivery.setCurrentIndex(delivery.findData('off'))
sounds._save()
assert stored(test.name).sound_path == ''
assert stored(test.name).audio_delivery() == 'off'
assert stored('Mob is casting').audio_muted
assert stored('Mob is casting').delivery == 'off'
stale = SettingsWindow('Sounds')
row = next(row for row in config.data['spells']['custom_timers'] if row[0] == test.name)
new = CustomTrigger(*row)
new.sound_path = 'portable:sounds/custom.wav'
new.delivery = 'tts'
row[:] = new.to_list()
stale._save()
assert stored(test.name).delivery == 'tts'
assert stored(test.name).sound_path == 'portable:sounds/custom.wav'

settings = SettingsWindow('Buffs & Triggers')
settings.fade_warning_seconds.setValue(40)
settings.fade_voice_warning_seconds.setValue(15)
settings._save()
filename = config._filename
config.load(filename)
config.verify_settings()
assert stored('Mob is casting').audio_muted
assert config.data['sounds']['routes']['market_sale']['delivery'] == 'off'
assert config.data['sounds']['routes']['opendkp_auction']['delivery'] == 'off'
assert config.data['spells']['fade_voice_warning_seconds'] == 15
reopened = SettingsWindow('Buffs & Triggers')
assert reopened.fade_voice_warning_seconds.value() == 15
assert reopened.fade_voice_warning_seconds.accessibleName() == 'Speak before fading'
if capture:
    reopened.show()
    app.processEvents()
    reopened._widget_stack.currentWidget().ensureWidgetVisible(
        reopened.fade_voice_warning_seconds, 30, 100)
    app.processEvents()
    reopened.grab().save(str(Path(capture) / 'fading-stops.png'))
    reopened.close()

# Actual attached spell row: speech at the chosen stop, not at the old 5s;
# repeated refresh does not replay it, and auction Off still keeps its text.
played, spoken, visual = [], [], []
am.play_alert = lambda *a, **k: played.append(a) or True
am.speak_text = lambda *a, **k: spoken.append(a) or True
app._queue_quickbar_notice = lambda *a, **k: visual.append(a)
config.data['general']['audio_muted'] = False
config.data['general']['master_volume'] = 100
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['sounds_when_hidden'] = True
config.data['sounds']['routes']['spell_fading']['delivery'] = 'voice'
parser = app._parsers_dict['spells']
parser._spell_container.add_spell(parser.spell_book['Fetter'], datetime.datetime.now(),
                                'a custom stop mob', 'Spiritflux', 'P1999Green')
widget = parser._spell_container.get_spell_target_by_name('a custom stop mob').spell_widget('fetter')
widget._warning_played = widget._final_warning_played = False
widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=16)
widget._update()
assert len(played) == 1 and not spoken
widget.end_time = datetime.datetime.now() + datetime.timedelta(seconds=15)
widget._update()
widget._update()
assert len(spoken) == 1 and len(played) == 1
assert 'Fetter fading' in spoken[0][0]
app.notify_event('market_sale', 'Jade Mace for sale by Example', overlay=False)
app.notify_event('opendkp_auction', 'Jade Mace auction', overlay=False)
assert len(spoken) == 1 and len(played) == 1
assert any('Jade Mace' in str(row) for row in visual)
assert len(updates) >= 4
print(json.dumps({'mute_saved': True, 'auction_off': True, 'spoken_stop': 15,
                  'speech_once': len(spoken), 'live_refreshes': len(updates)}), flush=True)
app.quit()
'''


def test_dialog_save_reopen_and_live_delivery(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', QT_ACCESSIBILITY='0',
               PYTHONPATH=str(ROOT / 'src'), VANTAGE_DATA_DIR=str(tmp_path / 'profile'))
    completed = subprocess.run([sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['speech_once'] == 1
    assert result['spoken_stop'] == 15
