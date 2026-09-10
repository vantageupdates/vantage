"""Safe, reversible Project 1999 character UI profile management."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from vantage.helpers.portable import data_dir
from vantage.helpers import ui_skin_updater


_PROFILE_RX = re.compile(
    r"^UI_(?P<character>.+?)_(?P<server>project1999|"
    r"p1999(?:green|blue|pvp|red))\.ini$", re.IGNORECASE)
_BACKUP_ID_RX = re.compile(r"^[0-9a-f]{32}$")
_REQUEST_NAME_RX = re.compile(r"^ui-profile-[0-9a-f]{32}\.json$")
_SKIN_RX = re.compile(r"^VantageUI-v\d+\.\d+\.\d+$")
MAX_PROFILE_BYTES = 4 * 1024 * 1024
MAX_PROFILES = 128


class UIProfileError(ValueError):
    """Raised when a profile operation cannot be completed safely."""


@dataclass(frozen=True)
class CharacterUIProfile:
    filename: str
    character: str
    server: str
    skin: str

    @property
    def label(self):
        server = {
            "p1999green": "Green", "p1999blue": "Blue",
            "p1999pvp": "Red", "p1999red": "Red",
            "project1999": "P99",
        }.get(self.server.casefold(), self.server)
        return f"{self.character} · {server}"


@dataclass(frozen=True)
class ProfileOperationResult:
    action: str
    changed: int
    backup_id: str
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class ProfileBackup:
    backup_id: str
    action: str
    created_utc: str
    label: str
    file_count: int


@dataclass(frozen=True)
class ElevatedUIProfileRequest:
    request_path: Path
    result_path: Path
    nonce: str
    started_at: float


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _validated_eq_root(value):
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise UIProfileError("Choose the EverQuest folder")
    if not (root / "eqgame.exe").is_file():
        raise UIProfileError("The selected folder does not contain eqgame.exe")
    uifiles = root / "uifiles"
    if not uifiles.is_dir() or uifiles.is_symlink():
        raise UIProfileError("The selected folder does not contain uifiles")
    return root


def _read_bytes(path):
    if path.is_symlink() or not path.is_file():
        raise UIProfileError(f"Unsafe or missing UI profile: {path.name}")
    payload = path.read_bytes()
    if len(payload) > MAX_PROFILE_BYTES:
        raise UIProfileError(f"UI profile is too large: {path.name}")
    return payload


def _skin_from_payload(payload):
    try:
        text = payload.decode("cp1252")
    except UnicodeError as error:
        raise UIProfileError("A UI profile could not be decoded") from error
    section = ""
    for row in text.splitlines():
        stripped = row.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().casefold()
        elif section == "main" and stripped.casefold().startswith("uiskin="):
            return stripped.split("=", 1)[1].strip()
    return ""


def _set_skin(payload, skin_folder):
    if not _SKIN_RX.fullmatch(str(skin_folder)):
        raise UIProfileError("Choose a verified versioned VantageUI folder")
    text = payload.decode("cp1252")
    newline = "\r\n" if "\r\n" in text else "\n"
    final_newline = text.endswith(("\r", "\n"))
    rows = text.splitlines()
    main_start = next((
        index for index, row in enumerate(rows)
        if row.strip().casefold() == "[main]"), None)
    if main_start is None:
        rows = ["[Main]", f"UISkin={skin_folder}", *rows]
    else:
        main_end = next((
            index for index in range(main_start + 1, len(rows))
            if rows[index].strip().startswith("[") and
            rows[index].strip().endswith("]")), len(rows))
        skin_index = next((
            index for index in range(main_start + 1, main_end)
            if rows[index].strip().casefold().startswith("uiskin=")), None)
        if skin_index is None:
            rows.insert(main_start + 1, f"UISkin={skin_folder}")
        else:
            rows[skin_index] = f"UISkin={skin_folder}"
    result = newline.join(rows)
    if final_newline:
        result += newline
    return result.encode("cp1252")


def discover_character_profiles(eq_root):
    """Return only ordinary P99 UI_<character>_<server>.ini files."""
    root = _validated_eq_root(eq_root)
    profiles = []
    for path in root.iterdir():
        match = _PROFILE_RX.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            continue
        profiles.append(CharacterUIProfile(
            path.name, match.group("character"), match.group("server"),
            _skin_from_payload(_read_bytes(path))))
        if len(profiles) > MAX_PROFILES:
            raise UIProfileError("Too many character UI profiles were found")
    return tuple(sorted(profiles, key=lambda item: (
        item.character.casefold(), item.server.casefold())))


def _profile_paths(root):
    return {
        profile.filename.casefold(): root / profile.filename
        for profile in discover_character_profiles(root)}


def _selected_skin(root, requested):
    requested = str(requested or "")
    if not _SKIN_RX.fullmatch(requested):
        raise UIProfileError("Choose a verified versioned VantageUI folder")
    selected = ui_skin_updater.installed_folder(root)
    if selected != requested:
        raise UIProfileError(
            "The requested skin is not the verified VantageUI selection")
    target = root / "uifiles" / requested
    if not target.is_dir() or target.is_symlink():
        raise UIProfileError("The selected VantageUI folder is missing")
    return requested


def _validated_state_dir(value):
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise UIProfileError("The profile backup folder is unavailable")
    return path


def _atomic_write(path, payload):
    if path.is_symlink() or not path.is_file():
        raise UIProfileError(f"Unsafe or missing UI profile: {path.name}")
    temporary = path.with_name(f".{path.name}.vantage-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest(directory, manifest):
    payload = (json.dumps(
        manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    temporary = directory / f".manifest-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "manifest.json")
    finally:
        temporary.unlink(missing_ok=True)


def _backup_and_apply(root, state_dir, action, label, updates):
    if not updates:
        raise UIProfileError("No character UI profiles were selected")
    backup_id = uuid.uuid4().hex
    backup_dir = _validated_state_dir(state_dir) / backup_id
    backup_dir.mkdir(mode=0o700)
    entries = []
    originals = {}
    for path, updated in updates:
        if path.parent.resolve(strict=True) != root:
            raise UIProfileError("A UI profile escaped the EverQuest folder")
        original = _read_bytes(path)
        if len(updated) > MAX_PROFILE_BYTES:
            raise UIProfileError(f"Updated UI profile is too large: {path.name}")
        originals[path] = original
        (backup_dir / path.name).write_bytes(original)
        entries.append({
            "name": path.name, "before_sha256": _digest(original),
            "after_sha256": _digest(updated)})
    manifest = {
        "schema": 1, "id": backup_id, "status": "prepared",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "action": action, "label": str(label)[:240],
        "eq_root": str(root), "files": entries}
    _write_manifest(backup_dir, manifest)
    changed = []
    try:
        for path, updated in updates:
            _atomic_write(path, updated)
            changed.append(path)
    except Exception:
        for path in reversed(changed):
            _atomic_write(path, originals[path])
        manifest["status"] = "rolled-back"
        _write_manifest(backup_dir, manifest)
        raise
    manifest["status"] = "committed"
    _write_manifest(backup_dir, manifest)
    return ProfileOperationResult(
        action, len(changed), backup_id,
        tuple(path.name for path in changed))


def apply_skin_to_all(
        eq_root, skin_folder, state_dir, *, include_eqclient=True,
        allow_no_changes=False):
    """Set only UISkin for every P99 character UI profile, with one backup."""
    if ui_skin_updater.game_running():
        raise UIProfileError("Close EverQuest before changing character UI files")
    root = _validated_eq_root(eq_root)
    skin_folder = _selected_skin(root, skin_folder)
    updates = []
    for profile in discover_character_profiles(root):
        path = root / profile.filename
        original = _read_bytes(path)
        updated = _set_skin(original, skin_folder)
        if updated != original:
            updates.append((path, updated))
    if include_eqclient:
        eqclient = root / "eqclient.ini"
        if eqclient.is_file() and not eqclient.is_symlink():
            original = _read_bytes(eqclient)
            updated = _set_skin(original, skin_folder)
            if updated != original:
                updates.append((eqclient, updated))
    if not updates and allow_no_changes:
        return ProfileOperationResult("skin", 0, "", ())
    if not updates:
        raise UIProfileError("Every detected character already uses this VantageUI")
    return _backup_and_apply(
        root, state_dir, "skin", f"Apply {skin_folder} to all characters",
        updates)


def copy_layout(eq_root, skin_folder, source_filename, target_filenames,
                state_dir):
    """Copy one complete UI layout to selected P99 targets, never hotkey INIs."""
    if ui_skin_updater.game_running():
        raise UIProfileError("Close EverQuest before copying character layouts")
    root = _validated_eq_root(eq_root)
    skin_folder = _selected_skin(root, skin_folder)
    paths = _profile_paths(root)
    source = paths.get(str(source_filename).casefold())
    if source is None:
        raise UIProfileError("Choose a valid source character layout")
    source_payload = _set_skin(_read_bytes(source), skin_folder)
    targets = []
    seen = set()
    for filename in target_filenames or ():
        folded = str(filename).casefold()
        target = paths.get(folded)
        if target is None or target == source or folded in seen:
            continue
        seen.add(folded)
        targets.append(target)
    if not targets:
        raise UIProfileError("Choose at least one other character")
    updates = [(target, source_payload) for target in targets]
    return _backup_and_apply(
        root, state_dir, "layout", f"Copy layout from {source.name}", updates)


def _load_manifest(state_dir, backup_id):
    if not _BACKUP_ID_RX.fullmatch(str(backup_id or "")):
        raise UIProfileError("Choose a valid Vantage UI backup")
    state = _validated_state_dir(state_dir)
    directory = state / str(backup_id)
    if directory.is_symlink() or not directory.is_dir() or directory.parent != state:
        raise UIProfileError("The selected UI backup is missing")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise UIProfileError("The selected UI backup is incomplete")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UIProfileError("The selected UI backup is unreadable") from error
    if (manifest.get("schema") != 1 or manifest.get("id") != backup_id or
            manifest.get("status") != "committed" or
            not isinstance(manifest.get("files"), list)):
        raise UIProfileError("The selected UI backup is not restorable")
    return directory, manifest


def list_backups(state_dir, eq_root=None):
    state = _validated_state_dir(state_dir)
    expected_root = str(_validated_eq_root(eq_root)) if eq_root else ""
    backups = []
    for directory in state.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not \
                _BACKUP_ID_RX.fullmatch(directory.name):
            continue
        try:
            _unused, manifest = _load_manifest(state, directory.name)
        except UIProfileError:
            continue
        if expected_root and manifest.get("eq_root") != expected_root:
            continue
        backups.append(ProfileBackup(
            directory.name, str(manifest.get("action") or "backup"),
            str(manifest.get("created_utc") or ""),
            str(manifest.get("label") or "UI backup"),
            len(manifest["files"])))
    return tuple(sorted(backups, key=lambda item: item.created_utc, reverse=True))


def restore_backup(eq_root, state_dir, backup_id):
    """Restore a committed batch and first back up the current target files."""
    if ui_skin_updater.game_running():
        raise UIProfileError("Close EverQuest before restoring character UI files")
    root = _validated_eq_root(eq_root)
    directory, manifest = _load_manifest(state_dir, backup_id)
    if manifest.get("eq_root") != str(root):
        raise UIProfileError("This backup belongs to a different EverQuest folder")
    updates = []
    for entry in manifest["files"]:
        name = str(entry.get("name") or "")
        if name != Path(name).name or not (
                _PROFILE_RX.fullmatch(name) or name.casefold() == "eqclient.ini"):
            raise UIProfileError("The selected backup contains an unsafe filename")
        backup_file = directory / name
        payload = _read_bytes(backup_file)
        if _digest(payload) != entry.get("before_sha256"):
            raise UIProfileError(f"Backup verification failed: {name}")
        target = root / name
        _read_bytes(target)
        updates.append((target, payload))
    return _backup_and_apply(
        root, state_dir, "restore",
        f"Restore {manifest.get('label') or backup_id}", updates)


def elevated_profile_command(request_path, nonce, *, current_executable=None,
                             frozen=None, source_script=None):
    current = Path(current_executable or sys.executable).resolve()
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    arguments = [
        "--manage-ui-profiles", str(Path(request_path).resolve()), str(nonce)]
    if is_frozen and current.is_file():
        return str(current), subprocess.list2cmdline(arguments)
    source = (Path(source_script) if source_script is not None else
              Path(__file__).resolve().parents[3] / "vantage_app.py")
    if source.is_file():
        return sys.executable, subprocess.list2cmdline([str(source), *arguments])
    return None


def request_elevated_profile_action(action, eq_root, **options):
    if os.name != "nt":
        return None
    _validated_eq_root(eq_root)
    request_dir = data_dir("ui-profile-requests")
    request_dir.mkdir(parents=True, exist_ok=True)
    request_id, nonce = uuid.uuid4().hex, uuid.uuid4().hex
    request_path = request_dir / f"ui-profile-{request_id}.json"
    result_path = request_path.with_suffix(".result.json")
    payload = {
        "schema": 1, "nonce": nonce, "action": str(action),
        "eq_root": str(_validated_eq_root(eq_root)), "options": options}
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    command = elevated_profile_command(request_path, nonce)
    if command is None:
        request_path.unlink(missing_ok=True)
        return None
    program, arguments = command
    try:
        launched = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", program, arguments, None, 0)
    except (AttributeError, OSError):
        launched = 0
    if int(launched) <= 32:
        request_path.unlink(missing_ok=True)
        return None
    return ElevatedUIProfileRequest(
        request_path, result_path, nonce, time.monotonic())


def process_elevated_profile_request(request_path, nonce):
    original = Path(request_path).expanduser()
    if original.is_symlink():
        return 2
    request = original.resolve(strict=True)
    if (request.parent.name.casefold() != "ui-profile-requests" or
            not _REQUEST_NAME_RX.fullmatch(request.name)):
        return 2
    result_path = request.with_suffix(".result.json")
    result = {"ok": False, "nonce": str(nonce), "error": "Invalid request"}
    exit_code = 1
    try:
        if request.stat().st_size > 64 * 1024:
            raise UIProfileError("UI profile request is too large")
        payload = json.loads(request.read_text(encoding="utf-8"))
        if payload.get("schema") != 1 or payload.get("nonce") != nonce:
            raise UIProfileError("UI profile request verification failed")
        options = payload.get("options")
        if not isinstance(options, dict):
            raise UIProfileError("UI profile request options are invalid")
        action = payload.get("action")
        root = payload.get("eq_root", "")
        state = data_dir("ui-profile-backups")
        if action == "skin":
            operation = apply_skin_to_all(
                root, options.get("skin_folder", ""), state,
                include_eqclient=bool(options.get("include_eqclient", True)))
        elif action == "layout":
            targets = options.get("targets")
            if not isinstance(targets, list) or len(targets) > MAX_PROFILES:
                raise UIProfileError("UI profile targets are invalid")
            operation = copy_layout(
                root, options.get("skin_folder", ""),
                options.get("source", ""), targets, state)
        elif action == "restore":
            operation = restore_backup(
                root, state, options.get("backup_id", ""))
        else:
            raise UIProfileError("Unknown UI profile action")
        result = {
            "ok": True, "nonce": nonce, "action": operation.action,
            "changed": operation.changed, "backup_id": operation.backup_id,
            "filenames": list(operation.filenames)}
        exit_code = 0
    except (OSError, UnicodeError, UIProfileError, json.JSONDecodeError) as error:
        result["error"] = str(error)
    try:
        result_path.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        return 3
    finally:
        request.unlink(missing_ok=True)
    return exit_code


def read_elevated_profile_result(pending):
    if not pending.result_path.is_file():
        return None
    try:
        result = json.loads(pending.result_path.read_text(encoding="utf-8"))
        if result.get("nonce") != pending.nonce:
            raise UIProfileError("UI profile result verification failed")
        return result
    finally:
        pending.result_path.unlink(missing_ok=True)
        pending.request_path.unlink(missing_ok=True)
