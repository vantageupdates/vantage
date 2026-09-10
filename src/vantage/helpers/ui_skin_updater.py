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
REGISTRY_NAME = ".vantage-ui-registry.json"
_STAGE = re.compile(r"\.vantage-ui-publish-[a-f0-9]{32}\Z")
_QUARANTINE = re.compile(r"\.vantage-ui-retired-[a-f0-9]{32}\Z")
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
    folder: str = ""
    warnings: tuple[str, ...] = ()


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
    if isinstance(tag, str) and tag.startswith("vantage-ui-v"):
        version = tag[len("vantage-ui-v"):]
    else:
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
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        return False
    names = {MANIFEST_ASSET.casefold(), PAYLOAD_ASSET.casefold()}
    return any(isinstance(asset, dict) and str(asset.get("name", "")).casefold() in names
               for asset in payload["assets"])


def select_release_history(payload):
    """Purely select the newest verified UI release from bounded history.

    A release containing either UI asset is never silently skipped if malformed.
    Legacy v<semver> asset releases and vantage-ui-v<semver> are recognized.
    """
    _require(isinstance(payload, list) and len(payload) <= 40,
             "Invalid bounded GitHub release history response.")
    candidates = []
    for candidate in payload:
        _require(isinstance(candidate, dict),
                 "Invalid GitHub release history entry.")
        if candidate.get("draft") is True or candidate.get("prerelease") is True:
            continue
        tag = candidate.get("tag_name", "")
        namespaced = (
            isinstance(tag, str) and tag.startswith("vantage-ui-v"))
        if namespaced or _has_ui_assets(candidate):
            # Parse every recognized candidate now. A broken newest or older
            # UI publication is never silently treated as valid.
            candidates.append(parse_release_payload(candidate))
    if candidates:
        return max(
            candidates,
            key=lambda release: tuple(map(int, release.version.split("."))))
    raise SkinUpdateError(
        "No stable Vantage UI release was found in the latest 40 releases.")


def check_release(progress=None):
    """Fetch one bounded release history and select its verified UI release."""
    progress = _monotonic_progress(progress)
    with tempfile.TemporaryDirectory(prefix="vantage-ui-check-") as directory:
        _emit_progress(progress, "Checking release", 0)
        history_path = Path(directory) / "releases.json"
        url = f"{RELEASES_API}?per_page=40&page=1"
        if progress is None:
            _download(url, history_path, 4 * 1024 * 1024)
        else:
            _download(
                url, history_path, 4 * 1024 * 1024,
                progress=lambda count, total: _emit_progress(
                    progress, "Searching verified UI releases", 5 if not total
                    else 5 + round(85 * count / total), count, total))
        result = select_release_history(_json(history_path.read_bytes()))
        _emit_progress(progress, "Release verified", 100)
        return result


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


def folder_name(version):
    """Canonical, case-sensitive folder for a strict numeric UI version."""
    _require(isinstance(version, str) and bool(_VERSION.fullmatch(version)),
             "Invalid Vantage UI folder version.")
    return f"{SKIN_FOLDER}-v{version}"


def _folder_version(name):
    prefix = SKIN_FOLDER + "-v"
    version = name[len(prefix):] if isinstance(name, str) and name.startswith(prefix) else ""
    _require(folder_name(version) == name, "Invalid managed Vantage UI folder name.")
    return version


def validate_manifest(data, version):
    folder_name(version)
    _require(len(data) <= MAX_MANIFEST_BYTES, "UI manifest is too large.")
    manifest = _json(data)
    _require(isinstance(manifest, dict) and type(manifest.get("schema")) is int
             and ((manifest["schema"] == 1 and manifest.get("skin_folder") == SKIN_FOLDER)
                  or (manifest["schema"] == 2 and manifest.get("skin_folder") == folder_name(version)))
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
    """The shared namespace is uifiles; never create or modify legacy VantageUI."""
    game = _plain_path(eq_dir)
    _require(game.is_dir() and (game / "eqgame.exe").is_file()
             and (game / "uifiles").is_dir(),
             "Select the EverQuest folder containing eqgame.exe and uifiles.")
    _plain_path(game / "eqgame.exe")
    target = _plain_path(game / "uifiles")
    _exact_child(target, LOCK_NAME)
    _exact_child(target, REGISTRY_NAME)
    return game, target


def _exact_child(parent, name):
    """Reject Windows case aliases even when tests run on a case-sensitive host."""
    matches = [entry.name for entry in parent.iterdir()
               if entry.name.casefold() == name.casefold()]
    _require(not matches or matches == [name], f"Case-alias collision: {name}.")
    return _plain_path(parent / name)


def _state_directory(game, target, state_dir):
    state = _plain_path(state_dir)
    _require(state != game and game not in state.parents,
             "Updater downloads must be stored outside the EverQuest folder.")
    state.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(str(target)).encode("utf-8")).hexdigest()[:24]
    state = _plain_path(state / key)
    state.mkdir(exist_ok=True)
    return state


