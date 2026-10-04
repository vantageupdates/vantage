"""Automatic and manual EverQuest log-folder setup."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import threading

from PySide6.QtCore import (
    QDateTime, QEvent, QLocale, QObject, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout,
)

from vantage.helpers.scaled_dialog import UniformScaleDialog


_SKIP_DIRECTORIES = {
    ".cache", ".git", "cache", "caches", "code cache", "codex",
    "crashpad", "discord", "githubdesktop", "google", "gpucache",
    "microsoft", "mozilla", "node_modules", "npm-cache", "openai",
    "packages", "pip", "python", "pythonsoftwarefoundation", "temp",
    "temporary internet files", "uv",
}
_MAX_DEPTH = 6
_MAX_DIRECTORIES_PER_ROOT = 5_000


@dataclass(frozen=True)
class LogFolderCandidate:
    path: str
    file_count: int
    newest_mtime: float
    newest_log: str


def _candidate(directory):
    try:
        path = Path(directory).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_dir():
        return None
    newest_mtime = 0.0
    newest_log = ""
    file_count = 0
    try:
        entries = path.iterdir()
        for entry in entries:
            if (not entry.is_file() or
                    not entry.name.casefold().startswith("eqlog_") or
                    entry.suffix.casefold() != ".txt"):
                continue
            file_count += 1
            try:
                modified = entry.stat().st_mtime
            except OSError:
                modified = 0.0
            if modified >= newest_mtime:
                newest_mtime = modified
                newest_log = entry.name
    except OSError:
        return None
    if not file_count:
        return None
    return LogFolderCandidate(
        str(path), file_count, newest_mtime, newest_log)


def resolve_log_folder(selection):
    """Accept either an EQ root or its Logs directory without writing files."""
    direct = _candidate(selection)
    if direct is not None:
        return direct
    try:
        nested = Path(selection).expanduser() / "Logs"
    except (TypeError, ValueError):
        return None
    return _candidate(nested)


def default_search_roots(environment=None):
    environment = os.environ if environment is None else environment
    roots = []
    seen = set()
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        value = str(environment.get(key) or "").strip()
        if not value:
            continue
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        folded = str(path).casefold()
        if path.is_dir() and folded not in seen:
            seen.add(folded)
            roots.append(path)
    return tuple(roots)


def _walk_log_directories(root):
    queue = deque(((Path(root), 0),))
    visited = 0
    while queue and visited < _MAX_DIRECTORIES_PER_ROOT:
        directory, depth = queue.popleft()
        visited += 1
        if directory.name.casefold() == "logs":
            yield directory
            # Active logs are direct children. Archive traversal is handled by
            # Log Searcher after the active Logs directory is connected.
            continue
        if depth >= _MAX_DEPTH:
            continue
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if (not entry.is_dir(follow_symlinks=False) or
                            entry.name.casefold() in _SKIP_DIRECTORIES):
                        continue
                except OSError:
                    continue
                queue.append((Path(entry.path), depth + 1))


def discover_log_folders(*, direct_paths=(), search_roots=None,
                         environment=None, deep_search=True):
    """Return readable EQ Logs folders, freshest first, from bounded roots."""
    candidates = {}

    def add(selection):
        candidate = resolve_log_folder(selection)
        if candidate is None:
            return
        key = candidate.path.casefold()
        previous = candidates.get(key)
        if previous is None or candidate.newest_mtime > previous.newest_mtime:
            candidates[key] = candidate

    for path in direct_paths:
        if path:
            add(path)
    roots = default_search_roots(environment) \
        if search_roots is None else tuple(search_roots)
    # Resolve the conventional locations before the bounded fallback walk.
    # This makes the normal Sony, Steam and VirtualStore installs appear
    # quickly even on AppData trees containing thousands of unrelated folders.
    common_relatives = (
        Path("Sony") / "EverQuest",
        Path("EverQuest"),
        Path("Project1999"),
        Path("P99"),
        Path("Steam") / "steamapps" / "common" / "EverQuest",
        Path("Daybreak Game Company") / "Installed Games" / "EverQuest",
        Path("VirtualStore") / "Program Files (x86)" / "Sony" / "EverQuest",
        Path("VirtualStore") / "Program Files" / "Sony" / "EverQuest",
    )
    for root in roots:
        add(root)
        for relative in common_relatives:
            add(Path(root) / relative)
        if deep_search:
            for directory in _walk_log_directories(root):
                add(directory)
    return tuple(sorted(
        candidates.values(),
        key=lambda item: (-item.newest_mtime, item.path.casefold())))


class _DiscoverySignals(QObject):
    finished = Signal(object, str)


class LogFolderDialog(UniformScaleDialog):
    """Choose the freshest detected EQ Logs folder or browse manually."""

    def __init__(self, current_path="", eq_root="", parent=None, *,
                 auto_start=True):
        super().__init__(
            QSize(680, 285), parent, minimum_size=QSize(544, 228),
            initial_size=QSize(680, 285), lock_aspect=True)
        self.setWindowTitle("Vantage · Connect EverQuest Logs")
        self.setObjectName("LogFolderSetupDialog")
        self.scaled_surface.setObjectName("LogFolderSetupSurface")
        self.selected_path = ""
        self._current_path = str(current_path or "")
        self._eq_root = str(eq_root or "")
        self._scan_deep = False
        self._signals = _DiscoverySignals(self)
        self._signals.finished.connect(self._scan_finished)

        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel("Connect EverQuest Logs")
        title.setObjectName("SettingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Vantage searches Program Files and AppData automatically. The "
            "folder with the newest EQ log is selected first; manual setup "
            "always remains available.")
        intro.setWordWrap(True)
        intro.setObjectName("VantageUIIntro")
        layout.addWidget(intro)

        self.detected_label = QLabel("&Detected log folder")
        self.detected = QComboBox()
        self.detected_label.setBuddy(self.detected)
        self.detected.setAccessibleName("Automatically detected EverQuest Logs folders")
        self.detected.setToolTip(
            "Detected folders are ordered by their most recently updated EQ log")
        self.detected.currentIndexChanged.connect(self._selection_changed)
        layout.addWidget(self.detected_label)
        layout.addWidget(self.detected)

        self.status = QLabel("Searching this PC for EverQuest logs…")
        self.status.setObjectName("VantageUIStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("EverQuest log folder detection status")
        layout.addWidget(self.status)
        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.scan_button = QPushButton("Search more locations")
        self.scan_button.setToolTip(
            "Run a wider search below Program Files and AppData")
        self.scan_button.clicked.connect(
            lambda _checked=False: self.start_scan(deep_search=True))
        actions.addWidget(self.scan_button)
        actions.addStretch(1)
        self.manual_button = QPushButton("Choose manually…")
        self.manual_button.setToolTip(
            "Choose an EverQuest folder or its Logs folder yourself")
        self.manual_button.clicked.connect(self._choose_manual)
        actions.addWidget(self.manual_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip(
            "Close without changing the linked log folder")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)
        self.use_button = QPushButton("Use detected logs")
        self.use_button.setObjectName("PrimaryAction")
        self.use_button.setDefault(True)
        self.use_button.setAutoDefault(True)
        self.use_button.setEnabled(False)
        self.use_button.setToolTip(
            "Connect the selected folder and listen for its newest log events")
        self.use_button.clicked.connect(self._accept_detected)
        actions.addWidget(self.use_button)
        layout.addLayout(actions)
        for control in (
                self.detected, self.scan_button, self.manual_button,
                self.cancel_button, self.use_button):
            control.installEventFilter(self)
        if auto_start:
            QTimer.singleShot(
                0, lambda: self.start_scan(deep_search=False))

    def showEvent(self, event):
        super().showEvent(event)
        # UniformScaleDialog uses a graphics proxy, so choose a meaningful
        # child explicitly instead of leaving focus on the unnamed view.
        QTimer.singleShot(0, self._focus_initial_control)

    def _focus_initial_control(self):
        target = self.detected if self.detected.count() else self.manual_button
        target.setFocus()

    def _set_status(self, message, *, announce=True):
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        if announce:
            event = QAccessibleAnnouncementEvent(self.status, message)
            event.setPoliteness(
                QAccessible.AnnouncementPoliteness.Polite)
            QAccessible.updateAccessibility(event)

    def _focusable_controls(self):
        controls = (
            self.detected, self.scan_button, self.manual_button,
            self.cancel_button, self.use_button)
        return [
            control for control in controls
            if control.isEnabled() and control.isVisibleTo(self.scaled_surface)
            and (control is not self.detected or control.count())]

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if (watched is self.detected and
                    key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and
                    not self.detected.view().isVisible() and
                    self.use_button.isEnabled()):
                self._accept_detected()
                return True
            controls = self._focusable_controls()
            if controls:
                backwards = (
                    key == Qt.Key.Key_Backtab or
                    (key == Qt.Key.Key_Tab and
                     bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)))
                if backwards and watched is controls[0]:
                    controls[-1].setFocus()
                    return True
                if key == Qt.Key.Key_Tab and not backwards \
                        and watched is controls[-1]:
                    controls[0].setFocus()
                    return True
        return super().eventFilter(watched, event)

    def start_scan(self, *, deep_search=True):
        if not self.scan_button.isEnabled():
            return False
        self._scan_deep = bool(deep_search)
        self.scan_button.setEnabled(False)
        self.use_button.setEnabled(False)
        self.detected.setEnabled(False)
        self._set_status(
            "Searching more locations in Program Files and AppData…"
            if self._scan_deep else
            "Checking common EverQuest locations…")
        self.manual_button.setFocus()
        direct = (self._current_path, self._eq_root)

        def worker():
            try:
                candidates = discover_log_folders(
                    direct_paths=direct, deep_search=self._scan_deep)
            except (OSError, RuntimeError, ValueError) as error:
                self._signals.finished.emit((), str(error))
            else:
                self._signals.finished.emit(candidates, "")

        threading.Thread(
            target=worker, name="Vantage-EQ-Log-Discovery", daemon=True).start()
        return True

    def _scan_finished(self, candidates, error):
        self.scan_button.setEnabled(True)
        self.detected.setEnabled(True)
        self.detected.clear()
        for candidate in candidates:
            self.detected.addItem(candidate.path, candidate)
        self.use_button.setEnabled(bool(candidates))
        if not candidates and not error and not self._scan_deep:
            message = "No common install found · searching more locations…"
            self._set_status(message)
            QTimer.singleShot(
                0, lambda: self.start_scan(deep_search=True))
            return
        if error:
            message = f"Automatic search could not finish · {error}"
        elif not candidates:
            message = (
                "No EQ logs were detected. Choose the folder manually after "
                "typing /log on in EverQuest.")
        else:
            message = f"Found {len(candidates)} log folder"
            if len(candidates) != 1:
                message += "s"
            message += " · newest activity is selected"
        self._set_status(message)
        self._selection_changed()
        self._focus_initial_control()

    def _selection_changed(self):
        candidate = self.detected.currentData()
        if not isinstance(candidate, LogFolderCandidate):
            return
        when = QLocale.system().toString(
            QDateTime.fromSecsSinceEpoch(int(candidate.newest_mtime)),
            QLocale.FormatType.ShortFormat)
        self.detected.setToolTip(
            f"{candidate.file_count} EQ logs · newest {when} · "
            f"{candidate.newest_log}")

    def _accept_detected(self):
        candidate = self.detected.currentData()
        if isinstance(candidate, LogFolderCandidate):
            self.selected_path = candidate.path
            self.accept()

    def _choose_manual(self):
        starting = self._current_path or self._eq_root or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Choose EverQuest or Logs Folder", starting)
        if not selected:
            return
        candidate = resolve_log_folder(selected)
        if candidate is None:
            QMessageBox.warning(
                self, "No EverQuest logs found",
                "That folder does not contain eqlog files. Type /log on in "
                "EverQuest, then choose the EverQuest folder or its Logs folder.")
            self.manual_button.setFocus()
            return
        self.selected_path = candidate.path
        self.accept()
