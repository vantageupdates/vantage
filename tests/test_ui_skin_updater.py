"""Offline safety tests: fixtures never access or alter a real EverQuest install."""

import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest

from vantage.helpers import ui_skin_updater as updater


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _entry(name, data=b"new UI"):
    return {"path": name, "size": len(data), "sha256": _hash(data)}


def _manifest(entries, **changes):
    value = {"schema": 1, "skin_folder": updater.SKIN_FOLDER, "version": "1.2.3", "files": entries}
    value.update(changes)
    return json.dumps(value).encode()


def _api(manifest=b"{}", archive=b"zip"):
    return {"id": 123, "tag_name": "v1.2.3", "draft": False, "prerelease": False,
            "assets": [{"name": name, "size": len(data), "digest": "sha256:" + _hash(data),
                        "browser_download_url": f"https://github.com/{updater.REPOSITORY}/releases/download/v1.2.3/{name}"}
                       for name, data in ((updater.MANIFEST_ASSET, manifest), (updater.PAYLOAD_ASSET, archive))]}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    game = tmp_path / "EverQuest"
    game.mkdir()
    (game / "eqgame.exe").write_bytes(b"fixture, not executable")
    (game / "uifiles").mkdir()
    target = game / "uifiles" / updater.SKIN_FOLDER
    target.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(updater, "game_running", lambda: False)
    return game, target, state


def _release(tmp_path, monkeypatch, files=None, manifest=None, version="1.2.3", schema=1):
    files = files or {"EQUI_Test.xml": b"<XML>new</XML>", "button.tga": b"new pixels"}
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as payload:
        for name, data in files.items():
            payload.writestr(name, data)
    manifest = manifest or _manifest([_entry(name, data) for name, data in files.items()],
        version=version, schema=schema,
        skin_folder=updater.SKIN_FOLDER if schema == 1 else updater.folder_name(version))
    data = archive.read_bytes()
    release = updater.parse_release_payload(_retag(_api(manifest, data), "vantage-ui-v" + version))
    assets = {release.manifest_url: manifest, release.payload_url: data}

    def download(url, destination, limit, expected_hash=None, expected_size=None,
                 progress=None):
        content = assets[url]
        assert len(content) <= limit
        assert _hash(content) == expected_hash
        assert len(content) == expected_size
        Path(destination).write_bytes(content)
        if progress:
            progress(len(content), len(content))

    monkeypatch.setattr(updater, "_download", download)
    return release


def test_stable_release_binds_both_exact_assets_and_digests():
    release = updater.parse_release_payload(_api())
    assert release.version == "1.2.3"
    assert release.release_id == 123
    assert release.manifest_sha256 == _hash(b"{}")
    assert updater.SKIN_FOLDER == "VantageUI"


@pytest.mark.parametrize("change", ["digest", "url", "size", "name", "duplicate", "cross-release"])
def test_release_rejects_untrusted_assets(change):
    value = _api()
    asset = value["assets"][0]
    if change == "digest":
        asset["digest"] = "sha256:" + "x" * 64
    elif change == "url":
        asset["browser_download_url"] = "https://evil.example/VantageUI-manifest.json"
    elif change == "cross-release":
        asset["browser_download_url"] = asset["browser_download_url"].replace("v1.2.3", "v1.2.4")
    elif change == "size":
        asset["size"] = updater.MAX_MANIFEST_BYTES + 1
    elif change == "name":
        asset["name"] = asset["name"].lower()
    else:
        value["assets"].append(asset.copy())
    with pytest.raises(updater.SkinUpdateError):
        updater.parse_release_payload(value)


@pytest.mark.parametrize("tag", ["v01.2.3", "v1.2", "v1.2.3-rc1", "main", "v1.2.3/path"])
def test_unstable_or_invalid_version_refused(tag):
    value = _api()
    value["tag_name"] = tag
    with pytest.raises(updater.SkinUpdateError):
        updater.parse_release_payload(value)


