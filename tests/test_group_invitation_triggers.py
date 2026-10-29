import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers import config
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import (
    CustomTrigger, Spells, compile_trigger_pattern, render_trigger_text)


ROOT = Path(__file__).resolve().parents[1]
INVITATIONS = {
    "Group invitation received": (
        "Mindflux invites you to join a group.",
        "Mindflux invited you to a group"),
    "Group invitation sent": (
        "You invite Wildflux to join your group.",
        "Group invitation sent to Wildflux"),
}


def _definition(name):
    return next(CustomTrigger(*row) for row in config.BASIC_ALERTS
                if row[0] == name)


@pytest.mark.parametrize("name", INVITATIONS)
def test_group_invitation_matches_only_its_complete_system_line(name):
    trigger = _definition(name)
    trigger.runtime_character = "Holyflux"
    pattern = compile_trigger_pattern(trigger.text, raw_regex=trigger.regex)
    line, expected = INVITATIONS[name]
    match = pattern.match(line)
    assert match is not None
    assert render_trigger_text(trigger.alert_text, match, trigger) == expected
    assert render_trigger_text(trigger.tts_text, match, trigger) == expected
    assert pattern.match(line.swapcase())
    other = next(value[0] for key, value in INVITATIONS.items() if key != name)
    for rejected in (
            other, "Prefix " + line, line + " suffix", line[:-1],
            f'Mindflux says, "{line}"', f"Mindflux tells you, '{line}'",
            "You have been invited to group", "", "You invite to join your group."):
        assert pattern.match(rejected) is None, rejected
    assert trigger.enabled is True
    assert trigger.regex is True
    assert trigger.timer_type == "none"
    assert trigger.overlay_id == "alerts"
    assert trigger.category == "Vantage · Basics"
    assert trigger.match_cooldown_seconds == 1.0
    assert trigger.to_list()[49] == "full"


def test_group_invitation_v5_upgrade_is_durable_and_preserves_custom_alerts(
        tmp_path, monkeypatch):
    previous = config.data
    filename = tmp_path / "config.json"
    monkeypatch.setattr(config, "_filename", str(filename))
    sent = _definition("Group invitation sent")
    sent.name = sent.name.upper()
    sent.enabled = False
    sent.audio_muted = True
    sent.sound_path = "my-group-invite.wav"
    sent.alert_text = "My customized group invitation"
    customized = sent.to_list()
    try:
        config.data = {"spells": {
            "custom_timers": [copy.deepcopy(customized)],
            "basic_alerts_version": 5,
        }}
        config.verify_settings()
        config.save()
        config.load(str(filename))
        config.verify_settings()
        config.verify_settings()
        rows = config.data["spells"]["custom_timers"]
        assert config.data["spells"]["basic_alerts_version"] == config.BASIC_ALERTS_VERSION
        for name in INVITATIONS:
            assert sum(row[0].casefold() == name.casefold() for row in rows) == 1
        assert next(row for row in rows if row[0] == sent.name) == customized
        received = next(CustomTrigger(*row) for row in rows
                        if row[0] == "Group invitation received")
        assert received.enabled is True
        assert received.audio_muted is False
        assert received.audio_delivery("basic") == "sound"
    finally:
        config.data = previous


