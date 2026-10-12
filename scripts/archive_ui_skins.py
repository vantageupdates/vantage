"""Build four complete manual UI downloads from pinned published assets, offline.

This transport-only tool never changes a skin, calls the updater, downloads a
release, or accesses an installed game. Stage future catalogs in a fresh output
directory: every existing archive and catalog is immutable to this builder.
"""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib


_SPEC = importlib.util.spec_from_file_location(
    "_vantage_archive_package", Path(__file__).with_name("package_ui_skin.py"))
package = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(package)
MAX_CATALOG_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = package.MAX_TOTAL_BYTES + 4 * 1024 * 1024
CATALOG_NAME = "catalog.json"
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_RELEASE_FIELDS = {"version", "buff_layout", "badge", "release_tag", "manifest", "payload"}


class ArchiveError(ValueError):
    """The pinned source or immutable output is unsafe or inconsistent."""


def _require(condition, message):
    if not condition:
        raise ArchiveError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate JSON field: " + key)
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as error:
        raise ArchiveError("Invalid bounded JSON metadata") from error


def _version(value):
    _require(isinstance(value, str) and len(value) <= 64
             and package.VERSION_PATTERN.fullmatch(value), "Invalid stable UI version")
    return tuple(map(int, value.split(".")))


def _checked_directory(path):
    try:
        return package._checked_directory(path)
    except package.PackageError as error:
        raise ArchiveError(str(error)) from error


def _read_regular(path, maximum):
    path = Path(path).absolute()
    _checked_directory(path.parent)
    before = path.lstat()
    _require(not package._is_link(path) and stat.S_ISREG(before.st_mode)
             and before.st_nlink == 1, "Only unlinked regular input/output files are allowed: " + path.name)
    _require(before.st_size <= maximum, "File exceeds its bounded size: " + path.name)
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                 and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                 "File identity changed while reading: " + path.name)
        data = handle.read(maximum + 1)
    after = path.lstat()
    _require(len(data) <= maximum and not package._is_link(path)
             and after.st_nlink == 1
             and (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino),
             "File changed while reading: " + path.name)
    return data


def _pin(pin, maximum):
    _require(isinstance(pin, dict) and set(pin) == {"size", "sha256"}, "Invalid release asset pin")
    _require(type(pin["size"]) is int and 0 < pin["size"] <= maximum,
             "Invalid release asset pin size")
    _require(isinstance(pin["sha256"], str) and _HASH.fullmatch(pin["sha256"]),
             "Invalid release asset SHA-256 pin")


def load_catalog(path):
    """Require four descending, unique releases and the newest vertical choice."""
    catalog = _json(_read_regular(path, MAX_CATALOG_BYTES))
    _require(isinstance(catalog, dict) and set(catalog) == {
        "schema", "preferred_layout", "preferred_version", "releases"}, "Invalid source catalog fields")
    _require(type(catalog["schema"]) is int and catalog["schema"] == 1, "Expected catalog schema 1")
    _require(catalog["preferred_layout"] == "vertical", "The preferred layout must be vertical")
    _version(catalog["preferred_version"])
    releases = catalog["releases"]
    _require(isinstance(releases, list) and len(releases) == 4, "The catalog must contain exactly four releases")
    versions, vertical = [], []
    for release in releases:
        _require(isinstance(release, dict) and set(release) == _RELEASE_FIELDS, "Invalid release catalog fields")
        versions.append(_version(release["version"]))
        _require(release["release_tag"] == "vantage-ui-v" + release["version"],
                 "The exact release tag must match its UI version")
        layout, badge = release["buff_layout"], release["badge"]
        _require(isinstance(layout, str) and layout in {"vertical", "horizontal"}, "Invalid buff orientation")
        _require(isinstance(badge, str) and (
            (layout == "vertical" and badge == "VBuff")
            or (layout == "horizontal" and badge in {"HBuff", "H"})), "Invalid historical layout badge")
        if layout == "vertical":
            vertical.append(release["version"])
        _pin(release["manifest"], MAX_MANIFEST_BYTES)
        _pin(release["payload"], MAX_ARCHIVE_BYTES)
    _require(len(set(versions)) == 4 and versions == sorted(versions, reverse=True),
             "Catalog versions must be unique and ordered newest first")
    _require(vertical and catalog["preferred_version"] == max(vertical, key=_version),
             "The preferred version must be the newest vertical catalog member")
    _require(any(release["buff_layout"] == "horizontal" for release in releases),
             "The catalog must also contain a horizontal release for the current pair")
    return catalog