def _legacy_notice(target, log):
    # Legacy recovery journals refer to in-place edits. Never resume or erase them
    # from the new updater: this also avoids accessing paths from untrusted JSON.
    legacy = target / SKIN_FOLDER
    if os.path.lexists(legacy):
        log("Legacy VantageUI is preserved; its version and in-game selection are unknown.")
        if os.path.lexists(legacy / RECOVERY_MARKER):
            log("Legacy VantageUI has an old recovery marker. Preserve its original "
                "backups and use the original updater for manual recovery. "
                "The versioned updater does not change that folder.")


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


def _write_new_bytes(path, data):
    """A fresh stage never overwrites a file added by another process."""
    _plain_path(path)
    with open(path, "xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


@contextmanager
def _directory_guard(path, deleting=False):
    """On Windows, hold ancestors open without delete sharing during mutations.

    This prevents replacing uifiles or its parents with a junction while a
    checked path is being used. Managed files receive their own handle checks.
    """
    path = _plain_path(path)
    handles = []
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            for part in reversed((path,) + tuple(path.parents)):
                before = part.lstat()
                access = 0x80 | (0x10000 if deleting and part == path else 0)
                handle = kernel.CreateFileW(str(part), access, 3, None, 3,
                                            0x02000000 | 0x00200000, None)
                if handle in (None, ctypes.c_void_p(-1).value):
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
                _plain_path(part)
                after = part.lstat()
                _require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
                         and stat.S_ISDIR(after.st_mode), "UI directory changed during access.")
            yield handles[-1]
        finally:
            for handle in reversed(handles):
                kernel.CloseHandle(handle)
    else:
        yield None


@contextmanager
def _file_source(path, deleting=False):
    """Open the exact regular file; Windows denies concurrent writes/replacement."""
    path = _plain_path(path)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
             f"Unsafe or hard-linked file: {path.name}")
    if os.name == "nt":
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0x80000000 | (0x10000 if deleting else 0),
                                    1, None, 3, 0x00200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    else:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        current = os.fstat(source.fileno())
        _require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                 and (before.st_dev, before.st_ino) == (current.st_dev, current.st_ino),
                 f"UI file changed during access: {path.name}")
        _plain_path(path)
        yield source
        if not deleting:
            after = path.lstat()
            _require((after.st_dev, after.st_ino) == (current.st_dev, current.st_ino)
                     and after.st_nlink == 1, f"UI file changed during access: {path.name}")


def _read_file(path, maximum=MAX_FILE_BYTES):
    with _file_source(Path(path)) as source:
        _require(os.fstat(source.fileno()).st_size <= maximum,
                 f"Unsafe or oversized file: {Path(path).name}")
        data = source.read(maximum + 1)
    _require(len(data) <= maximum, "File grew beyond its safety limit.")
    return data


def _directory_id(path):
    path = _plain_path(path)
    info = path.lstat()
    _require(stat.S_ISDIR(info.st_mode), "Managed UI folder is not a regular directory.")
    return [info.st_dev, info.st_ino]


def _empty_registry():
    return {"schema": 2, "revision": 0, "active": "", "previous": "",
            "managed": {}, "pending": None}


def _validate_record(name, record):
    version = _folder_version(name)
    _require(isinstance(record, dict) and set(record) ==
             {"version", "marker_sha256", "directory_id", "quarantine"}
             and record["version"] == version and _valid_hash(record["marker_sha256"])
             and isinstance(record["directory_id"], list)
             and len(record["directory_id"]) == 2
             and all(type(value) is int and value >= 0 for value in record["directory_id"])
             and record["directory_id"][1] != 0
             and isinstance(record["quarantine"], str)
             and (not record["quarantine"] or _QUARANTINE.fullmatch(record["quarantine"])),
             "Invalid managed UI registration. Preserve folders for manual review.")


