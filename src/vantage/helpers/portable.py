"""Per-user storage for the single-file Vantage executable."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import re


DATA_FOLDER_NAME = "Vantage"
PORTABLE_PREFIX = "portable:"
_DATA_OVERRIDE = "VANTAGE_DATA_DIR"


def application_dir() -> Path:
    """Return the folder containing the executable or source checkout."""
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def user_data_root() -> Path:
    """Return Vantage's writable profile folder, never the EXE folder."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data).expanduser().resolve() / DATA_FOLDER_NAME
    return Path.home().resolve() / "AppData" / "Local" / DATA_FOLDER_NAME


def data_dir(*parts: str, create: bool = True) -> Path:
    """Return a writable path in the current Windows user's profile."""
    override = os.environ.get(_DATA_OVERRIDE, "").strip()
    root = (Path(override).expanduser().resolve()
            if override else user_data_root())
    target = root.joinpath(*parts)
    if create:
        directory = target if not parts or target.suffix == "" else target.parent
        directory.mkdir(parents=True, exist_ok=True)
    return target


def store_portable_file(source: str, subdir: str = "sounds") -> str:
    """Copy a selected file into portable storage and return a relocatable URI."""
    original = Path(source).expanduser().resolve()
    if not original.is_file():
        return str(source or "")

    destination_dir = data_dir(subdir)
    destination = destination_dir / original.name
    original_bytes = original.read_bytes()
    if destination.exists() and destination.read_bytes() != original_bytes:
        digest = hashlib.sha256(original_bytes).hexdigest()[:8]
        destination = destination.with_name(
            f"{destination.stem}-{digest}{destination.suffix}")
    if not destination.exists() or destination.read_bytes() != original_bytes:
        shutil.copy2(original, destination)
    return f"{PORTABLE_PREFIX}{subdir}/{destination.name}"


def store_portable_bytes(content: bytes, filename: str,
                         subdir: str = "sounds") -> str:
    """Store trusted in-memory bytes and return a relocatable profile URI."""
    payload = bytes(content or b"")
    raw_name = Path(str(filename or "imported.wav")).name
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", Path(raw_name).stem).strip(" .-")
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", Path(raw_name).suffix).lower()
    safe_name = f"{stem or 'imported'}{suffix or '.wav'}"
    destination_dir = data_dir(subdir)
    destination = destination_dir / safe_name
    if destination.exists() and destination.read_bytes() != payload:
        digest = hashlib.sha256(payload).hexdigest()[:8]
        destination = destination.with_name(
            f"{destination.stem}-{digest}{destination.suffix}")
    if not destination.exists() or destination.read_bytes() != payload:
        destination.write_bytes(payload)
    return f"{PORTABLE_PREFIX}{subdir}/{destination.name}"


def resolve_portable_path(value: str) -> Path:
    """Resolve a portable URI while rejecting paths outside the data folder."""
    text = str(value or "").strip()
    if not text.startswith(PORTABLE_PREFIX):
        return Path(text).expanduser()
    relative = text[len(PORTABLE_PREFIX):].lstrip("/\\")
    root = data_dir()
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return root / "invalid-portable-path"
    return target