def _asset_names(names):
    names = list(names)
    try:
        package.validate_names(names)
    except package.PackageError as error:
        raise ArchiveError(str(error)) from error
    for name in names:
        base = name.split(".", 1)[0].upper()
        _require(len(name) <= 180 and not name.startswith(".")
                 and base not in {"CLOCK$", "CONIN$", "CONOUT$"}
                 and not re.fullmatch(r"(?:COM|LPT)[0-9¹²³]", base),
                 "Unsafe or private UI asset filename: " + name)


def _manifest(value, release):
    _require(isinstance(value, dict) and set(value) == {"schema", "version", "skin_folder", "files"},
             "Invalid canonical manifest fields")
    _require(type(value["schema"]) is int and value["schema"] == package.MANIFEST_SCHEMA,
             "Expected canonical manifest schema 2")
    _require(value["version"] == release["version"] and value["skin_folder"] ==
             package.SKIN_FOLDER_PREFIX + release["version"], "Manifest version or numeric folder does not match")
    entries = value["files"]
    _require(isinstance(entries, list) and 0 < len(entries) <= package.MAX_FILES,
             "Invalid bounded manifest file count")
    total = 0
    for entry in entries:
        _require(isinstance(entry, dict) and set(entry) == {"path", "size", "sha256"},
                 "Invalid manifest asset fields")
        _require(type(entry["size"]) is int and 0 <= entry["size"] <= package.MAX_FILE_BYTES,
                 "Invalid manifest asset size")
        _require(isinstance(entry["sha256"], str) and _HASH.fullmatch(entry["sha256"]),
                 "Invalid manifest asset digest")
        total += entry["size"]
    _require(total <= package.MAX_TOTAL_BYTES, "Manifest exceeds total asset size limit")
    _asset_names(entry["path"] for entry in entries)
    return {entry["path"]: entry for entry in entries}


def _xml_contracts(assets, release):
    roots = {}
    for name, data in assets.items():
        if Path(name).suffix.casefold() != ".xml":
            continue
        declaration = data.replace(b"\x00", b"").upper()
        _require(b"<!DOCTYPE" not in declaration and b"<!ENTITY" not in declaration,
                 "XML DTDs/entities are not allowed: " + name)
        try:
            roots[name] = ET.fromstring(data)
        except ET.ParseError as error:
            raise ArchiveError("Invalid XML asset: " + name) from error
    _require("EQUI_GroupWindow.xml" in roots and "EQUI_BuffWindow.xml" in roots,
             "The native group and buff XML assets are required")
    labels = roots["EQUI_GroupWindow.xml"].findall("./Label[@item='GW_VantageVersionLabel']")
    expected = "v{} ({})".format(release["version"], release["badge"])
    _require(len(labels) == 1 and labels[0].findtext("Text") == expected,
             "Native group badge does not match the recorded release: " + expected)
    screens = roots["EQUI_BuffWindow.xml"].findall("./Screen[@item='BuffWindow']")
    expected = "Effects ({})".format(release["badge"])
    _require(len(screens) == 1 and screens[0].findtext("Text") == expected,
             "Native buff window text does not match its recorded orientation: " + expected)