def _validate_registry(value):
    _require(isinstance(value, dict) and set(value) ==
             {"schema", "revision", "active", "previous", "managed", "pending"}
             and type(value["schema"]) is int and value["schema"] == 2
             and type(value["revision"]) is int and value["revision"] >= 0
             and isinstance(value["managed"], dict) and len(value["managed"]) <= 1000,
             "Invalid shared UI registry. Preserve folders for manual review.")
    for name, record in value["managed"].items():
        _validate_record(name, record)
    for key in ("active", "previous"):
        name = value[key]
        _require(isinstance(name, str) and (not name or name in value["managed"]),
                 "Invalid selected UI folder.")
        if name:
            _require(not value["managed"][name]["quarantine"],
                     "Selected UI folder is unexpectedly quarantined.")
    _require(not value["active"] or value["active"] != value["previous"],
             "Active and previous UI folders must be distinct.")
    _require(not value["managed"] or value["active"],
             "Registered UI folders require a selected active folder.")
    pending = value["pending"]
    if pending is not None:
        _require(isinstance(pending, dict) and set(pending) == {"folder", "stage", "record"}
                 and isinstance(pending["stage"], str) and _STAGE.fullmatch(pending["stage"])
                 and isinstance(pending["folder"], str)
                 and pending["folder"] not in value["managed"],
                 "Invalid shared UI publication journal.")
        _validate_record(pending["folder"], pending["record"])
        _require(not pending["record"]["quarantine"], "Invalid pending UI folder.")
    return value


def _registry(target):
    path = _exact_child(target, REGISTRY_NAME)
    if not path.exists():
        return _empty_registry(), None
    data = _read_file(path, MAX_MANIFEST_BYTES)
    return _validate_registry(_json(data)), data


def _registry_unchanged(target, expected):
    path = _exact_child(target, REGISTRY_NAME)
    current = _read_file(path, MAX_MANIFEST_BYTES) if path.exists() else None
    _require(current == expected, "The shared UI registry changed concurrently; stopping safely.")


def _save_registry(target, registry, expected):
    registry["revision"] += 1
    _validate_registry(registry)
    data = json.dumps(registry, sort_keys=True, indent=2).encode("utf-8")
    _require(len(data) <= MAX_MANIFEST_BYTES, "The shared UI registry is full; manual review is required.")
    _atomic_bytes(_exact_child(target, REGISTRY_NAME), data,
                  before_replace=lambda: _registry_unchanged(target, expected))
    return data