@pytest.mark.parametrize("name", ["../bad.xml", "a/b.xml", "a\\b.xml", "C:bad.xml", "a.xml:evil", "CON.xml",
                                  "LPT1.tga", "COM¹.png", "a.xml.", " a.xml", "bad.exe", "x.ini", "a\x00.xml"])
def test_manifest_refuses_path_attacks_and_non_ui_files(name):
    with pytest.raises(updater.SkinUpdateError):
        updater.validate_manifest(_manifest([_entry(name)]), "1.2.3")


@pytest.mark.parametrize("changes", [{"schema": True}, {"schema": 2}, {"skin_folder": "default"}, {"version": "1.2.4"}])
def test_manifest_binds_skin_version_and_schema(changes):
    with pytest.raises(updater.SkinUpdateError):
        updater.validate_manifest(_manifest([_entry("a.xml")], **changes), "1.2.3")


def test_manifest_rejects_windows_case_aliases_and_resource_bombs():
    for entries in ([ _entry("a.xml"), _entry("A.xml") ],
                    [dict(_entry("a.xml"), size=updater.MAX_FILE_BYTES + 1)],
                    [_entry(f"a{i}.xml") for i in range(updater.MAX_FILES + 1)],
                    [dict(_entry(f"a{i}.xml"), size=updater.MAX_FILE_BYTES) for i in range(9)]):
        with pytest.raises(updater.SkinUpdateError):
            updater.validate_manifest(_manifest(entries), "1.2.3")


@pytest.mark.parametrize("attack", ["symlink", "directory", "traversal", "extra", "wronghash", "wrongsize"])
def test_archive_validation_before_any_install(tmp_path, attack):
    archive = tmp_path / "attack.zip"
    name = "../a.xml" if attack == "traversal" else "a.xml"
    info = zipfile.ZipInfo(name)
    if attack == "symlink":
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    elif attack == "directory":
        info.external_attr = 0x10
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr(info, b"new UI")
        if attack == "extra":
            payload.writestr("extra.xml", b"new UI")
    entry = _entry("a.xml")
    if attack == "wronghash":
        entry["sha256"] = "0" * 64
    elif attack == "wrongsize":
        entry["size"] += 1
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(updater.SkinUpdateError):
        updater.stage_archive(archive, [entry], staging)


def test_active_game_refuses_before_network_or_mutation(fixture, tmp_path, monkeypatch):
    game, target, state = fixture
    release = _release(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "game_running", lambda: True)
    monkeypatch.setattr(updater, "_download", lambda *args: pytest.fail("Network must not be used"))
    with pytest.raises(updater.SkinUpdateError, match="Close EverQuest"):
        updater.install_release(release, game, state)
    assert list(target.iterdir()) == []


def test_failed_payload_hash_does_not_mutate_skin(fixture, tmp_path, monkeypatch):
    game, target, state = fixture
    (target / "EQUI_Test.xml").write_bytes(b"old")
    bad = _manifest([_entry("EQUI_Test.xml", b"wrong hash content"), _entry("button.tga", b"new pixels")])
    release = _release(tmp_path, monkeypatch, manifest=bad)
    with pytest.raises(updater.SkinUpdateError):
        updater.install_release(release, game, state)
    assert sorted(p.name for p in target.iterdir()) == ["EQUI_Test.xml"]
    assert (target / "EQUI_Test.xml").read_bytes() == b"old"


def test_live_install_is_explicit_opt_in_and_reports_monotonic_progress(
        fixture, tmp_path, monkeypatch):
    game, target, state = fixture
    release = _release(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "game_running", lambda: True)
    events = []
    result = updater.install_release(
        release, game, state, allow_game_running=True,
        progress=lambda *event: events.append(event), log=lambda _line: None)
    assert result.action == "installed"
    assert updater.installed_version(game) == "1.2.3"
    values = [event[1] for event in events]
    assert values == sorted(values)
    assert values[0] == 0 and values[-1] == 100
    assert any("do not reload" in event[0] for event in events)
    assert any(event[3] > 0 for event in events)


