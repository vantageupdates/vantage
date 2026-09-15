import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QLabel, QMessageBox

from vantage.helpers import config
from vantage.helpers.game_capture import GameWindowCapture
from vantage.helpers.quickbar_items import QUICKBAR_ITEMS
from vantage.helpers.vitals import (
    MIN_CONFIDENCE, VitalStopTracker, analyze_vital_bar,
    default_vital_bars, default_vital_stop, denormalize_rect,
    learn_fill_color, normalize_rect, preset_percentages,
    sanitize_vital_bars)
from vantage.parsers.vitals import (
    CalibrationControls, CalibrationOverlay, VitalStopDialog, Vitals)
import vantage.parsers.vitals as vitals_module


ROOT = Path(__file__).resolve().parents[1]


def _image(width=100, height=12, fill=60, rtl=False):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(12, 14, 18))
    start = width - fill if rtl else 0
    end = width if rtl else fill
    for x in range(start, end):
        for y in range(height):
            image.setPixelColor(x, y, QColor(205, 28, 35))
    return image


def _app():
    return QApplication.instance() or QApplication([])


def test_normalized_geometry_survives_window_move_resize_and_is_bounded():
    normalized = normalize_rect((200, 100, 400, 30), (1000, 500))
    assert normalized == [0.2, 0.2, 0.4, 0.06]
    assert denormalize_rect(normalized, (2000, 1000)) == (400, 200, 800, 60)
    assert denormalize_rect([.95, .95, .5, .5], (100, 100)) == (95, 95, 5, 5)


def test_pixel_reader_reports_ltr_rtl_and_rejects_missing_fill_color():
    ltr = analyze_vital_bar(_image(fill=62), [0, 0, 1, 1], [205, 28, 35])
    rtl = analyze_vital_bar(
        _image(fill=37, rtl=True), [0, 0, 1, 1], [205, 28, 35], "rtl")
    absent = analyze_vital_bar(_image(fill=60), [0, 0, 1, 1], [30, 210, 40])
    assert ltr.valid and ltr.percent == 62.0 and ltr.confidence >= MIN_CONFIDENCE
    assert rtl.valid and rtl.percent == 37.0 and rtl.confidence >= MIN_CONFIDENCE
    assert absent.valid is False and absent.percent is None
    assert "not visible" in absent.message.casefold()


def test_fill_color_learning_prefers_colored_fill_over_dark_background():
    color, confidence = learn_fill_color(
        _image(fill=70), [0, 0, 1, 1], "ltr")
    assert color
    assert color[0] > color[1] * 4
    assert confidence >= .5


def test_one_poll_monitors_every_enabled_saved_bar_from_the_same_frame():
    image = _image(fill=64)
    bars = default_vital_bars()
    for bar in bars:
        bar["rect"] = [0, 0, 1, 1]
        bar["color"] = [205, 28, 35]

    class Capture:
        def image_frame(self, **_kwargs):
            return ({"available": True, "message": "Reading"}, image, (0, 0, 100, 12))

    class Tracker:
        def __init__(self):
            self.seen = []

        def update(self, bar_id, percent, stops, confidence):
            self.seen.append((bar_id, percent, confidence))
            return []

    owner = type("Owner", (), {})()
    owner._capture = Capture()
    owner._bars = bars
    owner._cards = {}
    owner._readings = {}
    owner._tracker = Tracker()
    owner._last_live_frame = None
    owner._last_live_rect = ()
    owner._last_live_at = 0.0
    statuses = []
    owner._set_status = statuses.append
    owner._deliver_stop = lambda *_args: None

    Vitals.poll_now(owner)

    assert list(owner._readings) == [
        "my-hp", "my-mana", "target-hp", "group-hp"]
    assert [row[0] for row in owner._tracker.seen] == list(owner._readings)
    assert all(reading.valid for reading in owner._readings.values())
    assert statuses == ["ACTIVE · 4 live readings"]


