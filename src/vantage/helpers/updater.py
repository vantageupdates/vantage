"""Verified GitHub Releases updater for the single-file Windows build."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import (
    QByteArray, QEvent, QIODevice, QObject, QSaveFile, QSize, Qt, QTimer,
    QUrl, Signal)
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)
import semver

from vantage.helpers.icons import game_icon
from vantage.helpers.scaled_dialog import UniformScaleDialog


REPOSITORY = "vantageupdates/vantage"
RELEASE_HISTORY_API = (
    f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=40&page=1")
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
ASSET_NAME = "Vantage.exe"
USER_AGENT = "Vantage/1.44.67"
_COMPANION_TAG = re.compile(
    r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


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
    if not _COMPANION_TAG.fullmatch(tag):
        raise ValueError("The Companion release tag must be exact v<semver>.")
    try:
        version = semver.VersionInfo.parse(tag[1:])
    except (TypeError, ValueError) as error:
        raise ValueError("The latest release has an invalid version tag.") from error
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("The Companion release assets are invalid.")
    matches = [
        item for item in assets
        if isinstance(item, dict) and item.get("name") == ASSET_NAME]
    if len(matches) != 1:
        raise ValueError(
            f"Release {tag} must contain exactly one {ASSET_NAME}.")
    asset = matches[0]
    digest = str(asset.get("digest") or "").strip().casefold()
    if (not digest.startswith("sha256:") or
            not re.fullmatch(r"[a-f0-9]{64}", digest[7:])):
        raise ValueError(
            f"Release {tag} is missing its GitHub SHA-256 digest.")
    size = int(asset.get("size") or 0)
    if size < 1024 * 1024:
        raise ValueError(f"Release {tag} contains an incomplete executable.")
    download_url = str(asset.get("browser_download_url") or "").strip()
    expected_url = (
        f"https://github.com/{REPOSITORY}/releases/download/"
        f"{tag}/{ASSET_NAME}")
    if download_url != expected_url:
        raise ValueError("The release download does not match its exact tag.")
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


def _validated_release_history(payload):
    """Validate and return one decoded, bounded GitHub release-history list."""
    if not isinstance(payload, list) or len(payload) > 40:
        raise ValueError("GitHub returned invalid bounded release history.")
    for release in payload:
        if not isinstance(release, dict):
            raise ValueError("GitHub returned an invalid release entry.")
    return payload


def _select_companion_release(payload):
    candidates = []
    for release in payload:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "").strip()
        if not _COMPANION_TAG.fullmatch(tag):
            continue
        assets = release.get("assets", [])
        has_companion = any(
            isinstance(asset, dict) and
            asset.get("name") == ASSET_NAME
            for asset in (assets if isinstance(assets, list) else []))
        if has_companion:
            candidates.append((semver.VersionInfo.parse(tag[1:]), release))
    if not candidates:
        return None
    # Parse only the newest matching release. If it advertises Vantage.exe but
    # its metadata is unsafe, failing is safer than silently downgrading.
    return parse_release_payload(max(candidates, key=lambda item: item[0])[1])


def select_companion_release(payload):
    """Choose the newest stable exact Companion release from bounded history."""
    return _select_companion_release(_validated_release_history(payload))


class UpdateController(QObject):
    check_started = Signal()
    check_finished = Signal(object, str)
    check_failed = Signal(str)
    release_history_ready = Signal(object)
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
        request.setRawHeader(QByteArray(b"Cache-Control"), QByteArray(
            b"no-cache"))
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        request.setAttribute(
            QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        return request

    def check(self):
        if self.busy:
            return False
        self.check_started.emit()
        self._reply = self._network.get(self._request(RELEASE_HISTORY_API))
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
            message = f"GitHub update check failed: {error_text}"
            self.check_failed.emit(message)
            self.failed.emit(message)
            return
        try:
            history = _validated_release_history(
                json.loads(payload.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            message = str(exc)
            self.check_failed.emit(message)
            self.failed.emit(message)
            return
        # Every update product consumes this exact decoded response. VantageUI
        # validates its own candidate independently, so malformed UI metadata
        # cannot prevent Companion selection from the same bounded history.
        self.release_history_ready.emit(history)
        try:
            info = _select_companion_release(history)
        except (TypeError, ValueError) as exc:
            message = str(exc)
            self.check_failed.emit(message)
            self.failed.emit(message)
            return
        self.latest_info = info
        if info is None:
            self.check_finished.emit(
                None, "No verified Companion release was found in recent history.")
            return
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

    def launch_installer(self, info, staged_path, *, open_vantage_ui=False):
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
                'Vantage could not preserve live buffs and timers. The update '
                'was cancelled and Vantage remains open.')
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200
        command = [
            str(candidate), "--apply-update",
            "--target", str(target),
            "--wait-pid", str(os.getpid()),
            "--digest", info.digest,
            "--from-version", str(self.current_version),
        ]
        if open_vantage_ui:
            command.append("--open-vantage-ui")
        subprocess.Popen(
            command, cwd=str(target.parent), close_fds=True,
            creationflags=flags)
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

    def __init__(self, controller, parent=None, *, vantage_ui=None,
                 open_vantage_ui=None, update_vantage_ui=None,
                 restore_focus=None):
        super().__init__(
            QSize(560, 430), parent, minimum_size=QSize(430, 340),
            initial_size=QSize(560, 430), lock_aspect=False)
        self.setWindowTitle("Updates")
        self.setObjectName("UpdateDialog")
        self.controller = controller
        self.vantage_ui = vantage_ui
        self._open_vantage_ui = open_vantage_ui
        self._update_vantage_ui = update_vantage_ui
        self._restore_focus = restore_focus
        self._suppress_restore_focus = False
        self._ui_state = {}
        self.info = None
        self.staged_path = ""
        self._one_click_active = False
        self._manual_check_pending = False
        self._last_progress_announcement = 0

        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(18, 15, 18, 16)
        layout.setSpacing(8)
        title = QLabel("UPDATES")
        title.setObjectName("UpdateTitle")
        layout.addWidget(title)
        products = QFrame()
        products.setObjectName("UpdateProducts")
        products.setAccessibleName("Independent update products")
        products.setAccessibleDescription(
            "Vantage Companion and VantageUI have separate installed and available versions")
        product_layout = QGridLayout(products)
        product_layout.setContentsMargins(9, 7, 9, 7)
        product_layout.setHorizontalSpacing(12)
        product_layout.setVerticalSpacing(3)
        companion_name = QLabel("Vantage Companion")
        companion_name.setObjectName("UpdateProductName")
        companion_name.setAccessibleName("Vantage Companion update information")
        companion_name.setToolTip("Vantage Companion application updates")
        product_layout.addWidget(companion_name, 0, 0)
        self.version = QLabel()
        self.version.setObjectName("UpdateVersion")
        self.version.setAccessibleName("Vantage Companion versions")
        self.version.setToolTip("Installed and available Companion versions")
        product_layout.addWidget(self.version, 0, 1)
        self.download_button = QPushButton("Vantage current")
        self.download_button.setObjectName("PrimaryAction")
        self.download_button.setIcon(game_icon("ph-download"))
        self.download_button.setAccessibleName(
            "Vantage Companion is current")
        self.download_button.setToolTip(
            "Vantage Companion is already on the latest verified release")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download_and_install)
        product_layout.addWidget(self.download_button, 0, 2)
        ui_name = QLabel("VantageUI")
        ui_name.setObjectName("UpdateProductName")
        ui_name.setAccessibleName("VantageUI update information")
        ui_name.setToolTip("Independent optional EverQuest skin updates")
        product_layout.addWidget(ui_name, 1, 0)
        self.ui_version = QLabel("Installed: checking · Available: checking")
        self.ui_version.setObjectName("UpdateVersion")
        self.ui_version.setAccessibleName("VantageUI versions")
        self.ui_version.setAccessibleDescription(
            "Installed and independently available VantageUI versions")
        self.ui_version.setToolTip(
            "Installed and available versions of the optional VantageUI skin")
        product_layout.addWidget(self.ui_version, 1, 1)
        self.open_ui_button = QPushButton("Manage VantageUI")
        self.open_ui_button.setIcon(game_icon("ph-layout"))
        self.open_ui_button.setAccessibleName("Manage VantageUI")
        self.open_ui_button.setAccessibleDescription(
            "Opens the independent VantageUI installation and update area")
        self.open_ui_button.setToolTip(
            "Open the VantageUI installation, update, and restore controls")
        self.open_ui_button.setEnabled(callable(open_vantage_ui))
        self.open_ui_button.clicked.connect(self._open_ui_panel)
        product_layout.addWidget(self.open_ui_button, 1, 2)
        product_layout.setColumnStretch(1, 1)
        layout.addWidget(products)
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

        self.open_ui_after_restart = QCheckBox(
            "After Vantage restarts, open VantageUI")
        self.open_ui_after_restart.setChecked(False)
        self.open_ui_after_restart.setAccessibleName(
            "After Companion restarts, open VantageUI")
        self.open_ui_after_restart.setAccessibleDescription(
            "One-time option. Opens the VantageUI installer after a successful "
            "Companion update; it does not install the skin.")
        self.open_ui_after_restart.setToolTip(
            "One-time option: open the separate VantageUI installer after a "
            "successful Companion restart; this never installs the skin automatically")
        self.open_ui_after_restart.hide()
        layout.addWidget(self.open_ui_after_restart)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(5)
        self.check_button = QPushButton("Check again")
        self.check_button.setIcon(game_icon("refresh"))
        self.check_button.setAccessibleName(
            "Check for Vantage Companion and VantageUI updates")
        self.check_button.setAccessibleDescription(
            "Uses one bounded GitHub release-history request for both update products")
        self.check_button.setToolTip(
            "Check the official vantageupdates/vantage GitHub Releases page")
        self.check_button.clicked.connect(self.check)
        actions.addWidget(self.check_button)
        actions.addStretch(1)
        self.close_button = QPushButton("Later")
        self.close_button.setAccessibleName("Close Updates and decide later")
        self.close_button.setToolTip(
            "Close this dialog without changing Vantage")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        controller.check_finished.connect(self._checked)
        controller.failed.connect(self._failed)
        controller.download_progress.connect(self._download_progress)
        controller.download_ready.connect(self._download_ready)
        if vantage_ui is not None:
            signal = getattr(vantage_ui, "update_state_changed", None)
            if signal is not None:
                signal.connect(self._ui_state_changed)
        QWidget.setTabOrder(self.download_button, self.open_ui_button)
        QWidget.setTabOrder(self.open_ui_button, self.notes)
        QWidget.setTabOrder(self.notes, self.open_ui_after_restart)
        QWidget.setTabOrder(self.open_ui_after_restart, self.check_button)
        QWidget.setTabOrder(self.check_button, self.close_button)
        self._update_tab_controls = (
            self.download_button, self.open_ui_button, self.notes,
            self.open_ui_after_restart, self.check_button, self.close_button)
        for control in self._update_tab_controls:
            control.installEventFilter(self)
        self._show_current()
        self._ui_state_changed(self._ui_snapshot())

    def _show_current(self):
        self.version.setText(
            f"{self.controller.current_version} installed · checking")

    def _ui_snapshot(self):
        getter = getattr(self.vantage_ui, "update_snapshot", None)
        return getter() if callable(getter) else {}

    def _ui_state_changed(self, state):
        state = state if isinstance(state, dict) else {}
        self._ui_state = dict(state)
        installed = str(state.get("installed") or "Not installed")
        available = str(state.get("available") or (
            "checking" if state.get("busy") else "Not checked"))
        text = f"{installed} installed · {available} available"
        self.ui_version.setText(text)
        self.ui_version.setAccessibleDescription(
            f"VantageUI. {text}. Updates are managed independently.")
        if not installed or installed == "Not installed":
            action = "install"
        elif bool(state.get("update_available")):
            action = "update"
        else:
            action = "manage"
        self._ui_action_kind = action
        action_text = {
            "install": "Install VantageUI",
            "update": "Update VantageUI",
            "manage": "Manage VantageUI",
        }[action]
        self.open_ui_button.setText(action_text)
        self.open_ui_button.setAccessibleName(action_text)
        self.open_ui_button.setEnabled(
            not bool(state.get("busy")) and
            callable(self._update_vantage_ui if action != "manage" else
                     self._open_vantage_ui))
        self._refresh_joint_option()

    def _open_ui_panel(self):
        if (getattr(self, "_ui_action_kind", "manage") in
                {"install", "update"} and
                callable(self._update_vantage_ui)):
            self._update_vantage_ui()
        elif callable(self._open_vantage_ui):
            self._open_vantage_ui()

    def _refresh_joint_option(self):
        companion_ready = bool(
            self.info and
            self.info.version > self.controller.current_version)
        ui_ready = bool(self._ui_state.get("update_available"))
        self.open_ui_after_restart.setVisible(companion_ready and ui_ready)
        if not (companion_ready and ui_ready):
            self.open_ui_after_restart.setChecked(False)

    def _combined_status(self):
        companion_ready = bool(
            self.info and
            self.info.version > self.controller.current_version)
        companion = (
            f"Vantage {self.info.version} ready"
            if companion_ready else "Vantage is current")
        state = self._ui_state
        installed = str(state.get("installed") or "").strip()
        available = str(state.get("available") or "").strip()
        if state.get("check_error"):
            ui = "VantageUI check unavailable"
        elif installed and available and state.get("update_available"):
            ui = f"VantageUI {available} ready"
        elif not installed and available:
            ui = f"VantageUI {available} available to install"
        elif installed and available:
            ui = "VantageUI is current"
        else:
            ui = "VantageUI was not checked"
        return f"Check complete. {companion}. {ui}."

    def open_and_check(self):
        if not self.isVisible():
            self.open_ui_after_restart.setChecked(False)
        self.show()
        self.raise_()
        self.activateWindow()
        if self.controller.latest_info:
            self._checked(
                self.controller.latest_info,
                f"Latest published version: {self.controller.latest_info.version}")
        self._ui_state_changed(self._ui_snapshot())
        self.check()

    def check(self):
        self._set_status("Checking the official GitHub Release…", announce=True)
        self.check_button.setEnabled(False)
        self._manual_check_pending = True
        if not self.controller.check():
            self._manual_check_pending = False
            self._set_status(
                "Another update operation is already running.", announce=True)

    def _checked(self, info, message):
        manual_check = self._manual_check_pending
        self._manual_check_pending = False
        self.check_button.setEnabled(True)
        self.info = info
        if info:
            self.version.setText(
                f"{self.controller.current_version} installed · "
                f"{info.version} available")
            self.notes.setPlainText(info.notes or "No release notes provided.")
            available = info.version > self.controller.current_version
            self.download_button.setEnabled(available)
            self.download_button.setText(
                "Update Vantage" if available else "Vantage current")
            self.download_button.setAccessibleName(
                "Download, verify, install, and restart Vantage"
                if available else "Vantage Companion is current")
            self.download_button.setToolTip(
                "One click downloads and verifies Vantage.exe, installs it, "
                "and restarts only Vantage; EverQuest and WinEQ remain open"
                if available else
                "Vantage Companion is already on the latest verified release")
        else:
            self.download_button.setEnabled(False)
            self.download_button.setText("Vantage unavailable")
            self.notes.setPlainText(
                "The repository is connected, but it does not have a published Release yet.")
        self._refresh_joint_option()
        self._set_status(
            self._combined_status() if manual_check else message,
            announce=manual_check)

    def _failed(self, message):
        was_manual_check = self._manual_check_pending
        was_download = self._one_click_active
        interactive = was_manual_check or was_download
        self._manual_check_pending = False
        self._one_click_active = False
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(bool(
            self.info and self.info.version > self.controller.current_version))
        if was_download:
            self.download_button.setText("Try again")
        self.close_button.setEnabled(True)
        self._set_status(message, announce=interactive)
        if interactive and self.isVisible():
            focus_target = (
                self.check_button if was_manual_check else
                self.download_button)
            QTimer.singleShot(0, lambda: self._focus_control(focus_target))

    def _focus_control(self, control):
        """Move focus through the scaled graphics proxy to a real control."""
        if control is None or not control.isEnabled():
            return
        self.scaled_surface.setFocusProxy(control)
        self._dialog_view.setFocus(Qt.FocusReason.OtherFocusReason)
        self._dialog_proxy.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._dialog_scene.setActivePanel(self._dialog_proxy)
        self._dialog_scene.setFocusItem(
            self._dialog_proxy, Qt.FocusReason.OtherFocusReason)
        self._dialog_proxy.setFocus(Qt.FocusReason.OtherFocusReason)
        self.scaled_surface.setFocus(Qt.FocusReason.OtherFocusReason)
        control.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event):
        if (watched in getattr(self, "_update_tab_controls", ()) and
                event.type() == QEvent.Type.KeyPress and
                event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)):
            controls = [
                control for control in self._update_tab_controls
                if control.isEnabled() and control.isVisibleTo(
                    self.scaled_surface)]
            if watched in controls and controls:
                backwards = (
                    event.key() == Qt.Key.Key_Backtab or
                    bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                offset = -1 if backwards else 1
                next_index = (controls.index(watched) + offset) % len(controls)
                self._focus_control(controls[next_index])
                return True
        return super().eventFilter(watched, event)

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
        self._last_progress_announcement = 0
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
        value = max(0, min(100, round(received / total * 100))) if total else 0
        self.progress.setValue(value)
        milestone = min(75, (value // 25) * 25)
        if milestone >= 25 and milestone > self._last_progress_announcement:
            self._last_progress_announcement = milestone
            self._set_status(
                f"Downloading and verifying Vantage.exe · {milestone}%",
                announce=True)

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
            "Closing Vantage and applying the verified update…", announce=False)
        try:
            self.controller.launch_installer(
                self.info, self.staged_path,
                open_vantage_ui=self.open_ui_after_restart.isChecked())
        except (OSError, RuntimeError, ValueError) as error:
            self._failed(f"Update could not start: {error}")
            return
        self._one_click_active = False
        self._suppress_restore_focus = True
        app = QApplication.instance()
        if getattr(app, "_system_tray", None):
            app._system_tray.setVisible(False)
        app.quit()

    def hideEvent(self, event):
        super().hideEvent(event)
        if (not self._suppress_restore_focus and
                callable(self._restore_focus)):
            QTimer.singleShot(0, self._restore_focus)

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
