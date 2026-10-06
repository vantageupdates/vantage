"""Real native editor coverage for simple literal keyword triggers."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_trigger_tts_selection import QT_AUDIT_LIFECYCLE


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import os
from native_audit_fixture import isolate

isolate()
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings
from vantage.helpers.settings import CustomTriggerSettings, SettingsSignals
from vantage.parsers.spells import CustomTrigger

app = QApplication([])
app._signals = {'settings': SettingsSignals()}
app._parsers_dict = {}
for path in ('data/fonts/NotoSans-Regular.ttf', 'data/fonts/NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(path)
font = QFont('Noto Sans')
font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
app.setFont(font)
VantageApp._apply_theme(app)
settings.speech_voice_names = lambda: []
# A pre-127 row must retain its old full-line behavior, not silently broaden.
legacy = CustomTrigger('Legacy keyword', 'the tangrin', '', delivery='off')
legacy_values = legacy.to_list()[:49]
config.data['spells']['custom_timers'] = [legacy_values]
dialog = CustomTriggerSettings()
windows = [dialog]
scale = float(os.environ['VANTAGE_KEYWORD_EDITOR_SCALE'])
dialog.resize(QSize(round(960 * scale), round(760 * scale)))
dialog._load_from_config(selected_name=legacy.name)
dialog.show()
QTest.qWait(30)
view = dialog._dialog_view

def click_widget(widget):
    logical = widget.mapTo(dialog.scaled_surface, widget.rect().center())
    target = view.mapFromScene(dialog._dialog_proxy.mapToScene(logical))
    assert view.viewport().rect().contains(target), (widget.accessibleName(), target)
    QTest.mouseMove(view.viewport(), target)
    QTest.qWait(20)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()

def preview(line):
    dialog._sample_line.setText(line)
    matched = dialog._match_sample_line()
    app.processEvents()
    result = dialog._sample_result.toPlainText()
    assert 'No actions were run.' in result or 'No audio, timer, clipboard or overlay action was run' in result
    return matched, result

assert dialog._trigger_match_mode.currentData() == 'full'
assert not dialog._advanced_toggle.isChecked()
assert dialog._trigger_match_mode.isVisible() and dialog._trigger_text.isVisible()
assert dialog._trigger_match_mode not in dialog._advanced_core_fields
assert dialog._trigger_match_mode.accessibleName() == 'Trigger text matching scope'
assert 'ignoring case' in dialog._trigger_match_mode.accessibleDescription()
assert not preview('Someone mentions THE TANGRIN in a raid call.')[0]
assert preview('THE TANGRIN')[0]
dialog._sample_toggle.setChecked(False)
app.processEvents()

# Select the literal option through the actual keyboard event route in the
# scaled dialog, not by changing combo data or invoking production slots.
click_widget(dialog._trigger_match_mode)
QTest.keyClick(view.viewport(), Qt.Key.Key_Escape)
dialog._trigger_match_mode.setFocus()
QTest.keyClick(view.viewport(), Qt.Key.Key_Home)
assert dialog._trigger_match_mode.currentData() == 'contains'
assert 'literal words or a phrase anywhere' in dialog._token_legend.text()
dialog._advanced_toggle.setChecked(True)
assert 'literal words or a phrase anywhere' in dialog._token_legend.text()
dialog._advanced_toggle.setChecked(False)
assert dialog._trigger_match_mode.isVisible()
assert 'literal words or a phrase anywhere' in dialog._token_legend.text()
matched, result = preview('[Tue Oct 06 15:00:00 2026] Someone mentions THE TANGRIN in a raid call.')
assert matched and 'Match found' in result
assert not preview('This is a different monster.')[0]

# Any literal phrase uses the same path; punctuation is not an accidental
# wildcard, capture token, or regular expression in Contains text mode.
dialog._trigger_text.setText('rage {Mob} * [50%]')
assert preview('A caller says RAGE {MOB} * [50%] now!')[0]
assert not preview('A caller says rage Goblin other text 50 now!')[0]
dialog._trigger_text.setText('the tangrin')
dialog._sample_toggle.setChecked(False)
app.processEvents()
click_widget(dialog._save_trigger_button)
assert dialog._custom_triggers[legacy.name].match_mode == 'contains'
saved_row = next(row for row in config.data['spells']['custom_timers'] if row[0] == legacy.name)
assert len(saved_row) == 50 and saved_row[49] == 'contains'
assert legacy_values[1] == saved_row[1] == 'the tangrin'
dialog.hide()

reopened = CustomTriggerSettings()
windows.append(reopened)
reopened.resize(QSize(round(960 * scale), round(760 * scale)))
reopened._load_from_config(selected_name=legacy.name)
reopened.show()
QTest.qWait(30)
dialog, view = reopened, reopened._dialog_view
assert dialog._trigger_match_mode.currentData() == 'contains'
assert dialog._trigger_text.text() == 'the tangrin'
assert not dialog._advanced_toggle.isChecked()
click_widget(dialog._clone_trigger_button)
clone_name = legacy.name + ' · Copy'
assert dialog._current_trigger == clone_name
assert dialog._custom_triggers[clone_name].match_mode == 'contains'
assert dialog._custom_triggers[clone_name].enabled is False
assert dialog._trigger_match_mode.currentData() == 'contains'

# New triggers start with the uncomplicated literal mode, while saved legacy
# rules and explicit regex retain their deliberate semantics.
dialog._add_trigger_button.click()
assert dialog._current_trigger == ''
assert dialog._trigger_match_mode.currentData() == 'contains'
assert dialog._trigger_match_mode.isVisible()
dialog._trigger_name.setText('Fresh keyword')
dialog._trigger_text.setText('enraged')
assert preview('The tangrin has become ENRAGED!')[0]
dialog._sample_toggle.setChecked(False)
app.processEvents()
click_widget(dialog._save_trigger_button)
assert dialog._custom_triggers['Fresh keyword'].match_mode == 'contains'

dialog._advanced_toggle.setChecked(True)
dialog._trigger_regex.setChecked(True)
assert not dialog._trigger_match_mode.isEnabled()
assert dialog._trigger_match_mode.currentData() == 'contains'
assert 'Regular expression' in dialog._token_legend.text()
assert not preview('prefix enraged')[0]
assert preview('ENRAGED with a suffix')[0]
dialog._sample_toggle.setChecked(False)
dialog._save_trigger_button.click()
saved = dialog._custom_triggers['Fresh keyword']
assert saved.regex and saved.match_mode == 'contains'
dialog._trigger_regex.setChecked(False)
assert dialog._trigger_match_mode.isEnabled()
assert dialog._trigger_match_mode.currentData() == 'contains'
assert preview('prefix ENRAGED suffix')[0]

# Main literal matching does not broaden separately configured early enders.
dialog._add_end_pattern('stop now', False)
assert not preview('Please stop now after this pull.')[0]
matched, result = preview('STOP NOW')
assert matched and 'Early-ending pattern matched' in result
dialog._sample_toggle.setChecked(False)
dialog._save_trigger_button.click()
saved = dialog._custom_triggers['Fresh keyword']
assert saved.match_mode == 'contains' and not saved.regex
assert saved.end_patterns == [{'text': 'stop now', 'regex': False}]

finish_qt_audit(app, {
    'scale': dialog.uniform_scale,
    'legacy_full_retained': True,
    'basic_match_mode_visible': True,
    'keyboard_selects_contains': True,
    'help_tracks_scope_and_advanced': True,
    'case_insensitive_midline_preview': True,
    'metacharacters_are_literal': True,
    'save_reopen_clone_retains_scope': True,
    'new_trigger_defaults_contains': True,
    'regex_retains_old_matching_and_saved_mode': True,
    'early_enders_remain_full_line': True,
}, windows)
'''


@pytest.mark.parametrize('scale', (1.0, 1.5))
def test_keyword_trigger_editor_real_keyboard_preview_save_reopen_and_clone(tmp_path, scale):
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src')))
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['QT_ACCESSIBILITY'] = '0'
    env['QT_SCALE_FACTOR'] = str(scale)
    env['VANTAGE_KEYWORD_EDITOR_SCALE'] = str(scale)
    env['TEMP'] = env['TMP'] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, '-B', '-c', QT_AUDIT_LIFECYCLE + SCRIPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=50)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result.pop('scale') == pytest.approx(scale)
    assert all(result.values()), result