def test_second_instance_cannot_acquire_same_target_lock(fixture):
    _, target, _ = fixture
    with updater._target_lock(target):
        with pytest.raises(updater.SkinUpdateError, match="already installing"):
            with updater._target_lock(target):
                pytest.fail("Second instance obtained the lock")


def test_state_inside_game_and_invalid_game_directory_refused(fixture, tmp_path, monkeypatch):
    game, target, state = fixture
    release = _release(tmp_path, monkeypatch)
    with pytest.raises(updater.SkinUpdateError, match="outside"):
        updater.install_release(release, game, game / "backups")
    with pytest.raises(updater.SkinUpdateError, match="eqgame.exe"):
        updater.install_release(release, tmp_path, state)


@pytest.mark.parametrize("url", ["http://github.com/x", "https://github.com.evil.example/x",
                                "https://evil.example/x", "https://user@github.com/x", "https://github.com:444/x"])
def test_redirect_attack_is_refused(url):
    source = f"https://github.com/{updater.REPOSITORY}/releases/download/v1.2.3/{updater.PAYLOAD_ASSET}"
    handler = updater._PinnedRedirects(source)
    request = updater.urllib.request.Request(source)
    with pytest.raises(updater.SkinUpdateError):
        handler.redirect_request(request, None, 302, "Found", {}, url)


def test_release_asset_redirect_is_allowed():
    source = f"https://github.com/{updater.REPOSITORY}/releases/download/v1.2.3/{updater.PAYLOAD_ASSET}"
    handler = updater._PinnedRedirects(source)
    request = updater.urllib.request.Request(source)
    redirected = handler.redirect_request(request, None, 302, "Found", {},
        "https://release-assets.githubusercontent.com/github-production-release-asset/file?signature=abc")
    assert redirected.host == "release-assets.githubusercontent.com"


def test_reparse_point_is_rejected_without_requiring_symlink_privileges(fixture, monkeypatch):
    game, legacy, _ = fixture
    target = game / "uifiles"
    actual = Path.lstat

    def attributes(path, *args, **kwargs):
        info = actual(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", attributes)
    with pytest.raises(updater.SkinUpdateError, match="Links and junctions"):
        updater._target(game)


class _Response:
    def __init__(self, data, length=None):
        self.data = data
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


@pytest.mark.parametrize("attack", ["overflow", "oversized-header", "wrong-digest", "truncated"])
def test_network_stream_is_bounded_and_hash_pinned(tmp_path, monkeypatch, attack):
    data = b"1234567890"
    limit = 20
    expected_hash = _hash(data)
    expected_size = len(data)
    length = None
    if attack == "overflow":
        limit = 5
    elif attack == "oversized-header":
        length = 100
    elif attack == "wrong-digest":
        expected_hash = "0" * 64
    else:
        expected_size += 1
    response = _Response(data, length)
    monkeypatch.setattr(updater.urllib.request, "build_opener",
                        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: response))
    with pytest.raises(updater.SkinUpdateError):
        updater._download(f"https://github.com/{updater.REPOSITORY}/releases/download/v1.2.3/{updater.PAYLOAD_ASSET}",
                          tmp_path / "download", limit, expected_hash, expected_size)


def test_game_opened_immediately_before_replace_is_refused(fixture, monkeypatch):
    _, target, _ = fixture
    path = target / "a.xml"
    path.write_bytes(b"original")
    monkeypatch.setattr(updater, "game_running", lambda: True)
    with pytest.raises(updater.SkinUpdateError, match="Close EverQuest"):
        updater._atomic_bytes(path, b"update", before_replace=updater._require_game_closed)
    assert path.read_bytes() == b"original"
    assert not list(target.glob(".vantage-ui-stage-*"))


def test_hardlinked_lock_cannot_write_outside_skin(fixture, tmp_path):
    _, target, _ = fixture
    outside = tmp_path / "outside-empty.txt"
    outside.write_bytes(b"")
    os.link(outside, target / updater.LOCK_NAME)
    with pytest.raises(updater.SkinUpdateError, match="hard-linked"):
        with updater._target_lock(target):
            pytest.fail("Hard-linked lock acquired")
    assert outside.read_bytes() == b""


