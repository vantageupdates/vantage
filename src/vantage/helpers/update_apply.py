"""Standard-library-only update swap used before Qt starts.

The verified new Vantage executable runs this module from a temporary folder,
waits for the old process image to unlock, atomically replaces it, and relaunches
the stable path. No permanent updater executable is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


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


def _launch_target(target, *, updated_from="", error="", cleanup=""):
    environment = os.environ.copy()
    if updated_from:
        environment["VANTAGE_UPDATED_FROM"] = updated_from
    if error:
        environment["VANTAGE_UPDATE_ERROR"] = str(error)[:1000]
    if cleanup:
        environment["VANTAGE_UPDATE_CLEANUP"] = cleanup
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

        _launch_target(
            target, updated_from=options.from_version,
            cleanup=cleanup_dir)
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