def _verified_assets(manifest, payload, release):
    entries = _manifest(manifest, release)
    assets = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            _require(len(infos) == len(entries), "Payload has missing or extra UI assets")
            _asset_names(info.orig_filename for info in infos)
            _require({info.filename for info in infos} == set(entries), "Payload assets do not match the manifest")
            for info in infos:
                mode = info.external_attr >> 16
                _require(info.orig_filename == info.filename and not info.is_dir()
                         and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                         and not info.external_attr & (0x400 | 0x10)
                         and not info.flag_bits & 1, "Linked, encrypted or nonregular ZIP assets are not allowed")
                _require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                         "Unsupported ZIP compression")
                entry = entries[info.filename]
                _require(info.file_size == entry["size"] and 0 <= info.compress_size <= MAX_ARCHIVE_BYTES,
                         "Payload asset size differs from its manifest: " + info.filename)
                with archive.open(info, "r") as source:
                    data = source.read(entry["size"] + 1)
                _require(len(data) == entry["size"] and _digest(data) == entry["sha256"],
                         "Payload asset bytes differ from their manifest: " + info.filename)
                assets[info.filename] = data
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error) as error:
        raise ArchiveError("Invalid verified ZIP payload") from error
    _xml_contracts(assets, release)
    return assets


def _masked_group(assets, release):
    data = assets["EQUI_GroupWindow.xml"]
    pattern = rb"<Label\b(?=[^>]*\bitem\s*=\s*(['\"])GW_VantageVersionLabel\1)[^>]*>.*?</Label\s*>"
    labels = list(re.finditer(pattern, data, re.DOTALL))
    _require(len(labels) == 1, "Cannot isolate the exact native group version label bytes")
    label = labels[0]
    texts = list(re.finditer(rb"<Text\s*>([^<]*)</Text\s*>", label.group()))
    expected = "v{} ({})".format(release["version"], release["badge"]).encode("ascii")
    _require(len(texts) == 1 and texts[0].group(1) == expected,
             "Cannot isolate the exact native group version text bytes")
    start, end = texts[0].span(1)
    return data[:label.start() + start] + b"VANTAGE_UI_VERSION_BADGE" + data[label.start() + end:]


def _current_pair(catalog, sources):
    vertical = next(release for release in catalog["releases"]
                    if release["version"] == catalog["preferred_version"])
    horizontal = max((release for release in catalog["releases"] if release["buff_layout"] == "horizontal"),
                     key=lambda release: _version(release["version"]))
    vertical_assets, horizontal_assets = (sources[release["version"]][1] for release in (vertical, horizontal))
    _require(set(vertical_assets) == set(horizontal_assets), "Current pair base asset names differ")
    for name in vertical_assets:
        if name not in {"EQUI_BuffWindow.xml", "EQUI_GroupWindow.xml"}:
            _require(vertical_assets[name] == horizontal_assets[name], "Current pair base asset bytes differ: " + name)
    _require(_masked_group(vertical_assets, vertical) == _masked_group(horizontal_assets, horizontal),
             "Current pair group geometry or other bytes differ beyond the native version text")
    return vertical, horizontal


