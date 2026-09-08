"""Export and deterministically package the reviewed, flat EverQuest UI assets.

Packaging is read-only by default. Only an explicit --sync-from copies source
assets into ui/skin; neither mode writes to the installed EverQuest directory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = frozenset({".xml", ".tga", ".png", ".bmp", ".jpg", ".jpeg", ".dds"})
MAX_FILES = 2000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MANIFEST_NAME = "VantageUI-manifest.json"
PAYLOAD_NAME = "VantageUI-payload.zip"
MANIFEST_SCHEMA = 2
SKIN_FOLDER_PREFIX = "VantageUI-v"
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    "{}{}".format(prefix, number) for prefix in ("com", "lpt") for number in range(1, 10)
}


class PackageError(ValueError):
    """The candidate skin is not safe to export or publish."""


def validate_filename(name):
    """Accept a single portable Windows filename, never a path or private file."""
    if (not isinstance(name, str) or not name or name in (".", "..")
            or name != name.strip() or name.endswith(".")
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
            or name.split(".", 1)[0].casefold() in RESERVED_NAMES
            or Path(name).suffix.casefold() not in EXTENSIONS):
        raise PackageError("Not an allowed flat UI asset filename: {!r}".format(name))
    return name


def validate_names(names):
    seen = set()
    for name in names:
        validate_filename(name)
        key = name.casefold()
        if key in seen:
            raise PackageError("Case-insensitive filename collision: {!r}".format(name))
        seen.add(key)


def _is_link(path):
    # Windows junctions are reparse points too, and must not redirect an export.
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _checked_directory(path):
    path = Path(path).absolute()
    if not path.is_dir():
        raise PackageError("Missing directory: {}".format(path))
    for part in (path,) + tuple(path.parents):
        if _is_link(part):
            raise PackageError("Linked directories are not allowed: {}".format(part))
    return path


def _prepare_output_directory(path):
    # Check existing ancestry before mkdir so a junction cannot redirect even
    # the creation of intermediate build-output directories.
    nearest = path
    while not nearest.exists():
        if nearest.is_symlink():
            raise PackageError("Linked output directories are not allowed")
        nearest = nearest.parent
    _checked_directory(nearest)
    path.mkdir(parents=True, exist_ok=True)
    return _checked_directory(path)


def collect_assets(directory, source_export=False):
    """Read a bounded snapshot. Source export skips unrelated entries, not links.

    The curated repository folder is strict: unexpected files/directories fail
    packaging rather than accidentally publishing configuration or user data.
    """
    directory = _checked_directory(directory)
    assets = {}
    total = 0
    ignored = 0
    entries = sorted(directory.iterdir(), key=lambda path: (path.name.casefold(), path.name))
    for path in entries:
        if source_export and (path.suffix.casefold() not in EXTENSIONS or path.is_dir()):
            ignored += 1
            continue
        validate_filename(path.name)
        if _is_link(path) or not path.is_file():
            raise PackageError("Only regular flat asset files are allowed: {}".format(path))
        if path.stat().st_size > MAX_FILE_BYTES:
            raise PackageError("Asset exceeds per-file size limit: {}".format(path.name))
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise PackageError("Asset exceeds per-file size limit: {}".format(path.name))
        total += len(data)
        if total > MAX_TOTAL_BYTES or len(assets) >= MAX_FILES:
            raise PackageError("Skin exceeds total size or file-count limit")
        if path.suffix.casefold() == ".xml":
            declaration_bytes = data.replace(b"\x00", b"").upper()
            if b"<!DOCTYPE" in declaration_bytes or b"<!ENTITY" in declaration_bytes:
                raise PackageError("XML declarations with entities/DTDs are not allowed: {}".format(path.name))
            try:
                ET.fromstring(data)
            except ET.ParseError as error:
                raise PackageError("Invalid XML in {}: {}".format(path.name, error)) from error
        assets[path.name] = data
    validate_names(assets)
    if not assets:
        raise PackageError("Skin contains no allowed assets")
    return assets, ignored


def load_release(path):
    try:
        release = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PackageError("Cannot read release metadata: {}".format(error)) from error
    if (not isinstance(release, dict) or release.get("schema") != MANIFEST_SCHEMA
            or isinstance(release.get("schema"), bool)
            or not isinstance(release.get("version"), str)
            or not VERSION_PATTERN.fullmatch(release["version"])):
        raise PackageError("Expected schema 2 and a stable X.Y.Z UI version")
    expected_folder = SKIN_FOLDER_PREFIX + release["version"]
    if release.get("skin_folder") != expected_folder:
        raise PackageError(
            "skin_folder must exactly match the release version: {}".format(expected_folder))
    return {key: release[key] for key in ("schema", "version", "skin_folder")}


def create_manifest(assets, release):
    validate_names(assets)
    # A visible skin version must identify this exact delivery. Refuse a stale
    # tab rather than rewriting the canonical source or silently shipping it.
    for name, data in assets.items():
        if name.casefold() == "equi_hotbuttonwnd.xml":
            labels = ET.fromstring(data).findall("./Label[@item='HB_VantageVersionLabel']")
            expected = "VantageUI  v" + release["version"]
            if len(labels) != 1 or labels[0].findtext("Text") != expected:
                raise PackageError("Visible VantageUI version tab must match release: " + expected)
    manifest = dict(release)
    manifest["files"] = [
        {"path": name, "size": len(assets[name]), "sha256": hashlib.sha256(assets[name]).hexdigest()}
        for name in sorted(assets, key=lambda value: (value.casefold(), value))
    ]
    return manifest


def _atomic_write(path, data):
    if path.exists() and (_is_link(path) or not path.is_file()):
        raise PackageError("Refusing to replace a non-regular output: {}".format(path))
    handle, temporary = tempfile.mkstemp(prefix=".vantage-ui-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_source(source, destination):
    """Explicitly refresh repository assets, preserving source bytes and case."""
    source = _checked_directory(source)
    destination = Path(destination).absolute()
    if destination == source or source in destination.parents or destination in source.parents:
        raise PackageError("Source and repository asset directories must be separate")
    assets, ignored = collect_assets(source, source_export=True)
    if destination.exists():
        _checked_directory(destination)
        old_names = [item.name for item in destination.iterdir()]
        validate_names(old_names)
        for name in old_names:
            path = destination / name
            if _is_link(path) or not path.is_file():
                raise PackageError("Repository snapshot contains a non-regular entry")
    else:
        _checked_directory(destination.parent)
        destination.mkdir()
        old_names = []
    # Everything is validated before touching the repository snapshot. Only
    # allowlisted files in this exact snapshot directory may be replaced/deleted.
    for name in old_names:
        if name not in assets:
            (destination / name).unlink()
    for name, data in assets.items():
        _atomic_write(destination / name, data)
    return assets, ignored


def package_skin(skin_directory, release_path, output_directory):
    skin_directory = _checked_directory(skin_directory)
    assets, _ = collect_assets(skin_directory)
    release = load_release(release_path)
    output_directory = Path(output_directory).absolute()
    if output_directory == skin_directory or skin_directory in output_directory.parents:
        raise PackageError("Package output must not be inside the skin source")
    manifest = create_manifest(assets, release)
    _prepare_output_directory(output_directory)
    # ZIP_STORED avoids compression-library/version variance. The entire skin is
    # small; stable bytes across machines matter more than transport compression.
    handle, temporary = tempfile.mkstemp(prefix=".vantage-ui-", dir=str(output_directory))
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for entry in manifest["files"]:
                info = zipfile.ZipInfo(entry["path"], date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, assets[entry["path"]])
        target = output_directory / PAYLOAD_NAME
        if target.exists() and (_is_link(target) or not target.is_file()):
            raise PackageError("Refusing to replace a non-regular payload")
        os.replace(temporary, target)
        _atomic_write(output_directory / MANIFEST_NAME,
                      (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync-from", type=Path, help="Explicitly export flat assets from the canonical installed skin")
    parser.add_argument("--skin-dir", type=Path, default=ROOT / "ui" / "skin")
    parser.add_argument("--release", type=Path, default=ROOT / "ui" / "release.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "ui")
    args = parser.parse_args(argv)
    try:
        # Reject bad metadata before even an explicitly requested snapshot sync.
        load_release(args.release)
        ignored = 0
        if args.sync_from:
            _, ignored = sync_source(args.sync_from, args.skin_dir)
        manifest = package_skin(args.skin_dir, args.release, args.output)
    except (OSError, PackageError) as error:
        parser.exit(2, "UI package rejected: {}\n".format(error))
    print(json.dumps({"version": manifest["version"], "files": len(manifest["files"]),
                      "bytes": sum(item["size"] for item in manifest["files"]),
                      "ignored_source_entries": ignored, "output": str(args.output),
                      "xml_syntax_checked": True, "in_game_verified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
