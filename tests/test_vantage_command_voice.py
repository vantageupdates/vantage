from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QComboBox

from vantage.helpers import audio, config
from vantage.helpers.settings import CustomTriggerSettings, SettingsWindow
from vantage.helpers.vitals import default_vital_stop
from vantage.parsers import timers as timers_module
from vantage.parsers import vitals as vitals_module
from vantage.parsers.timers import SpawnTimerState, TimerEditDialog
from vantage.parsers.vitals import VitalStopDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_vantage_command_label_resolves_current_fake_inventory(monkeypatch):
    speech = SimpleNamespace(availableVoices=lambda: [
        SimpleNamespace(name=lambda: "Microsoft Zira"),
        SimpleNamespace(name=lambda: "Microsoft David"),
        SimpleNamespace(name=lambda: "Microsoft Mark")])
    monkeypatch.setattr(audio, "_speech_engine", lambda: speech)
    monkeypatch.setattr(audio, "_DEFAULT_VOICE_NAME", "Microsoft David")

    assert audio.vantage_command_voice_name() == "Microsoft Zira"
    assert audio.vantage_command_voice_label() == (
        "Vantage Adjutant · Microsoft Zira")


def test_notification_voice_route_uses_accessible_command_default(monkeypatch):
    _app()
    config.verify_settings()
    monkeypatch.setattr(
        "vantage.helpers.settings.speech_voice_names", lambda: ["Voice One"])
    delivery = QComboBox()
    delivery.addItem("Sound", "sound")
    delivery.addItem("Voice", "voice")
    delivery.addItem("Off", "off")
    delivery.setCurrentIndex(delivery.findData("voice"))
    picker = QComboBox()

    SettingsWindow._populate_route_picker(
        SimpleNamespace(), "market_sale", delivery, picker,
        values={"delivery": "voice", "voice": "", "sound": ""})

    assert picker.itemData(0) == ""
    assert picker.itemText(0).startswith("Vantage Adjutant")
    assert "calm installed female Windows voice" in picker.accessibleDescription()
    assert picker.currentData() == ""

    SettingsWindow._populate_route_picker(
        SimpleNamespace(), "market_sale", delivery, picker,
        values={"delivery": "voice", "voice": "Retired Voice", "sound": ""})
    assert picker.currentData() == "Retired Voice"
    assert "unavailable" in picker.currentText()
    assert "remains saved" in picker.accessibleDescription()

    delivery.setCurrentIndex(delivery.findData("sound"))
    SettingsWindow._populate_route_picker(
        SimpleNamespace(), "market_sale", delivery, picker,
        values={"delivery": "sound", "voice": "", "sound": ""})
    assert "gallery or custom WAV" in picker.accessibleDescription()
    assert "calm installed female Windows voice" not in picker.accessibleDescription()

    delivery.setCurrentIndex(delivery.findData("off"))
    SettingsWindow._populate_route_picker(
        SimpleNamespace(), "market_sale", delivery, picker,
        values={"delivery": "off", "voice": "", "sound": ""})
    assert "Audio delivery is off" in picker.accessibleDescription()
    assert "calm installed female Windows voice" not in picker.accessibleDescription()


def test_each_trigger_phase_preserves_an_unavailable_explicit_voice():
    _app()
    combos = [QComboBox(), QComboBox(), QComboBox()]
    for combo, saved in zip(
            combos, ("Old Basic", "Old Ending", "Old Ended")):
        combo.addItem("Vantage Adjutant", "")
        CustomTriggerSettings._set_voice_combo(combo, saved)
        assert combo.currentData() == saved
        assert "unavailable" in combo.currentText()
        assert "remains saved" in combo.accessibleDescription()


def test_timer_preserves_unavailable_explicit_voice(monkeypatch):
    _app()
    monkeypatch.setattr(timers_module, "speech_voice_names", lambda: ["Voice One"])
    timer = SpawnTimerState("Frenzy", 600, tts_voice="Old Timer Voice")
    dialog = TimerEditDialog(timer)
    assert dialog.tts_voice.currentData() == "Old Timer Voice"
    assert "unavailable" in dialog.tts_voice.currentText()
    assert "remains saved" in dialog.tts_voice.accessibleDescription()
    dialog.apply(timer)
    assert timer.tts_voice == "Old Timer Voice"
    dialog.close()


def test_vital_stop_voice_default_is_command_and_saved_voice_survives(
        monkeypatch):
    _app()
    monkeypatch.setattr(vitals_module, "speech_voice_names", lambda: ["Voice One"])
    default_stop = default_vital_stop(25)
    default_stop.update({"delivery": "tts", "voice": ""})
    dialog = VitalStopDialog(default_stop)
    assert dialog.voice.itemData(0) == ""
    assert dialog.voice.itemText(0).startswith("Vantage Adjutant")
    assert "calm installed female Windows voice" in dialog.voice.accessibleDescription()
    assert dialog.value()["voice"] == ""
    dialog.close()

    explicit_stop = default_vital_stop(25)
    explicit_stop.update({"delivery": "tts", "voice": "Voice One"})
    dialog = VitalStopDialog(explicit_stop)
    assert dialog.voice.currentData() == "Voice One"
    assert dialog.value()["voice"] == "Voice One"
    dialog.close()

    missing_stop = default_vital_stop(25)
    missing_stop.update({"delivery": "tts", "voice": "Old Vital Voice"})
    dialog = VitalStopDialog(missing_stop)
    assert dialog.voice.currentData() == "Old Vital Voice"
    assert "unavailable" in dialog.voice.currentText()
    assert "remains saved" in dialog.voice.accessibleDescription()
    assert dialog.value()["voice"] == "Old Vital Voice"
    dialog.close()
