"""Offline manual bundles never use a game directory or change published skins."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vantage_ui_archive", ROOT / "scripts" / "archive_ui_skins.py")
archiver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archiver)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_catalog(bundle):
    bundle.catalog_path.write_text(json.dumps(bundle.catalog), encoding="utf-8")


def source_zip(assets, infos=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in assets.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            if infos and name in infos:
                info = infos[name]
            archive.writestr(info, data)
    return stream.getvalue()


def save_release(bundle, index, manifest=None, assets=None, payload=None, infos=None):
    release = bundle.catalog["releases"][index]
    if assets is not None:
        bundle.assets[index] = assets
    assets = bundle.assets[index]
    if manifest is None:
        manifest = {"schema": 2, "version": release["version"],
                    "skin_folder": "VantageUI-v" + release["version"],
                    "files": [{"path": name, "size": len(data), "sha256": digest(data)}
                              for name, data in assets.items()]}
    manifest_data = json.dumps(manifest, indent=2).encode("utf-8")
    payload = source_zip(assets, infos) if payload is None else payload
    directory = bundle.directories[index]
    (directory / archiver.package.MANIFEST_NAME).write_bytes(manifest_data)
    (directory / archiver.package.PAYLOAD_NAME).write_bytes(payload)
    release["manifest"] = {"size": len(manifest_data), "sha256": digest(manifest_data)}
    release["payload"] = {"size": len(payload), "sha256": digest(payload)}
    save_catalog(bundle)
    return manifest


@pytest.fixture
def bundle(tmp_path):
    releases, directories, assets = [], [], []
    for version, layout, badge in (
            ("1.44.110", "horizontal", "HBuff"), ("1.44.109", "vertical", "VBuff"),
            ("1.44.108", "horizontal", "H"), ("1.44.107", "horizontal", "H")):
        releases.append({"version": version, "buff_layout": layout, "badge": badge,
                         "release_tag": "vantage-ui-v" + version})
        directory = tmp_path / ("published-" + version)
        directory.mkdir()
        directories.append(directory)
        assets.append({
            "EQUI_GroupWindow.xml": ('<XML>\r\n<Label item="GW_VantageVersionLabel">'
                '<Text>v{} ({})</Text><Size><CX>200</CX></Size></Label>\r\n</XML>\r\n'.format(version, badge)).encode(),
            "EQUI_BuffWindow.xml": ('<XML>\r\n<Screen item="BuffWindow"><Text>Effects ({})</Text>'
                                   '</Screen>\r\n</XML>\r\n'.format(badge)).encode(),
            "EQUI_Test.xml": b'<XML><Screen item="Test" /></XML>\r\n',
            "Colors.TGA": b"fixture image bytes\x00\xff" * 32,
            **{"asset-{:03}.tga".format(number): b"identical published pixels" * 32 for number in range(182)}})
    result = SimpleNamespace(
        catalog={"schema": 1, "preferred_layout": "vertical", "preferred_version": "1.44.109",
                 "releases": releases}, catalog_path=tmp_path / "releases.json",
        directories=directories, assets=assets, output=tmp_path / "downloads")
    for index in range(4):
        save_release(result, index)
    return result


def build(bundle, directories=None, output=None):
    return archiver.archive_skins(bundle.catalog_path,
                                  bundle.directories if directories is None else directories,
                                  bundle.output if output is None else output)


def test_complete_bundles_preserve_source_bytes_pins_and_normalized_single_folder(bundle):
    before = {(index, path.name): path.read_bytes() for index, directory in enumerate(bundle.directories)
              for path in directory.iterdir()}
    bundle.output.mkdir()
    (bundle.output / "README.md").write_bytes(b"preserve unrelated documentation")
    result = build(bundle, list(reversed(bundle.directories)))
    assert json.loads((bundle.output / "catalog.json").read_bytes()) == result
    for index, release in enumerate(result["releases"]):
        assert {key: value for key, value in release.items() if key != "archive"} == bundle.catalog["releases"][index]
        metadata = release["archive"]
        path = bundle.output / metadata["filename"]
        data = path.read_bytes()
        assert metadata == {"filename": "VantageUI-v{}-{}.zip".format(release["version"], release["badge"]),
                            "size": len(data), "sha256": digest(data), "files": 186}
        folder = "VantageUI-v" + release["version"] + "/"
        with zipfile.ZipFile(path) as archive:
            assert archive.namelist() == [folder] + [folder + name for name in
                sorted(bundle.assets[index], key=lambda name: (name.casefold(), name))]
            assert {name.split("/")[0] for name in archive.namelist()} == {folder[:-1]}
            for info in archive.infolist():
                assert info.date_time == (1980, 1, 1, 0, 0, 0) and info.create_system == 3
                if info.is_dir():
                    assert info.external_attr >> 16 == stat.S_IFDIR | 0o755
                else:
                    assert info.compress_type == zipfile.ZIP_DEFLATED
                    assert info.external_attr >> 16 == stat.S_IFREG | 0o644
                    assert archive.read(info) == bundle.assets[index][info.filename[len(folder):]]
            assert all(not name.endswith((".ini", ".json", ".exe", ".log")) for name in archive.namelist())
    assert (bundle.output / "README.md").read_bytes() == b"preserve unrelated documentation"
    assert before == {(index, path.name): path.read_bytes() for index, directory in enumerate(bundle.directories)
                      for path in directory.iterdir()}


def test_current_pair_contains_both_unchanged_folders_and_combined_count(bundle):
    result = build(bundle)
    pair = result["buff_pair"]
    assert pair["vertical"] == "1.44.109" and pair["horizontal"] == "1.44.110"
    metadata = pair["archive"]
    data = (bundle.output / metadata["filename"]).read_bytes()
    assert metadata == {"filename": "VantageUI-BuffPair-v1.44.109-v1.44.110.zip", "size": len(data),
                        "sha256": digest(data), "files": 372}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert len(archive.infolist()) == 374
        assert [info.filename for info in archive.infolist() if info.is_dir()] == [
            "VantageUI-v1.44.109/", "VantageUI-v1.44.110/"]
        for index in (1, 0):
            prefix = "VantageUI-v" + bundle.catalog["releases"][index]["version"] + "/"
            for name, expected in bundle.assets[index].items():
                assert archive.read(prefix + name) == expected
                assert archive.getinfo(prefix + name).compress_type == zipfile.ZIP_DEFLATED


def test_archives_and_catalog_are_deterministic_idempotent_and_compressed(bundle, tmp_path):
    first = build(bundle)
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in bundle.output.iterdir()}
    assert build(bundle) == first
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in bundle.output.iterdir()}
    other = tmp_path / "other-output"
    assert build(bundle, output=other) == first
    assert {path.name: path.read_bytes() for path in other.iterdir()} == {
        name: data for name, (data, _) in before.items()}
    for release in first["releases"]:
        assert release["archive"]["size"] < release["payload"]["size"]


@pytest.mark.parametrize("change", ["schema", "missing", "duplicate", "order", "preferred-member",
                                  "preferred-newest", "layout", "badge", "tag", "pin", "fields"])
def test_malformed_four_release_catalog_refuses_before_output(bundle, change):
    catalog = bundle.catalog
    if change == "schema":
        catalog["schema"] = True
    elif change == "missing":
        catalog["releases"].pop()
    elif change == "duplicate":
        catalog["releases"][3] = copy.deepcopy(catalog["releases"][2])
    elif change == "order":
        catalog["releases"].reverse()
    elif change == "preferred-member":
        catalog["preferred_version"] = "1.44.104"
    elif change == "preferred-newest":
        catalog["releases"][0].update(buff_layout="vertical", badge="VBuff")
    elif change == "layout":
        catalog["preferred_layout"] = "horizontal"
    elif change == "badge":
        catalog["releases"][1]["badge"] = "H"
    elif change == "tag":
        catalog["releases"][0]["release_tag"] = "v1.44.110"
    elif change == "pin":
        catalog["releases"][0]["payload"]["sha256"] = "invalid"
    else:
        catalog["releases"][0]["private"] = "must not carry through"
    save_catalog(bundle)
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert not bundle.output.exists()


def test_duplicate_json_fields_refuse_before_output(bundle):
    bundle.catalog_path.write_bytes(b'{"schema":1,"schema":1}')
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("asset", ["manifest", "payload"])
@pytest.mark.parametrize("pin", ["size", "sha256"])
def test_release_pins_are_verified_before_zip_is_read_or_outputs_exist(bundle, monkeypatch, asset, pin):
    record = bundle.catalog["releases"][-1][asset]
    record[pin] = record[pin] + 1 if pin == "size" else "0" * 64
    save_catalog(bundle)
    original = archiver._verified_assets
    def verify(manifest, payload, release):
        assert release["version"] != "1.44.107", "Unpinned ZIP must never be read"
        return original(manifest, payload, release)
    monkeypatch.setattr(archiver, "_verified_assets", verify)
    with pytest.raises(archiver.ArchiveError, match="pin verification"):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("change", ["schema", "version-folder", "missing", "duplicate", "case-collision",
                                  "path", "private", "wrong-size", "wrong-hash", "count-limit"])
def test_manifest_and_exact_payload_assets_are_required(bundle, change):
    index = 3
    manifest = json.loads((bundle.directories[index] / archiver.package.MANIFEST_NAME).read_bytes())
    if change == "schema":
        manifest["schema"] = 1
    elif change == "version-folder":
        manifest["skin_folder"] = "VantageUI"
    elif change == "missing":
        manifest["files"].pop()
    elif change == "duplicate":
        manifest["files"].append(copy.deepcopy(manifest["files"][0]))
    elif change == "case-collision":
        entry = copy.deepcopy(manifest["files"][0])
        entry["path"] = entry["path"].lower()
        manifest["files"].append(entry)
    elif change == "path":
        manifest["files"][0]["path"] = "../bad.xml"
    elif change == "private":
        manifest["files"][0]["path"] = "UI_Toon.ini"
    elif change == "wrong-size":
        manifest["files"][0]["size"] += 1
    elif change == "wrong-hash":
        manifest["files"][0]["sha256"] = "0" * 64
    else:
        manifest["files"] *= 20
    save_release(bundle, index, manifest=manifest)
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("attack", ["duplicate", "case", "path", "private", "symlink", "directory", "bad-zip"])
def test_payload_rejects_collision_unsafe_private_and_nonregular_entries(bundle, attack):
    index = 3
    assets = dict(bundle.assets[index])
    if attack == "bad-zip":
        payload = b"not an archive"
    elif attack in {"symlink", "directory"}:
        info = zipfile.ZipInfo("Colors.TGA")
        info.create_system = 3
        info.external_attr = ((stat.S_IFLNK | 0o777) if attack == "symlink" else (stat.S_IFDIR | 0o755)) << 16
        payload = source_zip(assets, {"Colors.TGA": info})
    else:
        # Keep the entry count equal to the manifest so name validation, rather
        # than only the count check, must reject each unsafe replacement.
        assets.pop("asset-181.tga")
        stream = io.BytesIO(source_zip(assets))
        with zipfile.ZipFile(stream, "a") as archive:
            names = {"duplicate": "Colors.TGA", "case": "colors.tga", "path": "../extra.xml",
                     "private": "UI_Toon.ini"}
            if attack == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate name"):
                    archive.writestr(names[attack], b"private")
            else:
                archive.writestr(names[attack], b"private")
        payload = stream.getvalue()
    save_release(bundle, index, payload=payload)
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("change", ["badge", "buff", "duplicate-badge", "missing-buff", "xml", "entity"])
def test_published_xml_and_recorded_orientation_are_required(bundle, change):
    assets = dict(bundle.assets[3])
    if change == "badge":
        assets["EQUI_GroupWindow.xml"] = assets["EQUI_GroupWindow.xml"].replace(b"(H)", b"(HBuff)")
    elif change == "buff":
        assets["EQUI_BuffWindow.xml"] = assets["EQUI_BuffWindow.xml"].replace(b"Effects (H)", b"Effects (VBuff)")
    elif change == "duplicate-badge":
        assets["EQUI_GroupWindow.xml"] = assets["EQUI_GroupWindow.xml"].replace(b"</XML>",
            b'<Label item="GW_VantageVersionLabel"><Text>v1.44.107 (H)</Text></Label></XML>')
    elif change == "missing-buff":
        assets.pop("EQUI_BuffWindow.xml")
    elif change == "xml":
        assets["EQUI_Test.xml"] = b"<XML>"
    else:
        assets["EQUI_Test.xml"] = b'<!DOCTYPE XML [<!ENTITY private "private">]><XML>&private;</XML>'
    save_release(bundle, 3, assets=assets)
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("change", ["asset-name", "asset-bytes", "group-geometry", "group-whitespace"])
def test_pair_rejects_base_mismatch_before_any_output(bundle, change):
    assets = dict(bundle.assets[0])
    if change == "asset-name":
        assets["other.tga"] = assets.pop("Colors.TGA")
    elif change == "asset-bytes":
        assets["Colors.TGA"] += b"changed horizontal base"
    elif change == "group-geometry":
        assets["EQUI_GroupWindow.xml"] = assets["EQUI_GroupWindow.xml"].replace(b"<CX>200</CX>", b"<CX>201</CX>")
    else:
        assets["EQUI_GroupWindow.xml"] = assets["EQUI_GroupWindow.xml"].replace(b"\r\n", b"\n")
    save_release(bundle, 0, assets=assets)
    with pytest.raises(archiver.ArchiveError, match="pair"):
        build(bundle)
    assert not bundle.output.exists()


@pytest.mark.parametrize("target", ["single", "pair", "catalog"])
def test_different_existing_output_is_preserved_and_stops_all_new_outputs(bundle, target):
    bundle.output.mkdir()
    names = {"single": "VantageUI-v1.44.107-H.zip", "pair": "VantageUI-BuffPair-v1.44.109-v1.44.110.zip",
             "catalog": "catalog.json"}
    path = bundle.output / names[target]
    path.write_bytes(b"existing immutable bytes")
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert {item.name: item.read_bytes() for item in bundle.output.iterdir()} == {
        names[target]: b"existing immutable bytes"}


def test_output_case_alias_refuses_before_any_write(bundle):
    bundle.output.mkdir()
    path = bundle.output / "vantageui-v1.44.110-hbuff.zip"
    path.write_bytes(b"preserved alias")
    with pytest.raises(archiver.ArchiveError, match="Case-alias"):
        build(bundle)
    assert list(bundle.output.iterdir()) == [path] and path.read_bytes() == b"preserved alias"


@pytest.mark.parametrize("target", ["catalog", "manifest", "payload", "output", "output-file"])
def test_linked_inputs_or_outputs_are_never_used(bundle, tmp_path, target):
    destination = tmp_path / "outside"
    destination.mkdir()
    private = destination / "private"
    private.write_bytes(b"must remain untouched")
    if target == "catalog":
        source, linked, is_directory = bundle.catalog_path, tmp_path / "linked-catalog.json", False
    elif target in {"manifest", "payload"}:
        name = archiver.package.MANIFEST_NAME if target == "manifest" else archiver.package.PAYLOAD_NAME
        linked = bundle.directories[0] / name
        source = destination / name
        source.write_bytes(linked.read_bytes())
        linked.unlink()
        is_directory = False
    elif target == "output":
        source, linked, is_directory = destination, bundle.output, True
    else:
        bundle.output.mkdir()
        source, linked, is_directory = private, bundle.output / "catalog.json", False
    try:
        linked.symlink_to(source, target_is_directory=is_directory)
    except OSError:
        pytest.skip("Symlink creation requires privileges on this Windows account")
    if target == "catalog":
        bundle.catalog_path = linked
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    assert private.read_bytes() == b"must remain untouched"
    assert not any(path.suffix == ".zip" for path in destination.iterdir())


@pytest.mark.parametrize("target", ["manifest", "payload", "output", "output-file"])
def test_reparse_point_detection_refuses_before_writes_without_link_privileges(bundle, monkeypatch, target):
    if target in {"manifest", "payload"}:
        name = archiver.package.MANIFEST_NAME if target == "manifest" else archiver.package.PAYLOAD_NAME
        linked = bundle.directories[0] / name
    else:
        bundle.output.mkdir()
        linked = bundle.output if target == "output" else bundle.output / "catalog.json"
        if target == "output-file":
            linked.write_bytes(b"preserved simulated reparse point")
    real_link = archiver.package._is_link
    monkeypatch.setattr(archiver.package, "_is_link", lambda path: Path(path) == linked or real_link(path))
    before = {path.name: path.read_bytes() for path in bundle.output.iterdir()} if bundle.output.exists() else None
    with pytest.raises(archiver.ArchiveError):
        build(bundle)
    if before is None:
        assert not bundle.output.exists()
    else:
        assert before == {path.name: path.read_bytes() for path in bundle.output.iterdir()}


@pytest.mark.parametrize("change", ["missing", "duplicate-dir", "wrong-name"])
def test_all_exact_release_directories_are_required_before_output(bundle, change):
    directories = list(bundle.directories)
    if change == "missing":
        directories.pop()
    elif change == "duplicate-dir":
        directories[-1] = directories[0]
    else:
        path = directories[-1] / archiver.package.MANIFEST_NAME
        path.rename(path.with_name("unexpected.json"))
    with pytest.raises(archiver.ArchiveError):
        build(bundle, directories)
    assert not bundle.output.exists()


@pytest.mark.parametrize("versions", [
    ("1.44.113", "1.44.112", "1.44.111", "1.44.109"),
    ("1.44.10", "1.44.9", "1.44.8", "1.44.7")])
def test_generic_future_catalog_uses_numeric_order_and_newest_vertical_pair(bundle, versions):
    for index, version in enumerate(versions):
        release = bundle.catalog["releases"][index]
        old_version, old_badge = release["version"], release["badge"]
        layout, badge = ("vertical", "VBuff") if index in (0, 3) else ("horizontal", "HBuff")
        release.update(version=version, buff_layout=layout, badge=badge, release_tag="vantage-ui-v" + version)
        assets = dict(bundle.assets[index])
        assets["EQUI_GroupWindow.xml"] = assets["EQUI_GroupWindow.xml"].replace(
            ("v{} ({})".format(old_version, old_badge)).encode(), ("v{} ({})".format(version, badge)).encode())
        assets["EQUI_BuffWindow.xml"] = assets["EQUI_BuffWindow.xml"].replace(
            ("Effects ({})".format(old_badge)).encode(), ("Effects ({})".format(badge)).encode())
        save_release(bundle, index, assets=assets)
    bundle.catalog["preferred_version"] = versions[0]
    save_catalog(bundle)
    result = build(bundle)
    assert result["buff_pair"]["vertical"] == versions[0]
    assert result["buff_pair"]["horizontal"] == versions[1]


def test_repository_downloads_match_every_original_published_manifest_asset():
    output = ROOT / "ui" / "downloads"
    source = archiver.load_catalog(output / "releases.json")
    result = json.loads((output / "catalog.json").read_bytes())
    assert {key: value for key, value in result.items() if key not in {"releases", "buff_pair"}} == {
        key: value for key, value in source.items() if key != "releases"}
    assert len(result["releases"]) == 4
    sources = {}
    for release, original in zip(result["releases"], source["releases"]):
        assert {key: value for key, value in release.items() if key != "archive"} == original
        manifest_bytes = (output / ("VantageUI-v" + release["version"] + ".manifest.json")).read_bytes()
        assert original["manifest"] == {"size": len(manifest_bytes), "sha256": digest(manifest_bytes)}
        entries = archiver._manifest(json.loads(manifest_bytes), original)
        metadata = release["archive"]
        expected_name = "VantageUI-v{}-{}.zip".format(release["version"], release["badge"])
        assert metadata["filename"] == expected_name and metadata["files"] == len(entries)
        data = (output / expected_name).read_bytes()
        assert metadata["size"] == len(data) and metadata["sha256"] == digest(data)
        prefix = "VantageUI-v" + release["version"] + "/"
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert set(archive.namelist()) == {prefix} | {prefix + name for name in entries}
            assets = {name: archive.read(prefix + name) for name in entries}
            for name, entry in entries.items():
                assert len(assets[name]) == entry["size"] and digest(assets[name]) == entry["sha256"]
            archiver._xml_contracts(assets, original)
        sources[release["version"]] = (output, assets)
    vertical, horizontal = archiver._current_pair(source, sources)
    pair = result["buff_pair"]
    assert pair["vertical"] == vertical["version"] and pair["horizontal"] == horizontal["version"]
    expected_name = "VantageUI-BuffPair-v{}-v{}.zip".format(vertical["version"], horizontal["version"])
    metadata = pair["archive"]
    assert metadata["filename"] == expected_name
    data = (output / expected_name).read_bytes()
    assert metadata["size"] == len(data) and metadata["sha256"] == digest(data)
    pair_assets = {"VantageUI-v" + version + "/" + name: content
                   for version in (vertical["version"], horizontal["version"])
                   for name, content in sources[version][1].items()}
    assert metadata["files"] == len(pair_assets)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert {info.filename for info in archive.infolist() if not info.is_dir()} == set(pair_assets)
        assert {info.filename for info in archive.infolist() if info.is_dir()} == {
            "VantageUI-v" + vertical["version"] + "/", "VantageUI-v" + horizontal["version"] + "/"}
        for name, content in pair_assets.items():
            assert archive.read(name) == content


def test_cli_builds_offline_and_rejects_invalid_catalog_without_output(bundle, capsys):
    argv = ["--catalog", str(bundle.catalog_path), "--output", str(bundle.output)]
    for directory in bundle.directories:
        argv.extend(["--release-dir", str(directory)])
    assert archiver.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["buff_pair"]["archive"]["files"] == 372
    bundle.catalog["releases"].pop()
    save_catalog(bundle)
    before = {path.name: path.read_bytes() for path in bundle.output.iterdir()}
    with pytest.raises(SystemExit) as error:
        archiver.main(argv)
    assert error.value.code == 2 and "UI archive rejected" in capsys.readouterr().err
    assert before == {path.name: path.read_bytes() for path in bundle.output.iterdir()}
