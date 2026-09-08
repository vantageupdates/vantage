import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "vantage_ui_package", Path(__file__).resolve().parents[1] / "scripts" / "package_ui_skin.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


@pytest.fixture
def candidate(tmp_path):
    skin = tmp_path / "skin"
    skin.mkdir()
    (skin / "EQUI_Test.xml").write_bytes(b'<XML><Screen item="Test" /></XML>\r\n')
    (skin / "Colors.TGA").write_bytes(b"fixture image bytes\x00\xff")
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"schema": 2, "version": "1.44.52",
                                   "skin_folder": "VantageUI-v1.44.52"}), encoding="utf-8")
    return skin, release, tmp_path / "output"


def test_manifest_exact_bytes_flat_entries_and_deterministic_archive(candidate):
    skin, release, output = candidate
    manifest = package.package_skin(skin, release, output)
    zip_bytes = (output / package.PAYLOAD_NAME).read_bytes()
    manifest_bytes = (output / package.MANIFEST_NAME).read_bytes()
    assert json.loads(manifest_bytes) == manifest
    assert manifest["schema"] == 2
    assert manifest["version"] == "1.44.52"
    assert manifest["skin_folder"] == "VantageUI-v1.44.52"
    assert [item["path"] for item in manifest["files"]] == ["Colors.TGA", "EQUI_Test.xml"]
    with zipfile.ZipFile(output / package.PAYLOAD_NAME) as archive:
        assert archive.namelist() == [item["path"] for item in manifest["files"]]
        assert package.MANIFEST_NAME not in archive.namelist()
        for item in manifest["files"]:
            data = archive.read(item["path"])
            assert data == (skin / item["path"]).read_bytes()
            assert item["size"] == len(data)
            assert item["sha256"] == hashlib.sha256(data).hexdigest()
            assert archive.getinfo(item["path"]).date_time == (1980, 1, 1, 0, 0, 0)
            assert archive.getinfo(item["path"]).external_attr >> 16 == 0o100644
    package.package_skin(skin, release, output)
    assert (output / package.PAYLOAD_NAME).read_bytes() == zip_bytes
    assert (output / package.MANIFEST_NAME).read_bytes() == manifest_bytes


@pytest.mark.parametrize("label", [
    "", '<Label item="HB_VantageVersionLabel"><Text>VantageUI  v1.44.51</Text></Label>',
    '<Label item="HB_VantageVersionLabel"><Text>VantageUI</Text></Label>',
    '<Label item="HB_VantageVersionLabel"><Text>VantageUI  v1.44.52</Text></Label>' * 2,
])
def test_package_refuses_missing_stale_or_duplicate_visible_version(candidate, label):
    skin, release, output = candidate
    (skin / "EQUI_HotButtonWnd.xml").write_text("<XML>" + label + "</XML>")
    with pytest.raises(package.PackageError, match="Visible VantageUI version tab"):
        package.package_skin(skin, release, output)
    assert not output.exists()


def test_package_preserves_correct_visible_version_bytes(candidate):
    skin, release, output = candidate
    data = b'<XML><Label item="HB_VantageVersionLabel"><Text>VantageUI  v1.44.52</Text></Label></XML>'
    (skin / "EQUI_HotButtonWnd.xml").write_bytes(data)
    package.package_skin(skin, release, output)
    with zipfile.ZipFile(output / package.PAYLOAD_NAME) as archive:
        assert archive.read("EQUI_HotButtonWnd.xml") == data
    assert (skin / "EQUI_HotButtonWnd.xml").read_bytes() == data


@pytest.mark.parametrize("name", ["../bad.xml", "sub/bad.xml", "sub\\bad.xml", "C:\\bad.xml",
                                  "C:bad.xml", "file.xml:stream", "settings.ini", "game.log",
                                  "bad.xml ", "nul.xml", "COM1.png", ".", "..", "bad\x00.xml"])
def test_reject_unsafe_or_private_filenames(name):
    with pytest.raises(package.PackageError):
        package.validate_filename(name)


def test_reject_case_collisions_even_on_windows():
    with pytest.raises(package.PackageError, match="collision"):
        package.validate_names(["EQUI_Test.xml", "equi_test.XML"])


@pytest.mark.parametrize("name", ["character.ini", "UIErrors.txt", "eqlog_test.txt", "tool.exe"])
def test_curated_package_refuses_unexpected_files(candidate, name):
    skin, release, output = candidate
    (skin / name).write_bytes(b"must not ship")
    with pytest.raises(package.PackageError):
        package.package_skin(skin, release, output)
    assert not output.exists()


def test_curated_package_refuses_nested_directory(candidate):
    skin, release, output = candidate
    (skin / "nested.xml").mkdir()
    with pytest.raises(package.PackageError, match="regular"):
        package.package_skin(skin, release, output)


