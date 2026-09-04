"""Verified GitHub Releases updater for the single-file Windows build."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import (
    QByteArray, QIODevice, QObject, QSaveFile, QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout)
import semver

from vantage.helpers.icons import game_icon
from vantage.helpers.scaled_dialog import UniformScaleDialog


REPOSITORY = "vantageupdates/vantage"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
ASSET_NAME = "Vantage.exe"
USER_AGENT = "Vantage/1.44.43"


def file_sha256(path):
    """Hash a portable build without loading the whole executable in RAM."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: semver.VersionInfo
    tag: str
    title: str
    notes: str
    published_at: str
    release_url: str
    download_url: str
    size: int
    digest: str


def parse_release_payload(payload):
    """Return a verified-shape Vantage release from GitHub's JSON object."""
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid release response.")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("The latest Vantage release is not a stable release.")
    tag = str(payload.get("tag_name") or "").strip()
    try:
        version = semver.VersionInfo.parse(tag.lstrip("vV"))
    except (TypeError, ValueError) as error:
        raise ValueError("The latest release has an invalid version tag.") from error
    asset = next((
        item for item in payload.get("assets", [])
        if isinstance(item, dict) and
        str(item.get("name") or "").casefold() == ASSET_NAME.casefold()), None)
    if not asset:
        raise ValueError(f"Release {tag} does not contain {ASSET_NAME}.")
    digest = str(asset.get("digest") or "").strip().casefold()
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError(
            f"Release {tag} is missing its GitHub SHA-256 digest.")
    size = int(asset.get("size") or 0)
    if size < 1024 * 1024:
        raise ValueError(f"Release {tag} contains an incomplete executable.")
    download_url = str(asset.get("browser_download_url") or "").strip()
    if not download_url.startswith(
            f"https://github.com/{REPOSITORY}/releases/download/"):
        raise ValueError("The release download does not belong to Vantage.")
    return ReleaseInfo(
        version=version,
        tag=tag,
        title=str(payload.get("name") or tag).strip(),
        notes=str(payload.get("body") or "No release notes provided.").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        release_url=str(payload.get("html_url") or RELEASES_URL).strip(),
        download_url=download_url,
        size=size,
        digest=digest)


