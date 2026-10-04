"""Selective layout copying keeps unrelated UI and character files intact."""
import json
import pytest
from vantage.helpers import ui_profile_manager as profiles


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / "EQ"
    root.mkdir()
    (root / "eqgame.exe").write_bytes(b"fixture")
    skin = "VantageUI-v1.44.99"
    (root / "uifiles" / skin).mkdir(parents=True)
    source = root / "UI_Alpha_P1999Green.ini"
    target = root / "UI_Beta_P1999Green.ini"
    source.write_bytes(b"[Main]\r\nUISkin=velious\r\n[ChatWindow]\r\nXPos1920x1080=10\r\nWidth1920x1080=600\r\n[BuffWindow]\r\nYPos1280x720=99\r\n")
    target.write_bytes(b"; target comment\r\n[Main]\r\nUISkin=rustle2\r\nOther=keep\r\n[ChatWindow]\r\nXPos1920x1080=80\r\n[BuffWindow]\r\nYPos1280x720=15\r\n[InventoryWindow]\r\nKeep=1\r\n")
    regular = root / "Beta_P1999Green.ini"
    regular.write_bytes(b"[Socials]\r\nMyClassMacro=keep\r\n")
    monkeypatch.setattr(profiles.ui_skin_updater, "game_running", lambda: False)
    monkeypatch.setattr(profiles.ui_skin_updater, "installed_folder", lambda _root: skin)
    return root, skin, source, target, regular, tmp_path / "backups"


def test_specific_windows_preserve_unselected_bytes_and_restore(install):
    root, skin, source, target, regular, state = install
    before, source_before, regular_before = target.read_bytes(), source.read_bytes(), regular.read_bytes()
    assert profiles.layout_sections(root, source.name) == ("ChatWindow", "BuffWindow")
    result = profiles.copy_layout(root, skin, source.name, [target.name], state, sections=["chatwindow"], update_skin=False)
    after = target.read_bytes()
    assert b"XPos1920x1080=10\r\nWidth1920x1080=600" in after
    assert b"[BuffWindow]\r\nYPos1280x720=15\r\n[InventoryWindow]\r\nKeep=1\r\n" in after
    assert after.startswith(b"; target comment\r\n[Main]\r\nUISkin=rustle2\r\nOther=keep\r\n")
    assert source.read_bytes() == source_before
    assert regular.read_bytes() == regular_before
    assert profiles.copy_layout(root, skin, source.name, [target.name], state, sections=["ChatWindow"], update_skin=False).changed == 0
    profiles.restore_backup(root, state, result.backup_id)
    assert target.read_bytes() == before


def test_all_windows_without_vantageui_keep_main_and_copy_every_resolution(install, monkeypatch):
    root, _skin, source, target, regular, state = install
    monkeypatch.setattr(profiles.ui_skin_updater, "installed_folder", lambda _root: "")
    profiles.copy_layout(root, "", source.name, [target.name], state, update_skin=False)
    assert b"UISkin=rustle2" in target.read_bytes()
    assert b"XPos1920x1080=10" in target.read_bytes()
    assert b"YPos1280x720=99" in target.read_bytes()
    assert regular.read_bytes() == b"[Socials]\r\nMyClassMacro=keep\r\n"


def test_selected_missing_target_section_is_added_and_skin_is_explicit(install):
    root, skin, source, target, _regular, state = install
    target.write_bytes(b"[Main]\nUISkin=velious\n[InventoryWindow]\nKeep=1")
    profiles.copy_layout(root, skin, source.name, [target.name], state, sections=["BuffWindow"])
    payload = target.read_bytes()
    assert f"UISkin={skin}".encode() in payload
    assert b"Keep=1\n[BuffWindow]\nYPos1280x720=99\n" in payload


@pytest.mark.parametrize("sections", [[], ["Main"], ["NotThere"], [123], "ChatWindow"])
def test_invalid_sections_never_write_or_create_backup(install, sections):
    root, skin, source, target, _regular, state = install
    before = target.read_bytes()
    with pytest.raises(profiles.UIProfileError):
        profiles.copy_layout(root, skin, source.name, [target.name], state, sections=sections)
    assert target.read_bytes() == before
    assert not state.exists()


def test_duplicate_ini_sections_rejected_before_write(install):
    root, skin, source, target, _regular, state = install
    source.write_bytes(source.read_bytes() + b"[chatwindow]\nXPos=5\n")
    with pytest.raises(profiles.UIProfileError, match="ambiguous"):
        profiles.copy_layout(root, skin, source.name, [target.name], state, sections=["ChatWindow"])
    assert not state.exists()


def test_elevated_layout_preserves_selected_scope(install, monkeypatch, tmp_path):
    root, _skin, source, target, _regular, state = install
    directory = tmp_path / "ui-profile-requests"
    directory.mkdir()
    request = directory / ("ui-profile-" + "a" * 32 + ".json")
    request.write_text(json.dumps({"schema": 1, "nonce": "fixture", "action": "layout", "eq_root": str(root), "options": {"skin_folder": "", "source": source.name, "targets": [target.name], "sections": ["BuffWindow"], "update_skin": False}}))
    monkeypatch.setattr(profiles, "data_dir", lambda *_args: state)
    assert profiles.process_elevated_profile_request(request, "fixture") == 0
    assert b"YPos1280x720=99" in target.read_bytes()
    assert b"XPos1920x1080=80" in target.read_bytes()
    assert b"UISkin=rustle2" in target.read_bytes()
