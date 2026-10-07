"""Preset preparation uses verified temporary game fixtures, never a live install."""
import json
from pathlib import Path

import pytest

from vantage.helpers import ui_skin_updater as updater
from tests.test_ui_skin_updater import _api, _release, _retag, fixture
from tests.test_ui_skin_versioned import _registry, _tree


def pair(tmp_path, monkeypatch):
    releases, assets = {}, {}
    for orientation, version in updater.BUFF_LAYOUT_VERSIONS.items():
        release = _release(tmp_path, monkeypatch, version=version, schema=2,
                           files={'EQUI_Test.xml': orientation.encode()})
        # Reuse the exact pinned fixture downloader before the next fixture replaces it.
        saved = tmp_path / ('saved-' + orientation)
        saved.mkdir()
        for url, name in ((release.manifest_url, 'manifest'), (release.payload_url, 'payload')):
            path = saved / name
            updater._download(url, path, updater.MAX_ARCHIVE_BYTES,
                              release.manifest_sha256 if name == 'manifest' else release.payload_sha256,
                              release.manifest_size if name == 'manifest' else release.payload_size)
            assets[url] = path.read_bytes()
        releases[version] = release
    def download(url, destination, limit, expected_hash=None, expected_size=None, progress=None):
        data = assets[url]
        assert len(data) <= limit
        assert updater._digest(data) == expected_hash and len(data) == expected_size
        Path(destination).write_bytes(data)
        if progress:
            progress(len(data), len(data))
    monkeypatch.setattr(updater, '_download', download)
    monkeypatch.setattr(updater, 'check_release_version', lambda version: releases[version])
    return releases


def test_exact_version_fetch_is_pinned_and_rejects_wrong_response(tmp_path, monkeypatch):
    requested = []
    def download(url, destination, limit):
        requested.append(url)
        Path(destination).write_text(json.dumps(_retag(_api(), 'vantage-ui-v1.44.102')))
    monkeypatch.setattr(updater, '_download', download)
    assert updater.check_release_version('1.44.102').version == '1.44.102'
    assert requested == [updater.RELEASES_API + '/tags/vantage-ui-v1.44.102']
    with pytest.raises(updater.SkinUpdateError, match='requested tag'):
        updater.check_release_version('1.44.103')
    with pytest.raises(updater.SkinUpdateError, match='Invalid'):
        updater.check_release_version('../main')


