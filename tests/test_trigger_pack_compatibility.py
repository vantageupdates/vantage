"""Bounded data-only exchange; no live game, audio, or network."""

import base64
import json
import zipfile

import pytest

from vantage.helpers import gina_import
from vantage.helpers.gina_import import (
    GinaImportError, import_gina_package, import_vantage_package_bytes,
    serialize_gina_package, serialize_vantage_package)
from vantage.helpers.portable import resolve_portable_path, store_portable_bytes
from vantage.parsers.spells import CustomTrigger


def _wav(marker=b"test"):
    return b"RIFF" + len(marker).to_bytes(4, "little") + b"WAVE" + marker


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-be"])
def test_entity_guard_covers_whole_bounded_document_and_utf16(tmp_path, encoding):
    path = tmp_path / "guard.xml"
    path.write_bytes((" " * 6000 + "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///x'>]><x/>").encode(encoding))
    with pytest.raises(GinaImportError, match="declarations"):
        import_gina_package(path)


def test_deep_groups_report_bounded_error_not_recursion(tmp_path):
    path = tmp_path / "deep.xml"
    path.write_text("<SharedData>" + "<TriggerGroup><Name>X</Name>" * 18 +
                    "<Trigger><TriggerText>hello</TriggerText></Trigger>" +
                    "</TriggerGroup>" * 18 + "</SharedData>")
    with pytest.raises(GinaImportError, match="nesting"):
        import_gina_package(path)


@pytest.mark.parametrize("failure", [zipfile.BadZipFile("Bad CRC"), RuntimeError("encrypted"), OSError("read failed")])
def test_package_read_failures_are_ui_safe_errors(tmp_path, monkeypatch, failure):
    package = tmp_path / "corrupt.gtp"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("ShareData.xml", b"<SharedData/>")
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_args, **_kwargs: (_ for _ in ()).throw(failure))
    with pytest.raises(GinaImportError):
        import_gina_package(package)


def test_preview_reports_unsupported_missing_combined_invalid_and_skipped(tmp_path):
    package = tmp_path / "warnings.xml"
    package.write_text("""<SharedData><TriggerGroups><TriggerGroup><Name>Raid</Name>
      <Enabled>False</Enabled><Triggers>
      <Trigger><Name>Review</Name><TriggerText>(?&lt;Actor&gt;.+)</TriggerText>
        <EnableRegex>True</EnableRegex><PlayMediaFile>True</PlayMediaFile><MediaFileId>9</MediaFileId>
        <UseTextToVoice>True</UseTextToVoice><TextToVoiceText>hello</TextToVoiceText>
        <MediaFileName>C:\\private\\alarm.wav</MediaFileName><RegexOptions>Compiled</RegexOptions>
        <TimerMillisecondDuration>1500</TimerMillisecondDuration></Trigger>
      <Trigger><Name>Skipped</Name><TriggerText/></Trigger>
      </Triggers></TriggerGroup></TriggerGroups></SharedData>""")
    batch = import_gina_package(package)
    assert len(batch) == 1 and batch[0].enabled is False
    codes = {entry["code"] for entry in batch.warnings}
    assert codes >= {"invalid-pattern", "regex-dialect", "combined-audio", "missing-audio",
                     "external-path", "unsupported-settings", "timer-precision", "skipped-entry", "group-options"}
    assert "one audio route" in " ".join(entry["message"] for entry in batch.warnings)
    assert batch[0].tts_text == "hello"
    assert batch[0].sound_path.startswith("builtin:")


