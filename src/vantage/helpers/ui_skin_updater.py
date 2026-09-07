"""Verified, transactional updater for the optional EverQuest UI skin.

No payload is executed, no game process is stopped, and no character INI or
other skin is modified. The module deliberately has no GUI/Qt dependency.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile


REPOSITORY = "vantageupdates/vantage"
SKIN_FOLDER = "VantageUI"
MANIFEST_ASSET = "VantageUI-manifest.json"
PAYLOAD_ASSET = "VantageUI-payload.zip"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases"
MAX_FILES = 2000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
NETWORK_TIMEOUT = 20
NETWORK_DEADLINE = 180
EXTENSIONS = {".xml", ".tga", ".png", ".bmp", ".jpg", ".jpeg", ".dds"}
VERSION_MARKER = ".vantage-ui-installed.json"
LOCK_NAME = ".vantage-ui-update.lock"
RECOVERY_MARKER = ".vantage-ui-recovery.json"
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com",
                "github-releases.githubusercontent.com"}


class SkinUpdateError(RuntimeError):
    """A safe refusal or unsuccessful update; details are suitable for the UI."""


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    manifest_url: str
    payload_url: str
    manifest_sha256: str
    payload_sha256: str
    release_id: int
    manifest_size: int
    payload_size: int


@dataclass(frozen=True)
class InstallResult:
    version: str
    changed_files: int
    action: str


def _require(condition, message):
    if not condition:
        raise SkinUpdateError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _valid_hash(value):
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate JSON field in update metadata.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error:
        raise SkinUpdateError("Invalid update metadata JSON.") from error


def _https_parts(url):
    parts = urllib.parse.urlsplit(url)
    _require(parts.scheme == "https" and not parts.username and not parts.password
             and not parts.fragment and parts.port in (None, 443), "Unsafe update URL.")
    return parts


class _PinnedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, original):
        self.original = original

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = _https_parts(newurl)
        original = _https_parts(self.original)
        same = (parts.hostname == original.hostname and parts.path == original.path
                and parts.query == original.query)
        asset_redirect = (original.hostname == "github.com"
                          and parts.hostname in _ASSET_HOSTS
                          and parts.path.startswith("/")
                          and "/../" not in urllib.parse.unquote(parts.path))
        _require(same or asset_redirect, "Update download redirected outside GitHub release assets.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url, destination, limit, expected_hash=None, expected_size=None,
              progress=None):
    """HTTPS with bounded streaming, timeout, redirect policy and optional pin."""
    parts = _https_parts(url)
    _require(parts.hostname in {"api.github.com", "github.com"}, "Untrusted update host.")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Vantage-UI-Updater", "Accept": "application/octet-stream"
        if parts.hostname == "github.com" else "application/vnd.github+json"})
    opener = urllib.request.build_opener(_PinnedRedirects(url))
    digest = hashlib.sha256()
    count = 0
    started = time.monotonic()
    with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
        length = response.headers.get("Content-Length")
        if length is not None:
            _require(length.isdigit() and int(length) <= limit, "Update exceeds its download limit.")
        total = expected_size if expected_size is not None else (
            int(length) if length is not None else 0)
        if progress is not None:
            progress(0, total)
        with open(destination, "xb") as output:
            while True:
                _require(time.monotonic() - started < NETWORK_DEADLINE, "Update download timed out.")
                chunk = response.read(min(1024 * 1024, limit - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                _require(count <= limit, "Update exceeds its download limit.")
                digest.update(chunk)
                output.write(chunk)
                if progress is not None:
                    progress(count, total)
            output.flush()
            os.fsync(output.fileno())
    _require(expected_size is None or count == expected_size, "Incomplete release asset download.")
    _require(expected_hash is None or digest.hexdigest() == expected_hash,
             "GitHub release asset SHA-256 verification failed.")


def _emit_progress(callback, stage, percent, received=0, total=0):
    """Report bounded progress without letting presentation code break safety."""
    if callback is None:
        return
    try:
        callback(str(stage), max(0, min(100, int(percent))),
                 max(0, int(received)), max(0, int(total)))
    except Exception:
        pass


def _monotonic_progress(callback):
    if callback is None or getattr(callback, "_vantage_monotonic", False):
        return callback
    highest = 0

    def report(stage, percent, received=0, total=0):
        nonlocal highest
        highest = max(highest, max(0, min(100, int(percent))))
        callback(stage, highest, received, total)

    report._vantage_monotonic = True
    return report


def _download_asset(url, destination, limit, expected_hash, expected_size,
                    progress):
    if progress is None:
        return _download(url, destination, limit, expected_hash, expected_size)
    return _download(url, destination, limit, expected_hash, expected_size,
                     progress=progress)


def parse_release_payload(payload):
    """Strictly bind both assets to one stable Vantage release and its digests."""
    _require(isinstance(payload, dict) and payload.get("draft") is False
             and payload.get("prerelease") is False, "A stable Vantage release is required.")
    tag = payload.get("tag_name", "")
    version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else ""
    _require(bool(_VERSION.fullmatch(version)), "Invalid stable Vantage version.")
    release_id = payload.get("id")
    _require(type(release_id) is int and release_id > 0, "Missing GitHub release identity.")
    assets = payload.get("assets")
    _require(isinstance(assets, list), "Missing GitHub release assets.")
    selected = []
    for name, maximum in ((MANIFEST_ASSET, MAX_MANIFEST_BYTES), (PAYLOAD_ASSET, MAX_ARCHIVE_BYTES)):
        matches = [asset for asset in assets if isinstance(asset, dict)
                   and str(asset.get("name", "")).casefold() == name.casefold()]
        _require(len(matches) == 1 and matches[0].get("name") == name,
                 f"Release {tag} must contain exactly one {name}.")
        asset = matches[0]
        expected_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        _require(asset.get("browser_download_url") == expected_url, "Release asset URL does not match its release.")
        digest = asset.get("digest", "")
        _require(isinstance(digest, str) and digest.startswith("sha256:")
                 and _valid_hash(digest[7:]), f"GitHub SHA-256 digest missing for {name}.")
        size = asset.get("size")
        _require(type(size) is int and 0 < size <= maximum, "Invalid release asset size.")
        selected.append((expected_url, digest[7:], size))
    return Release(version, tag, selected[0][0], selected[1][0], selected[0][1],
                   selected[1][1], release_id, selected[0][2], selected[1][2])


def _has_ui_assets(payload):
    _require(isinstance(payload, dict) and isinstance(payload.get("assets"), list),
             "Invalid GitHub release metadata.")
    names = {MANIFEST_ASSET.casefold(), PAYLOAD_ASSET.casefold()}
    return any(isinstance(asset, dict) and str(asset.get("name", "")).casefold() in names
               for asset in payload["assets"])


def check_release(progress=None):
    """Find the newest stable UI release, tolerating main-app-only releases.

    A release containing either UI asset is never silently skipped if malformed.
    Discovery is bounded to latest plus at most two pages of twenty releases.
    """
    progress = _monotonic_progress(progress)
    with tempfile.TemporaryDirectory(prefix="vantage-ui-check-") as directory:
        path = Path(directory) / "release.json"
        _emit_progress(progress, "Checking release", 0)
        if progress is None:
            _download(LATEST_RELEASE_API, path, 4 * 1024 * 1024)
        else:
            _download(LATEST_RELEASE_API, path, 4 * 1024 * 1024,
                      progress=lambda count, total: _emit_progress(
                          progress, "Downloading release information",
                          5 if not total else 5 + round(25 * count / total),
                          count, total))
        latest = _json(path.read_bytes())
        if _has_ui_assets(latest):
            result = parse_release_payload(latest)
            _emit_progress(progress, "Release verified", 100)
            return result
        _require(latest.get("draft") is False and latest.get("prerelease") is False,
                 "GitHub did not return a stable latest release.")
        for page in (1, 2):
            page_path = Path(directory) / f"releases-{page}.json"
            url = f"{RELEASES_API}?per_page=20&page={page}"
            if progress is None:
                _download(url, page_path, 4 * 1024 * 1024)
            else:
                base = 35 + (page - 1) * 25
                _download(url, page_path, 4 * 1024 * 1024,
                          progress=lambda count, total, base=base: _emit_progress(
                              progress, "Searching verified UI releases",
                              base if not total else base + round(20 * count / total),
                              count, total))
            releases = _json(page_path.read_bytes())
            _require(isinstance(releases, list) and len(releases) <= 20,
                     "Invalid GitHub release history response.")
            for candidate in releases:
                _require(isinstance(candidate, dict), "Invalid GitHub release history entry.")
                if candidate.get("draft") is True or candidate.get("prerelease") is True:
                    continue
                if _has_ui_assets(candidate):
                    result = parse_release_payload(candidate)
                    _emit_progress(progress, "Release verified", 100)
                    return result
            if len(releases) < 20:
                break
        raise SkinUpdateError("No stable Vantage UI release was found in the latest 40 releases.")


def _validate_release(release):
    _require(isinstance(release, Release), "Invalid release selection.")
    rebuilt = parse_release_payload({"id": release.release_id, "tag_name": release.tag,
        "draft": False, "prerelease": False, "assets": [
            {"name": MANIFEST_ASSET, "browser_download_url": release.manifest_url,
             "digest": "sha256:" + release.manifest_sha256, "size": release.manifest_size},
            {"name": PAYLOAD_ASSET, "browser_download_url": release.payload_url,
             "digest": "sha256:" + release.payload_sha256, "size": release.payload_size}]})
    _require(rebuilt == release, "Release version and assets disagree.")


def _safe_name(name, metadata=False):
    if metadata and name == VERSION_MARKER:
        return name
    _require(isinstance(name, str) and 0 < len(name) <= 180 and name not in (".", "..")
             and name == name.strip() and not name.endswith(".")
             and not any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
             and Path(name).suffix.lower() in EXTENSIONS, "Unsafe or unsupported UI filename.")
    base = name.split(".", 1)[0].upper()
    _require(base not in {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
             and not re.fullmatch(r"(?:COM|LPT)[0-9¹²³]", base), "Reserved Windows UI filename.")
    return name


def validate_manifest(data, version):
    _require(len(data) <= MAX_MANIFEST_BYTES, "UI manifest is too large.")
    manifest = _json(data)
    _require(isinstance(manifest, dict) and type(manifest.get("schema")) is int
             and manifest["schema"] == 1 and manifest.get("skin_folder") == SKIN_FOLDER
             and manifest.get("version") == version, "UI manifest does not match this release or skin.")
    entries = manifest.get("files")
    _require(isinstance(entries, list) and 0 < len(entries) <= MAX_FILES, "Invalid UI file count.")
    seen = set()
    total = 0
    for entry in entries:
        _require(isinstance(entry, dict), "Invalid UI manifest entry.")
        name = _safe_name(entry.get("path"))
        _require(name.casefold() not in seen, "Duplicate Windows filename in UI manifest.")
        seen.add(name.casefold())
        size = entry.get("size")
        _require(type(size) is int and 0 <= size <= MAX_FILE_BYTES and _valid_hash(entry.get("sha256")),
                 "Invalid UI file size or SHA-256.")
        total += size
        _require(total <= MAX_TOTAL_BYTES, "UI payload is too large.")
    return entries


def stage_archive(archive, entries, directory):
    """Extract only an exact, verified flat manifest; never use extractall()."""
    expected = {entry["path"]: entry for entry in entries}
    _require(Path(archive).stat().st_size <= MAX_ARCHIVE_BYTES, "UI archive is too large.")
    with zipfile.ZipFile(archive) as payload:
        members = payload.infolist()
        _require(len(members) == len(expected) <= MAX_FILES, "UI archive file list differs from manifest.")
        seen = set()
        for member in members:
            name = _safe_name(member.filename)
            _require(name not in seen and name in expected, "Unexpected or duplicate UI archive file.")
            seen.add(name)
            mode = (member.external_attr >> 16) & 0xFFFF
            _require(stat.S_IFMT(mode) in (0, stat.S_IFREG) and not member.is_dir()
                     and not (member.external_attr & 0x410) and not member.flag_bits & 1
                     and member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                     "Links, directories, encrypted or special archive files are forbidden.")
            entry = expected[name]
            _require(member.file_size == entry["size"], "UI archive size differs from manifest.")
            count = 0
            digest = hashlib.sha256()
            with payload.open(member) as source, open(Path(directory) / name, "xb") as output:
                while True:
                    chunk = source.read(min(1024 * 1024, entry["size"] - count + 1))
                    if not chunk:
                        break
                    count += len(chunk)
                    _require(count <= entry["size"], "UI file exceeds its declared size.")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            _require(count == entry["size"] and digest.hexdigest() == entry["sha256"],
                     f"UI file verification failed: {name}")


def _plain_path(path):
    """Reject symlinks/junctions in every existing ancestor without resolving them."""
    path = Path(os.path.abspath(path))
    _require(not str(path).startswith(("\\\\", "//")), "Use a local EverQuest/state directory, not a network path.")
    for part in reversed((path,) + tuple(path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & 0x400,
                 f"Links and junctions are not supported: {part}")
    return path


def _target(eq_dir, create=False):
    game = _plain_path(eq_dir)
    _require(game.is_dir() and (game / "eqgame.exe").is_file()
             and (game / "uifiles").is_dir(), "Select the EverQuest folder containing eqgame.exe and uifiles.")
    _plain_path(game / "eqgame.exe")
    target = _plain_path(game / "uifiles" / SKIN_FOLDER)
    if create and not target.exists():
        target.mkdir()
    if target.exists():
        _require(target.is_dir(), "The UI skin target is not a directory.")
        names = set()
        for entry in target.iterdir():
            _plain_path(entry)
            key = entry.name.casefold()
            _require(key not in names, "Case-duplicate files exist in the installed skin.")
            names.add(key)
    return game, target


def _state_directory(game, target, state_dir):
    state = _plain_path(state_dir)
    _require(state != game and game not in state.parents,
             "Updater backups must be stored outside the EverQuest folder.")
    state.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(str(target)).encode("utf-8")).hexdigest()[:24]
    state = _plain_path(state / key)
    state.mkdir(exist_ok=True)
    _check_recovery_marker(target, state)
    return state


def _check_recovery_marker(target, state):
    marker = _plain_path(target / RECOVERY_MARKER)
    if marker.exists():
        pending = _json(_read_file(marker, 16 * 1024))
        _require(isinstance(pending, dict) and pending.get("state") == str(state)
                 and isinstance(pending.get("transaction"), str)
                 and re.fullmatch(r"[a-f0-9]{32}", pending["transaction"]),
                 "This skin has a pending transaction from another updater state directory. "
                 "Open the original updater/profile to recover it before installing again.")
        return pending
    return None


def game_running():
    """Read-only Windows process snapshot; a failed probe refuses installation."""
    if os.name != "nt":
        return False
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    _require(handle not in (None, ctypes.c_void_p(-1).value), "Cannot safely check whether EverQuest is running.")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        _require(bool(kernel.Process32FirstW(handle, ctypes.byref(entry))), "Cannot read the Windows process list.")
        while True:
            if entry.szExeFile.casefold() == "eqgame.exe":
                return True
            if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                _require(ctypes.get_last_error() == 18, "Cannot finish checking the Windows process list.")
                break
        return False
    finally:
        kernel.CloseHandle(handle)


def _require_game_closed():
    _require(not game_running(), "Close EverQuest before updating or restoring its UI. Nothing was stopped.")


def _require_install_policy(allow_game_running=False):
    if not allow_game_running:
        _require_game_closed()


@contextmanager
def _target_lock(target):
    path = _plain_path(target / LOCK_NAME)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    locked = False
    try:
        lock_info = os.fstat(descriptor)
        _require(stat.S_ISREG(lock_info.st_mode) and lock_info.st_nlink == 1,
                 "Invalid or hard-linked UI updater lock file.")
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise SkinUpdateError("Another UI updater is already installing this skin.") from error
        else:
            import fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise SkinUpdateError("Another UI updater is already installing this skin.") from error
        locked = True
        yield
    finally:
        if locked and os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def _read_file(path, maximum=MAX_FILE_BYTES):
    _plain_path(path)
    _require(path.is_file() and path.stat().st_size <= maximum, f"Unsafe or oversized file: {path.name}")
    with open(path, "rb") as source:
        data = source.read(maximum + 1)
    _require(len(data) <= maximum, "File grew beyond its safety limit.")
    return data


def _current_hash(path):
    _plain_path(path)
    return _digest(_read_file(path)) if path.exists() else None


def _atomic_bytes(path, data, before_replace=None):
    """Same-directory replace, with durable content; no cross-volume rename."""
    _plain_path(path)
    temporary = path.parent / (".vantage-ui-stage-" + uuid.uuid4().hex)
    try:
        with open(temporary, "xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        _plain_path(path)
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary.exists():
            _plain_path(temporary)
            temporary.unlink()


def _write_json(path, value):
    _atomic_bytes(path, json.dumps(value, sort_keys=True, indent=2).encode("utf-8"))


def _load_journal(path, target, state):
    journal = _json(_read_file(path, 2 * 1024 * 1024))
    _require(isinstance(journal, dict) and journal.get("schema") == 1
             and journal.get("target") == str(target)
             and isinstance(journal.get("transaction"), str)
             and re.fullmatch(r"[a-f0-9]{32}", journal["transaction"]), "Invalid UI recovery journal. Manual review is required.")
    entries = journal.get("entries")
    _require(isinstance(entries, list) and 0 < len(entries) <= MAX_FILES + 1, "Invalid UI recovery file list.")
    seen = set()
    backup = _plain_path(state / journal["transaction"])
    _require(backup.is_dir(), "UI recovery backups are missing.")
    total = 0
    for index, entry in enumerate(entries):
        _require(isinstance(entry, dict), "Invalid UI recovery entry.")
        name = _safe_name(entry.get("path"), metadata=True)
        _require(name.casefold() not in seen and _valid_hash(entry.get("new"))
                 and (entry.get("old") is None or _valid_hash(entry["old"])), "Invalid UI recovery hashes.")
        seen.add(name.casefold())
        if entry["old"] is not None:
            data = _read_file(backup / f"{index:04d}.bin")
            total += len(data)
            _require(total <= MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES, "UI recovery backups exceed their safety limit.")
            _require(_digest(data) == entry["old"], "UI recovery backup verification failed.")
    return journal


def _restore(journal, target, state, log, strict=False,
             allow_game_running=False, progress=None):
    """Preflight every hash before restoring; never overwrite new user edits."""
    for entry in journal["entries"]:
        current = _current_hash(target / entry["path"])
        accepted = (entry["new"],) if strict else (entry["old"], entry["new"])
        _require(current in accepted, f"UI file changed since the update: {entry['path']}. Recovery paused to preserve it.")
    backup = state / journal["transaction"]
    count = len(journal["entries"])
    for restored, index in enumerate(reversed(range(count)), 1):
        entry = journal["entries"][index]
        path = target / entry["path"]
        current = _current_hash(path)
        _require(current in (entry["old"], entry["new"]), "UI file changed during recovery; stopping safely.")
        if current == entry["old"]:
            continue
        _require_install_policy(allow_game_running)
        _plain_path(target)
        if entry["old"] is None:
            path.unlink()
        else:
            data = _read_file(backup / f"{index:04d}.bin")
            _require(_digest(data) == entry["old"], "UI recovery backup changed; stopping safely.")
            _atomic_bytes(path, data, before_replace=lambda: _require_install_policy(
                allow_game_running))
        log(f"Restored {entry['path']}")
        _emit_progress(progress, "Restoring previous files",
                       15 + round(75 * restored / max(1, count)))


def _recover_pending(target, state, log, allow_game_running=False,
                     progress=None):
    # This check MUST also run under the target lock: a different updater/profile
    # may have begun a transaction while this instance was downloading its assets.
    pending = _check_recovery_marker(target, state)
    active = _plain_path(state / "active.json")
    if not active.exists():
        if pending:
            last = _plain_path(state / "last.json")
            _require(last.exists() and _load_journal(last, target, state)["transaction"] == pending["transaction"],
                     "The pending UI recovery journal is missing. Preserve this skin and its backups for manual recovery.")
            # Only a matching committed journal proves this marker harmless.
            (target / RECOVERY_MARKER).unlink()
        return False
    journal = _load_journal(active, target, state)
    _require(not pending or pending["transaction"] == journal["transaction"],
             "The UI transaction marker and recovery journal disagree. Manual recovery is required.")
    _require_install_policy(allow_game_running)
    log("Recovering an interrupted UI transaction before continuing.")
    _emit_progress(progress, "Recovering interrupted update", 5)
    _restore(journal, target, state, log,
             allow_game_running=allow_game_running, progress=progress)
    last = _plain_path(state / "last.json")
    if last.exists() and _load_journal(last, target, state)["transaction"] == journal["transaction"]:
        last.unlink()
    marker = _plain_path(target / RECOVERY_MARKER)
    if marker.exists():
        marker.unlink()
    active.unlink()
    return True


def installed_version(eq_dir):
    _, target = _target(eq_dir)
    path = target / VERSION_MARKER
    if not path.exists():
        return ""
    marker = _json(_read_file(path, MAX_MANIFEST_BYTES))
    version = marker.get("version", "") if isinstance(marker, dict) else ""
    _require(isinstance(version, str) and bool(_VERSION.fullmatch(version)), "Invalid installed UI version marker.")
    return version


def recover_pending(eq_dir, state_dir, log=print, allow_game_running=False,
                    progress=None):
    """Call at GUI startup after choosing EQ; no network or payload execution."""
    progress = _monotonic_progress(progress)
    game, target = _target(eq_dir)
    if not target.exists():
        return False
    state = _state_directory(game, target, state_dir)
    with _target_lock(target):
        return _recover_pending(target, state, log,
                                allow_game_running=allow_game_running,
                                progress=progress)


def install_release(release, eq_dir, state_dir, log=print,
                    allow_game_running=False, progress=None):
    progress = _monotonic_progress(progress)
    _validate_release(release)
    _require_install_policy(allow_game_running)
    _emit_progress(progress, "Preparing verified update", 0)
    game, target = _target(eq_dir)
    state = _state_directory(game, target, state_dir)
    # Stage and verify the complete payload outside EQ before creating/mutating its skin.
    with tempfile.TemporaryDirectory(prefix="download-", dir=state) as temporary:
        temporary = Path(temporary)
        manifest_path, payload_path = temporary / "manifest.json", temporary / "payload.zip"
        log(f"Downloading verified Vantage UI {release.version}.")
        manifest_progress = None if progress is None else lambda count, total: _emit_progress(
            progress, "Downloading manifest", 3 + round(12 * count / max(1, total)), count, total)
        _download_asset(release.manifest_url, manifest_path, MAX_MANIFEST_BYTES,
                        release.manifest_sha256, release.manifest_size,
                        manifest_progress)
        _emit_progress(progress, "Verifying manifest", 17)
        entries = validate_manifest(manifest_path.read_bytes(), release.version)
        payload_progress = None if progress is None else lambda count, total: _emit_progress(
            progress, "Downloading VantageUI files", 20 + round(35 * count / max(1, total)), count, total)
        _download_asset(release.payload_url, payload_path, MAX_ARCHIVE_BYTES,
                        release.payload_sha256, release.payload_size,
                        payload_progress)
        _emit_progress(progress, "Verifying downloaded files", 58)
        staging = temporary / "files"
        staging.mkdir()
        stage_archive(payload_path, entries, staging)
        _require_install_policy(allow_game_running)
        _, target = _target(eq_dir, create=True)
        with _target_lock(target):
            _recover_pending(target, state, log,
                             allow_game_running=allow_game_running,
                             progress=progress)
            current_version = installed_version(eq_dir)
            _require(not current_version or tuple(map(int, release.version.split(".")))
                     >= tuple(map(int, current_version.split("."))),
                     "An older release cannot overwrite a newer installed UI. Use Restore previous UI instead.")
            # Keep spelling of existing Windows filenames, but reject aliases elsewhere.
            installed = {entry.name.casefold(): entry.name for entry in target.iterdir()}
            files = [(installed.get(entry["path"].casefold(), entry["path"]),
                      _read_file(staging / entry["path"])) for entry in entries]
            marker = json.dumps({"schema": 1, "version": release.version,
                                 "release_id": release.release_id}, sort_keys=True).encode("utf-8")
            files.append((VERSION_MARKER, marker))
            changes = [(name, data) for name, data in files if _current_hash(target / name) != _digest(data)]
            if not changes:
                _emit_progress(progress, "VantageUI is current", 100)
                return InstallResult(release.version, 0, "already-current")
            transaction = uuid.uuid4().hex
            backup = _plain_path(state / transaction)
            backup.mkdir()
            journal = {"schema": 1, "transaction": transaction, "target": str(target),
                       "version": release.version, "entries": []}
            backup_total = 0
            _emit_progress(progress, "Backing up replaced files", 65)
            for index, (name, data) in enumerate(changes):
                old = _current_hash(target / name)
                if old is not None:
                    original = _read_file(target / name)
                    backup_total += len(original)
                    _require(backup_total <= MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES,
                             "Existing skin files exceed the safe backup size. Nothing has been replaced.")
                    _require(_digest(original) == old, "UI file changed while preparing its backup.")
                    _atomic_bytes(backup / f"{index:04d}.bin", original)
                journal["entries"].append({"path": name, "old": old, "new": _digest(data)})
            active = state / "active.json"
            _write_json(active, journal)
            try:
                _write_json(target / RECOVERY_MARKER,
                            {"state": str(state), "transaction": transaction})
                _emit_progress(progress, "Updating — do not reload the UI yet", 75)
                for changed_index, ((name, data), entry) in enumerate(
                        zip(changes, journal["entries"]), 1):
                    _require_install_policy(allow_game_running)
                    _target(eq_dir)
                    _require(_current_hash(target / name) == entry["old"], "UI file changed before installation; stopping safely.")
                    try:
                        _atomic_bytes(target / name, data,
                                      before_replace=lambda: _require_install_policy(
                                          allow_game_running))
                    except OSError as error:
                        raise SkinUpdateError(
                            f"Windows could not replace {name}: {error}. "
                            "The update did not complete; do not reload the UI yet.") from error
                    log(f"Updated {name}")
                    _emit_progress(progress, "Updating — do not reload the UI yet",
                                   75 + round(20 * changed_index / len(changes)))
                _emit_progress(progress, "Finalizing verified installation", 98)
                _write_json(state / "last.json", journal)
                active.unlink()
            except BaseException:
                # An active game or conflicting file can defer rollback to the next launch.
                try:
                    _restore(journal, target, state, log,
                             allow_game_running=allow_game_running)
                    last_path = state / "last.json"
                    if last_path.exists():
                        last_value = _json(_read_file(last_path, 2 * 1024 * 1024))
                        if isinstance(last_value, dict) and last_value.get("transaction") == transaction:
                            last_path.unlink()
                    marker_path = _plain_path(target / RECOVERY_MARKER)
                    if marker_path.exists():
                        marker_path.unlink()
                    if active.exists():
                        active.unlink()
                except BaseException as recovery_error:
                    log(f"Recovery is pending; do not reload this skin yet: {recovery_error}")
                raise
            # Payload and last.json are committed. A leftover marker is cleared on
            # the next launch; its cleanup failure must never undo a good commit.
            try:
                (target / RECOVERY_MARKER).unlink()
            except OSError:
                log("UI installed. Its completed transaction marker will be cleaned on the next launch.")
            _emit_progress(progress, "Installation complete", 100)
            return InstallResult(release.version, sum(name != VERSION_MARKER for name, _ in changes), "installed")


def rollback_last(eq_dir, state_dir, log=print, progress=None):
    progress = _monotonic_progress(progress)
    _require_game_closed()
    _emit_progress(progress, "Preparing restore", 0)
    game, target = _target(eq_dir)
    _require(target.exists(), "The Vantage UI skin has not been installed.")
    state = _state_directory(game, target, state_dir)
    with _target_lock(target):
        _recover_pending(target, state, log, progress=progress)
        last = _plain_path(state / "last.json")
        _require(last.exists(), "No previous UI installation is available to restore.")
        journal = _load_journal(last, target, state)
        # Check before publishing an active rollback journal; conflicts do not block later installs.
        for entry in journal["entries"]:
            _require(_current_hash(target / entry["path"]) == entry["new"],
                     f"UI file changed since the update: {entry['path']}. Restore would overwrite your edits.")
        _write_json(state / "active.json", journal)
        _write_json(target / RECOVERY_MARKER,
                    {"state": str(state), "transaction": journal["transaction"]})
        _restore(journal, target, state, log, strict=True, progress=progress)
        last.unlink()
        (target / RECOVERY_MARKER).unlink()
        (state / "active.json").unlink()
        result = InstallResult(installed_version(eq_dir),
                             sum(entry["path"] != VERSION_MARKER for entry in journal["entries"]), "restored")
        _emit_progress(progress, "Restore complete", 100)
        return result
