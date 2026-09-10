"""Account-free, persistent sync between the user's Vantage PCs.

Syncthing is used only as the encrypted device-to-device transport.  Vantage
owns the small, allowlisted profile documents inside the shared folder and
never exposes its configuration directory wholesale.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

from PySide6.QtCore import QObject, QSize, QTimer, Signal
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QGuiApplication)
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget)

from vantage.helpers import config
from vantage.helpers.auction_hotbutton import (
    export_managed_auction_hotbuttons, import_managed_auction_hotbuttons)
from vantage.helpers.icons import game_icon
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import scrollable
from vantage.helpers.scaled_dialog import UniformScaleDialog


PAIR_PREFIX = "VANTAGE-SYNC-1."
SNAPSHOT_SCHEMA = 1
SYNCTHING_RELEASE_API = (
    "https://api.github.com/repos/syncthing/syncthing/releases/latest")
MAX_RELEASE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_BINARY_BYTES = 64 * 1024 * 1024
SYNC_FOLDER_ID_PREFIX = "vantage-"
DEVICE_ID_RX = re.compile(
    r"^(?:[A-Z2-7]{7}-){7}[A-Z2-7]{7}$", re.IGNORECASE)

# These values identify one Windows installation or grant access elsewhere.
# They must never leave the current PC.
LOCAL_TOP_LEVEL = {"sharing", "mobile", "device_sync"}
LOCAL_KEYS = {
    "api_key", "auth", "credential", "eq_dir", "eq_executable",
    "eq_log_dir", "password", "refresh_token", "secret", "token", "url",
}
PRESENTATION_KEYS = {
    "always_on_top", "auto_hide_menu", "clickthrough", "collapsed",
    "column_widths", "frameless", "gear_column_widths", "geometry",
    "opacity", "orientation", "show_header", "table_column_widths", "toggled",
}


class DeviceSyncError(ValueError):
    """A safe, user-facing sync failure."""


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _b64_encode(payload):
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64_decode(value):
    text = str(value or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def normalize_device_id(value):
    value = str(value or "").strip().upper()
    if not DEVICE_ID_RX.fullmatch(value):
        raise DeviceSyncError("This Vantage sync code has an invalid device ID")
    return value


def build_pair_code(device_id, device_name, group_id, group_secret):
    """Create a copy/paste invitation. It contains no account information."""
    payload = {
        "v": 1,
        "device": normalize_device_id(device_id),
        "name": " ".join(str(device_name or "Vantage PC").split())[:80],
        "group": str(group_id or "").strip().lower(),
        "key": str(group_secret or "").strip(),
    }
    if not re.fullmatch(r"[a-f0-9]{24}", payload["group"]):
        raise DeviceSyncError("The local sync group is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", payload["key"]):
        raise DeviceSyncError("The local sync key is invalid")
    return PAIR_PREFIX + _b64_encode(_json_bytes(payload))


def decode_pair_code(code):
    text = "".join(str(code or "").split())
    if not text.startswith(PAIR_PREFIX) or len(text) > 900:
        raise DeviceSyncError("Paste a complete Vantage sync code")
    try:
        payload = json.loads(_b64_decode(text[len(PAIR_PREFIX):]))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise DeviceSyncError("This Vantage sync code is damaged") from error
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise DeviceSyncError("This Vantage sync code is not supported")
    device = normalize_device_id(payload.get("device"))
    group = str(payload.get("group") or "").lower()
    key = str(payload.get("key") or "")
    if not re.fullmatch(r"[a-f0-9]{24}", group):
        raise DeviceSyncError("This Vantage sync group is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
        raise DeviceSyncError("This Vantage sync key is invalid")
    return {
        "device": device,
        "name": " ".join(str(payload.get("name") or "Vantage PC").split())[:80],
        "group": group,
        "key": key,
    }


def _filtered_copy(value, *, include_layout=True, depth=0):
    if depth > 12:
        return None
    if isinstance(value, dict):
        result = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            folded = key.casefold()
            if (folded in LOCAL_KEYS or any(
                    word in folded for word in
                    ("password", "secret", "token", "credential", "api_key"))):
                continue
            if not include_layout and folded in PRESENTATION_KEYS:
                continue
            result[key] = _filtered_copy(
                child, include_layout=include_layout, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_filtered_copy(
            child, include_layout=include_layout, depth=depth + 1)
                for child in value[:2048]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return copy.deepcopy(value)
    return None


def export_sync_settings(settings, include_layout=True):
    """Return the portable profile subset; machine paths and secrets stay local."""
    source = settings if isinstance(settings, dict) else {}
    result = {}
    for section, value in source.items():
        if str(section).casefold() in LOCAL_TOP_LEVEL:
            continue
        if section == "vantage_ui":
            value = {
                key: child for key, child in value.items()
                if str(key).casefold() not in {"eq_dir", "installed_path"}}
        result[str(section)] = _filtered_copy(
            value, include_layout=include_layout)
    return result


def apply_sync_settings(current, incoming, include_layout=True):
    """Merge a validated portable profile without replacing local-only values."""
    portable = export_sync_settings(incoming, include_layout=include_layout)
    for section, value in portable.items():
        if isinstance(value, dict) and isinstance(current.get(section), dict):
            _merge_dict(current[section], value)
        else:
            current[section] = copy.deepcopy(value)
    return current


def _merge_dict(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def sign_snapshot(payload, group_secret):
    body = dict(payload)
    body.pop("signature", None)
    signature = hmac.new(
        str(group_secret).encode("ascii"), _json_bytes(body),
        hashlib.sha256).hexdigest()
    body["signature"] = signature
    return body


def verify_snapshot(payload, group_secret):
    if not isinstance(payload, dict):
        return False
    signature = str(payload.get("signature") or "")
    expected = sign_snapshot(payload, group_secret)["signature"]
    return bool(signature) and hmac.compare_digest(signature, expected)


def _safe_read_json(path, limit=8 * 1024 * 1024):
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > limit:
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _atomic_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=".vantage-sync-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _official_release_asset():
    request = Request(
        SYNCTHING_RELEASE_API,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "Vantage/1.44.75"})
    with urlopen(request, timeout=15) as response:
        raw = response.read(MAX_RELEASE_BYTES + 1)
    if len(raw) > MAX_RELEASE_BYTES:
        raise DeviceSyncError("The official Syncthing release response is too large")
    release = json.loads(raw.decode("utf-8"))
    if release.get("prerelease") or release.get("draft"):
        raise DeviceSyncError("The official release is not stable")
    suffix = "windows-amd64" if platform.machine().lower() not in {
        "arm64", "aarch64"} else "windows-arm64"
    asset = next((item for item in release.get("assets", [])
                  if re.fullmatch(
                      rf"syncthing-{suffix}-v\d+\.\d+\.\d+\.zip",
                      str(item.get("name") or ""))), None)
    if not asset:
        raise DeviceSyncError("No compatible official Windows transport was found")
    digest = str(asset.get("digest") or "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise DeviceSyncError("The official release did not provide a SHA-256 digest")
    return asset["browser_download_url"], digest.split(":", 1)[1]


def install_syncthing(progress=None):
    """Download one verified portable transport binary from the official release."""
    url, expected = _official_release_asset()
    request = Request(url, headers={"User-Agent": "Vantage/1.44.75"})
    with urlopen(request, timeout=45) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_ARCHIVE_BYTES:
            raise DeviceSyncError("The transport archive is larger than expected")
        chunks = []
        total = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise DeviceSyncError("The transport archive is larger than expected")
            chunks.append(chunk)
            if progress and length:
                progress(min(90, int(total * 90 / length)))
    archive = b"".join(chunks)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise DeviceSyncError("The transport SHA-256 verification failed")
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(archive)) as source:
        members = [entry for entry in source.infolist()
                   if Path(entry.filename).name.casefold() == "syncthing.exe"]
        if len(members) != 1 or members[0].file_size > MAX_BINARY_BYTES:
            raise DeviceSyncError("The official transport archive is invalid")
        binary = source.read(members[0])
    if not binary.startswith(b"MZ"):
        raise DeviceSyncError("The verified transport is not a Windows executable")
    target = data_dir("tools") / "syncthing.exe"
    temporary = target.with_suffix(".exe.part")
    temporary.write_bytes(binary)
    os.replace(temporary, target)
    if progress:
        progress(100)
    return target


class SyncthingTransport:
    """Minimal local-only REST controller for the Syncthing transport."""

    def __init__(self):
        self.home = data_dir("device-sync", "engine")
        self.shared = data_dir("device-sync", "shared")
        self.binary = data_dir("tools", create=False) / "syncthing.exe"
        self.process = None
        self.api_key = ""
        self.port = 0

    @property
    def installed(self):
        return self.binary.is_file() and not self.binary.is_symlink()

    def _run(self, *args, timeout=30):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [str(self.binary), *map(str, args)], capture_output=True,
            text=True, timeout=timeout, creationflags=flags, check=False)
        if result.returncode:
            raise DeviceSyncError(
                (result.stderr or result.stdout or "Sync transport failed").strip()[:500])
        return result.stdout.strip()

    def prepare(self):
        if not self.installed:
            raise DeviceSyncError("Install the account-free sync component first")
        self.home.mkdir(parents=True, exist_ok=True)
        if not (self.home / "config.xml").is_file():
            self._run("generate", f"--home={self.home}")
        self.api_key = secrets.token_urlsafe(32)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = int(probe.getsockname()[1])

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.prepare()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [str(self.binary), "serve", f"--home={self.home}",
             "--no-browser", "--no-console", "--no-restart", "--no-upgrade",
             f"--gui-address=127.0.0.1:{self.port}",
             f"--gui-apikey={self.api_key}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)

    def stop(self):
        if not self.process or self.process.poll() is not None:
            return
        try:
            self.request("POST", "/rest/system/shutdown")
            self.process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError, DeviceSyncError):
            self.process.terminate()
        self.process = None

    def request(self, method, path, payload=None):
        if not self.port or not self.api_key:
            raise DeviceSyncError("Device sync is not running")
        body = _json_bytes(payload) if payload is not None else None
        request = Request(
            f"http://127.0.0.1:{self.port}{path}", data=body, method=method,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=4) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except (HTTPError, URLError, OSError) as error:
            raise DeviceSyncError("The local sync service is starting") from error
        if len(raw) > 4 * 1024 * 1024:
            raise DeviceSyncError("The local sync response is too large")
        return json.loads(raw.decode("utf-8")) if raw else {}

    def device_id(self):
        return normalize_device_id(self.request("GET", "/rest/system/status")["myID"])

    def devices(self):
        return self.request("GET", "/rest/config/devices")

    def pending(self):
        return self.request("GET", "/rest/cluster/pending/devices")

    def _device_template(self, device_id, name):
        template = self.request("GET", "/rest/config/defaults/device")
        template.update({
            "deviceID": normalize_device_id(device_id),
            "name": " ".join(str(name or "Vantage PC").split())[:80],
            "addresses": ["dynamic"], "introducer": True,
            "autoAcceptFolders": False,
        })
        return template

    def add_device(self, device_id, name, group_id=None):
        device_id = normalize_device_id(device_id)
        self.request("POST", "/rest/config/devices",
                     self._device_template(device_id, name))
        self.ensure_folder([device_id], group_id=group_id)

    def remove_device(self, device_id, group_id=None):
        device_id = normalize_device_id(device_id)
        group = (str(group_id or "") or
                 config.data.get("device_sync", {}).get("group_id", ""))
        folder_id = SYNC_FOLDER_ID_PREFIX + group
        try:
            folder = self.request(
                "GET", "/rest/config/folders/" + quote(folder_id, safe=""))
            folder["devices"] = [
                item for item in folder.get("devices", [])
                if str(item.get("deviceID") or "") != device_id]
            self.request("POST", "/rest/config/folders", folder)
        except DeviceSyncError:
            pass
        self.request(
            "DELETE", "/rest/config/devices/" + quote(device_id, safe=""))

    def ensure_folder(self, additional_devices=(), group_id=None):
        status = self.request("GET", "/rest/system/status")
        local_id = normalize_device_id(status["myID"])
        group = (str(group_id or "") or
                 config.data.get("device_sync", {}).get("group_id", ""))
        folder_id = SYNC_FOLDER_ID_PREFIX + group
        for existing in self.request("GET", "/rest/config/folders"):
            existing_id = str(existing.get("id") or "")
            if (existing_id.startswith(SYNC_FOLDER_ID_PREFIX) and
                    existing_id != folder_id):
                self.request(
                    "DELETE", "/rest/config/folders/" +
                    quote(existing_id, safe=""))
        try:
            folder = self.request(
                "GET", "/rest/config/folders/" + quote(folder_id, safe=""))
        except DeviceSyncError:
            folder = self.request("GET", "/rest/config/defaults/folder")
            folder.update({
                "id": folder_id, "label": "Vantage device sync",
                "path": str(self.shared), "type": "sendreceive",
                "fsWatcherEnabled": True, "rescanIntervalS": 30,
                "versioning": {"type": "staggered", "params": {
                    "cleanInterval": "3600", "maxAge": "2592000",
                    "versionsPath": ""}, "cleanupIntervalS": 3600},
            })
        ids = {local_id, *[normalize_device_id(value)
                           for value in additional_devices]}
        ids.update(str(item.get("deviceID") or "")
                   for item in folder.get("devices", []))
        folder["devices"] = [{"deviceID": value}
                             for value in sorted(ids) if value]
        self.request("POST", "/rest/config/folders", folder)


class DeviceSyncController(QObject):
    status_changed = Signal(str)
    state_changed = Signal()
    progress_changed = Signal(int)
    install_completed = Signal(str)
    installation_finished = Signal(bool)
    poll_completed = Signal(object, str)
    operation_completed = Signal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.transport = SyncthingTransport()
        self._ready = False
        self._installing = False
        self._polling = False
        self._operation_busy = False
        self._device_id = ""
        self._peer_cache = []
        self._pending_cache = []
        self._last_local_hash = ""
        self._local_modified_at = 0.0
        self._last_hotbutton_hash = ""
        self._seen = {}
        self._state_path = data_dir("device-sync", "local-state.json")
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self.install_completed.connect(self._install_finished)
        self.poll_completed.connect(self._poll_finished)
        self.operation_completed.connect(self._operation_finished)
        self._ensure_identity()
        self._load_state()

    def _ensure_identity(self):
        settings = config.data.setdefault("device_sync", {})
        if not settings.get("group_id"):
            settings["group_id"] = secrets.token_hex(12)
        if not settings.get("group_secret"):
            settings["group_secret"] = secrets.token_urlsafe(32)
        if not settings.get("device_name"):
            settings["device_name"] = socket.gethostname()[:80] or "Vantage PC"
        config.save()

    def _load_state(self):
        state = _safe_read_json(self._state_path, limit=512 * 1024) or {}
        if state.get("group") != config.data["device_sync"].get("group_id"):
            return
        self._last_local_hash = str(state.get("local_hash") or "")[:64]
        self._last_hotbutton_hash = str(
            state.get("hotbutton_hash") or "")[:64]
        try:
            self._local_modified_at = max(
                0.0, float(state.get("local_modified_at") or 0))
        except (TypeError, ValueError):
            self._local_modified_at = 0.0
        raw_seen = state.get("seen", {})
        if isinstance(raw_seen, dict):
            for device, revision in list(raw_seen.items())[:64]:
                try:
                    if DEVICE_ID_RX.fullmatch(str(device)):
                        self._seen[str(device)] = max(0.0, float(revision))
                except (TypeError, ValueError):
                    pass

    def _save_state(self):
        _atomic_json(self._state_path, {
            "group": config.data["device_sync"].get("group_id", ""),
            "local_hash": self._last_local_hash,
            "local_modified_at": self._local_modified_at,
            "hotbutton_hash": self._last_hotbutton_hash,
            "seen": dict(list(self._seen.items())[-64:]),
        })

    @property
    def installed(self):
        return self.transport.installed

    @property
    def installing(self):
        return self._installing

    @property
    def operation_busy(self):
        return self._operation_busy

    @property
    def running(self):
        return bool(self.transport.process and self.transport.process.poll() is None)

    @property
    def ready(self):
        return self._ready

    @property
    def device_id(self):
        return self._device_id

    def install(self):
        if self._installing:
            return
        self._installing = True
        self.progress_changed.emit(0)
        self.state_changed.emit()
        self.status_changed.emit("Downloading the verified sync component…")

        def worker():
            error = ""
            try:
                install_syncthing(lambda value: self.progress_changed.emit(value))
            except Exception as caught:  # converted to a bounded UI message
                error = str(caught)
            self.install_completed.emit(error)

        threading.Thread(target=worker, daemon=True).start()

    def _install_finished(self, error):
        self._installing = False
        if error:
            self.progress_changed.emit(-1)
            self.status_changed.emit(f"Sync component not installed: {error}")
        else:
            config.data["device_sync"]["enabled"] = True
            config.save()
            self.status_changed.emit("Sync component verified and installed")
            self.start()
            self.progress_changed.emit(100)
        self.installation_finished.emit(not bool(error))
        self.state_changed.emit()

    def start(self):
        if not self.installed:
            self.status_changed.emit("Install the account-free sync component to begin")
            self.state_changed.emit()
            return False
        if self.running:
            return True
        try:
            self.transport.start()
        except DeviceSyncError as error:
            self.status_changed.emit(str(error))
            return False
        self._ready = False
        self.status_changed.emit("Starting encrypted device sync…")
        self._timer.start()
        self.refresh()
        return True

    def stop(self):
        self._timer.stop()
        self.transport.stop()
        self._ready = False

    def refresh(self):
        if self._polling:
            return
        if not self.running:
            self._ready = False
            self.state_changed.emit()
            return
        self._polling = True

        def worker():
            error = ""
            snapshot = {}
            try:
                device_id = self.transport.device_id()
                self.transport.ensure_folder()
                devices = self.transport.devices()
                connections = self.transport.request(
                    "GET", "/rest/system/connections").get("connections", {})
                pending = self.transport.pending()
                snapshot = {
                    "device_id": device_id,
                    "devices": devices,
                    "connections": connections,
                    "pending": pending,
                }
            except (DeviceSyncError, OSError, ValueError, KeyError, TypeError) as caught:
                error = str(caught)
            self.poll_completed.emit(snapshot, error)

        threading.Thread(target=worker, daemon=True).start()

    def _poll_finished(self, snapshot, error):
        self._polling = False
        if error:
            self._ready = False
            self.status_changed.emit(error)
            self.state_changed.emit()
            return
        try:
            self._device_id = normalize_device_id(snapshot["device_id"])
            states = snapshot.get("connections", {})
            self._peer_cache = [{
                "id": str(device.get("deviceID") or ""),
                "name": str(device.get("name") or "Vantage PC"),
                "connected": bool(states.get(
                    str(device.get("deviceID") or ""), {}).get(
                        "connected", False)),
            } for device in snapshot.get("devices", [])
                if str(device.get("deviceID") or "") != self._device_id]
            raw_pending = snapshot.get("pending", {})
            self._pending_cache = [{
                "id": device_id,
                "name": str(value.get("name") or "New PC"),
            } for device_id, value in raw_pending.items()
                if DEVICE_ID_RX.fullmatch(str(device_id))]
            self._ready = True
            self._export_if_changed()
            applied = self._apply_received()
            self._sync_hotbuttons_from_latest()
            peers = self.peers()
            connected = sum(1 for peer in peers if peer.get("connected"))
            message = (
                f"Synced {applied} update{'s' if applied != 1 else ''}"
                if applied else
                f"Connected · {connected}/{len(peers)} paired PC"
                f"{'s' if len(peers) != 1 else ''} online")
            self.status_changed.emit(message)
        except (DeviceSyncError, OSError, ValueError) as error:
            self._ready = False
            self.status_changed.emit(str(error))
        self.state_changed.emit()

    def pair_code(self):
        if not self._device_id:
            raise DeviceSyncError("Wait for device sync to finish starting")
        settings = config.data["device_sync"]
        return build_pair_code(
            self._device_id, settings["device_name"],
            settings["group_id"], settings["group_secret"])

    def join(self, code):
        invitation = decode_pair_code(code)
        if self._device_id and invitation["device"] == self._device_id:
            raise DeviceSyncError("Use this code on a different PC")
        return self._run_operation(
            "join", invitation,
            lambda: self.transport.add_device(
                invitation["device"], invitation["name"],
                group_id=invitation["group"]),
            f"Connecting to {invitation['name']}…")

    def pending(self):
        return list(self._pending_cache) if self._ready else []

    def approve(self, device_id, name):
        detail = {"device": normalize_device_id(device_id), "name": str(name)}
        group = config.data["device_sync"]["group_id"]
        return self._run_operation(
            "approve", detail,
            lambda: self.transport.add_device(
                detail["device"], detail["name"], group_id=group),
            f"Approving {detail['name']}…")

    def remove(self, device_id, name):
        detail = {"device": normalize_device_id(device_id), "name": str(name)}
        group = config.data["device_sync"]["group_id"]
        return self._run_operation(
            "remove", detail,
            lambda: self.transport.remove_device(
                detail["device"], group_id=group),
            f"Removing {detail['name']}…")

    def _run_operation(self, kind, detail, action, pending_message):
        if self._operation_busy:
            raise DeviceSyncError("Finish the current device action first")
        self._operation_busy = True
        self.status_changed.emit(pending_message)
        self.state_changed.emit()

        def worker():
            error = ""
            try:
                action()
            except (DeviceSyncError, OSError, ValueError, KeyError, TypeError) as caught:
                error = str(caught)
            self.operation_completed.emit(kind, detail, error)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _operation_finished(self, kind, detail, error):
        self._operation_busy = False
        if error:
            self.status_changed.emit(f"Device sync action failed: {error}")
            self.state_changed.emit()
            return
        device_id = detail["device"]
        name = detail["name"]
        if kind == "join":
            settings = config.data["device_sync"]
            settings["group_id"] = detail["group"]
            settings["group_secret"] = detail["key"]
            settings["enabled"] = True
            config.save()
            # Pull the inviter's current profile before this joining PC is
            # allowed to publish an older local copy.
            self._local_modified_at = 0.0
            self._seen = {}
            self._last_local_hash = self._content_hash(
                self._snapshot_payload())
            self._save_state()
            self.status_changed.emit(
                f"Request sent to {name} · approve it on that PC")
        elif kind == "approve":
            self.status_changed.emit(
                f"{name} approved and added to this sync group")
        else:
            self._seen.pop(device_id, None)
            self._save_state()
            self.status_changed.emit(f"{name} removed from this sync group")
        self.state_changed.emit()
        self.refresh()

    def peers(self):
        return list(self._peer_cache) if self._ready else []

    def _snapshot_payload(self):
        settings = config.data["device_sync"]
        payload = {
            "schema": SNAPSHOT_SCHEMA,
            "device": self._device_id,
            "name": settings["device_name"],
            "group": settings["group_id"],
            "generated_at": time.time(),
            "settings": export_sync_settings(
                config.data, settings.get("sync_layout", True))
                if settings.get("sync_settings", True) else {},
        }
        if settings.get("sync_items_notes", True):
            notes = _safe_read_json(data_dir("items-notes.json", create=False))
            if notes:
                payload["items_notes"] = notes
        if settings.get("sync_hotbuttons", True):
            eq_root = str(config.data.get("vantage_ui", {}).get("eq_dir") or "")
            try:
                payload["hotbuttons"] = export_managed_auction_hotbuttons(eq_root)
            except (OSError, ValueError):
                payload["hotbuttons"] = []
        return payload

    @staticmethod
    def _content_hash(payload):
        return hashlib.sha256(_json_bytes({
            "settings": payload.get("settings", {}),
            "items_notes": payload.get("items_notes", {}),
            "hotbuttons": payload.get("hotbuttons", []),
        })).hexdigest()

    def _export_if_changed(self):
        if not self._device_id:
            return
        payload = self._snapshot_payload()
        content_hash = self._content_hash(payload)
        if content_hash == self._last_local_hash:
            return
        self._last_local_hash = content_hash
        self._local_modified_at = payload["generated_at"]
        signed = sign_snapshot(
            payload, config.data["device_sync"]["group_secret"])
        _atomic_json(self.transport.shared / f"{self._device_id}.json", signed)
        self._save_state()

    def _apply_received(self):
        settings = config.data["device_sync"]
        secret = settings["group_secret"]
        group = settings["group_id"]
        peers = {peer["id"] for peer in self.peers()}
        candidates = []
        for path in self.transport.shared.glob("*.json"):
            payload = _safe_read_json(path)
            if not payload or not verify_snapshot(payload, secret):
                continue
            device = str(payload.get("device") or "")
            revision = float(payload.get("generated_at") or 0)
            if (device == self._device_id or device not in peers or
                    payload.get("group") != group or
                    payload.get("schema") != SNAPSHOT_SCHEMA or
                    revision <= float(self._seen.get(device, 0))):
                continue
            candidates.append((revision, device, payload))
        applied = 0
        for revision, device, payload in sorted(candidates):
            self._seen[device] = revision
            if revision <= self._local_modified_at:
                continue
            before = copy.deepcopy(config.data.get("device_sync", {}))
            if settings.get("sync_settings", True):
                apply_sync_settings(
                    config.data, payload.get("settings", {}),
                    settings.get("sync_layout", True))
            config.data["device_sync"] = before
            if settings.get("sync_items_notes", True) and isinstance(
                    payload.get("items_notes"), dict):
                _atomic_json(data_dir("items-notes.json"), payload["items_notes"])
            config.verify_settings()
            config.save()
            digest_source = {
                "settings": export_sync_settings(
                    config.data, settings.get("sync_layout", True)),
                "items_notes": _safe_read_json(
                    data_dir("items-notes.json", create=False)) or {},
                "hotbuttons": payload.get("hotbuttons", []),
            }
            self._last_local_hash = self._content_hash(digest_source)
            self._local_modified_at = revision
            app = self.parent()
            if app is not None and hasattr(app, "_signals"):
                app._signals["settings"].config_updated.emit()
            applied += 1
            self._save_state()
        return applied

    def _sync_hotbuttons_from_latest(self):
        """Apply the newest peer Socials after EQ closes so EQ cannot overwrite them."""
        settings = config.data["device_sync"]
        if not settings.get("sync_hotbuttons", True):
            return 0
        from vantage.helpers.ui_skin_updater import game_running
        if game_running():
            return 0
        secret = settings["group_secret"]
        group = settings["group_id"]
        peers = {peer["id"] for peer in self.peers()}
        latest = None
        for path in self.transport.shared.glob("*.json"):
            payload = _safe_read_json(path)
            if (not payload or not verify_snapshot(payload, secret) or
                    payload.get("group") != group or
                    payload.get("device") not in peers or
                    not isinstance(payload.get("hotbuttons"), list)):
                continue
            revision = float(payload.get("generated_at") or 0)
            if latest is None or revision > latest[0]:
                latest = (revision, payload["hotbuttons"])
        if latest is None or latest[0] < self._local_modified_at:
            return 0
        digest = hashlib.sha256(_json_bytes(latest[1])).hexdigest()
        if digest == self._last_hotbutton_hash:
            return 0
        eq_root = str(config.data.get("vantage_ui", {}).get("eq_dir") or "")
        changed = import_managed_auction_hotbuttons(eq_root, latest[1])
        self._last_hotbutton_hash = digest
        self._save_state()
        return changed


class DeviceSyncDialog(UniformScaleDialog):
    """Simple one-code setup for an account-free device group."""

    def __init__(self, controller, parent=None):
        super().__init__(
            QSize(680, 610), parent, minimum_size=QSize(360, 390))
        self.controller = controller
        self._peer_signature = None
        self._pending_ids = set()
        self.setWindowTitle("Vantage · Device Sync")
        outer = QVBoxLayout(self.scaled_surface)
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel("DEVICE SYNC")
        title.setObjectName("SettingsSectionTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Keep Vantage settings, window layout, watched items and notes on "
            "2, 3 or more PCs. No account: your data moves encrypted between "
            "approved devices and is not stored in a Vantage cloud.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status = QLabel("Not started")
        self.status.setObjectName("CombatDataNotice")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Device sync status")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setAccessibleName("Sync component installation progress")
        layout.addWidget(self.progress)

        self.install_button = QPushButton("Install secure sync")
        self.install_button.setIcon(game_icon("download"))
        self.install_button.setToolTip(
            "Download and SHA-256 verify the portable open-source Syncthing "
            "transport from its official GitHub release")
        self.install_button.clicked.connect(self.controller.install)
        layout.addWidget(self.install_button)

        options = QFormLayout()
        self.sync_settings = QCheckBox("Settings and WTS/WTB preferences")
        self.sync_settings.setToolTip(
            "Includes automatic-update opt-ins, but never passwords, tokens, "
            "credentials, or local paths")
        self.sync_layout = QCheckBox("Window sizes and layout")
        self.sync_items = QCheckBox("Item tracker and notes")
        self.sync_hotbuttons = QCheckBox("WTS/WTB buttons for matching characters")
        options.addRow("Sync", self.sync_settings)
        options.addRow("Also", self.sync_layout)
        options.addRow("Also", self.sync_items)
        options.addRow("Also", self.sync_hotbuttons)
        layout.addLayout(options)
        for checkbox in (
                self.sync_settings, self.sync_layout, self.sync_items,
                self.sync_hotbuttons):
            checkbox.toggled.connect(self._save_options)

        code_row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setReadOnly(True)
        self.code.setAccessibleName("This PC pairing code")
        self.code.setPlaceholderText("Starts after secure sync is installed")
        code_row.addWidget(self.code, 1)
        self.copy_button = QPushButton("Copy code")
        self.copy_button.setIcon(game_icon("copy"))
        self.copy_button.clicked.connect(self._copy_code)
        code_row.addWidget(self.copy_button)
        layout.addWidget(QLabel("Add another PC"))
        layout.addLayout(code_row)

        join_row = QHBoxLayout()
        self.join_code = QLineEdit()
        self.join_code.setAccessibleName("Pairing code from another PC")
        self.join_code.setPlaceholderText("Paste the code from an approved PC")
        join_row.addWidget(self.join_code, 1)
        self.join_button = QPushButton("Connect")
        self.join_button.setIcon(game_icon("link"))
        self.join_button.clicked.connect(self._join)
        join_row.addWidget(self.join_button)
        layout.addLayout(join_row)

        layout.addWidget(QLabel("Paired PCs"))
        self.peers = QListWidget()
        self.peers.setAccessibleName("Paired Vantage PCs")
        layout.addWidget(self.peers, 1)
        self.pending_label = QLabel("")
        self.pending_label.setWordWrap(True)
        layout.addWidget(self.pending_label)
        self.approve = QPushButton("Approve selected PC")
        self.approve.setIcon(game_icon("check"))
        self.approve.clicked.connect(self._approve)
        layout.addWidget(self.approve)
        self.remove_button = QPushButton("Remove selected PC")
        self.remove_button.setIcon(game_icon("delete"))
        self.remove_button.setToolTip(
            "Stop sharing with the selected paired PC; that PC must be "
            "approved again before it can reconnect")
        self.remove_button.clicked.connect(self._remove)
        layout.addWidget(self.remove_button)

        note = QLabel(
            "Both PCs must be online to exchange a change. Pairing stays saved, "
            "reconnects automatically across networks, and supports more than "
            "two PCs. Local EQ paths, passwords and sign-in tokens never sync. "
            "Transport: Syncthing (MPL 2.0).")
        note.setWordWrap(True)
        note.setObjectName("CombatDataNotice")
        layout.addWidget(note)
        outer.addWidget(scrollable(body, "DeviceSyncScroll"), 1)

        close = QPushButton("Close")
        close.clicked.connect(self.close)
        outer.addWidget(close)
        self.controller.status_changed.connect(self._set_status)
        self.controller.progress_changed.connect(self._progress)
        self.controller.installation_finished.connect(
            self._installation_finished)
        self.controller.state_changed.connect(self.refresh)
        self.refresh()

    def _progress(self, value):
        visible = 0 <= value < 100
        self.progress.setVisible(visible)
        if visible:
            self.progress.setValue(value)

    def _installation_finished(self, succeeded):
        self.progress.setVisible(False)
        self.refresh()
        (self.copy_button if succeeded else self.install_button).setFocus()

    def _set_status(self, message):
        message = str(message or "")
        changed = self.status.text() != message
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        if not changed or not self.isVisible():
            return
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.status, message))
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _save_options(self):
        settings = config.data["device_sync"]
        settings["sync_settings"] = self.sync_settings.isChecked()
        settings["sync_layout"] = self.sync_layout.isChecked()
        settings["sync_items_notes"] = self.sync_items.isChecked()
        settings["sync_hotbuttons"] = self.sync_hotbuttons.isChecked()
        settings["enabled"] = True
        config.save()

    def _copy_code(self):
        try:
            code = self.controller.pair_code()
        except DeviceSyncError as error:
            QMessageBox.information(self, "Device Sync", str(error))
            return
        QGuiApplication.clipboard().setText(code)
        self._set_status("Pairing code copied · paste it on the other PC")

    def _join(self):
        try:
            self.controller.join(self.join_code.text())
            self.join_code.clear()
        except DeviceSyncError as error:
            QMessageBox.warning(self, "Device Sync", str(error))

    def _approve(self):
        item = self.peers.currentItem()
        detail = item.data(256) if item else None
        if not detail or detail[0] != "pending":
            QMessageBox.information(
                self, "Device Sync", "Select a waiting PC first")
            return
        _kind, device_id, name = detail
        if QMessageBox.question(
                self, "Approve this PC?",
                f"Allow {name} to join this Vantage sync group?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.approve(device_id, name)
        except DeviceSyncError as error:
            QMessageBox.warning(self, "Device Sync", str(error))

    def _remove(self):
        item = self.peers.currentItem()
        detail = item.data(256) if item else None
        if not detail or detail[0] != "peer":
            QMessageBox.information(
                self, "Device Sync", "Select a paired PC first")
            return
        _kind, device_id, name = detail
        if QMessageBox.question(
                self, "Remove this PC?",
                f"Stop syncing with {name}?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.remove(device_id, name)
        except DeviceSyncError as error:
            QMessageBox.warning(self, "Device Sync", str(error))

    def refresh(self):
        settings = config.data.get("device_sync", {})
        for checkbox, key, default in (
                (self.sync_settings, "sync_settings", True),
                (self.sync_layout, "sync_layout", True),
                (self.sync_items, "sync_items_notes", True),
                (self.sync_hotbuttons, "sync_hotbuttons", True)):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(settings.get(key, default)))
            checkbox.blockSignals(False)
        self.install_button.setVisible(not self.controller.installed)
        self.install_button.setEnabled(not self.controller.installing)
        self.join_button.setEnabled(not self.controller.operation_busy)
        if self.controller.installed and not self.controller.running:
            self.controller.start()
        try:
            self.code.setText(self.controller.pair_code())
        except DeviceSyncError:
            self.code.clear()
        try:
            pending = self.controller.pending()
            peers = self.controller.peers()
            pending_ids = {peer["id"] for peer in pending}
            new_pending = pending_ids - self._pending_ids
            if new_pending and self.isVisible():
                message = (
                    "New PC waiting for approval" if len(new_pending) == 1 else
                    f"{len(new_pending)} new PCs waiting for approval")
                try:
                    QAccessible.updateAccessibility(
                        QAccessibleAnnouncementEvent(self.peers, message))
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self._pending_ids = pending_ids
            signature = (
                tuple((peer["id"], peer["name"]) for peer in pending),
                tuple((peer["id"], peer["name"], peer["connected"])
                      for peer in peers))
            if signature != self._peer_signature:
                current = self.peers.currentItem()
                selected = current.data(256) if current else None
                scroll = self.peers.verticalScrollBar().value()
                self.peers.clear()
                for peer in pending:
                    item = QListWidgetItem(
                        f"WAITING FOR APPROVAL · {peer['name']}")
                    item.setData(
                        256, ("pending", peer["id"], peer["name"]))
                    self.peers.addItem(item)
                for peer in peers:
                    state = (
                        "ONLINE" if peer["connected"] else
                        "OFFLINE · will reconnect")
                    item = QListWidgetItem(f"{state} · {peer['name']}")
                    item.setData(256, ("peer", peer["id"], peer["name"]))
                    self.peers.addItem(item)
                if selected:
                    for index in range(self.peers.count()):
                        if self.peers.item(index).data(256)[:2] == selected[:2]:
                            self.peers.setCurrentRow(index)
                            break
                self.peers.verticalScrollBar().setValue(scroll)
                self._peer_signature = signature
            self.pending_label.setText(
                f"{len(pending)} PC{'s' if len(pending) != 1 else ''} waiting"
                if pending else "No approval requests")
            self.approve.setEnabled(
                bool(pending) and not self.controller.operation_busy)
            self.remove_button.setEnabled(
                bool(peers) and not self.controller.operation_busy)
        except DeviceSyncError:
            self.pending_label.setText("Waiting for the local sync service")
            self.approve.setEnabled(False)
            self.remove_button.setEnabled(False)
