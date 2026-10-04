"""Premium audio feedback, lossless replay and compact orientation regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from vantage.helpers.application import VantageApp
from vantage.helpers.audio import AudioPreflightResult, AudioReplayDescriptor
from vantage.parsers import spells as sm
from vantage.parsers.spells import CustomTrigger, Spells

ROOT = Path(__file__).resolve().parents[1]


def test_replay_keeps_full_text_raw_volume_voice_profile_and_async_identity(monkeypatch):
    from vantage.helpers import application as am
    phrase = "Full speech must remain intact, including this final sentence after sixty characters."
    descriptor = AudioReplayDescriptor(
        "voice", phrase, 80, character="Mindflux", server="Green",
        channel="spells", voice_name="Fixture Voice", pitch=-2)
    host = SimpleNamespace(
        _refresh_quickbar=lambda: None,
        show_overlay_notification=lambda *_a, **_k: None)
    VantageApp.audio_started(
        host, "Long alert", "tts:" + phrase[:60], 40, "spells",
        visual_registered=True, replay_data=descriptor)
    original = host._last_audio_event
    original_label = host._last_audio
    calls = []
    monkeypatch.setattr(am, "audio_preflight",
                        lambda *_a, **_k: AudioPreflightResult("voice", "ready", True))
    monkeypatch.setattr(am, "speak_text",
                        lambda *a, **k: calls.append((a, k)) or True)
    assert VantageApp.show_last_sound(host)
    args, kwargs = calls[0]
    assert args == (phrase, 80)
    assert kwargs["character"] == "Mindflux"
    assert kwargs["server"] == "Green"
    assert kwargs["voice_name"] == "Fixture Voice"
    assert kwargs["pitch"] == -2
    assert kwargs["replay"] is True
    from dataclasses import replace
    # Native voice callback arrives after the replay method has returned.
    VantageApp.audio_started(
        host, "Replay · Long alert", "tts:" + phrase[:60], 40, "spells",
        visual_registered=True, replay_data=replace(descriptor, is_replay=True))
    assert host._last_audio_event == original
    assert host._last_audio == original_label
    assert host._last_audio_replay is descriptor


@pytest.mark.parametrize("stage", ["ending", "ended"])
@pytest.mark.parametrize("muted", [False, True])
def test_timer_written_stage_survives_audio_off_and_individual_mute(monkeypatch, stage, muted):
    notices, overlays = [], []
    host = SimpleNamespace(
        _queue_quickbar_notice=lambda text, **k: notices.append(text),
        show_overlay_notification=lambda *_a, **k: overlays.append(k))
    monkeypatch.setattr(sm, "QApplication",
                        SimpleNamespace(instance=lambda: host))
    trigger = CustomTrigger(name="Enrage", audio_muted=muted,
                            timer_ending_delivery="off", timer_ended_delivery="off",
                            overlay_id="none")
    owner = SimpleNamespace(
        _custom_trigger_has_audio=Spells._custom_trigger_has_audio,
        _deliver_custom_trigger_audio=lambda *_a, **_k: "",
        _record_trigger_match=lambda *_a, **_k: None)
    run = {"trigger": trigger, "name": "Enrage", "ending_text": "Enrage soon",
           "ended_text": "Enrage ended", "ending_tts": "", "ended_tts": ""}
    Spells._fire_trigger_stage(owner, run, stage)
    assert notices == ["Enrage soon" if stage == "ending" else "Enrage ended"]
    assert not overlays


NATIVE_SCRIPT = r"""
import datetime, json, os
from pathlib import Path
from types import SimpleNamespace
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from vantage.helpers import config, log_monitor as lm, settings as st, application as am
from vantage.helpers.application import VantageApp
from vantage.helpers.audio import set_audio_muted
from vantage.helpers.log_monitor import LogMonitorDialog
from vantage.helpers.settings import CustomTriggerSettings
from vantage.parsers.spells import CustomTrigger, Spell

app = VantageApp([])
config.data["general"]["audio_muted"] = False
config.data["general"]["master_volume"] = 100
set_audio_muted(False)
config.data["spells"]["fade_sound_volume"] = 80
config.data["spells"]["fade_sound_enabled"] = True
config.data["spells"]["sounds_when_hidden"] = False
calls = []
st.speak_text = lambda *a, **k: calls.append((a, k)) or True
st.play_alert = lambda *a, **k: calls.append((a, k)) or True
editor = CustomTriggerSettings()
editor._display_trigger(CustomTrigger(
    name="Example", text="example", delivery="tts", tts_text="Example voice",
    tts_volume=0, overlay_id="none"))