def test_presets_and_crossing_hysteresis_cooldown_are_deterministic():
    assert preset_percentages("quarters") == [25, 50, 75, 100]
    assert preset_percentages("every10") == list(range(10, 101, 10))
    stop = default_vital_stop(50, "below")
    stop.update({"id": "low", "hysteresis": 3, "cooldown": 30})
    tracker = VitalStopTracker()
    assert tracker.update("hp", 60, [stop], now=0) == []
    assert [event[1] for event in tracker.update("hp", 49, [stop], now=1)] == ["below"]
    assert tracker.update("hp", 51, [stop], now=2) == []
    assert tracker.update("hp", 55, [stop], now=3) == []
    assert tracker.update("hp", 49, [stop], now=4) == []
    assert tracker.update("hp", 55, [stop], now=31) == []
    assert [event[1] for event in tracker.update("hp", 49, [stop], now=32)] == ["below"]
    # Untrusted frames neither alert nor mutate the crossing state.
    assert tracker.update("hp", 80, [stop], confidence=.2, now=80) == []


def test_vitals_config_defaults_and_corruption_are_sanitized(tmp_path, monkeypatch):
    original = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        config.data = {
            "vitals": {
                "bars": [{
                    "id": "bad id", "name": "", "type": "unknown",
                    "rect": [2, -1, 99, 0], "color": [-2, 999, "x"],
                    "direction": "up", "tolerance": 999,
                    "stops": [{
                        "percent": -50, "direction": "sideways",
                        "delivery": "voice", "volume": 900,
                        "pitch": -99, "cooldown": 99999,
                    }],
                }],
                "poll_ms": 1,
                "sounds_when_hidden": "yes",
            }
        }
        config.verify_settings()
        vitals = config.data["vitals"]
        bar = vitals["bars"][0]
        stop = bar["stops"][0]
        assert vitals["poll_ms"] == 200
        assert vitals["sounds_when_hidden"] is True
        assert bar["type"] == "custom" and bar["rect"] == []
        assert bar["direction"] == "ltr" and bar["tolerance"] == 180
        assert stop["percent"] == 0 and stop["direction"] == "below"
        assert stop["delivery"] == "tts"
        assert stop["volume"] == 100 and stop["pitch"] == -10
        assert stop["cooldown"] == 3600

        config.data = {}
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp", "my_mana", "target_hp", "group_hp"]
        assert config.data["vitals"]["toggled"] is False
    finally:
        config.data = original


def test_target_hp_is_a_default_and_existing_profiles_receive_it_once(
        tmp_path, monkeypatch):
    original = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        defaults = default_vital_bars()
        assert [(bar["name"], bar["type"]) for bar in defaults] == [
            ("My HP", "my_hp"), ("My Mana", "my_mana"),
            ("Target / Mob HP", "target_hp"),
            ("Group HP", "group_hp")]

        config.data = {
            "vitals": {
                "bars": [defaults[0]],
                "defaults_version": 0,
            }
        }
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp", "target_hp"]
        config.data["vitals"]["bars"] = [defaults[0]]
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp"]
    finally:
        config.data = original


def test_raw_capture_is_opt_in_independent_but_refuses_background():
    capture = object.__new__(GameWindowCapture)
    capture._lock = threading.Lock()
    capture._supported = True
    capture._enabled = False
    capture._target = ""
    capture._last_title = ""
    capture._last_message = ""
    capture._fps = 5
    capture._quality_profile = "hd"
    capture._max_width = 1920
    capture._quality = 86
    capture._find_window = lambda: (123, "EverQuest")
    capture._is_window_minimized = lambda _hwnd: False
    capture._game_is_foreground = lambda _hwnd: False
    capture._capture_image = lambda _hwnd: (_image(), (0, 0, 100, 12))
    status, image, rect = capture.image_frame(
        require_enabled=False, require_foreground=True)
    assert status["available"] is False
    assert image.isNull() and rect == ()
    assert "foreground" in status["message"]

    capture._game_is_foreground = lambda _hwnd: True
    status, image, rect = capture.image_frame(
        require_enabled=False, require_foreground=True)
    assert status["available"] is True
    assert not image.isNull() and rect == (0, 0, 100, 12)

    capture._game_is_foreground = lambda _hwnd: False
    status, image, rect = capture.image_frame(
        require_enabled=False, require_foreground=False)
    assert status["available"] is True
    assert not image.isNull() and rect == (0, 0, 100, 12)


