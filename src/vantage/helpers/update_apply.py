"""Standard-library-only update swap used before Qt starts.

The verified new Vantage executable runs this module from a temporary folder,
waits for the old process image to unlock, atomically replaces it, and relaunches
the stable path. No permanent updater executable is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


_SPELL_HANDOFF_FILENAME = "update-spell-handoff.json"
_SPELL_HANDOFF_MAX_BYTES = 1024 * 1024
_SPELL_HANDOFF_MAX_ROWS = 512
_SPELL_HANDOFF_MAX_AGE_SECONDS = 24 * 60 * 60


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _spell_handoff_path():
    override = os.environ.get("VANTAGE_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        root = (Path(local_app_data).expanduser().resolve() / "Vantage"
                if local_app_data else
                Path.home().resolve() / "AppData" / "Local" / "Vantage")
    return root / _SPELL_HANDOFF_FILENAME


def _stamp_spell_handoff(*, path=None, now=None):
    """Atomically prove that the executable swap outlived old-process saves.

    This remains standard-library-only because it runs inside the staged
    updater before Qt or the normal application package starts.
    """
    source = Path(path) if path is not None else _spell_handoff_path()
    applied_at = float(now if now is not None else time.time())
    try:
        if (not math.isfinite(applied_at) or applied_at <= 0 or
                not source.is_file() or
                source.stat().st_size > _SPELL_HANDOFF_MAX_BYTES):
            return False
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload.get("rows") if isinstance(payload, dict) else None
        created_at = float(payload.get("created_at", 0.0))
        if (payload.get("schema") != 1 or not isinstance(rows, list) or
                len(rows) > _SPELL_HANDOFF_MAX_ROWS or
                not math.isfinite(created_at) or created_at <= 0 or
                created_at > applied_at + 300 or
                applied_at - created_at > _SPELL_HANDOFF_MAX_AGE_SECONDS):
            return False
        expected = str(payload.get("rows_sha256") or "")
        actual = hashlib.sha256(_json_bytes(rows)).hexdigest()
        if not expected or not hmac.compare_digest(expected, actual):
            return False
        payload["update_applied_at"] = applied_at
        raw = _json_bytes(payload)
        if len(raw) > _SPELL_HANDOFF_MAX_BYTES:
            return False
        source.parent.mkdir(parents=True, exist_ok=True)
        temporary = ""
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", delete=False, dir=source.parent,
                    prefix=".update-spell-handoff-stamp-",
                    suffix=".tmp") as handle:
                temporary = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, source)
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        return True
    except (OSError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
        return False


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_cleanup_dir(path):
    try:
        candidate = Path(path).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        candidate.relative_to(temp_root)
        if not candidate.name.startswith("Vantage-update-"):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def schedule_update_cleanup(path, delay=4.0):
    """Remove the temporary updater after its process has had time to exit."""
    target = _validated_cleanup_dir(path)
    if target is None:
        return

    def clean():
        time.sleep(max(1.0, float(delay)))
        for _attempt in range(20):
            try:
                shutil.rmtree(target)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.5)

    threading.Thread(
        target=clean, name="VantageUpdateCleanup", daemon=True).start()


def _launch_target(target, *, updated_from="", error="", cleanup="",
                   open_vantage_ui=False):
    environment = os.environ.copy()
    environment.pop("VANTAGE_OPEN_UI_AFTER_UPDATE", None)
    if updated_from:
        environment["VANTAGE_UPDATED_FROM"] = updated_from
    if error:
        environment["VANTAGE_UPDATE_ERROR"] = str(error)[:1000]
    if cleanup:
        environment["VANTAGE_UPDATE_CLEANUP"] = cleanup
    if updated_from and open_vantage_ui:
        environment["VANTAGE_OPEN_UI_AFTER_UPDATE"] = "1"
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    command = [str(target)]
    # Test only: make an end-to-end swap prove the replacement can start
    # without opening a normal Vantage window during the build audit.
    if environment.get("VANTAGE_UPDATE_SELF_TEST") == "1":
        command.append("--portable-self-test")
    subprocess.Popen(
        command, cwd=str(target.parent), env=environment,
        close_fds=True, creationflags=flags)


def apply_staged_update(arguments=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--apply-update", action="store_true")
    parser.add_argument("--target", required=True)
    parser.add_argument("--wait-pid", required=True, type=int)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--from-version", default="")
    parser.add_argument("--open-vantage-ui", action="store_true")
    options, _unknown = parser.parse_known_args(arguments)

    source = Path(sys.executable).resolve()
    target = Path(options.target).resolve()
    cleanup_dir = str(source.parent)
    expected = options.digest.removeprefix("sha256:").strip().casefold()
    try:
        if target.suffix.casefold() != ".exe":
            raise ValueError("The installed Vantage path is not an executable.")
        if source == target:
            raise ValueError("The update was not staged in the temporary folder.")
        if not expected or file_sha256(source).casefold() != expected:
            raise ValueError("The staged update failed SHA-256 verification.")
        with open(source, "rb") as executable:
            if executable.read(2) != b"MZ":
                raise ValueError("The staged update is not a Windows executable.")

        # The PyInstaller parent may briefly retain the old image after its Qt
        # child exits. Copy beside it first, then retry only the atomic swap.
        staged = target.with_name(f".{target.stem}.update{target.suffix}")
        shutil.copy2(source, staged)
        if file_sha256(staged).casefold() != expected:
            raise ValueError("The local update copy failed verification.")

        deadline = time.monotonic() + 35.0
        last_error = None
        while time.monotonic() < deadline:
            try:
                os.replace(staged, target)
                last_error = None
                break
            except OSError as error:
                last_error = error
                time.sleep(0.25)
        if last_error is not None:
            raise OSError("Windows did not release the old Vantage executable")

        # The old process has fully exited before the successful swap above,
        # so this one-shot stamp is necessarily newer than its final config
        # save. Environment propagation remains the primary signal, while the
        # stamp safely covers Windows launch paths which drop that variable.
        _stamp_spell_handoff()
        _launch_target(
            target, updated_from=options.from_version,
            cleanup=cleanup_dir,
            open_vantage_ui=options.open_vantage_ui)
        return 0
    except Exception as error:
        try:
            staged = target.with_name(f".{target.stem}.update{target.suffix}")
            if staged.exists():
                staged.unlink()
        except OSError:
            pass
        if target.is_file():
            try:
                _launch_target(
                    target, error=f"Update could not be installed: {error}",
                    cleanup=cleanup_dir)
            except OSError:
                pass
        return 1