def _trusted_marker(path, folder, record):
    """Trust the selected folder's identity, without claiming pristine payloads."""
    _validate_record(folder, record)
    _require(_directory_id(path) == record["directory_id"],
             f"Managed folder identity changed: {folder}.")
    with _directory_guard(path):
        marker_path = _exact_child(path, VERSION_MARKER)
        marker_data = _read_file(marker_path, MAX_MANIFEST_BYTES)
        _require(_digest(marker_data) == record["marker_sha256"],
                 f"Managed marker changed: {folder}.")
        marker = _json(marker_data)
        _require(isinstance(marker, dict) and marker.get("schema") == 2
                 and marker.get("folder") == folder
                 and marker.get("version") == record["version"]
                 and type(marker.get("release_id")) is int and marker["release_id"] > 0
                 and _valid_hash(marker.get("manifest_sha256"))
                 and _valid_hash(marker.get("payload_sha256")),
                 f"Invalid managed marker: {folder}.")
        validate_manifest(json.dumps({
            "schema": 2, "skin_folder": folder, "version": record["version"],
            "files": marker.get("files")}).encode(), record["version"])
        seen = set()
        for child in path.iterdir():
            _plain_path(child)
            info = child.lstat()
            _require((stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
                     or stat.S_ISDIR(info.st_mode),
                     f"Unsafe or hard-linked path in selected folder: {folder}/{child.name}")
            _require(child.name.casefold() not in seen,
                     f"Case-alias collision in selected folder: {folder}.")
            seen.add(child.name.casefold())
        _require(_directory_id(path) == record["directory_id"]
                 and _read_file(marker_path, MAX_MANIFEST_BYTES) == marker_data,
                 f"Managed UI metadata changed during verification: {folder}.")
        return marker


def _verified_tree(path, folder, record):
    """Require exact flat bytes and directory identity, including the full marker."""
    with _directory_guard(path):
        marker = _trusted_marker(path, folder, record)
        expected = {entry["path"]: entry for entry in marker["files"]}
        names = [entry.name for entry in path.iterdir()]
        _require(len(names) == len(expected) + 1
                 and set(names) == set(expected) | {VERSION_MARKER},
                 f"Extra, missing or renamed files in {folder}; preserving it.")
        files = {}
        for name, entry in expected.items():
            data = _read_file(path / name)
            _require(len(data) == entry["size"] and _digest(data) == entry["sha256"],
                     f"UI file changed: {folder}/{name}; preserving it.")
            files[name] = entry["sha256"]
        _require(_directory_id(path) == record["directory_id"]
                 and _digest(_read_file(path / VERSION_MARKER, MAX_MANIFEST_BYTES))
                     == record["marker_sha256"]
                 and {entry.name for entry in path.iterdir()} == set(names),
                 f"Managed UI folder changed during verification: {folder}.")
        files[VERSION_MARKER] = record["marker_sha256"]
        return marker, files


def _rename_no_replace(source, destination):
    _plain_path(source)
    _exact_child(destination.parent, destination.name)
    _require(not os.path.lexists(destination), f"UI folder collision: {destination.name}; preserved.")
    if os.name == "nt":
        # MoveFile semantics used by os.rename on Windows never replace a target.
        os.rename(source, destination)
    else:
        # Linux's no-replace rename also keeps empty collision folders untouched.
        kernel = ctypes.CDLL(None, use_errno=True)
        rename = getattr(kernel, "renameat2", None)
        _require(rename is not None, "Atomic no-replace folder publication is unavailable on this host.")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
            raise OSError(ctypes.get_errno(), "Could not publish UI folder without replacement")


def _sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _selected_trusted(target, registry):
    name = registry["active"]
    if name:
        _trusted_marker(_exact_child(target, name), name, registry["managed"][name])
    return name


def _selection_warnings(target, registry, name, log):
    if name:
        try:
            _verified_tree(_exact_child(target, name), name, registry["managed"][name])
        except (SkinUpdateError, OSError) as error:
            message = f"Preserved local changes in {name}; its files will not be overwritten: {error}"
            log(message)
            return (message,)
    return ()


def installed_folder(eq_dir):
    """Return the updater-selected folder, not the skin actually loaded by EQ."""
    _, target = _target(eq_dir)
    with _directory_guard(target):
        registry, snapshot = _registry(target)
        name = _selected_trusted(target, registry)
        _registry_unchanged(target, snapshot)
        return name


def installed_version(eq_dir):
    name = installed_folder(eq_dir)
    return _folder_version(name) if name else ""


def loadskin_command(eq_dir):
    name = installed_folder(eq_dir)
    return f"/loadskin {name} 1" if name else ""


def _finish_pending(target, registry, snapshot, log, allow_game_running=False,
                    progress=None):
    pending = registry["pending"]
    if pending is None:
        return registry, snapshot, False
    _require_install_policy(allow_game_running)
    name, record = pending["folder"], pending["record"]
    stage = _exact_child(target, pending["stage"])
    destination = _exact_child(target, name)
    stage_exists = os.path.lexists(stage)
    destination_exists = os.path.lexists(destination)
    _require(not (stage_exists and destination_exists),
             f"Interrupted publication has a folder collision: {name}. Both folders are preserved.")
    if not stage_exists and not destination_exists:
        log("Interrupted preparation left no UI folder; the previous selection is preserved.")
        registry["pending"] = None
        return registry, _save_registry(target, registry, snapshot), True
    if stage_exists:
        try:
            _verified_tree(stage, name, record)
        except (SkinUpdateError, OSError) as error:
            # Never recursively clean an incomplete or changed stage. Remove only
            # the pending pointer so a later update can proceed in a fresh folder.
            log(f"Incomplete staging folder preserved at {stage}: {error}")
            registry["pending"] = None
            return registry, _save_registry(target, registry, snapshot), True
        _registry_unchanged(target, snapshot)
        _require_install_policy(allow_game_running)
        _rename_no_replace(stage, destination)
        _sync_directory(target)
    _verified_tree(destination, name, record)
    old = _selected_trusted(target, registry)
    _selection_warnings(target, registry, old, log)
    _registry_unchanged(target, snapshot)
    registry["managed"][name] = record
    registry["previous"] = old
    registry["active"] = name
    registry["pending"] = None
    _require_install_policy(allow_game_running)
    snapshot = _save_registry(target, registry, snapshot)
    log(f"Selected {name}. In EverQuest, use /loadskin {name} 1.")
    _emit_progress(progress, "Verified folder selected", 98)
    return registry, snapshot, True


def _delete_verified_file(path, expected_hash):
    """Delete the exact reverified file, never a path that was swapped in."""
    with _file_source(path, deleting=True) as source:
        data = source.read(MAX_FILE_BYTES + 1)
        _require(len(data) <= MAX_FILE_BYTES and _digest(data) == expected_hash,
                 f"File changed before cleanup: {path.name}; preserving it.")
        info = os.fstat(source.fileno())
        current = path.lstat()
        _require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)
                 and current.st_nlink == 1, "File identity changed before cleanup.")
        if os.name == "nt":
            import msvcrt
            _delete_on_close(msvcrt.get_osfhandle(source.fileno()), path.name)
        else:
            # The containing directory is a private, verified quarantine; check
            # the open inode immediately before this single-file operation.
            path.unlink()


