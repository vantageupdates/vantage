import json
from pathlib import Path
import subprocess

import pytest

from vantage.helpers import ui_profile_manager as profiles


def _profile(character, server, skin, marker):
    return (
        "[Main]\r\n"
        f"UISkin={skin}\r\n"
        "AtlasSkin=Default\r\n"
        "[ChatWindow]\r\n"
        f"XPos={marker}\r\n").encode("cp1252")


@pytest.fixture
def eq_install(tmp_path, monkeypatch):
    root = tmp_path / "EverQuest"
    root.mkdir()
    (root / "eqgame.exe").write_bytes(b"game")
    skin = "VantageUI-v1.44.70"
    (root / "uifiles" / skin).mkdir(parents=True)
    (root / "UI_Alpha_P1999Green.ini").write_bytes(
        _profile("Alpha", "P1999Green", "velious", 11))
    (root / "UI_Beta_P1999Blue.ini").write_bytes(
        _profile("Beta", "P1999Blue", "rustle2", 99))
    (root / "Alpha_P1999Green.ini").write_bytes(
        b"[Socials]\r\nPage1Button1Name=WTS\r\n")
    (root / "eqclient.ini").write_bytes(
        b"[Main]\r\nUISkin=velious\r\nSound=TRUE\r\n")
    monkeypatch.setattr(profiles.ui_skin_updater, "game_running", lambda: False)
    monkeypatch.setattr(
        profiles.ui_skin_updater, "installed_folder", lambda _root: skin)
    return root, skin, tmp_path / "backups"


def test_discovery_only_returns_character_ui_profiles(eq_install):
    root, _skin, _state = eq_install
    found = profiles.discover_character_profiles(root)
    assert [(item.filename, item.label, item.skin) for item in found] == [
        ("UI_Alpha_P1999Green.ini", "Alpha · Green", "velious"),
        ("UI_Beta_P1999Blue.ini", "Beta · Blue", "rustle2"),
    ]


def test_apply_skin_changes_only_uiskin_and_creates_restore_point(eq_install):
    root, skin, state = eq_install
    alpha_path = root / "UI_Alpha_P1999Green.ini"
    character_settings = root / "Alpha_P1999Green.ini"
    settings_before = character_settings.read_bytes()

    result = profiles.apply_skin_to_all(root, skin, state)

    assert result.action == "skin"
    assert result.changed == 3
    assert f"UISkin={skin}" in alpha_path.read_text(encoding="cp1252")
    assert "XPos=11" in alpha_path.read_text(encoding="cp1252")
    assert "Sound=TRUE" in (root / "eqclient.ini").read_text(encoding="cp1252")
    assert character_settings.read_bytes() == settings_before
    backups = profiles.list_backups(state, root)
    assert len(backups) == 1
    assert backups[0].backup_id == result.backup_id
    assert backups[0].file_count == 3


def test_automatic_skin_sync_can_report_already_current_without_empty_backup(
        eq_install):
    root, skin, state = eq_install
    first = profiles.apply_skin_to_all(root, skin, state)
    second = profiles.apply_skin_to_all(
        root, skin, state, allow_no_changes=True)

    assert first.changed == 3
    assert second == profiles.ProfileOperationResult("skin", 0, "", ())
    assert len(profiles.list_backups(state, root)) == 1


def test_copy_layout_copies_only_ui_file_and_restore_is_reversible(eq_install):
    root, skin, state = eq_install
    beta = root / "UI_Beta_P1999Blue.ini"
    beta_before = beta.read_bytes()
    character_settings = root / "Alpha_P1999Green.ini"
    settings_before = character_settings.read_bytes()

    copied = profiles.copy_layout(
        root, skin, "UI_Alpha_P1999Green.ini",
        ["UI_Beta_P1999Blue.ini"], state)

    copied_text = beta.read_text(encoding="cp1252")
    assert copied.changed == 1
    assert "XPos=11" in copied_text
    assert f"UISkin={skin}" in copied_text
    assert character_settings.read_bytes() == settings_before

    restored = profiles.restore_backup(root, state, copied.backup_id)
    assert restored.action == "restore"
    assert beta.read_bytes() == beta_before
    assert len(profiles.list_backups(state, root)) == 2


def test_partial_write_failure_rolls_back_every_changed_file(
        eq_install, monkeypatch):
    root, skin, state = eq_install
    paths = [
        root / "UI_Alpha_P1999Green.ini",
        root / "UI_Beta_P1999Blue.ini",
        root / "eqclient.ini",
    ]
    before = {path: path.read_bytes() for path in paths}
    original_write = profiles._atomic_write
    calls = 0

    def fail_second(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("locked")
        return original_write(path, payload)

    monkeypatch.setattr(profiles, "_atomic_write", fail_second)
    with pytest.raises(PermissionError, match="locked"):
        profiles.apply_skin_to_all(root, skin, state)

    assert {path: path.read_bytes() for path in paths} == before
    assert profiles.list_backups(state, root) == ()


def test_profile_changes_wait_while_everquest_is_running(
        eq_install, monkeypatch):
    root, skin, state = eq_install
    monkeypatch.setattr(profiles.ui_skin_updater, "game_running", lambda: True)
    with pytest.raises(profiles.UIProfileError, match="Close EverQuest"):
        profiles.apply_skin_to_all(root, skin, state)


@pytest.mark.parametrize("source, targets", [
    ("missing.ini", ["UI_Beta_P1999Blue.ini"]),
    ("UI_Alpha_P1999Green.ini", ["UI_Alpha_P1999Green.ini"]),
])
def test_copy_layout_rejects_invalid_source_or_empty_targets(
        eq_install, source, targets):
    root, skin, state = eq_install
    with pytest.raises(profiles.UIProfileError):
        profiles.copy_layout(root, skin, source, targets, state)


def test_elevated_command_reuses_current_one_file_companion(tmp_path):
    companion = tmp_path / "Vantage.exe"
    companion.touch()
    request = tmp_path / "ui-profile-requests" / (
        "ui-profile-" + "a" * 32 + ".json")
    request.parent.mkdir()
    request.touch()

    program, arguments = profiles.elevated_profile_command(
        request, "nonce", current_executable=companion, frozen=True)

    assert Path(program) == companion
    assert arguments == subprocess.list2cmdline([
        "--manage-ui-profiles", str(request.resolve()), "nonce"])


def test_elevated_request_processes_only_declared_profile_action(
        eq_install, monkeypatch, tmp_path):
    root, skin, _state = eq_install
    requests = tmp_path / "ui-profile-requests"
    requests.mkdir()
    request = requests / ("ui-profile-" + "b" * 32 + ".json")
    nonce = "verified-nonce"
    request.write_text(json.dumps({
        "schema": 1, "nonce": nonce, "action": "skin",
        "eq_root": str(root),
        "options": {"skin_folder": skin, "include_eqclient": True},
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        profiles, "data_dir", lambda *_parts: tmp_path / "backups")
    monkeypatch.setattr(
        profiles, "apply_skin_to_all",
        lambda *args, **kwargs: calls.append((args, kwargs)) or
        profiles.ProfileOperationResult(
            "skin", 3, "c" * 32,
            ("UI_Alpha_P1999Green.ini", "UI_Beta_P1999Blue.ini",
             "eqclient.ini")))

    assert profiles.process_elevated_profile_request(request, nonce) == 0

    result = json.loads(request.with_suffix(".result.json").read_text())
    assert result["ok"] is True
    assert result["changed"] == 3
    assert calls[0][0][0] == str(root)
    assert calls[0][0][1] == skin
    assert calls[0][1]["include_eqclient"] is True
    assert not request.exists()