def test_vitals_contains_no_game_input_automation_path():
    source = inspect.getsource(vitals_module).casefold()
    forbidden = ("sendinput", "postmessage", "mouse_event", "keybd_event")
    assert all(token not in source for token in forbidden)


def test_quickbar_catalog_exposes_independent_vitals_action_with_unique_icon():
    matches = [item for item in QUICKBAR_ITEMS if item[0] == "vitals"]
    assert matches == [("vitals", "Vitals Monitor", "ph-vitals", "windows")]
    keys = [item[0] for item in QUICKBAR_ITEMS]
    assert keys.index("timers") == keys.index("spells") + 1


def test_numeric_and_keyboard_calibration_are_equivalent_and_bounded(monkeypatch):
    _app()
    announcements = []
    monkeypatch.setattr(
        "vantage.parsers.vitals._announce",
        lambda _widget, message: announcements.append(message))
    bounds = QRect(100, 200, 800, 600)
    controls = CalibrationControls(bounds, QRect(180, 260, 160, 18))
    seen = []
    controls.geometry_changed.connect(lambda rect: seen.append(QRect(rect)))
    controls.x.setValue(90)
    assert seen[-1] == QRect(190, 260, 160, 18)
    controls.nudge(-1, 1)
    assert controls.absolute_rect() == QRect(189, 261, 160, 18)
    assert controls.x.accessibleName() == "Calibration X coordinate"

    overlay = CalibrationOverlay(bounds, QRect(180, 260, 160, 18))
    before = overlay.geometry()
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Right,
        Qt.KeyboardModifier.NoModifier))
    QTest.qWait(220)
    assert overlay.geometry().x() == before.x() + 1
    assert announcements and "Calibration area" in announcements[-1]
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Down,
        Qt.KeyboardModifier.AltModifier))
    assert overlay.geometry().height() == before.height() + 1
    assert "Arrow keys" in overlay.accessibleDescription()

    cancelled = []
    overlay.cancel_requested.connect(lambda: cancelled.append(True))
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier))
    assert cancelled == [True]
    overlay.close()
    controls.close()


def test_stop_editor_exposes_delivery_sound_tts_off_and_tokens(monkeypatch):
    _app()
    monkeypatch.setattr(
        "vantage.parsers.vitals.speech_voice_names", lambda: ["Voice One"])
    dialog = VitalStopDialog({
        "delivery": "tts", "tts_text": "{name} {percent} {direction}",
        "voice": "Voice One", "volume": 42, "pitch": -3,
    })
    assert [dialog.delivery.itemData(index) for index in range(3)] == [
        "sound", "tts", "off"]
    assert dialog.delivery.currentData() == "tts"
    assert dialog.tts_text.toolTip().find("{name}") >= 0
    value = dialog.value()
    assert value["voice"] == "Voice One"
    assert value["volume"] == 42 and value["pitch"] == -3
    assert dialog.sound.accessibleName() == "Vital alert sound gallery"
    dialog.show()
    _app().processEvents()
    dialog.delivery.setCurrentIndex(dialog.delivery.findData("sound"))
    _app().processEvents()
    assert dialog.volume.isVisibleTo(dialog)
    dialog.delivery.setCurrentIndex(dialog.delivery.findData("tts"))
    _app().processEvents()
    assert dialog.volume.isVisibleTo(dialog)
    dialog.close()