def test_native_roundtrip_preserves_fields_groups_and_stages_only_selected_media(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(profile))
    wav = store_portable_bytes(_wav(), "portable.wav", subdir="sounds")
    trigger = CustomTrigger("One", "{Actor} casts {Spell}", "00:01:00", category="Raid/Control",
                            profile="AuditCleric", zone="Test zone", sound_path=wav, delivery="sound",
                            timer_ending_tts="Ending {Actor}", timer_ending_delivery="tts",
                            tts_voice="Saved voice", tts_volume=37, tts_pitch=2,
                            clipboard_text="/target {Actor}", match_cooldown_seconds=4,
                            end_patterns=[{"text": "done", "regex": False}], audio_muted=True)
    second = CustomTrigger("Two", "other", "", sound_path=wav)
    groups = {"Raid": {"enabled": False, "profiles": {"AuditCleric": True},
                       "style": {"font_color": "#E5C267"}, "credentials": "never export"},
              "Unselected": {"enabled": True}}
    before = trigger.to_list()
    content, warnings = serialize_vantage_package([trigger, second], groups)
    data = json.loads(content)
    assert not warnings and len(data["media"]) == 1
    assert "credentials" not in content.decode() and "Unselected" not in data["groups"]
    assert trigger.to_list() == before
    import_profile = tmp_path / "import"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(import_profile))
    batch = import_vantage_package_bytes(content)
    assert not import_profile.exists()
    assert batch.groups["Raid"]["enabled"] is False
    assert batch.groups["Raid"]["profiles"] == {"AuditCleric": True}
    assert all(not item.enabled for item in batch)
    assert batch[0].sound_path == "" and batch.has_embedded_audio(batch[0])
    batch.materialize_selected([batch[0]])
    assert resolve_portable_path(batch[0].sound_path).read_bytes() == _wav()
    assert batch[1].sound_path == ""
    after = batch[0].to_list()
    for index in range(len(before)):
        if index not in {4, 6, 8}:
            assert after[index] == before[index], index


def test_native_never_reads_or_exports_external_audio_path(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "profile"))
    outside = tmp_path / "secret.wav"
    outside.write_bytes(_wav(b"private"))
    content, warnings = serialize_vantage_package([CustomTrigger("Safe", "match", "", sound_path=str(outside))])
    assert str(outside).encode() not in content and b"private" not in content
    assert warnings[0]["code"] == "unshared-audio"
    batch = import_vantage_package_bytes(content)
    assert not batch._media and batch[0].sound_path == ""


def test_native_invalid_media_and_records_are_review_warnings_not_materialized(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "profile"))
    data = {"format": "vantage-trigger-pack", "version": 1,
            "triggers": [{"values": CustomTrigger("Good", "match", "").to_list(), "media": {"sound_path": "x"}},
                         {"values": ["Bad", "", ""]}],
            "media": {"x": {"name": "../../payload.exe", "base64": base64.b64encode(b"MZ").decode()}}}
    batch = import_vantage_package_bytes(json.dumps(data).encode())
    assert len(batch) == 1 and batch[0].enabled is False and not batch._media
    assert {entry["code"] for entry in batch.warnings} >= {"invalid-audio", "missing-audio", "skipped-entry"}
    assert not (tmp_path / "profile").exists()
    with pytest.raises(GinaImportError, match="could not be read"):
        import_vantage_package_bytes(b"{" + b"[" * 2000)
    with pytest.raises(GinaImportError, match="safety limit"):
        import_vantage_package_bytes(b" " * (gina_import.MAX_PACKAGE_BYTES + 1))


