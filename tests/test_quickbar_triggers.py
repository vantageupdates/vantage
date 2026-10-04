"""The standalone Triggers launcher reuses one owned editor and runtime."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers import config
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS

ROOT = Path(__file__).resolve().parents[1]


def test_missing_triggers_action_is_visible_once_and_explicit_choice_survives(
        tmp_path, monkeypatch):
    original = config.data
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'profile.json'))
    config.data = {'quickbar': {'show_spells': False}}
    try:
        config.verify_settings()
        assert config.data['quickbar']['show_triggers'] is True
        assert config.data['quickbar']['show_spells'] is False
        assert QUICKBAR_ITEM_KEYS.count('triggers') == 1
        assert QUICKBAR_ITEM_KEYS.index('triggers') == \
            QUICKBAR_ITEM_KEYS.index('spells') + 1
        config.data['quickbar']['show_triggers'] = False
        config.verify_settings()
        assert config.data['quickbar']['show_triggers'] is False
        assert config.data['quickbar']['show_spells'] is False
    finally:
        config.data = original


SCRIPT = r'''
import copy
import json
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.settings import CustomTriggerSettings
from vantage.helpers.trigger_groups import normalize_trigger_groups
from vantage.parsers.spells import CustomTrigger

config.data['general']['startup_window_state'] = 'normal'
config.data['spells']['use_custom_triggers'] = False
app = VantageApp([])
bar = app._parsers_dict['quickbar']
runtime = app._parsers_dict['spells']
original_parsers = dict(app._parsers_dict)
bar._set_collapsed(False)
bar._auto_hide_menu = False
bar._set_header_revealed(True)
bar.show()
QTest.qWait(30)
button = bar._buttons['triggers']

# Seed explicitly mixed enabled state and an exact character override. Opening
# a utility window must not turn monitoring on or reset these choices.
config.data['spells']['custom_timers'] = [
    CustomTrigger(name='Enabled fixture', text='Synthetic match',
                  enabled=True, category='Raid/Kael',
                  profile='AuditCleric', audio_muted=True).to_list(),
    CustomTrigger(name='Disabled fixture', text='Another synthetic match',
                  enabled=False, category='Raid/Kael').to_list(),
]
config.data['spells']['trigger_groups'] = {
    'Raid': {'enabled': False, 'profiles': {'AuditCleric': True}},
    'Raid/Kael': {'enabled': False, 'profiles': {'AuditCleric': False}},
}
config.data['spells']['trigger_categories'] = {}
normalize_trigger_groups(config.data['spells'])
runtime.load_custom_timers()

def choices():
    spells = config.data['spells']
    return {
        'monitoring': spells['use_custom_triggers'],
        'rows': {row[0]: CustomTrigger(*row).to_list()
                 for row in spells['custom_timers']},
        'groups': copy.deepcopy(spells['trigger_groups']),
    }

before = choices()
result = {'initial': {
    'visible': button.isVisibleTo(bar._surface),
    'label': button.text(), 'name': button.accessibleName(),
    'size': [button.width(), button.height()],
    'text_width': button.fontMetrics().horizontalAdvance(button.text()),
    'icon': not button.icon().isNull(),
    'checked': button.isChecked(),
    'cached_lazy': app._triggers_dialog_instance is None,
    'monitoring_off_text': 'monitoring is off' in button.toolTip(),
}}
button.click()
QTest.qWait(40)
dialog = app._triggers_dialog_instance
result['opened'] = {
    'existing_editor': isinstance(dialog, CustomTriggerSettings),
    'owned': dialog.parentWidget() is bar,
    'nonmodal': not dialog.isModal() and
                dialog.windowModality() == Qt.WindowModality.NonModal,
    'visible': dialog.isVisible(), 'checked': button.isChecked(),
    'dot': bar._enabled_dots['triggers'].isVisible(),
    'independent_buffs': not runtime.isVisible(),
    'choices_unchanged': choices() == before,
    'display_refresh_included': dialog in app._secondary_ui_surfaces(),
}
draft = dialog._trigger_name
draft.setText('Unsaved fixture draft')
same = app.show_triggers(owner=bar)
result['raise_existing'] = same is dialog and draft.text() == \
    'Unsaved fixture draft'
button.click()
QTest.qWait(60)
result['closed'] = {
    'hidden': not dialog.isVisible(), 'checked': button.isChecked(),
    'dot': bar._enabled_dots['triggers'].isVisible(),
    'focus': button.hasFocus(), 'choices_unchanged': choices() == before,
}
button.click()
QTest.qWait(40)
result['reused'] = app._triggers_dialog_instance is dialog
QTest.keyClick(dialog, Qt.Key.Key_Escape)
QTest.qWait(60)
result['escape'] = not dialog.isVisible() and button.hasFocus()

# Refresh from saved settings only when reopening a hidden cached editor.
config.data['spells']['use_custom_triggers'] = True
before_reopen = choices()
app.show_triggers(parent=bar)
QTest.qWait(30)
result['saved_choice_reopen'] = choices() == before_reopen and \
    'monitoring is on' in button.toolTip()
dialog.close()
QTest.qWait(40)
config.data['spells']['use_custom_triggers'] = False

# A non-Quick Bar caller gets the same owned editor and its own launcher back.
owner = QWidget()
owner.resize(200, 80)
layout = QVBoxLayout(owner)
launcher = QPushButton('Triggers', owner)
layout.addWidget(launcher)
owner.show()
owner.activateWindow()
launcher.setFocus()
QTest.qWait(30)
same = app.show_triggers(owner=owner)
QTest.qWait(30)
result['alternate_owner'] = same is dialog and dialog.parentWidget() is owner
dialog.close()
QTest.qWait(60)
result['alternate_focus'] = launcher.hasFocus()
owner.hide()

# The older Settings entry routes through the same cache, never exec/new.
settings = app.show_feature_settings('Buffs & Triggers', owner=bar)
settings._get_custom_timers()
QTest.qWait(30)
result['legacy_same'] = app._triggers_dialog_instance is dialog and \
    dialog.parentWidget() is settings and not dialog.isModal()
dialog.close()
settings.close()
QTest.qWait(30)

# Labels can use logical width, but never silently expand a saved rectangle.
# Isolate this authored-layout contract from real monitor recovery: Qt's
# offscreen screen is only 800 px wide (533 logical px at 150% DPI), smaller
# than the full action strip. Monitor-clamping behavior is tested separately.
bar._fit_to_available_screen = lambda: None
bar.resize(600, 75)
QTest.qWait(30)
saved_size = [bar.width(), bar.height()]
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(30)
result['saved_rectangle'] = [bar.width(), bar.height()] == saved_size
preset_cases = []
for scale in (.5, .75, 1):
    bar._set_replica_scale(scale)
    QTest.qWait(30)
    preset_cases.append([bar.width(), bar.height()] == [
        round(bar._design_size.width() * scale),
        round(bar._design_size.height() * scale)])
result['presets'] = preset_cases
config.data['quickbar']['orientation'] = 'vertical'
bar._apply_quickbar_settings(preserve_scale=False)
QTest.qWait(30)
result['vertical'] = {
    'size': [button.width(), button.height()], 'text': button.text(),
    'design_width': bar._design_size.width(),
    'name': button.accessibleName(),
    'visible': button.isVisibleTo(bar._surface),
}
config.data['quickbar']['orientation'] = 'horizontal'
bar._apply_quickbar_settings(preserve_scale=False)
QTest.qWait(30)
result['horizontal_restored'] = button.text() == 'Triggers' and \
    button.width() > 24 and button.height() == 24
result['one_runtime'] = app._parsers_dict == original_parsers and \
    app._parsers_dict['spells'] is runtime
print(json.dumps(result))
app.quit()
'''


@pytest.mark.parametrize('display_scale', ('1', '1.5'))
def test_triggers_is_a_visible_cached_owned_nonmodal_action(display_scale):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=display_scale,
               PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=os.pathsep.join((str(ROOT / 'tests'),
                                          str(ROOT / 'src'))))
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=False, capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    initial = result['initial']
    assert initial['visible'] and initial['icon'] and initial['cached_lazy']
    assert initial['label'] == initial['name'] == 'Triggers'
    assert initial['size'][0] >= initial['text_width'] + 31
    assert initial['size'][1] == 24 and not initial['checked']
    assert initial['monitoring_off_text']
    assert all(result['opened'].values()), result['opened']
    assert result['closed'] == {
        'hidden': True, 'checked': False, 'dot': False,
        'focus': True, 'choices_unchanged': True}
    for field in ('raise_existing', 'reused', 'escape', 'saved_choice_reopen',
                  'alternate_owner', 'alternate_focus', 'legacy_same',
                  'saved_rectangle', 'horizontal_restored', 'one_runtime'):
        assert result[field], (field, result)
    assert all(result['presets'])
    assert result['vertical'] == {
        'size': [24, 24], 'text': '', 'design_width': 30,
        'name': 'Triggers', 'visible': True}
