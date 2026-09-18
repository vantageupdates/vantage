import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
import os
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from vantage.helpers import config
from vantage.helpers import settings as settings_module
from vantage.helpers.settings import (
    CustomTriggerSettings, SettingsSignals, TRIGGER_ITEM_ID,
    TRIGGER_ITEM_KIND)
from vantage.parsers.spells import (
    CustomTrigger, Spells, compile_trigger_pattern)

app = QApplication([])
app._signals = {'settings': SettingsSignals()}
profile = Path(os.environ['VANTAGE_DATA_DIR'])
profile.mkdir(parents=True, exist_ok=True)
config._filename = str(profile / 'config.json')
config.verify_settings()
dialog = CustomTriggerSettings()

def find_mob_item():
    iterator = QTreeWidgetItemIterator(dialog._triggers)
    while iterator.value():
        item = iterator.value()
        if (item.data(0, TRIGGER_ITEM_KIND) == 'trigger' and
                item.data(0, TRIGGER_ITEM_ID) == 'Mob is casting'):
            return item
        iterator += 1
    raise AssertionError('Mob is casting tree row missing')

item = find_mob_item()
dialog._triggers.setCurrentItem(item)
dialog._activated()
original = dialog._custom_triggers['Mob is casting']
original_delivery = original.delivery
original_sound = original.sound_path

# The visible tree state persists immediately and the live Spells parser is
# refreshed by the existing settings signal without changing delivery data.
item.setCheckState(0, Qt.CheckState.Unchecked)
disabled = next(
    CustomTrigger(*row) for row in config.data['spells']['custom_timers']
    if row[0] == 'Mob is casting')
runtime = SimpleNamespace()
runtime._active_character = 'Mindflux'
runtime._current_zone = ''
runtime._custom_trigger_has_audio = Spells._custom_trigger_has_audio
runtime._custom_timers = [(
    compile_trigger_pattern(disabled.text, raw_regex=disabled.regex),
    [], disabled)]
disabled_runtime_audio = Spells._line_has_custom_audio(
    runtime,
    'a soothebrine seahorse begins to cast a spell.')

item = find_mob_item()
dialog._triggers.setCurrentItem(item)
item.setCheckState(0, Qt.CheckState.Checked)
enabled = next(
    CustomTrigger(*row) for row in config.data['spells']['custom_timers']
    if row[0] == 'Mob is casting')
runtime._custom_timers = [(
    compile_trigger_pattern(enabled.text, raw_regex=enabled.regex),
    [], enabled)]
enabled_runtime_audio = Spells._line_has_custom_audio(
    runtime,
    'froglok bok shaman begins to cast a spell.')

# Test the same user-facing route from the editor without requiring the
# Spells window to be visible.
dialog._display_trigger(enabled)
quickbar, overlays, sounds, speech = [], [], [], []
app._queue_quickbar_notice = (
    lambda message, channel='system': quickbar.append([message, channel]))
app.show_overlay_notification = (
    lambda title, message, **kwargs: overlays.append(
        [title, message, kwargs]))
settings_module.play_alert = (
    lambda *args, **kwargs: sounds.append((args, kwargs)) or True)
settings_module.speak_text = (
    lambda *args, **kwargs: speech.append((args, kwargs)) or True)

# Avoid invoking the native Windows accessibility bridge in this isolated
# offscreen process; verify the same visible/accessible status mutation.
def record_status(message):
    dialog._trigger_test_status.setText(message)
    dialog._trigger_test_status.setAccessibleName(message)
    return message
dialog._announce_trigger_test = record_status

dialog._trigger_delivery.setCurrentIndex(
    dialog._trigger_delivery.findData('sound'))
sound_status = dialog._test_trigger_action()
dialog._trigger_delivery.setCurrentIndex(
    dialog._trigger_delivery.findData('tts'))
tts_status = dialog._test_trigger_action()
dialog._trigger_delivery.setCurrentIndex(
    dialog._trigger_delivery.findData('off'))
off_status = dialog._test_trigger_action()

result = {
    'tree_headers': [dialog._triggers.headerItem().text(index)
                     for index in range(dialog._triggers.columnCount())],
    'tree_state': find_mob_item().text(1),
    'disabled_saved': disabled.enabled,
    'enabled_saved': enabled.enabled,
    'delivery_preserved': (
        disabled.delivery == enabled.delivery == original_delivery and
        disabled.sound_path == enabled.sound_path == original_sound),
    'runtime_audio': [disabled_runtime_audio, enabled_runtime_audio],
    'toggle_text': dialog._trigger_enabled.text(),
    'toggle_accessible': dialog._trigger_enabled.accessibleName(),
    'toggle_description': dialog._trigger_enabled.accessibleDescription(),
    'toggle_keyboard_focusable': dialog._trigger_enabled.focusPolicy() !=
                                 Qt.FocusPolicy.NoFocus,
    'test_button_name': dialog._test_trigger_button.accessibleName(),
    'test_button_description':
        dialog._test_trigger_button.accessibleDescription(),
    'test_button_keyboard_focusable': dialog._test_trigger_button.focusPolicy()
                                      != Qt.FocusPolicy.NoFocus,
    'statuses': [sound_status, tts_status, off_status],
    'status_accessible': dialog._trigger_test_status.accessibleName(),
    'quickbar': quickbar,
    'overlay_count': len(overlays),
    'sound_count': len(sounds),
    'speech_count': len(speech),
    'sound_allow_hidden': sounds[0][1].get('allow_hidden'),
    'speech_allow_hidden': speech[0][1].get('allow_hidden'),
}
print(json.dumps(result), flush=True)
# PySide 6 can fault while tearing down a synthetic, never-executed offscreen
# QApplication after QAccessible events. The isolated harness has already
# persisted state and flushed its only result; skip native Qt teardown.
os._exit(0)
'''


def test_trigger_test_routes_and_visible_toggle_state(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['QT_ACCESSIBILITY'] = '0'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['tree_headers'] == ['Trigger library', 'State', 'Scope']
    assert result['tree_state'] == 'On'
    assert result['disabled_saved'] is False
    assert result['enabled_saved'] is True
    assert result['delivery_preserved'] is True
    assert result['runtime_audio'] == [False, True]
    assert result['toggle_text'] == 'Trigger On'
    assert result['toggle_accessible'] == 'Individual trigger On'
    assert 'Press Space' in result['toggle_description']
    assert result['toggle_keyboard_focusable'] is True
    assert result['test_button_name'] == 'Test selected trigger notification'
    assert 'Quick Bar' in result['test_button_description']
    assert result['test_button_keyboard_focusable'] is True
    assert result['statuses'] == [
        'Test status · Sound played',
        'Test status · Text to speech queued',
        'Test status · audio Off; visual notification sent',
    ]
    assert result['status_accessible'] == result['statuses'][-1]
    assert len(result['quickbar']) == 3
    assert all(channel == 'spells' for _message, channel in result['quickbar'])
    assert result['overlay_count'] == 3
    assert result['sound_count'] == 1
    assert result['speech_count'] == 1
    assert result['sound_allow_hidden'] is True
    assert result['speech_allow_hidden'] is True