def test_runtime_delivery_passes_sound_and_tts_profile_controls(monkeypatch):
    played = []
    spoken = []
    monkeypatch.setattr(
        "vantage.parsers.vitals.play_alert",
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    monkeypatch.setattr(
        "vantage.parsers.vitals.speak_text",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    owner = type("Owner", (), {
        "_active_character": "Mindflux", "_active_server": "Green"})()
    sound = default_vital_stop(25)
    sound.update({"delivery": "sound", "sound": "builtin:soft-tick",
                  "volume": 37})
    assert Vitals._play_delivery(owner, sound, "My HP", 24, "below")
    assert played[0][0][:2] == ("builtin:soft-tick", 37)
    assert played[0][1]["channel"] == "vitals"
    assert played[0][1]["character"] == "Mindflux"
    assert played[0][1]["server"] == "Green"
    assert played[0][1]["allow_hidden"] is False

    voice = dict(sound)
    voice.update({
        "delivery": "tts", "tts_text": "{name}: {percent}, {direction}",
        "voice": "Narrator", "volume": 52, "pitch": 6})
    assert Vitals._play_delivery(owner, voice, "My Mana", 49.6, "above")
    assert spoken[0][0][:2] == ("My Mana: 50, above", 52)
    assert spoken[0][1]["voice_name"] == "Narrator"
    assert spoken[0][1]["pitch"] == 6
    assert spoken[0][1]["channel"] == "vitals"


def test_monitor_state_transitions_are_announced_once(monkeypatch):
    _app()
    announcements = []
    monkeypatch.setattr(
        "vantage.parsers.vitals._announce",
        lambda _widget, message: announcements.append(message))
    emitted = []
    owner = type("Owner", (), {})()
    owner._status_text = "NO READING · waiting"
    owner._status_badge = QLabel("NO READING")
    owner.status_changed = type("Signal", (), {
        "emit": lambda _self: emitted.append(True)})()
    Vitals._set_status(owner, "ACTIVE · 2 live readings")
    Vitals._set_status(owner, "ACTIVE · 2 live readings")
    assert announcements == ["ACTIVE · 2 live readings"]
    assert emitted == [True]


def test_application_registers_and_quickbar_toggles_vitals(tmp_path):
    script = r'''
import json
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from vantage.helpers.application import VantageApp

class NoReading:
    def image_frame(self, **_kwargs):
        return ({"available": False, "message": "EQ is not foreground"}, QImage(), ())
    def set_executable(self, _path):
        pass

app = VantageApp([])
vitals = app._parsers_dict["vitals"]
bar = app._parsers_dict["quickbar"]
vitals._capture = NoReading()
vitals.poll_now()
bar.refresh_state()
before = vitals.isVisible()
bar._trigger("vitals")
app.processEvents()
opened = (vitals.isVisible(), bar._buttons["vitals"].isChecked())
vitals.resize(240, 180)
app.processEvents()
vitals._update_uniform_scale()
responsive = {
    "width": vitals.width(),
    "surface_width": vitals._surface.width(),
    "scale": vitals._scale_view.transform().m11(),
    "button_height": vitals._cards["my-hp"].action_buttons["edit"].height(),
}
edit = vitals._cards["my-hp"].action_buttons["edit"]
vitals._focus_embedded_control(edit)
vitals._rebuild_cards()
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
restored_focus = focused.accessibleName() if focused is not None else ""
QMessageBox.question = staticmethod(
    lambda *_args: QMessageBox.StandardButton.Yes)
vitals._remove_bar("my-hp")
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
remove_focus = focused.accessibleName() if focused is not None else ""
vitals._rebuild_cards(("my-mana", "calibrate"))
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
calibration_focus = focused.accessibleName() if focused is not None else ""
bar._trigger("vitals")
app.processEvents()
closed = (vitals.isVisible(), bar._buttons["vitals"].isChecked())
print(json.dumps({
    "registered": vitals in app._parsers,
    "before": before, "opened": opened, "closed": closed,
    "tooltip": bar._buttons["vitals"].toolTip(),
    "status": vitals.quickbar_status(),
    "responsive": responsive,
    "restored_focus": restored_focus,
    "remove_focus": remove_focus,
    "calibration_focus": calibration_focus,
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["registered"] is True and result["before"] is False
    assert result["opened"] == [True, True]
    assert result["closed"] == [False, False]
    assert result["status"].startswith("NO READING")
    assert "NO READING" in result["tooltip"]
    assert result["responsive"] == {
        "width": 240, "surface_width": 240,
        "scale": 1.0, "button_height": 30}
    assert result["restored_focus"] == "Edit alerts My HP"
    assert result["remove_focus"] == "Monitor My Mana"
    assert result["calibration_focus"] == "Calibrate My Mana"