def _delete_on_close(handle, name):
    from ctypes import wintypes
    class Disposition(ctypes.Structure):
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    disposition = Disposition(True)
    _require(bool(kernel.SetFileInformationByHandle(
        handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition))),
        f"Windows could not retire {name}.")


def _delete_empty_directory(path, expected_id, before_delete):
    with _directory_guard(path, deleting=True) as handle:
        _require(_directory_id(path) == expected_id and not list(path.iterdir()),
                 "Retired UI folder changed or is no longer empty; preserving it.")
        before_delete()
        if os.name == "nt":
            _delete_on_close(handle, path.name)
        else:
            path.rmdir()


def _retained_folders(registry):
    """Keep exactly the selected release and its one rollback target.

    Only names already present in the verified shared registry qualify. The
    filesystem is never enumerated here, so unmanaged skins and personal UI
    folders cannot be mistaken for an obsolete managed version.
    """
    return {
        name for name in (registry["active"], registry["previous"])
        if name}


def _prune(target, registry, snapshot, log):
    """Best effort after commit. Only registered, exact older folders qualify."""
    warnings = []
    def warn(message):
        warnings.append(message)
        log(message)
    try:
        if game_running():
            warn("Older managed UI folder cleanup is deferred while EverQuest is running.")
            return registry, snapshot, tuple(warnings)
    except Exception as error:
        warn(f"UI installed; cleanup deferred because the game state is unknown: {error}")
        return registry, snapshot, tuple(warnings)
    keep = _retained_folders(registry)
    for name in list(registry["managed"]):
        if name in keep:
            continue
        record = registry["managed"][name]
        try:
            _registry_unchanged(target, snapshot)
            _require(not game_running(), "EverQuest opened; cleanup is deferred.")
            original = _exact_child(target, name)
            quarantine = (_exact_child(target, record["quarantine"])
                          if record["quarantine"] else None)
            if quarantine is not None and os.path.lexists(quarantine):
                _require(not os.path.lexists(original),
                         f"Both retired and original folders exist for {name}; preserving both.")
                path = quarantine
            else:
                path = original
            _, hashes = _verified_tree(path, name, record)
            if path == original:
                if quarantine is None:
                    record["quarantine"] = ".vantage-ui-retired-" + uuid.uuid4().hex
                    snapshot = _save_registry(target, registry, snapshot)
                    quarantine = _exact_child(target, record["quarantine"])
                _registry_unchanged(target, snapshot)
                _verified_tree(original, name, record)
                _require(not game_running(), "EverQuest opened; cleanup is deferred.")
                _rename_no_replace(original, quarantine)
                _sync_directory(target)
                path = quarantine
            # Recheck the whole tree after quarantine. A moved replacement, extra
            # file, private edit, hard link, or reparse point is never unlinked.
            with _directory_guard(path):
                _, hashes = _verified_tree(path, name, record)
                remaining = set(hashes)
                for filename in sorted(hashes, key=lambda item: item == VERSION_MARKER):
                    _registry_unchanged(target, snapshot)
                    _require(not game_running(), "EverQuest opened; remaining cleanup is deferred.")
                    _require(_directory_id(path) == record["directory_id"],
                             "Retired UI directory changed; preserving it.")
                    _require({entry.name for entry in path.iterdir()} == remaining,
                             "Retired UI folder contents changed; preserving remaining files.")
                    _delete_verified_file(_exact_child(path, filename), hashes[filename])
                    remaining.remove(filename)
            def before_directory_delete():
                _registry_unchanged(target, snapshot)
                _require(not game_running(), "EverQuest opened; remaining cleanup is deferred.")
            _delete_empty_directory(path, record["directory_id"], before_directory_delete)
            _sync_directory(target)
            del registry["managed"][name]
            snapshot = _save_registry(target, registry, snapshot)
            log(f"Removed unchanged unused managed folder {name}.")
        except Exception as error:
            warn(f"UI selection is saved. Preserved unused folder {name}; cleanup needs review: {error}")
            # A concurrent registry writer invalidates the whole remaining plan.
            try:
                _registry_unchanged(target, snapshot)
            except Exception:
                break
    return registry, snapshot, tuple(warnings)


