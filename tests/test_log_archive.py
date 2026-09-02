from datetime import datetime

from PySide6.QtCore import QCoreApplication

from vantage.helpers import config
from vantage.helpers.log_archive import (
    ARCHIVE_INTERVAL_MS,
    LogArchiveService,
    archive_oversized_logs,
)


ONE_MB = 1024 * 1024
STAMP = datetime(2026, 8, 30, 12, 34, 56)


def test_archive_moves_only_oversized_eq_logs_and_preserves_bytes(tmp_path):
    source = tmp_path / "eqlog_Alice_Green.txt"
    payload = b"x" * (ONE_MB + 7)
    source.write_bytes(payload)
    small = tmp_path / "eqlog_Bob_Green.txt"
    small.write_bytes(b"small")
    unrelated = tmp_path / "notes_for_raid.txt"
    unrelated.write_bytes(b"leave me alone")

    report = archive_oversized_logs(tmp_path, size_mb=1, now=STAMP)

    destination = (
        tmp_path / "archive" /
        "eqlog_Alice_Green_2026-08-30_12-34-56.txt")
    assert report.errors == ()
    assert report.moved == (str(destination),)
    assert not source.exists()
    assert destination.read_bytes() == payload
    assert small.read_bytes() == b"small"
    assert unrelated.read_bytes() == b"leave me alone"


def test_archive_uses_collision_safe_names_without_overwriting(tmp_path):
    source = tmp_path / "eqlog_Alice_Green.txt"
    source.write_bytes(b"new" + b"x" * ONE_MB)
    archive = tmp_path / "archive"
    archive.mkdir()
    existing = archive / "eqlog_Alice_Green_2026-08-30_12-34-56.txt"
    existing.write_bytes(b"existing")

    report = archive_oversized_logs(tmp_path, size_mb=1, now=STAMP)

    destination = archive / "eqlog_Alice_Green_2026-08-30_12-34-56-2.txt"
    assert report.moved == (str(destination),)
    assert existing.read_bytes() == b"existing"
    assert destination.read_bytes().startswith(b"new")


def test_archive_reports_unavailable_log_folder_without_creating_data(tmp_path):
    missing = tmp_path / "missing"

    report = archive_oversized_logs(missing, size_mb=1, now=STAMP)

    assert report.moved == ()
    assert report.errors == ("The linked log folder is unavailable.",)
    assert not missing.exists()


def test_service_is_hourly_opt_in_and_disabled_mode_never_moves_logs(
        tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    source = tmp_path / "eqlog_Alice_Green.txt"
    source.write_bytes(b"x" * (ONE_MB + 1))
    monkeypatch.setattr(config, "data", {"general": {
        "eq_log_dir": str(tmp_path),
        "log_archive_enabled": False,
        "log_archive_size_mb": 1,
    }})
    service = LogArchiveService()
    try:
        assert service.timer.interval() == ARCHIVE_INTERVAL_MS
        report = service.try_archive_logs()
        assert report.moved == ()
        assert report.errors == ()
        assert source.exists()
        assert not (tmp_path / "archive").exists()

        config.data["general"]["log_archive_enabled"] = True
        report = service.try_archive_logs()
        assert len(report.moved) == 1
        assert not source.exists()
    finally:
        service.timer.stop()


def test_config_defaults_and_bounds_log_archive_settings(monkeypatch):
    monkeypatch.setattr(config, "data", {})
    config.verify_settings()
    assert config.data["general"]["log_archive_enabled"] is False
    assert config.data["general"]["log_archive_size_mb"] == 100

    config.data["general"]["log_archive_enabled"] = "yes"
    config.data["general"]["log_archive_size_mb"] = 9999
    config.verify_settings()
    assert config.data["general"]["log_archive_enabled"] is False
    assert config.data["general"]["log_archive_size_mb"] == 2048