assert "Alert volume 0%" in editor._test_trigger_action()
assert not calls
status = QLabel()
result = editor._test_trigger_speech(
    editor._trigger_tts, editor._trigger_interrupt_speech, editor._trigger_tts_voice,
    editor._trigger_tts_volume, editor._trigger_tts_pitch, "Test", "Example", status)
assert "Alert volume 0%" in result
assert status.accessibleName() == result and not calls
editor._trigger_tts_volume.setValue(80)
assert "queued" in editor._test_trigger_action()
assert calls[-1][1]["allow_hidden"] is True
editor._trigger_audio_muted.setChecked(True)
assert "muted" in editor._test_trigger_action()
count = len(calls)
assert "muted" in editor._test_trigger_sound(editor._trigger_sound, "Test")
assert len(calls) == count
editor._trigger_audio_muted.setChecked(False)
editor._trigger_sound.setCurrentIndex(editor._trigger_sound.findData(""))
assert "Off" in editor._test_trigger_sound(editor._trigger_sound, "Test")

profile = {"character":"Mindflux", "server":"Green", "status":"ACTIVE",
           "last_write":"now", "size":100, "file":"synthetic-eqlog.txt"}
monitor = LogMonitorDialog(SimpleNamespace(
    _log_reader=SimpleNamespace(profiles=lambda: [profile])))
lm.speak_text = lambda *a, **k: calls.append((a, k)) or True
volume = monitor.table.cellWidget(0, 6)
volume.setValue(0)
monitor.table.cellWidget(0, 7).click()
assert "Character audio profile volume 0%" in monitor.test_status.text()
assert len(calls) == count
volume.setValue(100)
monitor.table.cellWidget(0, 7).click()
assert "voice queued" in monitor.test_status.text()
assert calls[-1][1]["allow_hidden"] is True
assert len(calls[-1][0]) == 2  # No implicit interrupt of active speech.

parser = app._parsers_dict["spells"]
parser._spell_container.add_spell(
    Spell(name="Fetter", duration=10, duration_formula=11, spell_icon=14),
    datetime.datetime.now(), "a fixture mob", "Mindflux", "Green")
row = parser._spell_container.get_spell_target_by_name("a fixture mob").spell_widget("fetter")
config.data["sounds"]["routes"]["spell_fading"]["delivery"] = "voice"
am.speak_text = lambda *a, **k: calls.append(("voice", a, k)) or True
am.play_alert = lambda *a, **k: calls.append(("sound", a, k)) or True
row._play_fade_alert(force=True)
assert calls[-1][0] == "voice"
assert calls[-1][2]["allow_hidden"] is True
before = len(calls)
config.data["sounds"]["routes"]["spell_fading"]["delivery"] = "off"
row._play_fade_alert(force=True)
assert len(calls) == before
config.data["sounds"]["routes"]["spell_fading"]["delivery"] = "voice"
config.data["spells"]["fade_sound_muted"].append("Fetter")
row._play_fade_alert(force=True)
assert len(calls) == before
print(json.dumps({"preview_status":True,"hidden_preview":True,"fade_route":True}))
app.quit()
"""


VERTICAL_SCRIPT = r"""
import json, os
from pathlib import Path
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter
from vantage.helpers import config
from vantage.helpers.application import VantageApp
app = VantageApp([])
bar = app._parsers_dict["quickbar"]
bar.show()
app.processEvents()
config.data["quickbar"]["show_notification_ticker"] = True
bar._last_orientation_toggle = 0
bar.orientation_button.click()
for _ in range(8): app.processEvents()
rail = bar.notification_rail
assert bar._orientation == "vertical"
assert bar.width() == bar._design_size.width() == 30
assert not rail.isVisible()
app._queue_quickbar_notice("Spirit of Wolf fading · Mindflux", channel="spells")
for _ in range(8): app.processEvents()
assert rail.isVisible() and rail.isWindow()
assert rail._current_text == "Spirit of Wolf fading · Mindflux"
assert bar.width() == 30
assert rail.width() == 320
bar._set_always_on_top(False)
for _ in range(8): app.processEvents()
assert not (rail.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
assert rail.isVisible()
bar._set_always_on_top(True)
for _ in range(8): app.processEvents()
assert rail.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
assert bar.frameGeometry().intersected(rail.frameGeometry()).isEmpty()
area = bar.screen().availableGeometry()
assert area.contains(rail.frameGeometry())
out = os.environ.get("VANTAGE_TEST_OUTPUT")
if out:
    target = Path(out); target.mkdir(parents=True, exist_ok=True)
    bar.grab().save(str(target/"quickbar-vertical-after.png"))
    rail.grab().save(str(target/"quickbar-vertical-notice-after.png"))
    sheet = QPixmap(364, max(bar.height(), rail.height()) + 16)
    sheet.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sheet)
    painter.drawPixmap(4, 4, bar.grab())
    painter.drawPixmap(40, max(4, bar.height()-rail.height()+4), rail.grab())
    painter.end()
    sheet.save(str(target/"quickbar-vertical-composite-after.png"))
