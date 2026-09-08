"""Versioned updater invariants; all filesystem mutations use tmp_path fixtures."""

import json
import os
from pathlib import Path

import pytest

from vantage.helpers import ui_skin_updater as updater
from tests.test_ui_skin_updater import _release, _entry, _manifest, fixture


def _install(tmp_path, monkeypatch, game, state, version="1.2.3", **kwargs):
    release = _release(tmp_path, monkeypatch, version=version, schema=2)
    return updater.install_release(release, game, state, log=lambda _: None, **kwargs)


def _registry(game):
    return json.loads((game / "uifiles" / updater.REGISTRY_NAME).read_text())


def _folder(game, version):
    return game / "uifiles" / updater.folder_name(version)


def _tree(path):
    return {entry.relative_to(path).as_posix(): entry.read_bytes()
            for entry in path.rglob("*") if entry.is_file()}


def test_legacy_unknown_files_other_skins_and_character_ini_are_preserved(
        fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    (legacy / "EQUI_Test.xml").write_bytes(b"unpublished local repair")
    (legacy / "personal.xml").write_bytes(b"my modification")
    (legacy / updater.VERSION_MARKER).write_text('{"schema":1,"version":"99.0.0"}')
    (game / "UI_MyCharacter.ini").write_bytes(b"personal layout")
    default = game / "uifiles" / "default"
    default.mkdir()
    (default / "EQUI_Test.xml").write_bytes(b"default UI")
    before = _tree(legacy)
    assert updater.installed_version(game) == ""
    assert updater.installed_folder(game) == ""
    assert updater.loadskin_command(game) == ""
    # A schema-1 release remains consumable, but it never authorizes legacy edits.
    release = _release(tmp_path, monkeypatch)
    result = updater.install_release(release, game, state, log=lambda _: None)
    assert result.folder == "VantageUI-v1.2.3"
    assert result.changed_files == 2 and result.action == "installed"
    assert _tree(legacy) == before
    assert (default / "EQUI_Test.xml").read_bytes() == b"default UI"
    assert (game / "UI_MyCharacter.ini").read_bytes() == b"personal layout"
    assert (_folder(game, "1.2.3") / "button.tga").read_bytes() == b"new pixels"
    assert updater.loadskin_command(game) == "/loadskin VantageUI-v1.2.3 1"
    with pytest.raises(updater.SkinUpdateError, match="No previous versioned"):
        updater.rollback_last(game, state, log=lambda _: None)
    assert updater.install_release(release, game, state, log=lambda _: None).action == "already-current"
    assert _tree(legacy) == before


def test_upgrade_retains_active_and_two_fallbacks_fourth_install_prunes_oldest(
        fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    unmanaged = _folder(game, "0.1.0")
    unmanaged.mkdir()
    (unmanaged / "custom.xml").write_bytes(b"not registered")
    for version in ("1.2.3", "1.2.4", "1.2.5"):
        result = _install(tmp_path, monkeypatch, game, state, version)
        assert result.warnings == ()
    assert set(_registry(game)["managed"]) == {"VantageUI-v1.2.3", "VantageUI-v1.2.4", "VantageUI-v1.2.5"}
    assert _install(tmp_path, monkeypatch, game, state, "1.2.6").warnings == ()
    registry = _registry(game)
    assert registry["active"] == "VantageUI-v1.2.6"
    assert registry["previous"] == "VantageUI-v1.2.5"
    assert set(registry["managed"]) == {"VantageUI-v1.2.4", "VantageUI-v1.2.5", "VantageUI-v1.2.6"}
    assert not _folder(game, "1.2.3").exists()
    assert _folder(game, "1.2.4").is_dir()
    assert unmanaged.is_dir() and legacy.is_dir()


@pytest.mark.parametrize("change", ["edit", "extra", "missing", "nested"])
def test_new_release_preserves_edited_active_and_later_retention_keeps_it(
        fixture, tmp_path, monkeypatch, change):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    original = _folder(game, "1.2.3")
    if change == "edit":
        (original / "EQUI_Test.xml").write_bytes(b"unpublished local edits")
    elif change == "extra":
        (original / "private.ini").write_bytes(b"private data")
    elif change == "missing":
        (original / "button.tga").unlink()
    else:
        (original / "private").mkdir()
        (original / "private" / "personal.txt").write_bytes(b"personal")
    before = _tree(original)
    # Identity and marker remain trusted, while no pristine-payload claim is made.
    assert updater.installed_folder(game) == "VantageUI-v1.2.3"
    assert updater.loadskin_command(game) == "/loadskin VantageUI-v1.2.3 1"
    result = _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert result.warnings and "local changes" in result.warnings[0]
    assert _registry(game)["previous"] == "VantageUI-v1.2.3"
    assert _tree(original) == before
    with pytest.raises(updater.SkinUpdateError):
        updater.rollback_last(game, state, log=lambda _: None)
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    assert _tree(original) == before  # Second fallback is retained even if edited.
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings and original.exists()
    assert _tree(original) == before
    assert updater.installed_version(game) == "1.2.6"


def test_recovery_can_finish_new_release_with_edited_previous_active(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    path = _folder(game, "1.2.3") / "EQUI_Test.xml"
    path.write_bytes(b"my active skin edits")
    real_rename = updater._rename_no_replace
    def interrupt(source, destination):
        real_rename(source, destination)
        raise KeyboardInterrupt()
    monkeypatch.setattr(updater, "_rename_no_replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    monkeypatch.setattr(updater, "_rename_no_replace", real_rename)
    logs = []
    assert updater.recover_pending(game, tmp_path / "another-profile", log=logs.append)
    assert updater.installed_version(game) == "1.2.4"
    assert path.read_bytes() == b"my active skin edits"
    assert any("Preserved local changes" in line for line in logs)


@pytest.mark.parametrize("change", ["marker", "directory-identity"])
def test_untrusted_active_metadata_still_blocks_new_release_and_folder_command(
        fixture, tmp_path, monkeypatch, change):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    original = _folder(game, "1.2.3")
    if change == "marker":
        (original / updater.VERSION_MARKER).write_text("{}")
    else:
        saved = tmp_path / "original-version"
        os.rename(original, saved)
        original.mkdir()
        for child in saved.iterdir():
            (original / child.name).write_bytes(child.read_bytes())
    with pytest.raises(updater.SkinUpdateError):
        updater.loadskin_command(game)
    with pytest.raises(updater.SkinUpdateError):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert not _folder(game, "1.2.4").exists()

def test_rollback_swaps_selection_and_never_writes_payload_bytes(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    before = {_folder(game, version): _tree(_folder(game, version))
              for version in ("1.2.3", "1.2.4")}
    result = updater.rollback_last(game, tmp_path / "another-profile", log=lambda _: None)
    assert (result.version, result.folder, result.changed_files) == ("1.2.3", "VantageUI-v1.2.3", 0)
    assert updater.loadskin_command(game) == "/loadskin VantageUI-v1.2.3 1"
    assert all(_tree(path) == contents for path, contents in before.items())
    assert _registry(game)["previous"] == "VantageUI-v1.2.4"
    assert updater.rollback_last(game, state, log=lambda _: None).version == "1.2.4"


@pytest.mark.parametrize("kind", ["unmanaged", "different-case", "empty-file"])
def test_new_version_collision_is_untouched(fixture, tmp_path, monkeypatch, kind):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    name = "vantageui-v1.2.4" if kind == "different-case" else "VantageUI-v1.2.4"
    collision = game / "uifiles" / name
    if kind == "empty-file":
        collision.write_bytes(b"collision")
    else:
        collision.mkdir()
        (collision / "private.xml").write_bytes(b"keep")
    with pytest.raises(updater.SkinUpdateError, match="collision"):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert collision.exists()
    assert updater.installed_version(game) == "1.2.3"


@pytest.mark.parametrize("change", ["modified", "extra", "missing", "marker", "nested"])
def test_same_version_changed_tree_is_not_repaired_or_relabelled(
        fixture, tmp_path, monkeypatch, change):
    game, _, state = fixture
    release = _release(tmp_path, monkeypatch, schema=2)
    updater.install_release(release, game, state, log=lambda _: None)
    target = _folder(game, "1.2.3")
    if change == "modified":
        (target / "EQUI_Test.xml").write_bytes(b"user edit")
    elif change == "extra":
        (target / "personal.ini").write_bytes(b"private")
    elif change == "missing":
        (target / "button.tga").unlink()
    elif change == "marker":
        (target / updater.VERSION_MARKER).write_text("{}")
    else:
        (target / "private").mkdir()
        (target / "private" / "secret.txt").write_bytes(b"private")
    before = _tree(target)
    with pytest.raises(updater.SkinUpdateError):
        updater.install_release(release, game, state, log=lambda _: None)
    assert _tree(target) == before


def test_release_10_is_newer_than_9_and_downgrade_refused(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state, "1.2.9")
    _install(tmp_path, monkeypatch, game, state, "1.2.10")
    with pytest.raises(updater.SkinUpdateError, match="older release"):
        _install(tmp_path, monkeypatch, game, state, "1.2.9")
    assert updater.installed_folder(game) == "VantageUI-v1.2.10"


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "1.2.3-rc1", "../1.2.3",
                                    "1.2.3/", "1.2.3 ", "1.2.3:evil", "", None])
def test_folder_names_reject_invalid_versions_and_traversal(version):
    with pytest.raises(updater.SkinUpdateError):
        updater.folder_name(version)


@pytest.mark.parametrize("folder", ["VantageUI", "vantageui-v1.2.3", "VantageUI-v1.2.4",
                                   "VantageUI-v1.2.3/../default"])
def test_schema2_rejects_any_noncanonical_folder(folder):
    with pytest.raises(updater.SkinUpdateError):
        updater.validate_manifest(_manifest([_entry("a.xml")], schema=2, skin_folder=folder), "1.2.3")


def test_schema2_accepts_exact_versioned_folder():
    assert updater.validate_manifest(_manifest([_entry("a.xml")], schema=2,
        skin_folder="VantageUI-v1.2.3"), "1.2.3")[0]["path"] == "a.xml"


@pytest.mark.parametrize("change", ["private", "edit", "marker", "nested", "hardlink"])
def test_retention_preserves_any_changed_or_private_older_folder(
        fixture, tmp_path, monkeypatch, change):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    older = _folder(game, "1.2.3")
    if change == "private":
        (older / "private.ini").write_bytes(b"personal")
    elif change == "edit":
        (older / "EQUI_Test.xml").write_bytes(b"local edits")
    elif change == "marker":
        (older / updater.VERSION_MARKER).write_bytes(b"changed marker")
    elif change == "nested":
        (older / "secret").mkdir()
        (older / "secret" / "private.txt").write_bytes(b"personal")
    else:
        external = tmp_path / "outside.xml"
        external.write_bytes((older / "EQUI_Test.xml").read_bytes())
        (older / "EQUI_Test.xml").unlink()
        os.link(external, older / "EQUI_Test.xml")
    before = _tree(older)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.action == "installed" and result.warnings
    assert _tree(older) == before
    assert updater.installed_version(game) == "1.2.6"
    assert "VantageUI-v1.2.3" in _registry(game)["managed"]


def test_retention_defers_until_game_closed_and_can_run_from_different_profile(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    monkeypatch.setattr(updater, "game_running", lambda: True)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6", allow_game_running=True)
    assert result.warnings and "deferred" in result.warnings[0]
    assert all(_folder(game, v).exists() for v in ("1.2.3", "1.2.4", "1.2.5", "1.2.6"))
    monkeypatch.setattr(updater, "game_running", lambda: False)
    updater.recover_pending(game, tmp_path / "profile-two", log=lambda _: None)
    assert not _folder(game, "1.2.3").exists()
    assert _folder(game, "1.2.4").exists() and _folder(game, "1.2.6").exists()


@pytest.mark.parametrize("interrupt_at", ["first-file", "second-file", "before-rename", "after-rename"])
def test_interrupted_publication_recovers_from_another_profile_without_legacy_edits(
        fixture, tmp_path, monkeypatch, interrupt_at):
    game, legacy, state = fixture
    (legacy / "original.xml").write_bytes(b"legacy")
    _install(tmp_path, monkeypatch, game, state)
    original_write = updater._write_new_bytes
    original_rename = updater._rename_no_replace
    def interrupted_write(path, data):
        if path.name == ("EQUI_Test.xml" if interrupt_at == "first-file" else "button.tga"):
            raise KeyboardInterrupt()
        return original_write(path, data)
    def interrupted_rename(source, destination):
        if interrupt_at == "before-rename":
            raise KeyboardInterrupt()
        original_rename(source, destination)
        raise KeyboardInterrupt()
    if interrupt_at in ("first-file", "second-file"):
        monkeypatch.setattr(updater, "_write_new_bytes", interrupted_write)
    else:
        monkeypatch.setattr(updater, "_rename_no_replace", interrupted_rename)
    with pytest.raises(KeyboardInterrupt):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert _registry(game)["active"] == "VantageUI-v1.2.3"
    assert _registry(game)["pending"] is not None
    monkeypatch.setattr(updater, "_write_new_bytes", original_write)
    monkeypatch.setattr(updater, "_rename_no_replace", original_rename)
    logs = []
    assert updater.recover_pending(game, tmp_path / "second-profile", log=logs.append)
    assert _registry(game)["pending"] is None
    assert (legacy / "original.xml").read_bytes() == b"legacy"
    if interrupt_at in ("first-file", "second-file"):
        assert updater.installed_version(game) == "1.2.3"
        assert any("Incomplete staging folder preserved" in line for line in logs)
    else:
        assert updater.installed_version(game) == "1.2.4"
        assert _registry(game)["previous"] == "VantageUI-v1.2.3"


def test_cleanup_failure_does_not_undo_committed_install(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    def blocked(*args):
        raise PermissionError("sharing violation")
    monkeypatch.setattr(updater, "_delete_verified_file", blocked)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.action == "installed" and result.warnings
    assert updater.installed_version(game) == "1.2.6"
    record = _registry(game)["managed"]["VantageUI-v1.2.3"]
    quarantine = game / "uifiles" / record["quarantine"]
    assert (quarantine / "EQUI_Test.xml").read_bytes() == b"<XML>new</XML>"
    assert _folder(game, "1.2.4").is_dir()


def test_concurrent_registry_change_before_commit_is_not_overwritten(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    real_rename = updater._rename_no_replace
    observed = None
    def alter_pointer(source, destination):
        nonlocal observed
        real_rename(source, destination)
        registry = _registry(game)
        registry["revision"] += 100
        observed = json.dumps(registry).encode()
        (game / "uifiles" / updater.REGISTRY_NAME).write_bytes(observed)
    monkeypatch.setattr(updater, "_rename_no_replace", alter_pointer)
    with pytest.raises(updater.SkinUpdateError, match="changed concurrently"):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert (game / "uifiles" / updater.REGISTRY_NAME).read_bytes() == observed
    assert updater.installed_version(game) == "1.2.3"
    assert _folder(game, "1.2.4").exists()


def test_concurrent_file_change_after_quarantine_prevents_deletion(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    real_rename = updater._rename_no_replace
    changed = None
    def alter_file(source, destination):
        nonlocal changed
        real_rename(source, destination)
        if destination.name.startswith(".vantage-ui-retired-"):
            changed = destination / "EQUI_Test.xml"
            changed.write_bytes(b"concurrent private edit")
    monkeypatch.setattr(updater, "_rename_no_replace", alter_file)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings
    assert changed.read_bytes() == b"concurrent private edit"
    assert (changed.parent / "button.tga").exists()
    assert updater.installed_version(game) == "1.2.6"


def test_shared_namespace_lock_serializes_different_profiles(fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    release = _release(tmp_path, monkeypatch)
    with updater._target_lock(game / "uifiles"):
        with pytest.raises(updater.SkinUpdateError, match="already installing"):
            updater.install_release(release, game, tmp_path / "other-profile", log=lambda _: None)
    assert not _folder(game, "1.2.3").exists()
    assert list(legacy.iterdir()) == []


def test_old_legacy_recovery_marker_is_preserved_and_explicitly_reported(fixture):
    game, legacy, state = fixture
    marker = legacy / updater.RECOVERY_MARKER
    marker.write_text('{"state":"never-follow-this-path","transaction":"old"}')
    before = marker.read_bytes()
    logs = []
    assert not updater.recover_pending(game, state, log=logs.append)
    assert marker.read_bytes() == before
    assert any("old recovery marker" in line and "original updater" in line for line in logs)


def test_rollback_refuses_changed_previous_folder_without_overwriting_it(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    path = _folder(game, "1.2.3") / "EQUI_Test.xml"
    path.write_bytes(b"private modifications")
    before = (game / "uifiles" / updater.REGISTRY_NAME).read_bytes()
    with pytest.raises(updater.SkinUpdateError, match="changed"):
        updater.rollback_last(game, state, log=lambda _: None)
    assert path.read_bytes() == b"private modifications"
    assert (game / "uifiles" / updater.REGISTRY_NAME).read_bytes() == before


def test_hardlinked_managed_marker_is_never_trusted(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    marker = _folder(game, "1.2.3") / updater.VERSION_MARKER
    outside = tmp_path / "marker-copy.json"
    os.link(marker, outside)
    with pytest.raises(updater.SkinUpdateError, match="hard-linked"):
        updater.installed_folder(game)
    assert outside.read_bytes() == marker.read_bytes()


def test_symlink_collision_never_changes_outside_target(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.xml").write_bytes(b"outside data")
    try:
        _folder(game, "1.2.3").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(updater.SkinUpdateError, match="Links and junctions"):
        _install(tmp_path, monkeypatch, game, state)
    assert (outside / "private.xml").read_bytes() == b"outside data"


def test_registry_rejects_traversal_and_case_aliases_before_any_cleanup(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    registry = _registry(game)
    record = registry["managed"]["VantageUI-v1.2.3"]
    registry["managed"]["../outside"] = record
    path = game / "uifiles" / updater.REGISTRY_NAME
    path.write_text(json.dumps(registry))
    before = _tree(_folder(game, "1.2.3"))
    with pytest.raises(updater.SkinUpdateError):
        updater.recover_pending(game, state, log=lambda _: None)
    assert _tree(_folder(game, "1.2.3")) == before


def test_same_version_republished_with_different_bytes_is_refused(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    before = _tree(_folder(game, "1.2.3"))
    replacement = _release(tmp_path, monkeypatch, schema=2,
                           files={"EQUI_Test.xml": b"unexpected new published bytes"})
    with pytest.raises(updater.SkinUpdateError, match="published bytes"):
        updater.install_release(replacement, game, state, log=lambda _: None)
    assert _tree(_folder(game, "1.2.3")) == before


def test_atomic_publication_never_replaces_an_empty_racing_collision(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    real_rename = updater.os.rename
    def collide(source, destination):
        destination.mkdir()
        real_rename(source, destination)
    if os.name != "nt":
        pytest.skip("Exercises the actual Windows no-replace rename primitive")
    monkeypatch.setattr(updater.os, "rename", collide)
    with pytest.raises(OSError):
        _install(tmp_path, monkeypatch, game, state)
    collision = _folder(game, "1.2.3")
    assert collision.is_dir() and list(collision.iterdir()) == []
    assert _registry(game)["active"] == ""
    assert _registry(game)["pending"] is not None
    monkeypatch.setattr(updater.os, "rename", real_rename)
    with pytest.raises(updater.SkinUpdateError, match="Both folders are preserved"):
        updater.recover_pending(game, state, log=lambda _: None)


def test_staging_file_added_by_another_process_is_never_overwritten(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    real_write = updater._write_new_bytes
    collision = None
    def collide(path, data):
        nonlocal collision
        if path.name == "EQUI_Test.xml":
            collision = path
            path.write_bytes(b"private staging edit")
        return real_write(path, data)
    monkeypatch.setattr(updater, "_write_new_bytes", collide)
    with pytest.raises(FileExistsError):
        _install(tmp_path, monkeypatch, game, state)
    assert collision.read_bytes() == b"private staging edit"
    assert not _folder(game, "1.2.3").exists()
    assert updater.installed_folder(game) == ""


@pytest.mark.parametrize("kind", ["folder", "file"])
def test_reparse_older_tree_is_preserved_without_symlink_privileges(
        fixture, tmp_path, monkeypatch, kind):
    from types import SimpleNamespace
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    older = _folder(game, "1.2.3")
    reparse = older if kind == "folder" else older / "EQUI_Test.xml"
    real_lstat = Path.lstat
    def attributes(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == reparse:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, "lstat", attributes)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings and "Links and junctions" in result.warnings[0]
    assert older.is_dir() and (older / "EQUI_Test.xml").read_bytes() == b"<XML>new</XML>"


def test_hardlinked_registry_is_refused_without_writing_external_data(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    source = game / "uifiles" / updater.REGISTRY_NAME
    external = tmp_path / "external-registry.json"
    os.link(source, external)
    before = external.read_bytes()
    with pytest.raises(updater.SkinUpdateError, match="hard-linked"):
        _install(tmp_path, monkeypatch, game, state, "1.2.4")
    assert external.read_bytes() == before
    assert not _folder(game, "1.2.4").exists()


def test_game_starting_during_cleanup_preserves_active_previous_and_remaining_retired_bytes(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    real_delete = updater._delete_verified_file
    def start_game(path, digest):
        real_delete(path, digest)
        monkeypatch.setattr(updater, "game_running", lambda: True)
    monkeypatch.setattr(updater, "_delete_verified_file", start_game)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.action == "installed" and result.warnings
    assert _folder(game, "1.2.4").is_dir() and _folder(game, "1.2.6").is_dir()
    record = _registry(game)["managed"]["VantageUI-v1.2.3"]
    retired = game / "uifiles" / record["quarantine"]
    assert len(list(retired.iterdir())) == 2
    assert (retired / updater.VERSION_MARKER).exists()


def test_user_file_added_mid_cleanup_is_preserved_and_stops_remaining_deletes(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    real_delete = updater._delete_verified_file
    private = None
    def private_edit(path, digest):
        nonlocal private
        real_delete(path, digest)
        private = path.parent / "private.ini"
        private.write_bytes(b"user file")
    monkeypatch.setattr(updater, "_delete_verified_file", private_edit)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings and "contents changed" in result.warnings[0]
    assert private.read_bytes() == b"user file"
    assert len(list(private.parent.iterdir())) == 3


def test_quarantined_directory_identity_swap_preserves_replacement_files(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    rename = updater._rename_no_replace
    changed = None
    def replace(source, destination):
        nonlocal changed
        rename(source, destination)
        if destination.name.startswith(".vantage-ui-retired-"):
            moved = tmp_path / "saved-original"
            os.rename(destination, moved)
            destination.mkdir()
            changed = destination / "private.xml"
            changed.write_bytes(b"replacement directory")
    monkeypatch.setattr(updater, "_rename_no_replace", replace)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings and "identity changed" in result.warnings[0]
    assert changed.read_bytes() == b"replacement directory"
    assert (tmp_path / "saved-original" / "EQUI_Test.xml").exists()


def test_no_100_percent_success_after_failed_staging_copy(fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    (legacy / "private.xml").write_bytes(b"keep")
    release = _release(tmp_path, monkeypatch)
    def blocked(path, data):
        raise PermissionError("sharing violation")
    monkeypatch.setattr(updater, "_write_new_bytes", blocked)
    monkeypatch.setattr(updater, "game_running", lambda: True)
    events = []
    with pytest.raises(PermissionError):
        updater.install_release(release, game, state, allow_game_running=True,
            log=lambda _: None, progress=lambda *event: events.append(event))
    assert all(event[1] < 100 for event in events)
    assert (legacy / "private.xml").read_bytes() == b"keep"
    assert not _folder(game, "1.2.3").exists()


def test_rollback_then_intermediate_release_never_prunes_a_newer_version(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state, "1.0.0")
    _install(tmp_path, monkeypatch, game, state, "3.0.0")
    updater.rollback_last(game, state, log=lambda _: None)
    result = _install(tmp_path, monkeypatch, game, state, "2.0.0")
    assert result.warnings and "newer registered folder" in result.warnings[0]
    assert _folder(game, "3.0.0").is_dir()
    assert updater.installed_version(game) == "2.0.0"
    assert _registry(game)["previous"] == "VantageUI-v1.0.0"


def test_verified_pending_folder_can_recover_while_game_open_only_with_opt_in(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    real_rename = updater._rename_no_replace
    def interrupted(source, destination):
        real_rename(source, destination)
        raise KeyboardInterrupt()
    monkeypatch.setattr(updater, "_rename_no_replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _install(tmp_path, monkeypatch, game, state)
    monkeypatch.setattr(updater, "_rename_no_replace", real_rename)
    monkeypatch.setattr(updater, "game_running", lambda: True)
    before = (game / "uifiles" / updater.REGISTRY_NAME).read_bytes()
    with pytest.raises(updater.SkinUpdateError, match="Close EverQuest"):
        updater.recover_pending(game, state, log=lambda _: None)
    assert (game / "uifiles" / updater.REGISTRY_NAME).read_bytes() == before
    assert updater.recover_pending(game, state, allow_game_running=True, log=lambda _: None)
    assert updater.installed_version(game) == "1.2.3"


def test_empty_directory_swapped_before_removal_is_preserved(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    _install(tmp_path, monkeypatch, game, state)
    _install(tmp_path, monkeypatch, game, state, "1.2.4")
    _install(tmp_path, monkeypatch, game, state, "1.2.5")
    actual = updater._delete_empty_directory
    replacement = None
    def swap(path, identity, before_delete):
        nonlocal replacement
        os.rename(path, tmp_path / "retired-empty-original")
        path.mkdir()
        replacement = path
        actual(path, identity, before_delete)
    monkeypatch.setattr(updater, "_delete_empty_directory", swap)
    result = _install(tmp_path, monkeypatch, game, state, "1.2.6")
    assert result.warnings and "folder changed" in result.warnings[0]
    assert replacement.is_dir() and list(replacement.iterdir()) == []
    assert updater.installed_version(game) == "1.2.6"