def _release_lookup(monkeypatch, responses):
    calls = []

    def download(url, destination, limit, *args):
        calls.append(url)
        assert limit == 4 * 1024 * 1024
        assert url in responses, f"Unexpected/unbounded release discovery: {url}"
        Path(destination).write_bytes(json.dumps(responses[url]).encode())

    monkeypatch.setattr(updater, "_download", download)
    return calls


def _retag(payload, tag):
    payload = json.loads(json.dumps(payload))
    old_tag = payload["tag_name"]
    payload["tag_name"] = tag
    for asset in payload["assets"]:
        asset["browser_download_url"] = asset["browser_download_url"].replace(
            f"/{old_tag}/", f"/{tag}/")
    return payload


def test_legacy_ui_release_works_from_bounded_history(monkeypatch):
    page = f"{updater.RELEASES_API}?per_page=20&page=1"
    calls = _release_lookup(monkeypatch, {page: [_api()]})
    assert updater.check_release().version == "1.2.3"
    assert calls == [page]


def test_new_namespaced_ui_tag_wins_by_semantic_version(monkeypatch):
    main_only = dict(_api(), tag_name="v9.0.0", assets=[])
    future = _retag(_api(), "vantage-ui-v2.0.0")
    page = f"{updater.RELEASES_API}?per_page=20&page=1"
    calls = _release_lookup(monkeypatch, {
        page: [_api(), main_only, future]})
    result = updater.check_release()
    assert result.version == "2.0.0"
    assert result.tag == "vantage-ui-v2.0.0"
    assert f"/{result.tag}/" in result.payload_url
    assert calls == [page]


@pytest.mark.parametrize("broken", ["missing-pair", "bad-digest", "duplicate", "cross-release"])
def test_malformed_recognized_ui_release_never_silently_falls_back(monkeypatch, broken):
    latest = _retag(_api(), "vantage-ui-v2.0.0")
    if broken == "missing-pair":
        latest["assets"].pop()
    elif broken == "bad-digest":
        latest["assets"][0]["digest"] = ""
    elif broken == "duplicate":
        latest["assets"].append(latest["assets"][0].copy())
    else:
        latest["assets"][0]["browser_download_url"] = "https://github.com/another/repo/asset"
    page = f"{updater.RELEASES_API}?per_page=20&page=1"
    calls = _release_lookup(monkeypatch, {page: [latest, _api()]})
    with pytest.raises(updater.SkinUpdateError):
        updater.check_release()
    assert calls == [page]


def test_broken_ui_release_in_history_is_not_skipped_for_older_good_one(monkeypatch):
    broken = _api()
    broken["assets"].pop()
    page = f"{updater.RELEASES_API}?per_page=20&page=1"
    _release_lookup(monkeypatch, {page: [broken, _api()]})
    with pytest.raises(updater.SkinUpdateError, match="exactly one"):
        updater.check_release()


def test_ui_release_discovery_is_bounded_to_two_twenty_item_pages(monkeypatch):
    main_only = dict(_api(), assets=[])
    responses = {f"{updater.RELEASES_API}?per_page=20&page={page}": [main_only] * 20
                 for page in (1, 2)}
    calls = _release_lookup(monkeypatch, responses)
    with pytest.raises(updater.SkinUpdateError, match="latest 40 releases"):
        updater.check_release()
    assert len(calls) == 2


def test_second_history_page_can_supply_paired_ui_release(monkeypatch):
    main_only = dict(_api(), assets=[])
    responses = {f"{updater.RELEASES_API}?per_page=20&page=1": [main_only] * 20,
                 f"{updater.RELEASES_API}?per_page=20&page=2": [_api()]}
    calls = _release_lookup(monkeypatch, responses)
    assert updater.check_release().version == "1.2.3"
    assert len(calls) == 2
