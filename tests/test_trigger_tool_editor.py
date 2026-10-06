"""Native editor checks in an isolated process with all delivery blocked."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(script):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=55)
    assert completed.returncode == 0, completed.stderr[-5000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


CORE_SCRIPT = r'''
import copy, json, os
from pathlib import Path
from native_audit_fixture import isolate
profile = isolate()
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QTreeWidgetItemIterator, QWidget
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings
from vantage.helpers.settings import CustomTriggerSettings, GinaImportPreviewDialog, TRIGGER_ITEM_ID, TRIGGER_ITEM_KIND
from vantage.helpers.gina_import import GinaImportBatch
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
basic = CustomTrigger('Mark alert', '{Actor} is marked.', '', category='Raid/Markers',
                      alert_text='MARK {Actor}', delivery='off', timer_ending_delivery='off', timer_ended_delivery='off')
advanced = CustomTrigger('Respawn reminder', 'You have slain {Mob}', '00:05:00', category='Raid/Timers',
                         alert_text='Spawn soon {Mob}', delivery='tts', tts_text='Respawn {Mob}',
                         comments='Review imported timer stages', timer_name='Respawn ${1}',
                         timer_ending_seconds=30, timer_ending_alert='Spawn in 30',
                         timer_ending_delivery='off', timer_ended_alert='Spawn due', timer_ended_delivery='off',
                         end_patterns=[{'text':'{Mob} has spawned.', 'regex':False}],
                         end_text='{Mob} has spawned.', clipboard_text='/target {Mob}',
                         tts_volume=55, tts_pitch=2, tts_voice='Synthetic missing voice')
config.data['spells']['custom_timers'] = [basic.to_list(), advanced.to_list()]
config.data['spells']['trigger_groups'] = {'Raid': {'enabled':True, 'style': {'font_color':'#E5C267'}}}
owner = QWidget()
dialog = CustomTriggerSettings(parent=owner)
assert dialog.parentWidget() is owner
dialog._load_from_config(selected_name=basic.name)
dialog._advanced_toggle.setChecked(False)
dialog.show()
app.processEvents()
assert not dialog._sample_host.isVisible() and not dialog._sample_result.isVisible()
assert 'dry-run' in dialog._sample_result.toolTip()
assert 'expanded output' in dialog._sample_result.toolTip()
assert 'No audio, timers, clipboard changes or overlays are run.' in dialog._sample_result.toolTip()
assert dialog._triggers.maximumHeight() == 140
assert '\n' not in dialog._token_legend.text()
core = dialog.scaled_surface.findChild(QScrollArea, 'TriggerEditScroll')
core.verticalScrollBar().setValue(0)
app.processEvents()
position = dialog._trigger_enabled.mapTo(core.viewport(), QPoint(0,0))
assert position.y() + dialog._trigger_enabled.height() <= core.viewport().height(), (position.y(),core.viewport().height())
basic_area = dialog._basic_action_scroll
basic_area.verticalScrollBar().setValue(0)
app.processEvents()
delivery_position = dialog._trigger_delivery.mapTo(basic_area.viewport(), QPoint(0,0))
assert delivery_position.y() + dialog._trigger_delivery.height() <= basic_area.viewport().height()

def snapshot():
    result = []
    iterator = QTreeWidgetItemIterator(dialog._triggers)
    while iterator.value():
        item = iterator.value()
        result.append((str(item.data(0,TRIGGER_ITEM_ID)), str(item.data(0,TRIGGER_ITEM_KIND))))
        iterator += 1
    return result

before_order = snapshot()
before_config = copy.deepcopy(config.data)
dialog._trigger_text.setText('{Actor} casts {Spell}.')
dialog._library_search.setText('timers')
app.processEvents()
assert dialog._trigger_text.text() == '{Actor} casts {Spell}.'
assert snapshot() == before_order and config.data == before_config
visible = []
iterator = QTreeWidgetItemIterator(dialog._triggers)
while iterator.value():
    item = iterator.value()
    if not item.isHidden(): visible.append(str(item.data(0,TRIGGER_ITEM_ID)))
    iterator += 1
assert advanced.name in visible and basic.name not in visible and 'Raid' in visible
dialog._library_search.clear()
assert snapshot() == before_order

capture_root = os.environ.get('VANTAGE_TRIGGER_CAPTURE_DIR')
def capture(name):
    if capture_root:
        path = Path(capture_root)
        path.mkdir(parents=True, exist_ok=True)
        app.processEvents()
        assert dialog.grab().save(str(path / (name + '.png')))
capture('triggers-basic')

dialog._load_from_config(selected_name=advanced.name)
assert dialog._advanced_toggle.isChecked()
draft_before = dialog._draft_trigger().to_list()
dialog._advanced_toggle.setChecked(False)
assert dialog._draft_trigger().to_list() == draft_before
dialog._advanced_toggle.setChecked(True)
assert dialog._draft_trigger().to_list() == draft_before
assert '\n' in dialog._token_legend.text()
capture('triggers-advanced')

parser = app._parsers_dict['spells']
parser._active_character = 'AuditCleric'
app._log_status = 'Synthetic audit: no live log monitored'
dialog._refresh_monitor_status()
assert 'AuditCleric' in dialog._monitor_status.text()
assert 'no live log' in dialog._monitor_status.text()
assert dialog._monitor_status.textFormat() == Qt.TextFormat.PlainText
rows_before = copy.deepcopy(config.data['spells']['custom_timers'])
tracking_before = {key: copy.deepcopy(value) for key,value in config.data['spells'].items()
                   if key not in {'use_custom_triggers'}}
dialog._monitor_enabled.setChecked(False)
assert config.data['spells']['use_custom_triggers'] is False
assert all(config.data['spells'][key] == value for key,value in tracking_before.items())
assert 'paused' in dialog._monitor_status.text()
dialog._monitor_enabled.setChecked(True)
assert config.data['spells']['custom_timers'] == rows_before

calls = []
settings.play_alert = lambda *args,**kwargs: calls.append('audio')
settings.speak_text = lambda *args,**kwargs: calls.append('speech')
app._queue_quickbar_notice = lambda *args,**kwargs: calls.append('notice')
app.show_overlay_notification = lambda *args,**kwargs: calls.append('overlay')
QApplication.clipboard().setText('clipboard unchanged')
dialog._trigger_text.setText('{Actor} casts {Spell}.')
dialog._trigger_alert.setText('Actor {Actor} · Spell ${2} · Count {COUNTER}')
dialog._sample_line.setText('[Sun Oct 04 10:00:00 2026] a goblin casts Fireball.')
saved = copy.deepcopy(config.data)
live = {name: trigger.to_list() for name,trigger in dialog._custom_triggers.items()}
history = list(parser._trigger_history)
runs = copy.copy(parser._trigger_runs)
assert dialog._match_sample_line() is True
result = dialog._sample_result.toPlainText()
assert 'Actor=a goblin' in result and 'Spell=Fireball' in result and 'Spell Fireball' in result
assert 'Count 1' in result and 'No audio, timer, clipboard or overlay' in result
assert not calls and config.data == saved
assert {name:trigger.to_list() for name,trigger in dialog._custom_triggers.items()} == live
assert list(parser._trigger_history) == history and parser._trigger_runs == runs
assert QApplication.clipboard().text() == 'clipboard unchanged'
capture('triggers-sample-match')
dialog._sample_toggle.setChecked(False)
assert not dialog._sample_host.isVisible() and dialog._sample_result.toPlainText() == result
dialog._trigger_text.setText('{c} is marked.')
dialog._sample_line.setText('OtherCharacter is marked.')
assert dialog._match_sample_line() is False
dialog._sample_line.setText('AuditCleric is marked.')
assert dialog._match_sample_line() is True
dialog._trigger_regex.setChecked(True)
dialog._trigger_text.setText('(')
assert dialog._match_sample_line() is False and 'Invalid pattern' in dialog._sample_result.toPlainText()
dialog._sample_toggle.setChecked(False)
dialog._load_from_config(selected_name=basic.name)
dialog._advanced_toggle.setChecked(False)
dialog.resize(480,480)
app.processEvents()
capture('triggers-narrow')

batch = GinaImportBatch([CustomTrigger('<b>Imported</b>', 'match', '')], warnings=[
    {'trigger':'<b>Imported</b>', 'code':'test', 'message':'<img src="outside"> Unsupported regex and missing WAV.'}])
preview = GinaImportPreviewDialog(batch, dialog)
assert preview.compatibility_warnings.textFormat() == Qt.TextFormat.PlainText
assert '<img' in preview.compatibility_warnings.text()
preview.show()
app.processEvents()
if capture_root:
    assert preview.grab().save(str(Path(capture_root)/'triggers-import-warnings.png'))
preview.reject()
print(json.dumps({'parent':True,'compact_primary_controls':True,'search_preserves_draft':True,
                  'advanced_retains_fields':True,'monitor_preserves_tracking':True,
                  'dry_run_has_no_actions':True,'character_token_exact':True,'plain_text_warnings':True}))
dialog._save_to_config = lambda: None
dialog.close()
app.quit()
'''


def test_native_trigger_editor_scope_search_disclosure_and_safe_draft_preview():
    assert all(_run(CORE_SCRIPT).values())


SHARING_SCRIPT = r'''
import copy, json
from pathlib import Path
from native_audit_fixture import isolate
profile = isolate()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QTreeWidgetItemIterator
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings, trigger_sharing
from vantage.helpers.gina_import import import_vantage_package_bytes, serialize_vantage_package
from vantage.helpers.portable import store_portable_bytes
from vantage.helpers.settings import CustomTriggerSettings, GinaImportPreviewDialog, TRIGGER_ITEM_ID, TRIGGER_ITEM_KIND
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
local = CustomTrigger('Local trigger', 'local', '', category='Raid/Control', delivery='off')
other = CustomTrigger('Outside group', 'other', '', category='Other', delivery='off')
config.data['spells']['custom_timers'] = [local.to_list(),other.to_list()]
config.data['spells']['trigger_groups'] = {
    'Raid': {'enabled':False,'profiles':{'AuditCleric':True},'style':{'font_color':'#E5C267'}},
    'Raid/Control': {'enabled':True,'profile_styles':{'AuditCleric':{'font_color':'#76B7B2'}}}}
dialog = CustomTriggerSettings()
dialog._load_from_config(selected_name=local.name)
assert [trigger.name for trigger in dialog._selected_pack_triggers()] == [local.name]
dialog._triggers.clearSelection()
dialog._triggers.setCurrentItem(None)
assert not dialog._selected_pack_triggers()
dialog._share_scope.setCurrentIndex(dialog._share_scope.findData('all'))
assert len(dialog._selected_pack_triggers()) == 2
dialog._share_scope.setCurrentIndex(dialog._share_scope.findData('selection'))
iterator = QTreeWidgetItemIterator(dialog._triggers)
while iterator.value():
    item = iterator.value()
    if item.data(0,TRIGGER_ITEM_KIND) == 'group' and item.data(0,TRIGGER_ITEM_ID) == 'Raid':
        dialog._triggers.setCurrentItem(item)
        break
    iterator += 1
assert [trigger.name for trigger in dialog._selected_pack_triggers()] == [local.name]
# End the native traversal before the import flow rebuilds this same tree.
# Retained iterator/item wrappers can outlive their deleted native rows.
del iterator, item
saved = copy.deepcopy(config.data)
assert dialog._prepare_share() is not None and config.data == saved

# The actual warning acknowledgement dialog is dismissed before a file chooser
# or output file can be created. No fixture relies on a desktop user's profile.
paths = []
QFileDialog.getSaveFileName = lambda *args,**kwargs: (paths.append('asked') or str(profile/'cancelled.gtp'), '')
QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
dialog._export_gina_pack()
assert not paths and not (profile/'cancelled.gtp').exists()

messages = []
QMessageBox.information = lambda *args,**kwargs: messages.append(str(args[-1]))
QMessageBox.warning = lambda *args,**kwargs: messages.append(str(args[-1]))
QMessageBox.question = lambda *args,**kwargs: (messages.append(str(args[2])) or QMessageBox.StandardButton.Yes)
dialog._confirm_share = lambda *args,**kwargs: True
dialog._copy_share(False)
code = QApplication.clipboard().text()
assert code.startswith('VT1:')
if len(code) > 240:
    assert any('EverQuest /tell' in message and str(len(code)) in message.replace(',','') for message in messages)
copied = import_vantage_package_bytes(trigger_sharing.decode_trigger_share_code(code))
assert len(copied) == 1 and copied[0].enabled is False
dialog._copy_share(True)
link = QApplication.clipboard().text()
assert link.startswith('https://vantageupdates.github.io/vantage/companion/share.html#')
assert trigger_sharing.decode_trigger_share_code(link) == trigger_sharing.decode_trigger_share_code(code)

wav = store_portable_bytes(b'RIFF'+(4).to_bytes(4,'little')+b'WAVEtest','share.wav',subdir='sounds')
incoming = CustomTrigger(local.name, 'imported {Actor}', '', category='Raid/Control',
                         sound_path=wav, delivery='legacy', tts_text='Retained speech', enabled=True)
unselected = CustomTrigger('Not chosen', 'unused', '', sound_path=wav, delivery='sound')
content,_ = serialize_vantage_package([incoming,unselected], {
    'Raid': {'enabled':True,'profiles':{'AuditCleric':False},'style':{'font_color':'#DF706A'}},
    'Raid/Control': {'enabled':False,'profile_styles':{'AuditCleric':{'font_color':'#DF706A'}}}})
shared = trigger_sharing.create_trigger_share_code(content)
QInputDialog.getMultiLineText = lambda *args,**kwargs: (shared,True)
before_config = copy.deepcopy(config.data)
GinaImportPreviewDialog.exec = lambda self: QDialog.DialogCode.Rejected
dialog._paste_share()
assert config.data == before_config
assert not (profile/'sounds'/'gina-imports').exists()

local_groups = copy.deepcopy(config.data['spells']['trigger_groups'])
def accept_first(self):
    assert 'Pack WAV' in self.table.item(0,4).text()
    assert 'TTS' not in self.table.item(0,4).text()
    self._set_all(False)
    self._rows[0][0].setChecked(True)
    return QDialog.DialogCode.Accepted
GinaImportPreviewDialog.exec = accept_first
dialog._paste_share()
assert len(dialog._custom_triggers) == 3 and 'Not chosen' not in dialog._custom_triggers
added = [trigger for trigger in dialog._custom_triggers.values() if trigger.text == incoming.text]
assert len(added) == 1 and added[0].enabled is False and added[0].name != local.name
assert added[0].sound_path.startswith('portable:sounds/gina-imports/')
for path in ('Raid','Raid/Control'):
    assert config.data['spells']['trigger_groups'][path] == local_groups[path]
assert dialog._custom_triggers[local.name].to_list() == local.to_list()

dialog._load_from_config(selected_name=local.name)
QApplication.clipboard().setText('not replaced')
trigger_sharing.create_trigger_share_code = lambda *args,**kwargs: (_ for _ in ()).throw(trigger_sharing.TriggerShareError('too large'))
dialog._copy_share(False)
assert QApplication.clipboard().text() == 'not replaced'
assert any('No audio was removed' in message for message in messages)
print(json.dumps({'selection_group_all_none':True,'prepare_is_pure':True,'gina_cancel_no_file':True,
                  'code_link_copy':True,'preview_cancel_no_media':True,'paste_disabled_selected_copies':True,
                  'local_group_collision_preserved':True,'oversized_no_silent_omission':True}))
dialog._save_to_config = lambda: None
dialog.close()
app.quit()
'''


def test_native_trigger_sharing_scopes_acknowledgement_and_reviewed_disabled_import():
    assert all(_run(SHARING_SCRIPT).values())