class UpdateController(QObject):
    check_finished = Signal(object, str)
    update_available = Signal(object)
    failed = Signal(str)
    download_progress = Signal(int, int)
    download_ready = Signal(object, str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = semver.VersionInfo.parse(str(current_version))
        self.latest_info = None
        self._network = QNetworkAccessManager(self)
        self._reply = None
        self._save_file = None
        self._download_hash = None
        self._downloaded = 0
        self._download_info = None
        self._staged_dir = None
        self._staged_path = None
        self._preserve_staged = False
        QApplication.instance().aboutToQuit.connect(self.cleanup)

    @property
    def busy(self):
        return self._reply is not None

    @property
    def staged_path(self):
        return str(self._staged_path or "")

    def _request(self, url):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(QByteArray(b"Accept"), QByteArray(
            b"application/vnd.github+json"))
        request.setRawHeader(QByteArray(b"X-GitHub-Api-Version"), QByteArray(
            b"2026-03-10"))
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(
            USER_AGENT.encode("ascii")))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        return request

    def check(self):
        if self.busy:
            return False
        self._reply = self._network.get(self._request(LATEST_RELEASE_API))
        self._reply.finished.connect(self._check_finished)
        return True

    def _check_finished(self):
        reply = self._reply
        self._reply = None
        status = int(reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        payload = bytes(reply.readAll())
        error = reply.error()
        error_text = reply.errorString()
        reply.deleteLater()
        if status == 404:
            self.latest_info = None
            self.check_finished.emit(
                None, "No Vantage release has been published yet.")
            return
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(f"GitHub update check failed: {error_text}")
            return
        try:
            info = parse_release_payload(json.loads(payload.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        self.latest_info = info
        if info.version > self.current_version:
            message = f"Vantage {info.version} is ready to download."
            self.check_finished.emit(info, message)
            self.update_available.emit(info)
        else:
            self.check_finished.emit(
                info, f"Vantage {self.current_version} is up to date.")

    def download(self, info):
        if self.busy or not isinstance(info, ReleaseInfo):
            return False
        self.cleanup()
        self._preserve_staged = False
        self._download_info = info
        self._staged_dir = Path(tempfile.mkdtemp(prefix="Vantage-update-"))
        self._staged_path = self._staged_dir / ASSET_NAME
        self._save_file = QSaveFile(str(self._staged_path))
        if not self._save_file.open(QIODevice.OpenModeFlag.WriteOnly):
            self.failed.emit("Vantage could not create the temporary update file.")
            self.cleanup()
            return False
        self._download_hash = hashlib.sha256()
        self._downloaded = 0
        self._reply = self._network.get(self._request(info.download_url))
        self._reply.readyRead.connect(self._download_ready_read)
        self._reply.downloadProgress.connect(self.download_progress.emit)
        self._reply.finished.connect(self._download_finished)
        return True

    def _download_ready_read(self):
        if not self._reply or not self._save_file:
            return
        chunk = bytes(self._reply.readAll())
        if not chunk:
            return
        self._download_hash.update(chunk)
        self._downloaded += len(chunk)
        if self._save_file.write(chunk) != len(chunk):
            self._reply.abort()

    def _download_finished(self):
        reply = self._reply
        self._download_ready_read()
        self._reply = None
        error = reply.error()
        error_text = reply.errorString()
        reply.deleteLater()
        info = self._download_info
        actual_digest = f"sha256:{self._download_hash.hexdigest()}"
        valid = (
            error == QNetworkReply.NetworkError.NoError and info and
            self._downloaded == info.size and actual_digest == info.digest)
        if not valid:
            if self._save_file:
                self._save_file.cancelWriting()
            message = (
                "The downloaded update failed size or SHA-256 verification."
                if error == QNetworkReply.NetworkError.NoError else
                f"Update download failed: {error_text}")
            self.failed.emit(message)
            self.cleanup()
            return
        if not self._save_file.commit():
            self.failed.emit("Windows could not finalize the downloaded update.")
            self.cleanup()
            return
        self._save_file = None
        try:
            with open(self._staged_path, "rb") as executable:
                if executable.read(2) != b"MZ":
                    raise ValueError
        except (OSError, ValueError):
            self.failed.emit("The downloaded file is not a Windows executable.")
            self.cleanup()
            return
        self.download_ready.emit(info, str(self._staged_path))

    def launch_installer(self, info, staged_path):
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Updates can be installed only from Vantage.exe.")
        candidate = Path(staged_path).resolve()
        target = Path(sys.executable).resolve()
        expected = info.digest.removeprefix("sha256:")
        if not candidate.is_file():
            raise RuntimeError("The verified update file is no longer available.")
        if file_sha256(candidate) != expected:
            raise RuntimeError("The staged update changed after verification.")
        handle, probe = tempfile.mkstemp(
            prefix=".vantage-write-test-", dir=str(target.parent))
        os.close(handle)
        Path(probe).unlink()
        app = QApplication.instance()
        checkpoint = getattr(app, 'checkpoint_for_update', None)
        if not callable(checkpoint) or not checkpoint():
            raise RuntimeError(
                'Vantage could not preserve live buffs and timers; update cancelled.')
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200
        subprocess.Popen([
            str(candidate), "--apply-update",
            "--target", str(target),
            "--wait-pid", str(os.getpid()),
            "--digest", info.digest,
            "--from-version", str(self.current_version),
        ], cwd=str(target.parent), close_fds=True, creationflags=flags)
        self._preserve_staged = True

    def cleanup(self):
        if self._preserve_staged:
            return
        if self._reply:
            self._reply.abort()
            self._reply.deleteLater()
            self._reply = None
        if self._save_file:
            self._save_file.cancelWriting()
            self._save_file = None
        if self._staged_dir and self._staged_dir.exists():
            shutil.rmtree(self._staged_dir, ignore_errors=True)
        self._staged_dir = None
        self._staged_path = None


class UpdateDialog(UniformScaleDialog):
    """Compact, keyboard-operable update status and download surface."""

    def __init__(self, controller, parent=None):
        super().__init__(
            QSize(520, 350), parent, minimum_size=QSize(286, 193),
            initial_size=QSize(520, 350), lock_aspect=True)
        self.setWindowTitle("Vantage Update")
        self.setObjectName("UpdateDialog")
        self.controller = controller
        self.info = None
        self.staged_path = ""
        self._one_click_active = False

        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(18, 15, 18, 16)
        layout.setSpacing(8)
        title = QLabel("VANTAGE UPDATE")
        title.setObjectName("UpdateTitle")
        layout.addWidget(title)
        self.version = QLabel()
        self.version.setObjectName("UpdateVersion")
        layout.addWidget(self.version)
        self.status = QLabel("Ready to check GitHub Releases.")
        self.status.setObjectName("UpdateStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName(
            "Update status: Ready to check GitHub Releases.")
        self.status.setAccessibleDescription(
            "Ready to check GitHub Releases.")
        layout.addWidget(self.status)
        self.notes = QPlainTextEdit()
        self.notes.setObjectName("UpdateNotes")
        self.notes.setReadOnly(True)
        self.notes.setPlainText(
            "Release notes will appear here after Vantage checks the official repository.")
        self.notes.setAccessibleName("Vantage release notes")
        self.notes.setToolTip("Changes published with the selected GitHub Release")
        layout.addWidget(self.notes, 1)
        self.progress = QProgressBar()
        self.progress.setObjectName("UpdateProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setAccessibleName("Update download progress")
        self.progress.setToolTip(
            "Download progress; the file is verified before installation")
        layout.addWidget(self.progress)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(5)
        self.check_button = QPushButton("Check again")
        self.check_button.setIcon(game_icon("refresh"))
        self.check_button.setToolTip(
            "Check the official vantageupdates/vantage GitHub Releases page")
        self.check_button.clicked.connect(self.check)
        actions.addWidget(self.check_button)
        actions.addStretch(1)
        self.download_button = QPushButton("Download and install update")
        self.download_button.setObjectName("PrimaryAction")
        self.download_button.setIcon(game_icon("ph-download"))
        self.download_button.setAccessibleName(
            "Download, verify, install, and restart Vantage")
        self.download_button.setToolTip(
            "One click downloads and verifies Vantage.exe, installs it, and "
            "restarts only Vantage; EverQuest and WinEQ remain open")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download_and_install)
        actions.addWidget(self.download_button)
        self.close_button = QPushButton("Later")
        self.close_button.setToolTip(
            "Close this dialog without changing Vantage")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        controller.check_finished.connect(self._checked)
        controller.failed.connect(self._failed)
        controller.download_progress.connect(self._download_progress)
        controller.download_ready.connect(self._download_ready)
        self._show_current()

    def _show_current(self):
        self.version.setText(
            f"INSTALLED  {self.controller.current_version}   ·   "
            f"SOURCE  {REPOSITORY}")

    def open_and_check(self):
        self.show()
        self.raise_()
        self.activateWindow()
        if self.controller.latest_info:
            self._checked(
                self.controller.latest_info,
                f"Latest published version: {self.controller.latest_info.version}")
        self.check()

    def check(self):
        self._set_status("Checking the official GitHub Release…", announce=True)
        self.check_button.setEnabled(False)
        if not self.controller.check():
            self._set_status(
                "Another update operation is already running.", announce=True)

    def _checked(self, info, message):
        self.check_button.setEnabled(True)
        self._set_status(message, announce=True)
        self.info = info
        if info:
            self.version.setText(
                f"INSTALLED  {self.controller.current_version}   ·   "
                f"LATEST  {info.version}")
            self.notes.setPlainText(info.notes or "No release notes provided.")
            available = info.version > self.controller.current_version
            self.download_button.setEnabled(available)
            self.download_button.setText("Download and install update")
        else:
            self.download_button.setEnabled(False)
            self.notes.setPlainText(
                "The repository is connected, but it does not have a published Release yet.")

    def _failed(self, message):
        self._one_click_active = False
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(bool(
            self.info and self.info.version > self.controller.current_version))
        self.download_button.setText("Try again")
        self.close_button.setEnabled(True)
        self._set_status(message, announce=True)
        if self.isVisible():
            QTimer.singleShot(0, lambda: self.download_button.setFocus(
                Qt.FocusReason.OtherFocusReason))

    def download(self):
        """Backward-compatible alias for the one-click update action."""
        self.download_and_install()

    def download_and_install(self):
        if not self.info:
            return
        if self.controller.busy:
            self._set_status(
                "Another update operation is already running.", announce=True)
            return
        self._one_click_active = True
        self._set_status(
            "Downloading and verifying Vantage.exe…", announce=True)
        self.progress.setValue(0)
        self.download_button.setEnabled(False)
        self.download_button.setText("Downloading…")
        self.check_button.setEnabled(False)
        self.close_button.setEnabled(False)
        if not self.controller.download(self.info):
            self._failed("The update could not start.")

    def _download_progress(self, received, total):
        if not self._one_click_active:
            return
        total = total if total > 0 else (self.info.size if self.info else 0)
        self.progress.setValue(
            max(0, min(100, round(received / total * 100))) if total else 0)

    def _download_ready(self, info, path):
        if not self._one_click_active:
            return
        self.info = info
        self.staged_path = path
        self.progress.setValue(100)
        self._set_status(
            "Verified · installing update and restarting Vantage…",
            announce=True)
        self.download_button.setText("Installing…")
        QTimer.singleShot(0, self.install)

    def install(self):
        if not self.info or not self.staged_path:
            return
        self.download_button.setEnabled(False)
        self._set_status(
            "Closing Vantage and applying the verified update…", announce=True)
        try:
            self.controller.launch_installer(self.info, self.staged_path)
        except (OSError, RuntimeError, ValueError) as error:
            self._failed(f"Update could not start: {error}")
            return
        self._one_click_active = False
        app = QApplication.instance()
        if getattr(app, "_system_tray", None):
            app._system_tray.setVisible(False)
        app.quit()

    def _set_status(self, message, announce=False):
        """Keep visible and assistive update status in one synchronized path."""
        message = " ".join(str(message or "").split())
        self.status.setText(message)
        self.status.setAccessibleName(f"Update status: {message}")
        self.status.setAccessibleDescription(message)
        if announce and self.isVisible():
            try:
                QAccessible.updateAccessibility(
                    QAccessibleAnnouncementEvent(self.status, message))
            except (AttributeError, RuntimeError, TypeError):
                pass
