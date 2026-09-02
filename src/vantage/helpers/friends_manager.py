"""EQTool-compatible EverQuest Friends INI management with safe recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.portable import data_dir
from vantage.helpers.scaled_dialog import UniformScaleDialog


FRIEND_SERVERS = (
    ("Green · P1999Green", "P1999Green"),
    ("Blue · P1999Blue", "P1999Blue"),
    ("Red · P1999PVP", "P1999Red"),
    ("Real-Test", "Real-Test"),
)


def friend_server_suffix(server):
    """Match EQTool's one special display-name to filename-suffix mapping."""
    return "P1999PVP" if server == "P1999Red" else str(
        server or "P1999Green")


def everquest_root_from_logs(log_directory):
    try:
        path = Path(log_directory).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_dir():
        return None
    return path.parent if path.name.casefold() == "logs" else path


def normalize_friend_names(value):
    lines = value.splitlines() if isinstance(value, str) else list(value or [])
    unique = {}
    for raw in lines:
        name = str(raw or "").strip()
        if not name or name.casefold() == "*null*":
            continue
        unique.setdefault(name.casefold(), name)
    return sorted(unique.values(), key=str.casefold)[:100]


def friend_ini_files(eq_root, server):
    try:
        root = Path(eq_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    if not root.is_dir():
        return []
    suffix = friend_server_suffix(server)
    try:
        candidates = root.glob(f"*_{suffix}.ini")
        return sorted((
            path for path in candidates
            if path.is_file() and not path.name.casefold().startswith("ui_")
        ), key=lambda path: path.name.casefold())
    except OSError:
        return []


def _decode_ini(content):
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig"), "utf-8-sig"
    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252"), "cp1252"


def read_friends_from_text(text):
    friends = []
    in_friends = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_friends = line.casefold() == "[friends]"
        elif in_friends and line:
            equals = line.find("=")
            if equals > 0:
                value = line[equals + 1:].strip()
                if value and value.casefold() != "*null*":
                    friends.append(value)
    return friends


def read_friends_from_ini(path):
    text, _encoding = _decode_ini(Path(path).read_bytes())
    return read_friends_from_text(text)


def merge_friend_files(files):
    names = []
    errors = []
    for path in files:
        try:
            names.extend(read_friends_from_ini(path))
        except OSError as error:
            errors.append(f"{Path(path).name}: {error}")
    return normalize_friend_names(names), errors


def render_friends_ini(text, friend_names, newline=None):
    """Replace or append the same 100-entry section written by EQTool."""
    newline = newline or ("\r\n" if "\r\n" in text else "\n")
    lines = str(text or "").splitlines()
    section_start = -1
    section_end = len(lines)
    for index, raw in enumerate(lines):
        line = raw.strip()
        if section_start < 0 and line.casefold() == "[friends]":
            section_start = index
            continue
        if (section_start >= 0 and index > section_start and
                line.startswith("[")):
            section_end = index
            break
    names = normalize_friend_names(friend_names)
    entries = [
        f"Friend{index}={names[index]}"
        if index < len(names) else f"Friend{index}=*NULL*"
        for index in range(100)
    ]
    if section_start >= 0:
        lines[section_start + 1:section_end] = entries
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[Friends]", *entries])
    return newline.join(lines) + newline


def _atomic_write(path, content):
    path = Path(path)
    temporary = path.with_name(
        f".{path.name}.vantage-{os.getpid()}-{datetime.now():%H%M%S%f}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass(frozen=True)
class FriendsScan:
    root: str
    server: str
    files: tuple[str, ...]
    friends: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class FriendsWriteReport:
    updated: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    backup_manifest: str = ""


class FriendsBackupStore:
    """Keep exact original bytes outside the EQ and executable directories."""

    def __init__(self, root=None):
        self.root = Path(root) if root else data_dir() / "friends-backups"
        self.latest_path = self.root / "latest.json"

    def create(self, files, server):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        batch = self.root / stamp
        batch.mkdir(parents=True, exist_ok=False)
        entries = []
        for index, source in enumerate(files):
            source = Path(source).resolve(strict=True)
            backup = batch / f"{index:03d}-{source.name}.bak"
            backup.write_bytes(source.read_bytes())
            entries.append({
                "original": str(source),
                "backup": str(backup),
            })
        manifest = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "server": str(server),
            "entries": entries,
        }
        manifest_path = batch / "manifest.json"
        manifest_bytes = json.dumps(
            manifest, indent=2, sort_keys=True).encode("utf-8")
        _atomic_write(manifest_path, manifest_bytes)
        _atomic_write(self.latest_path, manifest_bytes)
        return manifest_path

    def has_backup(self):
        return self.latest_path.is_file()

    def restore_latest(self):
        try:
            manifest = json.loads(self.latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            return FriendsWriteReport(errors=(f"Backup unavailable: {error}",))
        restored = []
        errors = []
        for entry in manifest.get("entries", []):
            original = Path(str(entry.get("original") or ""))
            backup = Path(str(entry.get("backup") or ""))
            try:
                _atomic_write(original, backup.read_bytes())
                restored.append(str(original))
            except OSError as error:
                errors.append(f"{original.name}: {error}")
        return FriendsWriteReport(
            updated=tuple(restored), errors=tuple(errors),
            backup_manifest=str(self.latest_path))


def scan_friends(eq_root, server):
    files = friend_ini_files(eq_root, server)
    friends, errors = merge_friend_files(files)
    return FriendsScan(
        root=str(eq_root or ""), server=str(server),
        files=tuple(str(path) for path in files),
        friends=tuple(friends), errors=tuple(errors))


def push_friends(files, friend_names, server, backup_store=None):
    files = [Path(path) for path in files]
    if not files:
        return FriendsWriteReport(errors=(
            "No character INI files were found for this server.",))
    backup_store = backup_store or FriendsBackupStore()
    try:
        manifest = backup_store.create(files, server)
    except OSError as error:
        return FriendsWriteReport(errors=(
            f"No files changed because the backup failed: {error}",))
    names = normalize_friend_names(friend_names)
    updated = []
    errors = []
    for path in files:
        try:
            original = path.read_bytes()
            text, encoding = _decode_ini(original)
            newline = "\r\n" if b"\r\n" in original else "\n"
            rendered = render_friends_ini(text, names, newline)
            _atomic_write(path, rendered.encode(encoding))
            updated.append(str(path))
        except (OSError, UnicodeError) as error:
            errors.append(f"{path.name}: {error}")
    return FriendsWriteReport(
        updated=tuple(updated), errors=tuple(errors),
        backup_manifest=str(manifest))


class FriendsManagerDialog(UniformScaleDialog):
    """Compact native editor for EQTool's Friends synchronization workflow."""

    def __init__(self, parent=None, backup_store=None):
        super().__init__(
            QSize(650, 460), parent, minimum_size=QSize(195, 138),
            initial_size=QSize(585, 414))
        self.setWindowTitle("Vantage · EverQuest Friends")
        self.backup_store = backup_store or FriendsBackupStore()
        self._scan = FriendsScan("", "P1999Green", (), ())

        root = QVBoxLayout(self.scaled_surface)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QLabel("EVERQUEST FRIENDS")
        title.setObjectName("SettingsLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setToolTip(
            "Synchronize the [Friends] section across character INI files")
        root.addWidget(title)

        self.source = QLabel()
        self.source.setObjectName("CombatDataNotice")
        self.source.setWordWrap(True)
        root.addWidget(self.source)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        server_label = QLabel("Server")
        server_label.setToolTip(
            "Server suffix used to find the matching character INI files")
        controls.addWidget(server_label)
        self.server = QComboBox()
        self.server.setAccessibleName("EverQuest friends server")
        self.server.setToolTip(
            "Choose the server suffix whose character INI files will be synchronized")
        for label, value in FRIEND_SERVERS:
            self.server.addItem(label, value)
        self.server.currentIndexChanged.connect(self.reload)
        controls.addWidget(self.server, 1)
        self.file_count = QLabel("0 files")
        self.file_count.setAccessibleName("Matching character INI file count")
        self.file_count.setToolTip(
            "Only root character INI files are included; UI_ files are excluded")
        controls.addWidget(self.file_count)
        root.addLayout(controls)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("FriendsEditor")
        self.editor.setAccessibleName("EverQuest friends, one per line")
        self.editor.setToolTip(
            "One character per line. Names are deduplicated, sorted, and limited to 100")
        self.editor.setPlaceholderText(
            "One character name per line · maximum 100")
        root.addWidget(self.editor, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("CombatDataNotice")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Friends synchronization status")
        self.status.setToolTip(
            "Shows the read source, write result, or recovery status")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        self.reload_button = QPushButton("Reload")
        self.reload_button.setIcon(game_icon("refresh"))
        self.reload_button.setAccessibleName("Reload friends from EverQuest")
        self.reload_button.setToolTip(
            "Read and merge the selected server's character INI files again")
        self.reload_button.clicked.connect(self.reload)
        buttons.addWidget(self.reload_button)
        self.restore_button = QPushButton("Restore Last Push")
        self.restore_button.setIcon(game_icon("refresh"))
        self.restore_button.setAccessibleName("Restore last Friends push")
        self.restore_button.setToolTip(
            "Restore the exact INI bytes saved before the most recent push")
        self.restore_button.clicked.connect(self.restore_last_push)
        buttons.addWidget(self.restore_button)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.setAccessibleName("Close Friends manager")
        close_button.setToolTip("Close without writing any INI file")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        self.push_button = QPushButton("Push to Files")
        self.push_button.setObjectName("PrimaryAction")
        self.push_button.setIcon(game_icon("export"))
        self.push_button.setAccessibleName("Push friends to character INI files")
        self.push_button.setToolTip(
            "After confirmation, replace [Friends] in every matching character INI")
        self.push_button.clicked.connect(self.push)
        buttons.addWidget(self.push_button)
        root.addLayout(buttons)

        self.reload()

    def _eq_root(self):
        return everquest_root_from_logs(
            config.data.get("general", {}).get("eq_log_dir", ""))

    def reload(self, _index=None):
        eq_root = self._eq_root()
        server = self.server.currentData() or "P1999Green"
        if not eq_root:
            self._scan = FriendsScan("", server, (), ())
            self.editor.clear()
            self.file_count.setText("0 files")
            self.source.setText(
                "NO LINKED EVERQUEST FOLDER · Select EverQuest\\Logs from the tray first.")
            self.source.setToolTip(
                "Friends are stored beside the Logs folder in the EverQuest directory")
            self.status.setText("Nothing was read or changed.")
            self.push_button.setEnabled(False)
        else:
            self._scan = scan_friends(eq_root, server)
            self.editor.setPlainText("\n".join(self._scan.friends))
            count = len(self._scan.files)
            self.file_count.setText(f"{count} file" + ("s" if count != 1 else ""))
            self.source.setText(
                f"SOURCE · {eq_root} · suffix {friend_server_suffix(server)}")
            self.source.setToolTip(
                "Only matching root character INI files are read; UI_ files are ignored")
            detail = (
                f"Loaded {len(self._scan.friends)} unique friend" +
                ("s" if len(self._scan.friends) != 1 else "") +
                f" from {count} character file" + ("s" if count != 1 else ""))
            if self._scan.errors:
                detail += f" · {len(self._scan.errors)} read error(s)"
            self.status.setText(detail)
            self.push_button.setEnabled(bool(count))
        self.restore_button.setEnabled(self.backup_store.has_backup())

    def push(self):
        count = len(self._scan.files)
        if not count:
            QMessageBox.warning(
                self, "Vantage · No Files",
                "No character INI files were found for this server.")
            return
        names = normalize_friend_names(self.editor.toPlainText())
        answer = QMessageBox.question(
            self, "Vantage · Push Friends",
            f"Replace [Friends] in {count} character INI file" +
            ("s" if count != 1 else "") +
            f" with {len(names)} unique name" +
            ("s" if len(names) != 1 else "") +
            "?\n\nVantage will save an exact restorable backup first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("Push cancelled · no files changed.")
            return
        report = push_friends(
            self._scan.files, names, self.server.currentData(),
            self.backup_store)
        self.restore_button.setEnabled(self.backup_store.has_backup())
        self.reload()
        if report.errors:
            self.status.setText(
                f"Updated {len(report.updated)}/{count} files · "
                f"{len(report.errors)} error(s) · backup remains available")
            QMessageBox.warning(
                self, "Vantage · Partial Friends Push",
                "Some files could not be updated. The exact pre-push backup is "
                "available through Restore Last Push.\n\n" +
                "\n".join(report.errors[:8]))
        else:
            self.status.setText(
                f"PUSHED · {len(names)} friends · {count} files · backup ready")

    def restore_last_push(self):
        if not self.backup_store.has_backup():
            self.status.setText("No Friends backup is available yet.")
            return
        answer = QMessageBox.question(
            self, "Vantage · Restore Friends",
            "Restore every character INI from the exact bytes saved before the "
            "most recent Friends push?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("Restore cancelled · no files changed.")
            return
        report = self.backup_store.restore_latest()
        self.reload()
        if report.errors:
            self.status.setText(
                f"Restored {len(report.updated)} files · "
                f"{len(report.errors)} error(s)")
            QMessageBox.warning(
                self, "Vantage · Partial Friends Restore",
                "\n".join(report.errors[:8]))
        else:
            self.status.setText(
                f"RESTORED · {len(report.updated)} character INI files")