def test_pair_prepares_immutable_skins_and_never_writes_hotkeys(fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    (game / 'UI_Toon_P1999.ini').write_bytes(b'unchanged window positions')
    (game / 'Toon_P1999.ini').write_bytes(b'unchanged socials')
    before = {name: (game / name).read_bytes() for name in ('UI_Toon_P1999.ini', 'Toon_P1999.ini')}
    pair(tmp_path, monkeypatch)
    progress = []
    result = updater.prepare_buff_layouts(game, state, log=lambda _: None,
                                         progress=lambda stage, percent, *_: progress.append(percent))
    assert result.action == 'buff-layouts-ready' and result.version == '1.44.107'
    assert _registry(game)['previous'] == 'VantageUI-v1.44.104'
    assert _registry(game)['active'] == 'VantageUI-v1.44.107'
    assert progress == sorted(progress) and progress[-1] == 100
    for orientation, version in updater.BUFF_LAYOUT_VERSIONS.items():
        assert (game / 'uifiles' / updater.folder_name(version) / 'EQUI_Test.xml').read_bytes() == orientation.encode()
    assert {name: (game / name).read_bytes() for name in before} == before
    snapshots = {version: _tree(game / 'uifiles' / updater.folder_name(version))
                 for version in updater.BUFF_LAYOUT_VERSIONS.values()}
    updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert snapshots == {version: _tree(game / 'uifiles' / updater.folder_name(version))
                         for version in updater.BUFF_LAYOUT_VERSIONS.values()}


def test_normal_downgrade_remains_refused_and_preset_exception_is_narrow(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    updater.install_release(releases['1.44.107'], game, state, log=lambda _: None)
    with pytest.raises(updater.SkinUpdateError, match='older release'):
        updater.install_release(releases['1.44.104'], game, state, log=lambda _: None)
    assert updater.prepare_buff_layouts(game, state, log=lambda _: None).version == '1.44.107'
    other = _release(tmp_path, monkeypatch, version='1.44.101', schema=2)
    with pytest.raises(updater.SkinUpdateError, match='fixed native buff presets'):
        updater.install_release(other, game, state, prepare_buff_preset=True)


def test_modified_horizontal_is_not_downgraded_or_replaced(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    updater.install_release(releases['1.44.107'], game, state, log=lambda _: None)
    path = game / 'uifiles' / 'VantageUI-v1.44.107' / 'EQUI_Test.xml'
    path.write_bytes(b'my personal edits')
    before = _tree(game / 'uifiles')
    with pytest.raises(updater.SkinUpdateError):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert _tree(game / 'uifiles') == before


def test_newer_selection_refuses_old_pair_before_network_or_write(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    release = _release(tmp_path, monkeypatch, version='1.44.108', schema=2)
    updater.install_release(release, game, state, log=lambda _: None)
    before = _tree(game / 'uifiles')
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No network for obsolete pair'))
    with pytest.raises(updater.SkinUpdateError, match='newer UI'):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert _tree(game / 'uifiles') == before


def test_second_failure_does_not_claim_ready_or_damage_first(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        if release.version == '1.44.107':
            raise updater.SkinUpdateError('Fixture interrupted second install')
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError, match='second install'):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert updater.installed_version(game) == '1.44.104'
    assert (game / 'uifiles' / 'VantageUI-v1.44.104' / 'EQUI_Test.xml').read_bytes() == b'vertical'


def test_final_ready_gate_rechecks_both_trees_after_second_install(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        result = real_install(release, *args, **kwargs)
        if release.version == '1.44.107':
            (game / 'uifiles' / 'VantageUI-v1.44.104' / 'EQUI_Test.xml').write_bytes(b'concurrent edits')
        return result
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert updater.installed_version(game) == '1.44.107'
    assert (game / 'uifiles' / 'VantageUI-v1.44.104' / 'EQUI_Test.xml').read_bytes() == b'concurrent edits'


def test_prepared_presets_survive_normal_future_cleanup(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    pair(tmp_path, monkeypatch)
    updater.prepare_buff_layouts(game, state, log=lambda _: None)
    for version in ('1.44.108', '1.44.109'):
        release = _release(tmp_path, monkeypatch, version=version, schema=2)
        updater.install_release(release, game, state, log=lambda _: None)
    assert set(_registry(game)['managed']) == {
        'VantageUI-v1.44.104', 'VantageUI-v1.44.107', 'VantageUI-v1.44.108', 'VantageUI-v1.44.109'}


def test_migrating_old_prepared_pair_preserves_registered_folders(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    for version in ('1.44.102', '1.44.103'):
        release = _release(tmp_path, monkeypatch, version=version, schema=2)
        updater.install_release(release, game, state, log=lambda _: None)
    old = {version: _tree(game / 'uifiles' / updater.folder_name(version))
           for version in ('1.44.102', '1.44.103')}
    pair(tmp_path, monkeypatch)
    updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert set(_registry(game)['managed']) == {
        'VantageUI-v1.44.102', 'VantageUI-v1.44.103', 'VantageUI-v1.44.104', 'VantageUI-v1.44.107'}
    assert old == {version: _tree(game / 'uifiles' / updater.folder_name(version)) for version in old}


@pytest.mark.parametrize('old_version', ('1.44.105', '1.44.106'))
def test_preset_flag_does_not_allow_direct_old_horizontal_to_104(fixture, tmp_path, monkeypatch,
                                                              old_version):
    game, _, state = fixture
    old_release = _release(tmp_path, monkeypatch, version=old_version, schema=2)
    updater.install_release(old_release, game, state, log=lambda _: None)
    releases = pair(tmp_path, monkeypatch)
    before = _tree(game / 'uifiles')
    with pytest.raises(updater.SkinUpdateError, match='older release'):
        updater.install_release(releases['1.44.104'], game, state, log=lambda _: None,
                                prepare_buff_preset=True)
    assert _tree(game / 'uifiles') == before


@pytest.mark.parametrize('existing_vertical', (False, True))
@pytest.mark.parametrize('old_version', ('1.44.105', '1.44.106'))
def test_migrating_old_horizontal_upgrades_before_preparing_older_vertical(
        fixture, tmp_path, monkeypatch, existing_vertical, old_version):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    pair_download = updater._download
    if existing_vertical:
        updater.install_release(releases['1.44.104'], game, state, log=lambda _: None)
        vertical_tree = _tree(game / 'uifiles' / 'VantageUI-v1.44.104')
    old_release = _release(tmp_path, monkeypatch, version=old_version, schema=2)
    updater.install_release(old_release, game, state, log=lambda _: None)
    old_tree = _tree(game / 'uifiles' / updater.folder_name(old_version))
    # Keep the original fetched bytes: rebuilding a fixture ZIP at a later
    # timestamp would correctly look like an overwritten immutable release.
    monkeypatch.setattr(updater, '_download', pair_download)
    real_install = updater.install_release
    order, progress = [], []
    def install(release, *args, **kwargs):
        order.append(release.version)
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    result = updater.prepare_buff_layouts(game, state, log=lambda _: None,
                                         progress=lambda stage, percent, *_: progress.append(percent))
    assert order == ['1.44.107', '1.44.104', '1.44.107']
    assert result.version == '1.44.107' and result.action == 'buff-layouts-ready'
    assert progress == sorted(progress) and progress[-1] == 100
    assert set(_registry(game)['managed']) == {
        'VantageUI-v1.44.104', updater.folder_name(old_version), 'VantageUI-v1.44.107'}
    assert _tree(game / 'uifiles' / updater.folder_name(old_version)) == old_tree
    if existing_vertical:
        assert _tree(game / 'uifiles' / 'VantageUI-v1.44.104') == vertical_tree


@pytest.mark.parametrize('old_version', ('1.44.105', '1.44.106'))
def test_migration_interruption_does_not_claim_ready_or_damage_old_horizontal(
        fixture, tmp_path, monkeypatch, old_version):
    game, _, state = fixture
    old_release = _release(tmp_path, monkeypatch, version=old_version, schema=2)
    updater.install_release(old_release, game, state, log=lambda _: None)
    old_tree = _tree(game / 'uifiles' / updater.folder_name(old_version))
    pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        if release.version == '1.44.104':
            raise updater.SkinUpdateError('Fixture interrupted vertical preparation')
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError, match='interrupted vertical'):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert updater.installed_version(game) == '1.44.107'
    assert _tree(game / 'uifiles' / updater.folder_name(old_version)) == old_tree
