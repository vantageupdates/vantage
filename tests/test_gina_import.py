import zipfile

import pytest

from vantage.helpers.gina_import import GinaImportError, import_gina_package
from vantage.helpers.portable import resolve_portable_path
from vantage.parsers.spells import CustomTrigger


SAMPLE_XML = b"""<?xml version='1.0' encoding='utf-8'?>
<SharedData><TriggerGroups><TriggerGroup><Name>Basics</Name><Triggers>
  <Trigger><Name>Charm break</Name><TriggerText>^Your charm spell has worn off\\.$</TriggerText>
    <EnableRegex>True</EnableRegex><UseTextToVoice>True</UseTextToVoice>
    <TextToVoiceText>Charm broke</TextToVoiceText><TimerType>NoTimer</TimerType>
    <TimerDuration>0</TimerDuration><Category>Danger</Category></Trigger>
  <Trigger><Name>Respawn</Name><TriggerText>You have slain {S}</TriggerText>
    <EnableRegex>False</EnableRegex><TimerType>Timer</TimerType>
    <Comments>Imported respawn behavior</Comments>
    <TimerName>Spawn ${1}</TimerName><TimerMillisecondDuration>300000</TimerMillisecondDuration>
    <RestartBasedOnTimerName>True</RestartBasedOnTimerName>
    <TimerVisibleDuration>45</TimerVisibleDuration>
    <TimerStartBehavior>StartNewTimer</TimerStartBehavior>
    <UseTimerEnding>True</UseTimerEnding><TimerEndingTime>30</TimerEndingTime>
    <TimerEndingTrigger><UseText>True</UseText><DisplayText>Spawn in 30</DisplayText>
      <PlayMediaFile>True</PlayMediaFile></TimerEndingTrigger>
    <UseTimerEnded>True</UseTimerEnded>
    <TimerEndedTrigger><UseText>True</UseText><DisplayText>Spawn due</DisplayText>
      <UseTextToVoice>True</UseTextToVoice><TextToVoiceText>Spawn due</TextToVoiceText>
    </TimerEndedTrigger>
    <UseCounterResetTimer>True</UseCounterResetTimer><CounterResetDuration>900</CounterResetDuration>
    <CopyToClipboard>True</CopyToClipboard><ClipboardText>/loc</ClipboardText>
    <TimerEarlyEnders><EarlyEnder><EarlyEndText>{S} has spawned.</EarlyEndText>
      <EnableRegex>False</EnableRegex>
    </EarlyEnder></TimerEarlyEnders>
    <Category>Timers</Category></Trigger>
</Triggers></TriggerGroup></TriggerGroups></SharedData>"""


def test_gina_package_imports_as_disabled_editable_copies(tmp_path):
    package = tmp_path / "sample.gtp"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ShareData.xml", SAMPLE_XML)

    imported = import_gina_package(package)

    assert len(imported) == 2
    assert all(not trigger.enabled for trigger in imported)
    assert imported[0].regex is True
    assert imported[0].sound_path == ""
    assert imported[0].tts_text == "Charm broke"
    assert imported[0].source == "Imported pack · sample"
    assert imported[1].time == "00:05:00"
    assert imported[1].name == "Respawn"
    assert imported[1].timer_name == "Spawn ${1}"
    assert imported[1].restart_based_on_timer_name is True
    assert imported[0].category == "Basics/Danger"
    assert imported[1].category == "Basics/Timers"
    assert imported[1].overlay_id == "timers"
    assert imported[1].restart_behavior == "new"
    assert imported[1].end_text == "{S} has spawned."
    assert imported[1].comments == "Imported respawn behavior"
    assert imported[1].timer_type == "countdown"
    assert imported[1].timer_visible_seconds == 45
    assert imported[1].timer_ending_seconds == 30
    assert imported[1].timer_ending_alert == "Spawn in 30"
    assert imported[1].timer_ending_sound.startswith("builtin:")
    assert imported[1].timer_ended_alert == "Spawn due"
    assert imported[1].timer_ended_tts == "Spawn due"
    assert imported[1].counter_reset_seconds == 900
    assert imported[1].clipboard_text == "/loc"
    assert imported[1].end_patterns == [
        {"text": "{S} has spawned.", "regex": False}]


def test_gina_import_rejects_entity_declarations(tmp_path):
    xml = tmp_path / "unsafe.xml"
    xml.write_bytes(b"<!DOCTYPE x [<!ENTITY secret SYSTEM 'file:///x'>]><x/>")

    with pytest.raises(GinaImportError):
        import_gina_package(xml)


def _wav(marker):
    payload = bytes(marker)
    return b"RIFF" + len(payload).to_bytes(4, "little") + b"WAVE" + payload


