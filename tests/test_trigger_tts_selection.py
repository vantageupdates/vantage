"""Exercise real scaled trigger delivery choices without native audio or a live profile."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


QT_AUDIT_LIFECYCLE = r'''
def finish_qt_audit(app, result, windows):
    """Dispose owned Qt windows before the application and normal exit."""
    import gc
    import json
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QComboBox, QToolTip

    app.setQuitOnLastWindowClosed(False)
    failures = []
    def dispose_windows():
        try:
            QToolTip.hideText()
            compatibility_editors = []
            for owned in windows:
                for combo in owned.findChildren(QComboBox):
                    combo.hidePopup()
                owned.hide()
                # The legacy early-ender compatibility field is deliberately
                # absent from the visible form and has no Qt parent. Its
                # Python owner does not suffice during application teardown.
                editor = getattr(owned, '_trigger_end_text', None)
                if editor is not None and editor.parent() is None:
                    compatibility_editors.append(editor)
            app.processEvents()
            for editor in compatibility_editors:
                editor.deleteLater()
            for owned in reversed(windows):
                owned.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert all(not shiboken6.isValid(owned) for owned in windows)
            assert all(not shiboken6.isValid(editor) for editor in compatibility_editors)
            app.processEvents()
            assert not app.topLevelWidgets(), [
                widget.metaObject().className() for widget in app.topLevelWidgets()]
        except BaseException as error:
            failures.append(error)
        finally:
            app.quit()

    # A real event loop services queued focus, popup, and DeferredDelete work.
    QTimer.singleShot(0, dispose_windows)
    assert app.exec() == 0
    if failures:
        raise failures[0]
    gc.collect()
    shiboken6.delete(app)
    assert not shiboken6.isValid(app)
    gc.collect()
    print(json.dumps(result), flush=True)
'''


SCRIPT = r'''
import copy
import json
import os
from native_audit_fixture import isolate

profile = isolate()
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem, QTreeWidgetItemIterator
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings
from vantage.helpers.portable import store_portable_bytes
from vantage.helpers.settings import CustomTriggerSettings, SettingsSignals, TRIGGER_ITEM_ID, TRIGGER_ITEM_KIND
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, Spells

app = QApplication([])
app._signals = {'settings': SettingsSignals()}
from PySide6.QtGui import QFont, QFontDatabase
for path in ('data/fonts/NotoSans-Regular.ttf','data/fonts/NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(path)
interface_font = QFont('Noto Sans')
interface_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
interface_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
app.setFont(interface_font)
VantageApp._apply_theme(app)
class RuntimeAudio:
    _deliver_custom_trigger_audio = Spells._deliver_custom_trigger_audio
app._parsers_dict = {'spells': RuntimeAudio()}
settings.speech_voice_names = lambda: ['Synthetic voice']
sound = store_portable_bytes(b'RIFF'+(4).to_bytes(4,'little')+b'WAVEtest',
                             'retained.wav', subdir='sounds')
original = CustomTrigger(
    'TTS selection', 'synthetic trigger', '00:01:00', category='Raid/Voice',
    delivery='sound', sound_path=sound, tts_text='Saved basic',
    timer_ending_seconds=15, timer_ending_delivery='sound', timer_ending_sound=sound,
    timer_ending_tts='Saved ending', timer_ended_delivery='sound',
    timer_ended_sound=sound, timer_ended_tts='Saved ended',
    tts_voice='Missing retained voice', timer_ending_voice='Synthetic voice',
    timer_ended_voice='Synthetic voice', tts_volume=61, timer_ending_volume=72,
    timer_ended_volume=83, tts_pitch=-2, timer_ending_pitch=3, timer_ended_pitch=1,
    interrupt_speech=True, timer_ending_interrupt=False, timer_ended_interrupt=True)
config.data['spells']['custom_timers'] = [original.to_list()]
config.data['spells']['trigger_groups'] = {
    'Raid': {'enabled':True,'profiles':{'OtherCharacter':False}},
    'Raid/Voice': {'enabled':True,'profile_styles':{'OtherCharacter':{'font_color':'#DF706A'}}}}
groups_before = copy.deepcopy(config.data['spells']['trigger_groups'])
dialog = CustomTriggerSettings()
# The real app retains its settings dialogs. Keep each synthetic window alive
# as well, so rebinding a variable cannot destroy a proxy/queued native event.
retained_windows = [dialog]
scale = float(os.environ.get('VANTAGE_TTS_AUDIT_SCALE','0.8'))
dialog.resize(QSize(round(960*scale),round(760*scale)))
dialog._load_from_config(selected_name=original.name)
dialog._advanced_toggle.setChecked(True)
dialog.show()
QTest.qWait(30)
view = dialog._dialog_view

def click_widget(widget, point=None):
    logical = widget.mapTo(dialog.scaled_surface, point or widget.rect().center())
    target = view.mapFromScene(dialog._dialog_proxy.mapToScene(logical))
    assert view.viewport().rect().contains(target), (widget.accessibleName(), target)
    QTest.mouseMove(view.viewport(), target)
    QTest.qWait(20)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()

def choose_audio(combo, mode):
    area = dialog._action_tabs.currentWidget()
    area.ensureWidgetVisible(combo)
    app.processEvents()
    QTest.qWait(40)
    click_widget(combo, QPoint(combo.width()-10, combo.height()//2))
    # Qt's popup intentionally guards the opening mouse release. Allow it to
    # settle before issuing the second independent pointer selection.
    QTest.qWait(220)
    dropdown = combo.view()
    assert dropdown.isVisible(), combo.accessibleName()
    index = combo.model().index(combo.findData(mode), 0)
    row = dropdown.visualRect(index)
    popup = next(item for item in dialog._dialog_scene.items()
                 if item is not dialog._dialog_proxy and item.isVisible() and
                 item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsPanel)
    position = dropdown.viewport().mapTo(dropdown.window(), row.center())
    target = view.mapFromScene(popup.mapToScene(position))
    assert view.viewport().rect().contains(target), target
    QTest.mouseMove(view.viewport(), target)
    QTest.qWait(30)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()
    QTest.qWait(40)
    assert combo.currentData() == mode, (combo.accessibleName(), combo.currentData(), mode)
    assert not dropdown.isVisible()

stages = (
    (0,'basic',dialog._trigger_tts,dialog._trigger_delivery),
    (2,'ending',dialog._trigger_ending_tts,dialog._trigger_ending_delivery),
    (3,'ended',dialog._trigger_ended_tts,dialog._trigger_ended_delivery))
checks = []
for tab, phase, editor, combo in stages:
    dialog._action_tabs.setCurrentIndex(tab)
    app.processEvents()
    choose_audio(combo,'tts')
    _, sound_panel, speech_panel = dialog._trigger_delivery_panels[(0,2,3).index(tab)]
    assert speech_panel.isVisible() and speech_panel.isEnabled()
    assert editor.isEnabled() and not sound_panel.isVisible() and not sound_panel.isEnabled()
    assert speech_panel._delivery_label.isVisible() and not sound_panel._delivery_label.isVisible()
    for mode in ('sound','tts','off','tts'):
        choose_audio(combo,mode)
    assert speech_panel.isVisible() and editor.text() == 'Saved '+phase
    dialog._action_tabs.currentWidget().ensureWidgetVisible(editor)
    app.processEvents()
    click_widget(editor)
    QTest.keyClick(view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(view.viewport(), 'Chosen '+phase)
    assert editor.text() == 'Chosen '+phase
    dialog._action_tabs.currentWidget().ensureWidgetVisible(combo)
    app.processEvents()
    combo.setFocus()
    QTest.keyClick(view.viewport(),Qt.Key.Key_Home)
    assert combo.currentData() == 'sound'
    QTest.keyClick(view.viewport(),Qt.Key.Key_Down)
    assert combo.currentData() == 'tts'
    QTest.keyClick(view.viewport(),Qt.Key.Key_Down)
    assert combo.currentData() == 'off'
    assert not speech_panel.isEnabled() and not sound_panel.isEnabled()
    QTest.keyClick(view.viewport(),Qt.Key.Key_Up)
    assert combo.currentData() == 'tts' and editor.text() == 'Chosen '+phase
    checks.append(phase)

click_widget(dialog._save_trigger_button)
assert dialog._custom_triggers[original.name].delivery == 'tts'
saved = dialog._custom_triggers[original.name]
assert [saved.sound_path,saved.timer_ending_sound,saved.timer_ended_sound] == [sound]*3
assert [saved.tts_text,saved.timer_ending_tts,saved.timer_ended_tts] == ['Chosen basic','Chosen ending','Chosen ended']
assert [saved.tts_voice,saved.timer_ending_voice,saved.timer_ended_voice] == ['Missing retained voice','Synthetic voice','Synthetic voice']
assert config.data['spells']['trigger_groups']['Raid']['profiles'] == groups_before['Raid']['profiles']
assert config.data['spells']['trigger_groups']['Raid/Voice']['profile_styles'] == groups_before['Raid/Voice']['profile_styles']
dialog.hide()
reopened = CustomTriggerSettings()
retained_windows.append(reopened)
reopened.resize(QSize(round(960*scale),round(760*scale)))
reopened._load_from_config(selected_name=original.name)
reopened.show()
app.processEvents()
assert [row[0].currentData() for row in reopened._trigger_delivery_panels] == ['tts']*3
assert reopened._trigger_tts_voice.currentData() == 'Missing retained voice'
assert [reopened._trigger_tts_volume.value(),reopened._trigger_ending_volume.value(),reopened._trigger_ended_volume.value()] == [61,72,83]
assert [reopened._trigger_tts_pitch.value(),reopened._trigger_ending_pitch.value(),reopened._trigger_ended_pitch.value()] == [-2,3,1]

spoken, played = [], []
spells_module.speak_text = lambda *args,**kwargs: spoken.append((args,kwargs)) or True
spells_module.play_alert = lambda *args,**kwargs: played.append((args,kwargs)) or True
parser = app._parsers_dict['spells']
for phase in ('basic','ending','ended'):
    prefix = '' if phase == 'basic' else 'timer_'+phase+'_'
    speech = saved.tts_text if phase == 'basic' else getattr(saved,prefix+'tts')
    interrupt = saved.interrupt_speech if phase == 'basic' else getattr(saved,prefix+'interrupt')
    assert parser._deliver_custom_trigger_audio(saved,phase,sound,speech,interrupt,'Synthetic test') == 'Text-to-speech'
assert not played and [call[0][0] for call in spoken] == ['Chosen basic','Chosen ending','Chosen ended']
assert [call[0][1] for call in spoken] == [61,72,83]
assert [call[1]['pitch'] for call in spoken] == [-2,3,1]

reopened._trigger_audio_muted.setChecked(True)
reopened._save_trigger()
muted = reopened._custom_triggers[original.name]
assert muted.delivery == muted.timer_ending_delivery == muted.timer_ended_delivery == 'tts'
for phase in ('basic','ending','ended'):
    assert muted.audio_delivery(phase) == 'off'
    assert parser._deliver_custom_trigger_audio(muted,phase,sound,'Muted text',False,'Synthetic muted') == ''
assert len(spoken) == 3 and not played
reopened._trigger_audio_muted.setChecked(False)
reopened._trigger_delivery.setCurrentIndex(reopened._trigger_delivery.findData('off'))
reopened._save_trigger()
off = reopened._custom_triggers[original.name]
assert off.delivery == 'off' and off.tts_text == 'Chosen basic' and off.sound_path == sound
assert parser._deliver_custom_trigger_audio(off,'basic',sound,off.tts_text,False,'Synthetic off') == ''
assert len(spoken) == 3 and not played

iterator = QTreeWidgetItemIterator(reopened._triggers)
while iterator.value():
    item = iterator.value()
    if item.data(0,TRIGGER_ITEM_KIND) == 'group' and item.data(0,TRIGGER_ITEM_ID) == 'Raid/Voice':
        reopened._triggers.setCurrentItem(item)
        break
    iterator += 1
assert reopened._current_trigger is None
reopened._category_scope.setCurrentText('OtherCharacter')
draft_before = copy.deepcopy(config.data['spells']['custom_timers'])
reopened._trigger_delivery.setCurrentIndex(reopened._trigger_delivery.findData('tts'))
reopened._save_trigger()
assert config.data['spells']['custom_timers'] == draft_before

# Legacy GINA rows may keep both WAV and TTS values, while their selected
# delivery remains explicit and editable. Empty library/group selection does
# not lock the pickers or alter the saved trigger when a group is saved.
legacy = CustomTrigger('Legacy voice','legacy','00:01:00',delivery='legacy',tts_text='Legacy text',
                       timer_ending_delivery='legacy',timer_ending_tts='Legacy ending',
                       timer_ended_delivery='legacy',timer_ended_sound=sound,timer_ended_tts='Legacy ended')
reopened._display_trigger(legacy)
assert [row[0].currentData() for row in reopened._trigger_delivery_panels] == ['tts','tts','sound']
assert all(row[0].isEnabled() for row in reopened._trigger_delivery_panels), [
    (row[0].accessibleName(), row[0].isEnabled(),repr(row[0].parentWidget())) for row in reopened._trigger_delivery_panels]
assert reopened._trigger_ended_tts.text() == 'Legacy ended'
reopened._display_trigger(CustomTrigger('Blank','blank',delivery='legacy'))
assert [row[0].currentData() for row in reopened._trigger_delivery_panels] == ['off']*3
assert reopened._trigger_delivery.isEnabled()
assert not reopened._trigger_ending_delivery.isEnabled() and not reopened._trigger_ended_delivery.isEnabled()

dialog = reopened
view = dialog._dialog_view
dialog._add_trigger()
assert dialog._trigger_timer_type.currentData() == 'none'
dialog._trigger_name.setText('New speech alert')
dialog._trigger_text.setText('new synthetic match')
dialog._action_tabs.setCurrentIndex(0)
app.processEvents()
choose_audio(dialog._trigger_delivery,'tts')
dialog._trigger_tts.setText('New voice message')
click_widget(dialog._save_trigger_button)
assert dialog._custom_triggers['New speech alert'].delivery == 'tts'
assert dialog._custom_triggers['New speech alert'].timer_type == 'none'
assert dialog._custom_triggers['New speech alert'].tts_text == 'New voice message'

finish_qt_audit(app, {'scale':dialog.uniform_scale,'dpi_factor':os.environ.get('QT_SCALE_FACTOR','1'),
                  'pointer_phases':checks,'keyboard_phases':checks,'save_reopen_retains_audio':True,
                  'runtime_uses_selected_tts':True,'mute_off_retains_choices':True,'group_cannot_change_delivery':True,
                  'legacy_audio_loads_without_locking':True,'new_voice_alert_saves_without_timer':True}, retained_windows)
'''


@pytest.mark.parametrize(
    ("dialog_scale", "dpi_factor"),
    ((0.8, 1.0), (1.0, 1.0), (1.25, 1.25), (1.5, 1.5)),
)
def test_real_trigger_delivery_pointer_keyboard_save_and_runtime(
        tmp_path, dialog_scale, dpi_factor):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ACCESSIBILITY"] = "0"
    env["QT_SCALE_FACTOR"] = str(dpi_factor)
    env["VANTAGE_TTS_AUDIT_SCALE"] = str(dialog_scale)
    env["TEMP"] = env["TMP"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", QT_AUDIT_LIFECYCLE + SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=80)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["scale"] == pytest.approx(dialog_scale)
    assert result["pointer_phases"] == ["basic", "ending", "ended"]
    assert result["keyboard_phases"] == ["basic", "ending", "ended"]
    for check in (
            "save_reopen_retains_audio", "runtime_uses_selected_tts",
            "mute_off_retains_choices", "group_cannot_change_delivery",
            "legacy_audio_loads_without_locking",
            "new_voice_alert_saves_without_timer"):
        assert result[check] is True


SOUNDS_SCRIPT = r'''
import copy
import json
import os
from types import SimpleNamespace
from native_audit_fixture import isolate

profile = isolate()
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings
from vantage.helpers.portable import store_portable_bytes
from vantage.helpers.settings import SettingsWindow, CustomTriggerSettings, SettingsSignals
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, Spells

app = QApplication([])
app._signals = {'settings': SettingsSignals()}
from PySide6.QtGui import QFont, QFontDatabase
for path in ('data/fonts/NotoSans-Regular.ttf','data/fonts/NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(path)
interface_font = QFont('Noto Sans')
interface_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
interface_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
app.setFont(interface_font)
app.show_device_sync = lambda: None
app.arrange_notification_overlays = lambda: None
app.show_overlay_notification = lambda *_args,**_kwargs: None
app.manage_notification_overlays = lambda *_args,**_kwargs: None
VantageApp._apply_theme(app)
class RuntimeAudio:
    _deliver_custom_trigger_audio = Spells._deliver_custom_trigger_audio
app._parsers_dict = {'spells': RuntimeAudio()}
# The real Windows accessibility bridge can fault while an offscreen test
# process exits. Verify visible/accessibility status fields, without sending
# synthetic announcements to that native bridge.
settings.QAccessible.updateAccessibility = lambda *_args: None
settings.speech_voice_names = lambda: ['Synthetic voice']
wav = store_portable_bytes(b'RIFF'+(4).to_bytes(4,'little')+b'WAVEtest','retained.wav',subdir='sounds')
wave = CustomTrigger('WAV and voice','synthetic {Actor}','00:01:00',category='Raid/Voice',
                     delivery='sound',sound_path=wav,tts_text='Basic {Actor}',tts_voice='Missing saved voice',
                     tts_volume=64,tts_pitch=2,interrupt_speech=True,
                     timer_ending_seconds=15,timer_ending_delivery='tts',timer_ending_sound=wav,
                     timer_ending_tts='Ending {Actor}',timer_ending_voice='Synthetic voice',
                     timer_ending_volume=73,timer_ending_pitch=-3,
                     timer_ended_delivery='off',timer_ended_sound=wav,timer_ended_tts='Ended {Actor}',
                     timer_ended_volume=82,timer_ended_pitch=1,timer_ended_interrupt=True)
tts = CustomTrigger('Voice only','voice only','',delivery='tts',tts_text='Only voice',tts_volume=55)
blank = CustomTrigger('Blank off','blank','',delivery='off',tts_text='Retained off message')
legacy = CustomTrigger('Legacy retained','legacy','',sound_path=wav,tts_text='Legacy retained text')
config.data['spells']['custom_timers'] = [row.to_list() for row in (wave,tts,blank,legacy)]
config.data['spells']['trigger_groups'] = {'Raid':{'enabled':True,'profiles':{'OtherCharacter':False}},
    'Raid/Voice':{'enabled':True,'profile_styles':{'OtherCharacter':{'font_color':'#DF706A'}}}}
groups_before = copy.deepcopy(config.data['spells']['trigger_groups'])
original_rows = copy.deepcopy(config.data['spells']['custom_timers'])
window = SettingsWindow('Sounds')
retained_windows = [window]
scale = float(os.environ.get('VANTAGE_SOUNDS_AUDIT_SCALE','0.8'))
window.resize(QSize(round(window._dialog_design_size.width()*scale),round(window._dialog_design_size.height()*scale)))
window.show()
QTest.qWait(30)

def route_for(name,stage='basic',owner=None):
    return next(route for route in (owner or window)._trigger_audio_routes
                if route['name'] == name and route['stage'] == stage)

def click_widget(widget,point=None,owner=None):
    owner = owner or window
    area = owner._widget_stack.currentWidget()
    area.ensureWidgetVisible(widget)
    app.processEvents()
    QTest.qWait(40)
    logical = widget.mapTo(owner.scaled_surface,point or widget.rect().center())
    target = owner._dialog_view.mapFromScene(owner._dialog_proxy.mapToScene(logical))
    assert owner._dialog_view.viewport().rect().contains(target), (widget.accessibleName(),target)
    QTest.mouseMove(owner._dialog_view.viewport(),target)
    QTest.qWait(20)
    QTest.mouseClick(owner._dialog_view.viewport(),Qt.MouseButton.LeftButton,pos=target)
    app.processEvents()

def choose(route,mode,owner=None):
    owner = owner or window
    combo = route['delivery']
    click_widget(combo,QPoint(combo.width()-10,combo.height()//2),owner)
    QTest.qWait(220)
    dropdown = combo.view()
    assert dropdown.isVisible()
    capture_dir = os.environ.get('VANTAGE_TRIGGER_CAPTURE_DIR')
    if capture_dir and route['stage'] == 'basic' and route['name'] == wave.name:
        from pathlib import Path
        assert owner.grab().save(str(Path(capture_dir)/('sounds-trigger-dropdown-'+str(round(scale*100))+'.png')))
    popup = next(item for item in owner._dialog_scene.items()
                 if item is not owner._dialog_proxy and item.isVisible() and
                 item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsPanel)
    index = combo.model().index(combo.findData(mode),0)
    row = dropdown.visualRect(index)
    target = owner._dialog_view.mapFromScene(popup.mapToScene(
        dropdown.viewport().mapTo(dropdown.window(),row.center())))
    QTest.mouseMove(owner._dialog_view.viewport(),target)
    QTest.qWait(30)
    QTest.mouseClick(owner._dialog_view.viewport(),Qt.MouseButton.LeftButton,pos=target)
    app.processEvents()
    QTest.qWait(40)
    assert combo.currentData() == mode
    assert route['speech_host'].isVisible() == (mode == 'tts')
    assert route['sound_host'].isVisible() == (mode == 'sound')

assert len(window._trigger_audio_routes) == 6
assert route_for(tts.name)['delivery'].currentData() == 'tts'
assert route_for(blank.name)['delivery'].currentData() == 'off'
assert route_for(legacy.name)['delivery'].currentData() == 'sound'
assert route_for(wave.name)['voice'].currentData() == 'Missing saved voice'
assert [route_for(wave.name,phase)['delivery'].itemData(i) for phase in ('basic',) for i in range(3)] == ['sound','tts','off']

# Draft editing is reversible, including Text to speech and its parameters.
basic = route_for(wave.name)
choose(basic,'tts')
click_widget(basic['text'])
QTest.keyClick(window._dialog_view.viewport(),Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
QTest.keyClicks(window._dialog_view.viewport(),'Cancelled text')
basic['volume'].setValue(25)
basic['pitch'].setValue(-8)
window._cancelled()
assert config.data['spells']['custom_timers'] == original_rows
window.show()
app.processEvents()
assert basic['delivery'].currentData() == 'sound'
assert basic['text'].text() == 'Basic {Actor}' and basic['volume'].value() == 64 and basic['pitch'].value() == 2

calls, played = [], []
settings.speak_text = lambda *args,**kwargs: calls.append((args,kwargs)) or True
settings.play_alert = lambda *args,**kwargs: played.append((args,kwargs)) or True
choose(basic,'tts')
assert not settings.audio_preflight('tts',text='muted',volume=64,channel='spells',allow_hidden=True).ready
window._test_trigger_audio_route(basic)
assert not calls and not played
settings.audio_preflight = lambda *args,**kwargs: SimpleNamespace(ready=True,reason='')

for phase in ('basic','ending','ended'):
    route = route_for(wave.name,phase)
    choose(route,'tts')
    route['text'].setText('Saved '+phase+(' ${Actor}' if phase == 'basic' else ' {Actor}'))
    result = window._test_trigger_audio_route(route)
    assert route['status'].textFormat() == Qt.TextFormat.PlainText
    assert route['status'].text() == route['status'].accessibleName() == result
    assert route['status'].isVisible()
assert len(calls) == 3 and not played
assert [call[0][0] for call in calls] == ['Saved basic sample','Saved ending sample','Saved ended sample']
assert [call[0][1] for call in calls] == [64,73,82]
assert [call[1]['pitch'] for call in calls] == [2,-3,1]
assert calls[0][1]['voice_name'] == 'Missing saved voice'
assert all(call[1]['allow_hidden'] and call[1]['channel'] == 'spells' for call in calls)

mute = dict(window._trigger_audio_mutes)[wave.name]
mute.setChecked(True)
assert 'this trigger is muted' in window._test_trigger_audio_route(basic)
assert len(calls) == 3
mute.setChecked(False)
choose(basic,'off')
assert 'audio Off' in window._test_trigger_audio_route(basic) and len(calls) == 3
choose(basic,'tts')
basic['delivery'].setFocus()
QTest.keyClick(window._dialog_view.viewport(),Qt.Key.Key_Home)
assert basic['delivery'].currentData() == 'sound'
QTest.keyClick(window._dialog_view.viewport(),Qt.Key.Key_Down)
assert basic['delivery'].currentData() == 'tts'

basic['delivery'].setFocus()
tabbed = []
for _ in range(len(window._scoped_focus_controls)+2):
    control = window.scaled_surface.focusWidget()
    tabbed.append(control)
    if control is window._save_button:
        break
    QTest.keyClick(window._dialog_view.viewport(),Qt.Key.Key_Tab)
    app.processEvents()
assert window._save_button in tabbed
assert all(basic[key] in tabbed for key in ('delivery','test','text','voice','volume','pitch','interrupt'))

capture_dir = os.environ.get('VANTAGE_TRIGGER_CAPTURE_DIR')
if capture_dir:
    from pathlib import Path
    window._widget_stack.currentWidget().ensureWidgetVisible(basic['delivery'])
    app.processEvents()
    QTest.qWait(40)
    assert window.grab().save(str(Path(capture_dir)/('sounds-trigger-text-to-speech-'+str(round(scale*100))+'.png')))

# Save should merge by trigger name when an unrelated setting changes while
# this window is open, and should not convert untouched legacy rows.
row = next(row for row in config.data['spells']['custom_timers'] if row[0] == wave.name)
external = CustomTrigger(*row)
external.comments = 'Concurrent comment preserved'
external.match_cooldown_seconds = 2.5
row[:] = external.to_list()
window._save()
assert config.data['spells']['trigger_groups'] == groups_before
assert config.data['general']['audio_muted'] is True and config.data['general']['master_volume'] == 0
saved = next(CustomTrigger(*row) for row in config.data['spells']['custom_timers'] if row[0] == wave.name)
assert saved.delivery == saved.timer_ending_delivery == saved.timer_ended_delivery == 'tts'
assert [saved.sound_path,saved.timer_ending_sound,saved.timer_ended_sound] == [wav]*3
assert [saved.tts_text,saved.timer_ending_tts,saved.timer_ended_tts] == ['Saved basic ${Actor}','Saved ending {Actor}','Saved ended {Actor}']
assert saved.comments == 'Concurrent comment preserved' and saved.match_cooldown_seconds == 2.5
assert next(CustomTrigger(*row) for row in config.data['spells']['custom_timers'] if row[0] == legacy.name).delivery == 'legacy'

window = SettingsWindow('Sounds')
retained_windows.append(window)
window.show()
app.processEvents()
window.resize(QSize(round(window._dialog_design_size.width()*scale),round(window._dialog_design_size.height()*scale)))
QTest.qWait(30)
assert [route_for(wave.name,phase)['delivery'].currentData() for phase in ('basic','ending','ended')] == ['tts']*3
editor = CustomTriggerSettings()
retained_windows.append(editor)
editor._load_from_config(selected_name=wave.name)
assert [row[0].currentData() for row in editor._trigger_delivery_panels] == ['tts']*3
assert editor._trigger_tts.text() == 'Saved basic ${Actor}'

spoken = []
spells_module.speak_text = lambda *args,**kwargs: spoken.append((args,kwargs)) or True
spells_module.play_alert = lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('Inactive WAV played'))
parser = app._parsers_dict['spells']
for phase in ('basic','ending','ended'):
    fields = window._trigger_audio_fields(phase)
    assert parser._deliver_custom_trigger_audio(saved,phase,getattr(saved,fields['sound']),
        getattr(saved,fields['text']),getattr(saved,fields['interrupt']),'Synthetic dispatch') == 'Text-to-speech'
assert len(spoken) == 3

basic = route_for(wave.name)
choose(basic,'off')
dict(window._trigger_audio_mutes)[wave.name].setChecked(True)
window._save()
off = next(CustomTrigger(*row) for row in config.data['spells']['custom_timers'] if row[0] == wave.name)
assert off.delivery == 'off' and off.audio_muted is True
assert off.tts_text == 'Saved basic ${Actor}' and off.sound_path == wav
assert off.timer_ending_delivery == off.timer_ended_delivery == 'tts'
assert parser._deliver_custom_trigger_audio(off,'ending',wav,off.timer_ending_tts,False,'Muted') == ''
assert len(spoken) == 3

finish_qt_audit(app, {'sounds_tts_option_selectable':True,'all_phases':True,'tts_only_off_and_legacy_visible':True,
    'draft_cancel_restores':True,'preview_routes_selected_audio':True,'mute_off_preserve_choices':True,
    'save_reopen_editor_runtime_match':True,'inactive_wav_retained':True,'concurrent_fields_retained':True,
    'keyboard_reaches_speech_fields_and_save':True}, retained_windows)
'''


@pytest.mark.parametrize(
    ("dialog_scale", "dpi_factor"),
    ((0.8, 1.0), (1.0, 1.0), (1.25, 1.25), (1.5, 1.5)),
)
def test_sounds_trigger_tts_delivery_draft_preview_save_and_keyboard(
        tmp_path, dialog_scale, dpi_factor):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ACCESSIBILITY"] = "0"
    env["QT_SCALE_FACTOR"] = str(dpi_factor)
    env["VANTAGE_SOUNDS_AUDIT_SCALE"] = str(dialog_scale)
    env["TEMP"] = env["TMP"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", QT_AUDIT_LIFECYCLE + SOUNDS_SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=80)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert all(result.values()), result


LEGACY_SPEECH_EDIT_SCRIPT = r'''
import json
import os
from types import SimpleNamespace
from native_audit_fixture import isolate

isolate()
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from vantage.helpers.application import VantageApp
from vantage.helpers import config, settings
from vantage.helpers.settings import SettingsWindow, SettingsSignals
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, Spells

app = QApplication([])
app._signals = {'settings': SettingsSignals()}
for path in ('data/fonts/NotoSans-Regular.ttf','data/fonts/NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(path)
font = QFont('Noto Sans')
font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
app.setFont(font)
VantageApp._apply_theme(app)
app.show_device_sync = lambda: None
app.arrange_notification_overlays = lambda: None
app.show_overlay_notification = lambda *_args,**_kwargs: None
app.manage_notification_overlays = lambda *_args,**_kwargs: None
settings.QAccessible.updateAccessibility = lambda *_args: None
settings.speech_voice_names = lambda: []
settings.audio_preflight = lambda *_args,**_kwargs: SimpleNamespace(ready=True,reason='')
preview = []
settings.speak_text = lambda *args,**kwargs: preview.append((args,kwargs)) or True
settings.play_alert = lambda *_args,**_kwargs: (_ for _ in ()).throw(AssertionError('Inactive Sound dispatched'))

class RuntimeAudio:
    _deliver_custom_trigger_audio = Spells._deliver_custom_trigger_audio
runtime = RuntimeAudio()
app._parsers_dict = {'spells': runtime}
edited = CustomTrigger('Legacy speech edit','legacy edit','00:01:00',
    tts_text='Basic legacy speech',timer_ending_seconds=10,
    timer_ending_tts='Ending legacy speech',timer_ended_tts='Ended legacy speech')
untouched = CustomTrigger('Untouched legacy speech','untouched','00:01:00',
    tts_text='Untouched basic',timer_ending_seconds=10,
    timer_ending_tts='Untouched ending',timer_ended_tts='Untouched ended')
inactive = CustomTrigger('Inactive saved speech','inactive','',
    sound_path='builtin:crystal-ping',tts_text='Inactive message')
voice_with_wave = CustomTrigger('Legacy voice with inactive WAV','voice wave','',tts_text='Selected speech')
silent = CustomTrigger('Legacy Off with inactive speech','silent','')
concurrent = CustomTrigger('Concurrent legacy speech','concurrent','00:01:00',
    tts_text='Concurrent basic',timer_ending_seconds=10,
    timer_ending_tts='Concurrent ending',timer_ended_tts='Concurrent ended')
original_untouched = untouched.to_list()
config.data['spells']['custom_timers'] = [trigger.to_list() for trigger in
    (edited,untouched,inactive,voice_with_wave,silent,concurrent)]
config.data['spells']['fade_sound_volume'] = 37
window = SettingsWindow('Sounds')

def route_for(name,stage='basic'):
    return next(route for route in window._trigger_audio_routes
                if route['name'] == name and route['stage'] == stage)

def stored(name):
    return CustomTrigger(*next(row for row in config.data['spells']['custom_timers'] if row[0] == name))

# Edit only volume; leave the resolved TTS selector exactly as it opened.
for stage in ('basic','ending','ended'):
    route = route_for(edited.name,stage)
    assert route['delivery'].currentData() == 'tts' and route['volume'].value() == 100
    route['volume'].setValue(42)
    assert route['delivery'].currentData() == route['saved']['delivery'] == 'tts'
    route['test'].click()
assert [call[0][1] for call in preview] == [42,42,42]

# Change inactive speech, then return to the initial Sound choice.
route = route_for(inactive.name)
route['delivery'].setCurrentIndex(route['delivery'].findData('tts'))
route['text'].setText('Retained inactive edit')
route['delivery'].setCurrentIndex(route['delivery'].findData('sound'))

# Add an inactive WAV, then return to the initial TTS choice.
route = route_for(voice_with_wave.name)
assert route['delivery'].currentData() == route['saved']['delivery'] == 'tts'
route['delivery'].setCurrentIndex(route['delivery'].findData('sound'))
route['sound'].setCurrentIndex(route['sound'].findData('builtin:crystal-ping'))
route['delivery'].setCurrentIndex(route['delivery'].findData('tts'))
assert route['delivery'].currentData() == route['saved']['delivery'] == 'tts'

# Retain edited speech while returning to the initial Off choice.
route = route_for(silent.name)
assert route['delivery'].currentData() == route['saved']['delivery'] == 'off'
route['delivery'].setCurrentIndex(route['delivery'].findData('tts'))
route['text'].setText('Retained silent speech')
route['delivery'].setCurrentIndex(route['delivery'].findData('off'))

# Another editor changes explicit modes while this legacy draft stays open.
for stage in ('basic','ending','ended'):
    route_for(concurrent.name,stage)['volume'].setValue(42)
row = next(row for row in config.data['spells']['custom_timers'] if row[0] == concurrent.name)
external = CustomTrigger(*row)
external.delivery = 'sound'
external.timer_ending_delivery = 'off'
external.timer_ended_delivery = 'tts'
external.sound_path = 'builtin:crystal-ping'
external.comments = 'Concurrent comment retained'
row[:] = external.to_list()

# The real Save path merges every dirty phase in one editing session.
window._save()
saved = stored(edited.name)
assert saved.delivery == saved.timer_ending_delivery == saved.timer_ended_delivery == 'tts'
assert next(row for row in config.data['spells']['custom_timers'] if row[0] == untouched.name) == original_untouched
inactive_saved = stored(inactive.name)
assert inactive_saved.delivery == 'sound'
assert inactive_saved.sound_path == 'builtin:crystal-ping' and inactive_saved.tts_text == 'Retained inactive edit'
voice_saved = stored(voice_with_wave.name)
assert voice_saved.delivery == voice_saved.audio_delivery() == 'tts'
assert voice_saved.sound_path == 'builtin:crystal-ping' and voice_saved.tts_text == 'Selected speech'
silent_saved = stored(silent.name)
assert silent_saved.delivery == silent_saved.audio_delivery() == 'off' and silent_saved.tts_text == 'Retained silent speech'
merged = stored(concurrent.name)
assert [merged.delivery,merged.timer_ending_delivery,merged.timer_ended_delivery] == ['sound','off','tts']
assert [merged.tts_volume,merged.timer_ending_volume,merged.timer_ended_volume] == [42,42,42]
assert merged.sound_path == 'builtin:crystal-ping' and merged.comments == 'Concurrent comment retained'
assert config.data['spells']['fade_sound_volume'] == 37

spoken, played = [], []
spells_module.speak_text = lambda *args,**kwargs: spoken.append((args,kwargs)) or True
spells_module.play_alert = lambda *args,**kwargs: played.append((args,kwargs)) or True
for stage in ('basic','ending','ended'):
    fields = window._trigger_audio_fields(stage)
    assert runtime._deliver_custom_trigger_audio(saved,stage,getattr(saved,fields['sound']),
        getattr(saved,fields['text']),getattr(saved,fields['interrupt']),'Synthetic legacy') == 'Text-to-speech'
assert [call[0][1] for call in spoken] == [call[0][1] for call in preview] == [42,42,42]
assert runtime._deliver_custom_trigger_audio(voice_saved,'basic',voice_saved.sound_path,
    voice_saved.tts_text,False,'Synthetic retained WAV') == 'Text-to-speech'
assert len(spoken) == 4 and not played
assert runtime._deliver_custom_trigger_audio(silent_saved,'basic','',silent_saved.tts_text,
    False,'Synthetic retained Off') == ''
assert len(spoken) == 4 and not played
assert runtime._deliver_custom_trigger_audio(inactive_saved,'basic',inactive_saved.sound_path,
    inactive_saved.tts_text,False,'Synthetic retained Sound').startswith('Sound')
assert len(spoken) == 4 and len(played) == 1
finish_qt_audit(app, {'legacy_visible_volume_test_equals_runtime_all_phases':True,
    'untouched_legacy_preserved':True,'inactive_audio_choices_preserved':True,
    'edited_legacy_sound_tts_off_remain_selected':True,
    'concurrent_explicit_modes_preserved':True}, [window])
'''


def test_legacy_speech_field_edit_commits_visible_phase_volume_and_retains_modes(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ACCESSIBILITY"] = "0"
    env["QT_SCALE_FACTOR"] = "1.0"
    env["TEMP"] = env["TMP"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", QT_AUDIT_LIFECYCLE + LEGACY_SPEECH_EDIT_SCRIPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert all(result.values()), result