def test_gina_subset_roundtrip_xml_archive_audio_and_explicit_losses(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "profile"))
    wav = store_portable_bytes(_wav(), "main.wav", subdir="sounds")
    trigger = CustomTrigger("Pack", "{Actor} is marked.", "00:00:30", category="Raid/Markers",
                            sound_path=wav, alert_text="MARK {Actor}", timer_type="countdown",
                            timer_name="Mark ${1}", restart_behavior="new", restart_based_on_timer_name=True,
                            timer_visible_seconds=12, timer_ending_seconds=5,
                            timer_ending_tts="Ending", timer_ending_delivery="tts",
                            timer_ended_alert="Done", counter_reset_seconds=45,
                            clipboard_text="/target {Actor}", profile="AuditCleric", text_color="#E5C267",
                            end_patterns=[{"text": "marked ends", "regex": False}])
    content, warnings = serialize_gina_package([trigger], {"Raid": {"enabled": False}})
    codes = {entry["code"] for entry in warnings}
    assert codes >= {"gina-subset", "gina-settings-loss", "gina-group-loss"}
    package = tmp_path / "export.gtp"
    package.write_bytes(content)
    with zipfile.ZipFile(package) as archive:
        assert "ShareData.xml" in archive.namelist()
        audio = [entry for entry in archive.infolist() if entry.filename.endswith(".wav")]
        assert len(audio) == 1 and audio[0].comment == b"1"
    batch = import_gina_package(package)
    imported = batch[0]
    assert imported.enabled is False and imported.category == trigger.category
    for field in ("name", "text", "time", "alert_text", "timer_name", "restart_behavior",
                  "restart_based_on_timer_name", "timer_visible_seconds", "timer_ending_seconds",
                  "timer_ending_tts", "timer_ended_alert", "counter_reset_seconds", "clipboard_text", "end_patterns"):
        assert getattr(imported, field) == getattr(trigger, field), field
    assert imported.profile == "" and imported.text_color == ""
    assert batch.has_embedded_audio(imported)


def test_gina_gallery_audio_loss_is_explicit():
    content, warnings = serialize_gina_package([CustomTrigger("Gallery", "match", "", sound_path="builtin:warden-bell")])
    assert content and "gina-audio-loss" in {entry["code"] for entry in warnings}


def test_native_malformed_metadata_and_nonfinite_rows_are_bounded_review_warnings():
    good = CustomTrigger("Good", "match", "").to_list()
    bad = CustomTrigger("Bad", "other", "").to_list()
    bad[36] = float("inf")
    data = {"format": "vantage-trigger-pack", "version": 1,
            "triggers": [{"values": good}, {"values": bad}],
            "groups": {"Bad order": {"order": float("inf")}, "NaN": {"order": float("nan")},
                       "/".join(["Deep"] * 2000): True,
                       "Raid": {"profiles": {str(index): False for index in range(257)}}}}
    batch = import_vantage_package_bytes(json.dumps(data).encode())
    assert len(batch) == 1 and batch[0].enabled is False
    assert len(batch.groups) == 1
    assert {entry["code"] for entry in batch.warnings} >= {"skipped-entry", "group-metadata"}
    data["triggers"][1]["values"] = CustomTrigger("Deep rule", "other", "", category="/".join(["x"] * 2000)).to_list()
    batch = import_vantage_package_bytes(json.dumps(data).encode())
    assert len(batch) == 1 and any(entry["code"] == "skipped-entry" for entry in batch.warnings)


def test_native_denied_portable_wav_is_explicit_omission(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "profile"))
    wav = store_portable_bytes(_wav(), "denied.wav", subdir="sounds")
    source = resolve_portable_path(wav)
    original_read = type(source).read_bytes
    def denied(path):
        if path == source:
            raise PermissionError("synthetic denied WAV")
        return original_read(path)
    monkeypatch.setattr(type(source), "read_bytes", denied)
    content, warnings = serialize_vantage_package([CustomTrigger("Denied", "match", "", sound_path=wav)])
    assert not json.loads(content)["media"]
    assert warnings[0]["code"] == "unshared-audio"


def test_native_unknown_overlay_and_string_booleans_do_not_silently_change_behavior():
    good = CustomTrigger("Route review", "match", "").to_list()
    good[10] = "recipient-missing-custom-overlay"
    invalid = CustomTrigger("Invalid Boolean", "other", "").to_list()
    invalid[7] = "False"
    data = {"format": "vantage-trigger-pack", "version": 1,
            "triggers": [{"values": good}, {"values": invalid}]}
    batch = import_vantage_package_bytes(json.dumps(data).encode())
    assert len(batch) == 1 and batch[0].enabled is False
    assert batch[0].overlay_id != good[10]
    assert {entry["code"] for entry in batch.warnings} >= {"overlay-remapped", "skipped-entry"}