def test_gtp_stages_embedded_wavs_and_commits_only_selected_triggers(
        tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(profile))
    xml = b"""<SharedData><TriggerGroups><TriggerGroup><Name>Raid</Name>
    <TriggerGroups><TriggerGroup><Name>Control</Name><Triggers>
      <Trigger><Name>Mez</Name><TriggerText>is entranced</TriggerText>
        <PlayMediaFile>True</PlayMediaFile><MediaFileId>7</MediaFileId>
        <TimerType>Timer</TimerType><TimerDuration>60</TimerDuration>
        <UseTimerEnding>True</UseTimerEnding><TimerEndingTime>10</TimerEndingTime>
        <TimerEndingTrigger><PlayMediaFile>True</PlayMediaFile>
          <MediaFileId>8</MediaFileId></TimerEndingTrigger>
        <UseTimerEnded>True</UseTimerEnded><TimerEndedTrigger>
          <PlayMediaFile>True</PlayMediaFile><MediaFileId>9</MediaFileId>
        </TimerEndedTrigger><Category>Crowd Control</Category></Trigger>
      <Trigger><Name>Unselected</Name><TriggerText>not this one</TriggerText>
        <PlayMediaFile>True</PlayMediaFile><MediaFileId>10</MediaFileId>
      </Trigger>
    </Triggers></TriggerGroup></TriggerGroups></TriggerGroup>
    </TriggerGroups></SharedData>"""
    package = tmp_path / "audio.gtp"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ShareData.xml", xml)
        for file_id, filename in (
                (7, "main.wav"), (8, "ending.wav"),
                (9, "ended.wav"), (10, "unused.wav")):
            info = zipfile.ZipInfo(filename)
            info.comment = str(file_id).encode("ascii")
            archive.writestr(info, _wav(filename.encode("ascii")))

    batch = import_gina_package(package)

    assert not profile.exists()
    assert batch[0].category == "Raid/Control/Crowd Control"
    assert batch.has_embedded_audio(batch[0]) is True
    assert batch.has_embedded_audio(batch[1]) is True
    batch.materialize_selected([batch[0]])

    assert batch[0].sound_path == "portable:sounds/gina-imports/main.wav"
    assert batch[0].timer_ending_sound == (
        "portable:sounds/gina-imports/ending.wav")
    assert batch[0].timer_ended_sound == (
        "portable:sounds/gina-imports/ended.wav")
    assert resolve_portable_path(batch[0].sound_path).read_bytes() == _wav(b"main.wav")
    assert not (profile / "sounds" / "gina-imports" / "unused.wav").exists()
    assert batch[1].sound_path.startswith("builtin:")
    restored = CustomTrigger(*batch[0].to_list())
    assert restored.category == "Raid/Control/Crowd Control"
    assert restored.sound_path == batch[0].sound_path
    assert restored.timer_ending_sound == batch[0].timer_ending_sound
    assert restored.timer_ended_sound == batch[0].timer_ended_sound


def test_gtp_ignores_invalid_or_non_wav_embedded_content(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(profile))
    xml = b"""<SharedData><TriggerGroups><TriggerGroup><Name>Unsafe</Name>
    <Triggers><Trigger><Name>Bad sound</Name><TriggerText>bad</TriggerText>
    <PlayMediaFile>True</PlayMediaFile><MediaFileId>4</MediaFileId>
    </Trigger></Triggers></TriggerGroup></TriggerGroups></SharedData>"""
    package = tmp_path / "unsafe-media.gtp"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ShareData.xml", xml)
        info = zipfile.ZipInfo("../../payload.exe")
        info.comment = b"4"
        archive.writestr(info, b"MZ-not-a-wave")

    batch = import_gina_package(package)
    original_fallback = batch[0].sound_path
    batch.materialize_selected(batch)

    assert original_fallback.startswith("builtin:")
    assert batch[0].sound_path == original_fallback
    assert not profile.exists()


def test_gtt_import_preserves_timer_actions_and_named_color(tmp_path):
    gtt = tmp_path / "raid.gtt"
    gtt.write_text(
        "Trigger={S} has been entranced.;Comment=Mez timer;Display=True;"
        "ShowText=True;DisplayText=MEZ {S};TextColour=Yellow;Timer=True;"
        "TimerText=Entrance {S};Hours=0;Minutes=1;Seconds=14;"
        "Behaviour=Always start a new timer;CompletionDisplay=True;"
        "CompletionText=MEZ ENDED;EndEarly=True;"
        "EndEarlyText={S} is no longer mesmerized.;PlaySound=True;"
        "SoundLink=C:\\sounds\\alarm.wav;PlayTTS=True;TTSText=Mez landed;\n",
        encoding="cp1252")

    imported = import_gina_package(gtt)

    assert len(imported) == 1
    trigger = imported[0]
    assert trigger.enabled is False
    assert trigger.source == "Imported GTT · raid"
    assert trigger.name == "Entrance {S}"
    assert trigger.timer_name == "Entrance {S}"
    assert trigger.time == "00:01:14"
    assert trigger.timer_type == "countdown"
    assert trigger.restart_behavior == "new"
    assert trigger.alert_text == "MEZ {S}"
    assert trigger.timer_ended_alert == "MEZ ENDED"
    assert trigger.end_patterns == [{
        "text": "{S} is no longer mesmerized.", "regex": False}]
    assert trigger.tts_text == "Mez landed"
    assert trigger.sound_path.startswith("builtin:")
    assert trigger.text_color == "#E5C267"


def test_gtt_import_reads_utf16_and_rejects_non_trigger_text(tmp_path):
    valid = tmp_path / "utf16.gtt"
    valid.write_text(
        "Trigger=You are marked.;Timer=False;Display=True;"
        "DisplayText=MARKED;TextColour=Red;",
        encoding="utf-16")
    assert import_gina_package(valid)[0].text_color == "#DF706A"

    invalid = tmp_path / "empty.gtt"
    invalid.write_text("not a trigger", encoding="utf-8")
    with pytest.raises(GinaImportError):
        import_gina_package(invalid)
