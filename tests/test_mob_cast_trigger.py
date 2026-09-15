import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import (
    CustomTrigger, Spells, compile_trigger_pattern,
    external_npc_cast_actor, render_trigger_text, trigger_match_allowed)


ROOT = Path(__file__).resolve().parents[1]


def _definition():
    return next(
        CustomTrigger(*row) for row in config.BASIC_ALERTS
        if row[0] == "Mob is casting")


def test_classic_p99_external_cast_filter_accepts_evidenced_npcs_only():
    trigger = _definition()
    pattern = compile_trigger_pattern(trigger.text)
    positives = (
        "a soothebrine seahorse begins to cast a spell.",
        "froglok bok shaman begins to cast a spell.",
        # Single title-cased actors require bundled P99 NPC/map evidence.
        "Daman begins to cast a spell.",
    )
    for line in positives:
        match = pattern.match(line)
        assert external_npc_cast_actor(line, "Mindflux")
        assert trigger_match_allowed(trigger, match, line, "Mindflux")

    negatives = (
        "You begin casting Regrowth of the Grove.",
        "Mindflux begins to cast a spell.",
        "Anotherplayer begins to cast a spell.",
        "Daman's spell has landed.",
        "Daman begins to cast a spell!",
        "begins to cast a spell.",
        "",
        None,
    )
    for line in negatives:
        match = pattern.match(line or "")
        assert external_npc_cast_actor(line, "Mindflux") == ""
        assert not trigger_match_allowed(
            trigger, match, line, "Mindflux")


def test_mob_cast_basic_seed_and_round_trip_are_backward_compatible(
        tmp_path, monkeypatch):
    previous = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        config.data = {
            "spells": {
                "custom_timers": [],
                "basic_alerts_version": 2,
            }
        }
        config.verify_settings()
        trigger = next(
            CustomTrigger(*row)
            for row in config.data["spells"]["custom_timers"]
            if row[0] == "Mob is casting")
        assert trigger.text == "{mob} begins to cast a spell."
        assert trigger.alert_text == "{mob} is casting"
        assert trigger.tts_text == "{mob} is casting"
        assert trigger.audio_delivery("basic") == "sound"
        assert trigger.match_filter == "external_npc_cast"
        assert trigger.match_cooldown_seconds == 2.0

        restored = CustomTrigger(*trigger.to_list())
        assert restored.match_filter == "external_npc_cast"
        assert restored.match_cooldown_seconds == 2.0
        assert restored.tts_text == "{mob} is casting"

        legacy = CustomTrigger(*trigger.to_list()[:46])
        assert legacy.match_filter == ""
        assert legacy.match_cooldown_seconds == 0.75
    finally:
        config.data = previous


def test_mob_cast_sound_tts_off_routes_and_resolves_actor_token(monkeypatch):
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
        match = compile_trigger_pattern(trigger.text).match(
            "froglok bok shaman begins to cast a spell.")
        trigger.runtime_character = "Mindflux"
        message = render_trigger_text(trigger.tts_text, match, trigger)
        assert message == "froglok bok shaman is casting"

        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, message, False,
            "Mob cast", "Mindflux", "Green").startswith("Sound · ")
        assert played[0][0][:2] == ("builtin:warden-bell", 67)
        assert played[0][1]["channel"] == "spells"

        trigger.delivery = "tts"
        trigger.tts_voice = "Narrator"
        trigger.tts_volume = 54
        trigger.tts_pitch = -4
        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, message, False,
            "Mob cast", "Mindflux", "Green") == "Text-to-speech"
        assert spoken[0][0][:2] == (message, 54)
        assert spoken[0][1]["voice_name"] == "Narrator"
        assert spoken[0][1]["pitch"] == -4

        trigger.delivery = "off"
        assert Spells._deliver_custom_trigger_audio(
            None, trigger, "basic", trigger.sound_path, message, False,
            "Mob cast", "Mindflux", "Green") == ""
        assert len(played) == 1 and len(spoken) == 1
    finally:
        config.data = previous


RUNTIME_SCRIPT = r'''
import datetime
import json
from vantage.helpers.application import VantageApp
from vantage.parsers import spells as spells_module

app = VantageApp([])
panel = app._parsers_dict["spells"]
panel._active_character = "Mindflux"
panel._active_server = "Green"
played = []
spells_module.play_alert = (
    lambda *args, **kwargs: played.append((args, kwargs)) or True)
stamp = datetime.datetime.now()
lines = [
    "a soothebrine seahorse begins to cast a spell.",
    "a soothebrine seahorse begins to cast a spell.",
    "froglok bok shaman begins to cast a spell.",
    "You begin casting Regrowth of the Grove.",
    "Mindflux begins to cast a spell.",
    "Anotherplayer begins to cast a spell.",
    "Daman's spell has landed.",
]
for line in lines:
    panel.parse(stamp, line)
matches = [
    row for row in panel.trigger_history()
    if row["trigger"] == "Mob is casting" and row["status"] == "Matched"]
print(json.dumps({
    "sounds": len(played),
    "matched_lines": [row["line"] for row in reversed(matches)],
    "outputs": [row["output"] for row in reversed(matches)],
}))
app.quit()
'''


def test_runtime_filters_self_and_unknown_players_and_throttles_per_mob(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", RUNTIME_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["sounds"] == 2
    assert result["matched_lines"] == [
        "a soothebrine seahorse begins to cast a spell.",
        "froglok bok shaman begins to cast a spell.",
    ]
    assert all("Sound ·" in output for output in result["outputs"])


UI_SCRIPT = r'''
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.helpers.settings import CustomTriggerSettings
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
trigger = next(
    CustomTrigger(*row) for row in config.data["spells"]["custom_timers"]
    if row[0] == "Mob is casting")
dialog = CustomTriggerSettings()
dialog._display_trigger(trigger)
result = {
    "name": dialog._trigger_name.text(),
    "text": dialog._trigger_text.text(),
    "tts": dialog._trigger_tts.text(),
    "delivery": [dialog._trigger_delivery.itemData(index)
                 for index in range(dialog._trigger_delivery.count())],
    "guard": dialog._trigger_match_cooldown.value(),
    "guard_name": dialog._trigger_match_cooldown.accessibleName(),
    "guard_description": dialog._trigger_match_cooldown.accessibleDescription(),
}
print(json.dumps(result))
dialog.close()
app.quit()
'''


def test_mob_cast_uses_accessible_common_trigger_editor(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", UI_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["name"] == "Mob is casting"
    assert result["text"] == "{mob} begins to cast a spell."
    assert result["tts"] == "{mob} is casting"
    assert result["delivery"] == ["sound", "tts", "off"]
    assert result["guard"] == 2.0
    assert result["guard_name"] == "Trigger repeat guard duration"
    assert "each actor" in result["guard_description"]