def recover_pending(eq_dir, state_dir, log=print, allow_game_running=False,
                    progress=None):
    """Recover shared publication from any profile; never replay legacy edits."""
    progress = _monotonic_progress(progress)
    game, target = _target(eq_dir)
    _state_directory(game, target, state_dir)
    _legacy_notice(target, log)
    with _directory_guard(target), _target_lock(target):
        registry, snapshot = _registry(target)
        registry, snapshot, recovered = _finish_pending(
            target, registry, snapshot, log, allow_game_running, progress)
        _, _, warnings = _prune(target, registry, snapshot, log)
        if recovered:
            _emit_progress(progress, "Recovery complete", 100)
        return recovered


def _create_publish_stage(path, *, platform_name=None):
    """Create only a new stage, with the target's normal Windows inheritance.

    Python 3.13 gives Windows mode 0700 a private DACL that survives rename.
    Mode 0777 is ignored there: it inherits the parent's ACL, not world-write
    permissions. POSIX stages remain private. Never repair an existing path.
    """
    platform_name = os.name if platform_name is None else platform_name
    path.mkdir(mode=0o777 if platform_name == "nt" else 0o700)


def install_release(release, eq_dir, state_dir, log=print,
                    allow_game_running=False, progress=None):
    progress = _monotonic_progress(progress)
    _validate_release(release)
    _require_install_policy(allow_game_running)
    _emit_progress(progress, "Preparing verified update", 0)
    game, target = _target(eq_dir)
    state = _state_directory(game, target, state_dir)
    _legacy_notice(target, log)
    name = folder_name(release.version)
    # Verify complete downloads outside EQ, then copy verified bytes to a fresh
    # same-volume staging directory. Existing versioned folders are never written.
    with tempfile.TemporaryDirectory(prefix="download-", dir=state) as temporary:
        temporary = Path(temporary)
        manifest_path, payload_path = temporary / "manifest.json", temporary / "payload.zip"
        log(f"Downloading verified Vantage UI {release.version}.")
        manifest_progress = None if progress is None else lambda count, total: _emit_progress(
            progress, "Downloading manifest", 3 + round(12 * count / max(1, total)), count, total)
        _download_asset(release.manifest_url, manifest_path, MAX_MANIFEST_BYTES,
                        release.manifest_sha256, release.manifest_size, manifest_progress)
        _emit_progress(progress, "Verifying manifest", 17)
        entries = validate_manifest(manifest_path.read_bytes(), release.version)
        payload_progress = None if progress is None else lambda count, total: _emit_progress(
            progress, "Downloading VantageUI files", 20 + round(35 * count / max(1, total)), count, total)
        _download_asset(release.payload_url, payload_path, MAX_ARCHIVE_BYTES,
                        release.payload_sha256, release.payload_size, payload_progress)
        _emit_progress(progress, "Verifying downloaded files", 58)
        staging = temporary / "files"
        staging.mkdir()
        stage_archive(payload_path, entries, staging)
        marker = {"schema": 2, "version": release.version, "folder": name,
                  "release_id": release.release_id,
                  "manifest_sha256": release.manifest_sha256,
                  "payload_sha256": release.payload_sha256, "files": entries}
        marker_data = json.dumps(marker, sort_keys=True, indent=2).encode("utf-8")
        _require(len(marker_data) <= MAX_MANIFEST_BYTES, "Installed UI marker is too large.")
        _require_install_policy(allow_game_running)
        with _directory_guard(target), _target_lock(target):
            registry, snapshot = _registry(target)
            registry, snapshot, _ = _finish_pending(
                target, registry, snapshot, log, allow_game_running, progress)
            current = _selected_trusted(target, registry)
            selection_warnings = _selection_warnings(target, registry, current, log)
            _require(not current or tuple(map(int, release.version.split("."))) >=
                     tuple(map(int, _folder_version(current).split("."))),
                     "An older release cannot replace a newer selected UI. Use Restore previous UI instead.")
            destination = _exact_child(target, name)
            if os.path.lexists(destination):
                record = registry["managed"].get(name)
                _require(record is not None and not record["quarantine"],
                         f"Unmanaged UI folder collision: {name}. The existing folder is preserved.")
                existing, _ = _verified_tree(destination, name, record)
                _require(existing == marker and record["marker_sha256"] == _digest(marker_data),
                         f"The published bytes for {name} differ from its installed release; preserved.")
                if current != name:
                    registry["previous"], registry["active"] = current, name
                    snapshot = _save_registry(target, registry, snapshot)
                registry, snapshot, warnings = _prune(target, registry, snapshot, log)
                _emit_progress(progress, "VantageUI is current", 100)
                return InstallResult(release.version, 0, "already-current", name,
                                     selection_warnings + warnings)
            _require(name not in registry["managed"],
                     f"Registered UI folder {name} is missing or retired; manual review is required.")
            stage_name = ".vantage-ui-publish-" + uuid.uuid4().hex
            publish_stage = _exact_child(target, stage_name)
            _registry_unchanged(target, snapshot)
            _require_install_policy(allow_game_running)
            _create_publish_stage(publish_stage)
            record = {"version": release.version, "marker_sha256": _digest(marker_data),
                      "directory_id": _directory_id(publish_stage), "quarantine": ""}
            registry["pending"] = {"folder": name, "stage": stage_name, "record": record}
            snapshot = _save_registry(target, registry, snapshot)
            _emit_progress(progress, "Preparing new folder — do not reload it yet", 65)
            for index, entry in enumerate(entries, 1):
                _registry_unchanged(target, snapshot)
                _require_install_policy(allow_game_running)
                _require(_directory_id(publish_stage) == record["directory_id"],
                         "UI staging folder changed; stopping safely.")
                data = _read_file(staging / entry["path"])
                _require(len(data) == entry["size"] and _digest(data) == entry["sha256"],
                         "Verified UI staging file changed before publication.")
                with _directory_guard(publish_stage):
                    _require_install_policy(allow_game_running)
                    _write_new_bytes(publish_stage / entry["path"], data)
                _emit_progress(progress, "Preparing new folder — do not reload it yet",
                               65 + round(28 * index / len(entries)))
            with _directory_guard(publish_stage):
                _write_new_bytes(publish_stage / VERSION_MARKER, marker_data)
            registry, snapshot, _ = _finish_pending(
                target, registry, snapshot, log, allow_game_running, progress)
            _require(registry["active"] == name, "New UI folder was preserved for review; installation did not finish.")
            registry, snapshot, warnings = _prune(target, registry, snapshot, log)
            _emit_progress(progress, "Installation complete", 100)
            return InstallResult(release.version, len(entries), "installed", name,
                                 selection_warnings + warnings)


def rollback_last(eq_dir, state_dir, log=print, progress=None):
    """Swap updater selections only; no UI files or INIs are overwritten."""
    progress = _monotonic_progress(progress)
    _require_game_closed()
    _emit_progress(progress, "Preparing restore", 0)
    game, target = _target(eq_dir)
    _state_directory(game, target, state_dir)
    _legacy_notice(target, log)
    with _directory_guard(target), _target_lock(target):
        registry, snapshot = _registry(target)
        registry, snapshot, _ = _finish_pending(target, registry, snapshot, log, progress=progress)
        active = _selected_trusted(target, registry)
        previous = registry["previous"]
        _require(previous, "No previous versioned UI installation is available to restore.")
        _verified_tree(_exact_child(target, previous), previous, registry["managed"][previous])
        _require_game_closed()
        registry["active"], registry["previous"] = previous, active
        snapshot = _save_registry(target, registry, snapshot)
        log(f"Selected {previous}. In EverQuest, use /loadskin {previous} 1.")
        _emit_progress(progress, "Restore complete", 100)
        return InstallResult(_folder_version(previous), 0, "restored", previous)