def test_export_ignores_non_assets_never_changes_source_and_removes_stale_snapshot(candidate, tmp_path):
    source, _, _ = candidate
    (source / "account.ini").write_bytes(b"private")
    (source / "arrow.cur").write_bytes(b"cursor")
    (source / "nested").mkdir()
    (source / "nested" / "not-exported.xml").write_bytes(b"<XML />")
    destination = tmp_path / "snapshot"
    destination.mkdir()
    (destination / "stale.png").write_bytes(b"stale")
    before = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    assets, ignored = package.sync_source(source, destination)
    assert ignored == 3
    assert sorted(path.name for path in destination.iterdir()) == sorted(assets)
    assert "Colors.TGA" in assets
    assert {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()} == before
    for name, data in assets.items():
        assert (destination / name).read_bytes() == data


def test_export_rejects_bad_snapshot_without_deleting_user_data(candidate, tmp_path):
    source, _, _ = candidate
    destination = tmp_path / "snapshot"
    destination.mkdir()
    (destination / "private.ini").write_bytes(b"keep")
    with pytest.raises(package.PackageError):
        package.sync_source(source, destination)
    assert (destination / "private.ini").read_bytes() == b"keep"


@pytest.mark.parametrize("xml", [b"<broken>", b'<!DOCTYPE XML [<!ENTITY x "test">]><XML>&x;</XML>',
                                  '<!DOCTYPE XML [<!ENTITY x "test">]><XML>&x;</XML>'.encode("utf-16")])
def test_invalid_or_entity_xml_fails_before_output(candidate, xml):
    skin, release, output = candidate
    (skin / "EQUI_Test.xml").write_bytes(xml)
    with pytest.raises(package.PackageError):
        package.package_skin(skin, release, output)
    assert not output.exists()


@pytest.mark.parametrize("limit,value", [("MAX_FILES", 1), ("MAX_FILE_BYTES", 2), ("MAX_TOTAL_BYTES", 2)])
def test_enforces_bounded_payload(candidate, monkeypatch, limit, value):
    skin, release, output = candidate
    monkeypatch.setattr(package, limit, value)
    with pytest.raises(package.PackageError, match="limit"):
        package.package_skin(skin, release, output)


def test_rejects_empty_snapshot(tmp_path):
    with pytest.raises(package.PackageError, match="no allowed"):
        package.collect_assets(tmp_path)


@pytest.mark.parametrize("change", [
    {"schema": True},
    {"schema": 1},
    {"schema": 3},
    {"version": "1.2.3-beta", "skin_folder": "VantageUI-v1.2.3-beta"},
    {"version": "01.2.3", "skin_folder": "VantageUI-v01.2.3"},
    {"skin_folder": "default"},
    {"skin_folder": "VantageUI"},
    {"skin_folder": "VantageUI-v1.44.51"},
    {"skin_folder": "vantageui-v1.44.52"},
])
def test_release_contract_requires_schema_two_and_exact_versioned_folder(candidate, change):
    skin, release, output = candidate
    data = json.loads(release.read_text(encoding="utf-8"))
    data.update(change)
    release.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(package.PackageError):
        package.package_skin(skin, release, output)


def test_never_writes_output_inside_skin_or_syncs_to_source(candidate):
    skin, release, _ = candidate
    with pytest.raises(package.PackageError):
        package.package_skin(skin, release, skin / "dist")
    with pytest.raises(package.PackageError):
        package.sync_source(skin, skin)


def test_reject_linked_asset_before_reading(candidate, monkeypatch):
    skin, release, output = candidate
    original = package._is_link
    monkeypatch.setattr(package, "_is_link", lambda path: path.name == "Colors.TGA" or original(path))
    with pytest.raises(package.PackageError, match="regular"):
        package.package_skin(skin, release, output)


def test_rejects_linked_output_ancestry_before_creating_directories(candidate, monkeypatch):
    skin, release, output = candidate
    output.mkdir()
    original = package._is_link
    monkeypatch.setattr(package, "_is_link", lambda path: path == output or original(path))
    with pytest.raises(package.PackageError, match="Linked"):
        package.package_skin(skin, release, output / "new" / "nested")
    assert not (output / "new").exists()


def test_repository_snapshot_parses_and_matches_release_contract():
    root = Path(__file__).resolve().parents[1]
    assets, ignored = package.collect_assets(root / "ui" / "skin")
    assert ignored == 0
    assert "EQUI_CastSpellWnd.xml" in assets
    assert "SIDL.xml" in assets
    release = package.load_release(root / "ui" / "release.json")
    assert release == {"schema": 2, "version": "1.44.65",
                       "skin_folder": "VantageUI-v1.44.65"}