@pytest.mark.parametrize("name", INVITATIONS)
def test_group_invitation_sound_tts_off_and_individual_mute(name, monkeypatch):
    previous = config.data
    config.data = {
        "spells": {"fade_sound_volume": 67},
        "sharing": {"player_name": "Holyflux"},
    }
    played, spoken = [], []
    monkeypatch.setattr(spells_module, "play_alert",
                        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    monkeypatch.setattr(spells_module, "speak_text",
                        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    try:
        trigger = _definition(name)
        line, expected = INVITATIONS[name]
        match = compile_trigger_pattern(trigger.text, raw_regex=True).match(line)
        speech = render_trigger_text(trigger.tts_text, match, trigger)

        def deliver():
            return Spells._deliver_custom_trigger_audio(
                None, trigger, "basic", trigger.sound_path, speech, False,
                name, "Holyflux", "Green", visual_registered=True)

        assert deliver().startswith("Sound · ")
        assert played[0][0][:2] == ("builtin:warden-bell", 67)
        trigger.delivery = "tts"
        trigger.tts_voice = "Adjutant"
        trigger.tts_volume = 81
        trigger.tts_pitch = -2
        assert deliver() == "Text-to-speech"
        assert spoken[0][0][:2] == (expected, 81)
        assert spoken[0][1]["voice_name"] == "Adjutant"
        assert spoken[0][1]["pitch"] == -2
        trigger.audio_muted = True
        assert deliver() == ""
        trigger.audio_muted = False
        trigger.delivery = "off"
        assert deliver() == ""
        assert len(played) == len(spoken) == 1
    finally:
        config.data = previous


RUNTIME_SCRIPT = r'''
import datetime
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.parsers import spells as spells_module

app = VantageApp([])
spells = app._parsers_dict['spells']
names = {'Group invitation received', 'Group invitation sent'}
rows = [row for row in config.data['spells']['custom_timers'] if row[0] in names]
assert len(rows) == 2
config.data['spells']['custom_timers'] = rows
config.data['spells']['use_custom_triggers'] = True
config.data['spells']['trigger_categories']['Vantage · Basics'] = True
spells.load_custom_timers()
notices, overlays, sounds, speech = [], [], [], []
app._queue_quickbar_notice = lambda message, channel='system': notices.append([message, channel])
app.show_overlay_notification = lambda title, message, **kwargs: overlays.append([title, message, kwargs.get('register')])
spells_module.play_alert = lambda *args, **kwargs: sounds.append((args, kwargs)) or True
spells_module.speak_text = lambda *args, **kwargs: speech.append((args, kwargs)) or True
stamp = datetime.datetime.now()
incoming = 'Mindflux invites you to join a group.'
outgoing = 'You invite Wildflux to join your group.'
for line in (incoming, incoming, outgoing, outgoing,
             'Mindflux says, "' + incoming + '"',
             "Wildflux tells you, '" + outgoing + "'"):
    spells.parse(stamp, line)
first = list(notices)
first_overlays = list(overlays)
first_audio = len(sounds)
for row in rows:
    row[6] = False
spells.load_custom_timers()
spells.parse(stamp, incoming)
spells.parse(stamp, outgoing)
disabled_count = len(notices)
for row in rows:
    row[6] = True
    row[48] = True
spells.load_custom_timers()
spells.parse(stamp, outgoing)
print(json.dumps({
    'first': first, 'overlays': first_overlays, 'first_audio': first_audio,
    'disabled_count': disabled_count, 'muted_last': notices[-1],
    'final_notice_count': len(notices), 'final_audio_count': len(sounds),
    'speech_count': len(speech), 'running_timers': len(spells._trigger_runs),
}))
app.quit()
'''


def test_group_invitation_runtime_emits_one_named_notice_and_respects_off_mute(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", QT_ACCESSIBILITY="0",
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"),
               VANTAGE_DATA_DIR=str(tmp_path / "profile"))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", RUNTIME_SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, check=True, timeout=40)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    expected = [[message, "spells"] for _line, message in INVITATIONS.values()]
    assert result["first"] == expected
    assert len(result["overlays"]) == 2
    assert [row[1] for row in result["overlays"]] == [row[0] for row in expected]
    assert all(row[2] is False for row in result["overlays"])
    assert result["first_audio"] == 2
    assert result["disabled_count"] == 2
    assert result["muted_last"] == expected[1]
    assert result["final_notice_count"] == 3
    assert result["final_audio_count"] == 2
    assert result["speech_count"] == 0
    assert result["running_timers"] == 0
