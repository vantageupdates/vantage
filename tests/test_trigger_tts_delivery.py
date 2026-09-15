import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, Spells


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dispatches_phase_specific_tts_and_explicit_off(monkeypatch):
    config.data = {'spells': {'fade_sound_volume': 37}}
    spoken = []
    played = []
    monkeypatch.setattr(
        spells_module, 'speak_text',
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    monkeypatch.setattr(
        spells_module, 'play_alert',
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    trigger = CustomTrigger(
        delivery='tts', tts_voice='Voice A', tts_volume=81,
        tts_pitch=2, timer_ending_delivery='tts',
        timer_ending_voice='Voice B', timer_ending_volume=62,
        timer_ending_pitch=-4, timer_ended_delivery='tts',
        timer_ended_voice='Voice C', timer_ended_volume=43,
        timer_ended_pitch=8)

    for stage, message, interrupt in (
            ('basic', 'Basic message', False),
            ('ending', 'Ending message', True),
            ('ended', 'Ended message', False)):
        result = Spells._deliver_custom_trigger_audio(
            None, trigger, stage, 'builtin:danger-double', message,
            interrupt, f'Test {stage}', 'Druid', 'Green')
        assert result == 'Text-to-speech'

    assert played == []
    assert [(call[0][0], call[0][1], call[0][2]) for call in spoken] == [
        ('Basic message', 81, False),
        ('Ending message', 62, True),
        ('Ended message', 43, False),
    ]
    assert [call[1]['voice_name'] for call in spoken] == [
        'Voice A', 'Voice B', 'Voice C']
    assert [call[1]['pitch'] for call in spoken] == [2, -4, 8]
    assert all(call[1]['channel'] == 'spells' for call in spoken)

    trigger.timer_ended_delivery = 'off'
    assert Spells._deliver_custom_trigger_audio(
        None, trigger, 'ended', 'builtin:danger-double', 'Do not speak',
        False, 'Test off') == ''
    assert len(spoken) == 3


def test_explicit_sound_does_not_fall_through_to_tts(monkeypatch):
    config.data = {'spells': {'fade_sound_volume': 55}}
    spoken = []
    played = []
    monkeypatch.setattr(
        spells_module, 'speak_text',
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    monkeypatch.setattr(
        spells_module, 'play_alert',
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    trigger = CustomTrigger(
        delivery='sound', sound_path='builtin:crystal-ping',
        tts_text='Do not speak')

    result = Spells._deliver_custom_trigger_audio(
        None, trigger, 'basic', trigger.sound_path, trigger.tts_text,
        False, 'Basic', 'Druid', 'Green')

    assert result.startswith('Sound · ')
    assert spoken == []
    assert played[0][0][:3] == ('builtin:crystal-ping', 55, 1)


UI_SCRIPT = r"""
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import settings as settings_module
from vantage.helpers.settings import CustomTriggerSettings
from vantage.parsers.spells import CustomTrigger

settings_module.speech_voice_names = lambda: ['Voice A', 'Voice B']
app = VantageApp([])
dialog = CustomTriggerSettings()
trigger = CustomTrigger(
    name='Speech UI', text='Test line', time='00:01:00',
    timer_type='countdown', delivery='tts',
    tts_text='Basic speech', tts_voice='Voice B', tts_volume=74,
    tts_pitch=-2, timer_ending_delivery='sound',
    timer_ending_sound='builtin:crystal-ping',
    timer_ended_delivery='off')
dialog._display_trigger(trigger)
dialog.show()
app.processEvents()

basic_delivery, basic_sound, basic_speech = dialog._trigger_delivery_panels[0]
ending_delivery, ending_sound, ending_speech = dialog._trigger_delivery_panels[1]
ended_delivery, ended_sound, ended_speech = dialog._trigger_delivery_panels[2]
dialog._trigger_tts.clear()
status = basic_speech._speech_status
test_message = dialog._test_trigger_speech(
    dialog._trigger_tts, dialog._trigger_interrupt_speech,
    dialog._trigger_tts_voice, dialog._trigger_tts_volume,
    dialog._trigger_tts_pitch, 'Test speech', 'Basic trigger', status)

ended_delivery.setCurrentIndex(ended_delivery.findData('tts'))
app.processEvents()
result = {
    'tabs': [dialog._action_tabs.tabText(i)
             for i in range(dialog._action_tabs.count())],
    'delivery_choices': [basic_delivery.itemData(i)
                         for i in range(basic_delivery.count())],
    'basic_delivery': basic_delivery.currentData(),
    'basic_sound_enabled': basic_sound.isEnabled(),
    'basic_speech_enabled': basic_speech.isEnabled(),
    'ending_delivery': ending_delivery.currentData(),
    'ending_sound_enabled': ending_sound.isEnabled(),
    'ending_speech_enabled': ending_speech.isEnabled(),
    'ended_delivery': ended_delivery.currentData(),
    'ended_sound_enabled': ended_sound.isEnabled(),
    'ended_speech_enabled': ended_speech.isEnabled(),
    'voice': dialog._trigger_tts_voice.currentData(),
    'voice_count': dialog._trigger_tts_voice.count(),
    'volume': dialog._trigger_tts_volume.value(),
    'volume_range': [dialog._trigger_tts_volume.minimum(),
                     dialog._trigger_tts_volume.maximum()],
    'pitch': dialog._trigger_tts_pitch.value(),
    'pitch_range': [dialog._trigger_tts_pitch.minimum(),
                    dialog._trigger_tts_pitch.maximum()],
    'delivery_accessible': basic_delivery.accessibleName(),
    'voice_accessible': dialog._trigger_tts_voice.accessibleName(),
    'test_message': test_message,
    'test_status_visible': status.isVisible(),
    'test_status_accessible': status.accessibleName(),
    'basic_scroll_max': dialog._basic_action_scroll.verticalScrollBar().maximum(),
    'basic_scroll_horizontal': dialog._basic_action_scroll.horizontalScrollBar().maximum(),
    'speech_width': basic_speech.width(),
    'action_width': dialog._action_tabs.width(),
    'speech_control_rendered_heights': [
        round(control.height() * dialog.uniform_scale, 2)
        for control in (
            dialog._trigger_tts, dialog._trigger_tts_voice,
            dialog._trigger_tts_volume, dialog._trigger_tts_pitch,
            dialog._trigger_interrupt_speech, basic_speech._speech_test)],
    'sound_visible': basic_sound.isVisible(),
    'speech_visible': basic_speech.isVisible(),
    'sound_label_visible': basic_sound._delivery_label.isVisible(),
    'speech_label_visible': basic_speech._delivery_label.isVisible(),
    'sound_label_buddy': basic_sound._delivery_label.buddy()
                         is dialog._trigger_sound,
    'speech_label_buddy': basic_speech._delivery_label.buddy()
                          is dialog._trigger_tts,
}
print(json.dumps(result))
dialog.close()
app.quit()
"""


def test_trigger_editor_exposes_accessible_delivery_and_speech_controls(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', UI_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['tabs'] == [
        'Basic', 'Timer', 'Timer Ending', 'Timer Ended']
    assert result['delivery_choices'] == ['sound', 'tts', 'off']
    assert result['basic_delivery'] == 'tts'
    assert result['basic_sound_enabled'] is False
    assert result['basic_speech_enabled'] is True
    assert result['ending_delivery'] == 'sound'
    assert result['ending_sound_enabled'] is True
    assert result['ending_speech_enabled'] is False
    assert result['ended_delivery'] == 'tts'
    assert result['ended_sound_enabled'] is False
    assert result['ended_speech_enabled'] is True
    assert result['voice'] == 'Voice B'
    assert result['voice_count'] == 3
    assert result['volume'] == 74
    assert result['volume_range'] == [0, 100]
    assert result['pitch'] == -2
    assert result['pitch_range'] == [-10, 10]
    assert result['delivery_accessible'] == 'Basic trigger audio delivery'
    assert result['voice_accessible'] == 'Basic trigger Windows voice'
    assert result['test_message'].endswith('enter a message first')
    assert result['test_status_visible'] is True
    assert result['test_status_accessible'] == result['test_message']
    assert result['basic_scroll_max'] > 0
    assert result['basic_scroll_horizontal'] == 0
    assert result['speech_width'] <= result['action_width']
    assert min(result['speech_control_rendered_heights']) >= 24
    assert result['sound_visible'] is False
    assert result['speech_visible'] is True
    assert result['sound_label_visible'] is False
    assert result['speech_label_visible'] is True
    assert result['sound_label_buddy'] is True
    assert result['speech_label_buddy'] is True
