from pathlib import Path
import shutil

from vantage.helpers.portable import (
    data_dir, resolve_portable_path, store_portable_bytes,
    store_portable_file, user_data_root)


def test_copied_sounds_remain_relocatable_inside_profile(tmp_path, monkeypatch):
    first_root = tmp_path / "first" / "Vantage"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(first_root))

    source = tmp_path / "alarm.wav"
    source.write_bytes(b"RIFF-portable-test")
    stored = store_portable_file(str(source))

    assert stored == "portable:sounds/alarm.wav"
    assert resolve_portable_path(stored).read_bytes() == b"RIFF-portable-test"
    assert data_dir("cache").is_dir()

    second_root = tmp_path / "second" / "Vantage"
    second_root.parent.mkdir(parents=True)
    shutil.copytree(first_root, second_root)
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(second_root))

    assert resolve_portable_path(stored) == second_root / "sounds" / "alarm.wav"
    assert resolve_portable_path(stored).is_file()


def test_portable_uri_cannot_escape_data_folder(tmp_path, monkeypatch):
    root = tmp_path / "Vantage"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(root))

    resolved = resolve_portable_path("portable:../../outside.txt")

    assert resolved == root / "invalid-portable-path"
    assert not resolved.exists()


def test_in_memory_files_are_sanitized_deduplicated_and_collision_safe(
        tmp_path, monkeypatch):
    root = tmp_path / "Vantage"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(root))

    first = store_portable_bytes(
        b"RIFF-one-WAVE", "../../danger alarm.WAV", "sounds/gina-imports")
    same = store_portable_bytes(
        b"RIFF-one-WAVE", "danger alarm.WAV", "sounds/gina-imports")
    other = store_portable_bytes(
        b"RIFF-two-WAVE", "danger alarm.WAV", "sounds/gina-imports")

    assert first == same == "portable:sounds/gina-imports/danger alarm.wav"
    assert other.startswith("portable:sounds/gina-imports/danger alarm-")
    assert resolve_portable_path(first).read_bytes() == b"RIFF-one-WAVE"
    assert resolve_portable_path(other).read_bytes() == b"RIFF-two-WAVE"


def test_default_storage_uses_local_app_data_not_executable_folder(
        tmp_path, monkeypatch):
    monkeypatch.delenv("VANTAGE_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    expected = (tmp_path / "LocalAppData" / "Vantage").resolve()

    assert user_data_root() == expected
    assert data_dir() == expected
