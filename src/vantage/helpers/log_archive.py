"""Opt-in EQTool-style rotation for oversized EverQuest text logs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from vantage.helpers import config


ARCHIVE_INTERVAL_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class LogArchiveReport:
    moved: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    archive_dir: str = ""


def archive_oversized_logs(log_directory, size_mb=100, now=None):
    """Move oversized eqlog files into a timestamped sibling archive."""
    try:
        root = Path(log_directory).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return LogArchiveReport(errors=("The linked log folder is unavailable.",))
    if not root.is_dir():
        return LogArchiveReport(errors=("The linked log folder is unavailable.",))
    try:
        threshold = max(1, int(size_mb)) * 1024 * 1024
    except (TypeError, ValueError):
        threshold = 100 * 1024 * 1024
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    archive_dir = root / "archive"
    moved = []
    errors = []
    try:
        candidates = sorted(root.glob("eqlog_*_*.txt"), key=lambda path: path.name.casefold())
    except OSError as error:
        return LogArchiveReport(errors=(f"Could not list EQ logs: {error}",))
    for source in candidates:
        try:
            if not source.is_file() or source.stat().st_size < threshold:
                continue
            archive_dir.mkdir(parents=False, exist_ok=True)
            destination = archive_dir / f"{source.stem}_{stamp}{source.suffix}"
            suffix = 2
            while destination.exists():
                destination = archive_dir / (
                    f"{source.stem}_{stamp}-{suffix}{source.suffix}")
                suffix += 1
            source.replace(destination)
            moved.append(str(destination))
        except OSError as error:
            errors.append(f"{source.name}: {error}")
    return LogArchiveReport(
        moved=tuple(moved), errors=tuple(errors),
        archive_dir=str(archive_dir) if moved or archive_dir.exists() else "")


class LogArchiveService(QObject):
    """Run the opt-in archive check on EQTool's one-hour cadence."""

    completed = Signal(object)

    def __init__(self, parent=None, interval_ms=ARCHIVE_INTERVAL_MS):
        super().__init__(parent)
        self.last_report = LogArchiveReport()
        self.timer = QTimer(self)
        self.timer.setInterval(max(1000, int(interval_ms)))
        self.timer.timeout.connect(self.try_archive_logs)
        self.timer.start()

    def try_archive_logs(self):
        if not config.data.get("general", {}).get(
                "log_archive_enabled", False):
            self.last_report = LogArchiveReport()
            return self.last_report
        general = config.data.get("general", {})
        self.last_report = archive_oversized_logs(
            general.get("eq_log_dir", ""),
            general.get("log_archive_size_mb", 100))
        if self.last_report.moved or self.last_report.errors:
            self.completed.emit(self.last_report)
        return self.last_report