def _zip_bytes(skins):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for version, assets in skins:
            folder = package.SKIN_FOLDER_PREFIX + version + "/"
            directory = zipfile.ZipInfo(folder, date_time=(1980, 1, 1, 0, 0, 0))
            directory.create_system = 3
            directory.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            archive.writestr(directory, b"")
            for name in sorted(assets, key=lambda value: (value.casefold(), value)):
                info = zipfile.ZipInfo(folder + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, assets[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def _check_outputs(output, outputs):
    nearest = output
    while not os.path.lexists(nearest):
        nearest = nearest.parent
    _checked_directory(nearest)
    if not os.path.lexists(output):
        return
    _checked_directory(output)
    planned = {name.casefold(): name for name in outputs}
    for path in output.iterdir():
        expected = planned.get(path.name.casefold())
        if expected is not None:
            _require(path.name == expected, "Case-alias output collision: " + path.name)
    for name, data in outputs.items():
        path = output / name
        if os.path.lexists(path):
            _require(_read_regular(path, len(data)) == data, "Immutable output differs; preserved: " + name)


def _publish_immutable(path, data):
    _check_outputs(path.parent, {path.name: data})
    if os.path.lexists(path):
        return
    handle, temporary = tempfile.mkstemp(prefix=".vantage-ui-archive-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        _check_outputs(path.parent, {path.name: data})
        try:
            # Hard-link publication is atomic and cannot replace a racing target
            # on Windows or POSIX. The private staging link is removed below.
            os.link(temporary, path)
        except FileExistsError:
            _check_outputs(path.parent, {path.name: data})
    finally:
        os.unlink(temporary)


def archive_skins(catalog_path, release_directories, output_directory):
    """Preverify all four inputs and conflicts, then publish immutable bundles."""
    catalog = load_catalog(catalog_path)
    directories = list(release_directories)
    _require(len(directories) == 4, "Exactly four release directories are required")
    releases = {release["version"]: release for release in catalog["releases"]}
    sources = {}
    for directory in directories:
        directory = _checked_directory(directory)
        names = [path.name for path in directory.iterdir()]
        for name in (package.MANIFEST_NAME, package.PAYLOAD_NAME):
            _require([value for value in names if value.casefold() == name.casefold()] == [name],
                     "Release directory must contain the exact asset name: " + name)
        manifest_data = _read_regular(directory / package.MANIFEST_NAME, MAX_MANIFEST_BYTES)
        manifest = _json(manifest_data)
        _require(isinstance(manifest, dict), "Invalid release manifest")
        version = manifest.get("version")
        _version(version)
        _require(version in releases and version not in sources, "Unknown or duplicate release directory version")
        release = releases[version]
        _require(len(manifest_data) == release["manifest"]["size"] and
                 _digest(manifest_data) == release["manifest"]["sha256"], "Manifest release pin verification failed")
        payload = _read_regular(directory / package.PAYLOAD_NAME, MAX_ARCHIVE_BYTES)
        _require(len(payload) == release["payload"]["size"] and _digest(payload) == release["payload"]["sha256"],
                 "Payload release pin verification failed")
        sources[version] = (directory, _verified_assets(manifest, payload, release))
    _require(set(sources) == set(releases), "A catalog release directory is missing")
    output = Path(output_directory).absolute()
    _require(all(output != source and source not in output.parents for source, _ in sources.values()),
             "Archive output must be outside every release input directory")
    vertical, horizontal = _current_pair(catalog, sources)
    outputs, result_releases = {}, []
    for release in catalog["releases"]:
        assets = sources[release["version"]][1]
        data = _zip_bytes([(release["version"], assets)])
        name = "VantageUI-v{}-{}.zip".format(release["version"], release["badge"])
        outputs[name] = data
        result_releases.append(dict(release, archive={
            "filename": name, "size": len(data), "sha256": _digest(data), "files": len(assets)}))
    pair_skins = [(release["version"], sources[release["version"]][1]) for release in (vertical, horizontal)]
    pair_data = _zip_bytes(pair_skins)
    pair_name = "VantageUI-BuffPair-v{}-v{}.zip".format(vertical["version"], horizontal["version"])
    outputs[pair_name] = pair_data
    result = dict(catalog, releases=result_releases, buff_pair={
        "vertical": vertical["version"], "horizontal": horizontal["version"],
        "archive": {"filename": pair_name, "size": len(pair_data), "sha256": _digest(pair_data),
                    "files": sum(len(assets) for _, assets in pair_skins)}})
    outputs[CATALOG_NAME] = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    _check_outputs(output, outputs)
    try:
        package._prepare_output_directory(output)
    except package.PackageError as error:
        raise ArchiveError(str(error)) from error
    for name, data in outputs.items():
        _publish_immutable(output / name, data)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = archive_skins(args.catalog, args.release_dir, args.output)
    except (OSError, ArchiveError) as error:
        parser.exit(2, "UI archive rejected: {}\n".format(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
