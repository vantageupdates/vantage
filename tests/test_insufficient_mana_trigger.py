import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, Spells, compile_trigger_pattern


ROOT = Path(__file__).resolve().parents[1]


def _definition():
    return next(
        CustomTrigger(*row) for row in config.BASIC_ALERTS
        if row[0] == "Insufficient mana")


def test_insufficient_mana_regex_matches_only_complete_system_line():
    trigger = _definition()
    pattern = compile_trigger_pattern(trigger.text, raw_regex=trigger.regex)

    for line in (
            "Insufficient Mana to cast this spell!",
            "insufficient mana to cast this spell."):
        assert pattern.match(line)

    for line in (
            "Insufficient Mana to cast this spell",
            "Insufficient Mana to cast this spell?",
            "Prefix Insufficient Mana to cast this spell!",
            "Insufficient Mana to cast this spell! suffix",
            'Mindflux says, "Insufficient Mana to cast this spell!"',
            "Your spell fizzles!",
            "",
    ):
        assert not pattern.match(line)


def test_insufficient_mana_v3_migration_round_trip_and_idempotence(
        tmp_path, monkeypatch):
    previous = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        config.data = {
            "spells": {
                "custom_timers": [],
                "basic_alerts_version": 3,
            }
        }
        config.verify_settings()
        rows = [
            row for row in config.data["spells"]["custom_timers"]
            if row[0] == "Insufficient mana"]
        assert len(rows) == 1
        assert config.data["spells"]["basic_alerts_version"] == 4

        trigger = CustomTrigger(*rows[0])
        serialized = trigger.to_list()
        assert len(rows[0]) == len(serialized) == 48
        assert serialized == rows[0]
        assert trigger.text == r"^Insufficient Mana to cast this spell[!.]$"
        assert trigger.regex is True
        assert trigger.enabled is True
        assert trigger.alert_text == "Insufficient mana"
        assert trigger.tts_text == "Insufficient mana"
        assert trigger.category == "Vantage · Basics"
        assert trigger.overlay_id == "alerts"
        assert trigger.comments == (
            "Classic P99 client insufficient-mana system line.")
        assert trigger.match_filter == ""
        assert trigger.match_cooldown_seconds == 0.75

        config.verify_settings()
        assert sum(
            row[0] == "Insufficient mana"
            for row in config.data["spells"]["custom_timers"]) == 1
    finally:
        config.data = previous


def test_insufficient_mana_migration_preserves_customized_same_name(
        tmp_path, monkeypatch):
    previous = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    custom = [
        "INSUFFICIENT MANA", r"^Insufficient Mana to cast this spell[!.]$",
        "00:00:00", "", "custom.wav", "My alert", False, True,
        "Vantage · Basics",
    ]
    try:
        config.data = {
            "spells": {
                "custom_timers": [custom.copy()],
                "basic_alerts_version": 3,
            }
        }
        config.verify_settings()
        matches = [
            row for row in config.data["spells"]["custom_timers"]
            if row[0].casefold() == "insufficient mana"]
        assert matches == [custom]
        assert config.data["spells"]["basic_alerts_version"] == 4
    finally:
        config.data = previous


def test_insufficient_mana_sound_tts_and_off_routes(monkeypatch):
    previous = config.data
    config.data = {
        "spells": {"fade_sound_volume": 67},
        "sharing": {"player_name": "Mindflux"},
    }
    played, spoken = [], []
    monkeypatch.setattr(
        spells_module, "play_alert",
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    monkeypatch.setattr(
        spells_module, "speak_text",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    try:
        trigger = _definition()
        assert trigger.audio_delivery("basic") == "sound"
        assert trigger.sound_path == "builtin:soft-tick"
        assert trigger.tts_volume == 85
        assert trigger.tts_pitch == 0

        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, trigger.tts_text,
            False, "Insufficient mana", "Mindflux", "Green"
        ).startswith("Sound · ")
        assert played[0][0][:2] == ("builtin:soft-tick", 67)

        trigger.delivery = "tts"
        trigger.tts_voice = "Adjutant"
        trigger.tts_volume = 85
        trigger.tts_pitch = -2
        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, trigger.tts_text,
            False, "Insufficient mana", "Mindflux", "Green"
        ) == "Text-to-speech"
        assert spoken[0][0][:2] == ("Insufficient mana", 85)
        assert spoken[0][1]["voice_name"] == "Adjutant"
        assert spoken[0][1]["pitch"] == -2

        trigger.delivery = "off"
        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, trigger.tts_text,
            False, "Insufficient mana", "Mindflux", "Green") == ""
        assert len(played) == 1 and len(spoken) == 1
    finally:
        config.data = previous


UI_SCRIPT = r'''
import json
from PySide6.QtWidgets import QPushButton
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.helpers.settings import CustomTriggerSettings
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
trigger = next(
    CustomTrigger(*row) for row in config.data["spells"]["custom_timers"]
    if row[0] == "Insufficient mana")
dialog = CustomTriggerSettings()
dialog._display_trigger(trigger)
result = {
    "name": dialog._trigger_name.text(),
    "text": dialog._trigger_text.text(),
    "regex": dialog._trigger_regex.isChecked(),
    "tts": dialog._trigger_tts.text(),
    "delivery": [dialog._trigger_delivery.itemData(index)
                 for index in range(dialog._trigger_delivery.count())],
    "voice_name": dialog._trigger_tts_voice.accessibleName(),
    "pitch_name": dialog._trigger_tts_pitch.accessibleName(),
    "test_controls": sorted(
        button.accessibleName()
        for panel in dialog._trigger_delivery_panels[0][1:]
        for button in panel.findChildren(QPushButton)
        if button.accessibleName().startswith("Test basic trigger")),
    "guard": dialog._trigger_match_cooldown.value(),
    "guard_name": dialog._trigger_match_cooldown.accessibleName(),
}
print(json.dumps(result))
dialog.close()
app.quit()
'''


def test_insufficient_mana_uses_common_accessible_editor_controls(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", UI_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["name"] == "Insufficient mana"
    assert result["text"] == r"^Insufficient Mana to cast this spell[!.]$"
    assert result["regex"] is True
    assert result["tts"] == "Insufficient mana"
    assert result["delivery"] == ["sound", "tts", "off"]
    assert result["voice_name"] == "Basic trigger Windows voice"
    assert result["pitch_name"] == "Basic trigger speech pitch"
    assert result["test_controls"] == [
        "Test basic trigger sound", "Test basic trigger speech"]
    assert result["guard"] == 0.75
    assert result["guard_name"] == "Trigger repeat guard duration"