bar.move(area.right()-bar.width()+1, max(area.top(), bar.y()))
app.processEvents()
assert area.contains(rail.frameGeometry())
bar.hide()
app.processEvents()
assert not rail.isVisible()
bar.show()
for _ in range(5): app.processEvents()
assert rail.isVisible()
rail._expire_current()
for _ in range(5): app.processEvents()
assert not rail.isVisible()
menu, actions = bar._build_window_context_menu()
assert "notification_history" in actions
bar._last_orientation_toggle = 0
bar.orientation_button.click()
for _ in range(8): app.processEvents()
assert bar._orientation == "horizontal"
assert not rail.isWindow()
assert rail.parentWidget() is bar._surface
bar._last_orientation_toggle = 0
bar.orientation_button.click()
for _ in range(8): app.processEvents()
# Migrate geometry saved by the old 240 px implementation without moving it.
config.data["quickbar"]["geometry"] = [bar.x(),bar.y(),240,bar.height()+19]
bar.apply_saved_presentation()
for _ in range(8): app.processEvents()
assert bar.width() == bar._design_size.width() == 30
assert not rail.isVisible()
saved_column = [bar.x(),bar.y(),45,bar._design_size.height()]
config.data['quickbar']['geometry'] = saved_column[:]
bar.apply_saved_presentation()
for _ in range(8): app.processEvents()
assert [bar.x(),bar.y(),bar.width(),bar.height()] == saved_column
print(json.dumps({"vertical_width":bar.width(),"flyout":True,"migrated":True}))
app.quit()
"""


def _run(script):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT/"tests"),str(ROOT/"src")))
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_native_audio_previews_honor_each_gate_and_actual_fade_route():
    assert _run(NATIVE_SCRIPT) == {
        "preview_status":True,"hidden_preview":True,"fade_route":True}


def test_actual_orientation_button_with_notifications_stays_one_column():
    assert _run(VERTICAL_SCRIPT) == {
        "vertical_width":45,"flyout":True,"migrated":True}


MAP_LOOT_SCRIPT = r"""
import json, os
from pathlib import Path
from types import SimpleNamespace
from native_audit_fixture import isolate
isolate()
from PySide6.QtWidgets import QWidget, QScrollArea
from vantage.helpers.application import VantageApp
from vantage.parsers.maps.window import MapLootDialog
app = VantageApp([])
opened = []
point = SimpleNamespace(label="Synthetic named mob",
                        location=SimpleNamespace(x=40,y=25,z=0))
dialog = MapLootDialog(point, {"drops":["Journeyman's Boots"]}, "Chardok",
                       opened.append, lambda: None)
dialog.show()
for _ in range(8): app.processEvents()
body = dialog.findChild(QWidget, "MapLootBody")
viewport = dialog.findChild(QScrollArea, "MapLootScroll").viewport()
image = body.grab().toImage()
color = image.pixelColor(image.width()//2, image.height()-5).name()
assert color == "#090a0c", color
assert viewport.objectName() == "MapLootViewport"
dialog.item_buttons[0].click()
assert opened == ["Journeyman's Boots"]
out = os.environ.get("VANTAGE_TEST_OUTPUT")
if out: dialog.grab().save(str(Path(out)/"map-loot-after.png"))
print(json.dumps({"body":color,"itemLink":True}))
dialog.close()
app.quit()
"""


def test_map_loot_scroll_body_is_dark_and_item_link_remains_active():
    assert _run(MAP_LOOT_SCRIPT) == {"body":"#090a0c","itemLink":True}
