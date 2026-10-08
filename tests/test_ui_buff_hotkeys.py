"""Preset preparation uses verified temporary game fixtures, never a live install."""
import json
from dataclasses import replace
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


def test_current_pair_and_all_previous_pair_versions_are_retained():
    assert updater.BUFF_LAYOUT_VERSIONS == {'vertical': '1.44.109', 'horizontal': '1.44.110'}
    assert set(updater.BUFF_LAYOUT_RETAINED_VERSIONS) == {
        f'1.44.{patch}' for patch in range(102, 111)}


@pytest.mark.parametrize('already_horizontal', (False, True))
@pytest.mark.parametrize('checked_version', ('1.44.109', '1.44.110'))
def test_normal_update_prepares_both_and_reuses_checked_release(
        fixture, tmp_path, monkeypatch, already_horizontal, checked_version):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    if already_horizontal:
        updater.install_release(releases['1.44.110'], game, state, log=lambda _: None)
        horizontal_before = _tree(game / 'uifiles' / 'VantageUI-v1.44.110')
    requested, order, progress = [], [], []
    def check(version):
        requested.append(version)
        return releases[version]
    monkeypatch.setattr(updater, 'check_release_version', check)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        order.append(release.version)
        assert kwargs['prepare_buff_preset'] is True
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    result = updater.install_update(
        releases[checked_version], game, state, log=lambda _: None,
        progress=lambda stage, percent, *_: progress.append(percent))
    assert requested == ['1.44.110' if checked_version == '1.44.109' else '1.44.109']
    assert order == ['1.44.109', '1.44.110']
    assert result.action == 'buff-layouts-ready'
    assert result.version == '1.44.110' and result.folder == 'VantageUI-v1.44.110'
    assert result.changed_files == (1 if already_horizontal else 2)
    assert progress == sorted(progress) and progress[-1] == 100
    assert set(_registry(game)['managed']) == {'VantageUI-v1.44.109', 'VantageUI-v1.44.110'}
    if already_horizontal:
        assert _tree(game / 'uifiles' / 'VantageUI-v1.44.110') == horizontal_before


def test_legacy_update_keeps_single_release_result(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    release = _release(tmp_path, monkeypatch, version='1.44.108', schema=2)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('Legacy update is single-release'))
    result = updater.install_update(release, game, state, log=lambda _: None)
    assert result.action == 'installed' and result.version == '1.44.108'
    assert set(_registry(game)['managed']) == {'VantageUI-v1.44.108'}


def test_legacy_update_forwards_installer_arguments(monkeypatch):
    release = updater.parse_release_payload(_api())
    log = lambda _: None
    progress = lambda *_: None
    expected = updater.InstallResult(release.version, 0, 'already-current', 'fixture')
    def install(selected, game, state, **kwargs):
        assert selected is release and (game, state) == ('game', 'state')
        assert kwargs == {'log': log, 'allow_game_running': True, 'progress': progress}
        return expected
    monkeypatch.setattr(updater, 'install_release', install)
    assert updater.install_update(release, 'game', 'state', log, True, progress) is expected


@pytest.mark.parametrize('version', ('1.44.111', '1.45.0'))
def test_future_update_refuses_obsolete_pair_before_network_or_write(
        fixture, monkeypatch, version):
    game, _, state = fixture
    release = updater.parse_release_payload(_retag(_api(), 'vantage-ui-v' + version))
    before_game, before_state = _tree(game), _tree(state)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No obsolete pair fetch'))
    monkeypatch.setattr(updater, 'install_release', lambda *_: pytest.fail('No future writes'))
    with pytest.raises(updater.SkinUpdateError, match='Use its current updater'):
        updater.install_update(release, game, state, log=lambda _: None)
    assert _tree(game) == before_game and _tree(state) == before_state


@pytest.mark.parametrize('tag', ('v1.44.110', 'vantage-ui-v1.44.108'))
def test_supplied_horizontal_must_be_exact_current_namespaced_release(
        fixture, monkeypatch, tag):
    game, _, state = fixture
    release = updater.parse_release_payload(_retag(_api(), tag))
    before_game, before_state = _tree(game), _tree(state)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No preset fetch'))
    with pytest.raises(updater.SkinUpdateError, match='fixed native preset tag'):
        updater.prepare_buff_layouts(game, state, horizontal_release=release)
    assert _tree(game) == before_game and _tree(state) == before_state


@pytest.mark.parametrize('version', ('1.44.109', '1.44.110'))
def test_current_version_with_legacy_tag_cannot_claim_both_layouts(fixture, monkeypatch, version):
    game, _, state = fixture
    release = updater.parse_release_payload(_retag(_api(), 'v' + version))
    before = _tree(game)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No preset fetch'))
    with pytest.raises(updater.SkinUpdateError, match='fixed native preset tag'):
        updater.install_update(release, game, state)
    assert _tree(game) == before


@pytest.mark.parametrize('tag', ('v1.44.109', 'vantage-ui-v1.44.108'))
def test_supplied_vertical_must_be_exact_current_namespaced_release(fixture, monkeypatch, tag):
    game, _, state = fixture
    release = updater.parse_release_payload(_retag(_api(), tag))
    before_game, before_state = _tree(game), _tree(state)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No preset fetch'))
    with pytest.raises(updater.SkinUpdateError, match='fixed native preset tag'):
        updater.prepare_buff_layouts(game, state, vertical_release=release)
    assert _tree(game) == before_game and _tree(state) == before_state


@pytest.mark.parametrize('field', ('version', 'manifest_url', 'manifest_sha256'))
def test_malformed_checked_vertical_refuses_before_fetch_or_write(
        fixture, tmp_path, monkeypatch, field):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    selected = releases['1.44.109']
    changes = {'version': '1.44.108', 'manifest_url': selected.manifest_url + '?changed',
               'manifest_sha256': 'invalid-digest'}
    selected = replace(selected, **{field: changes[field]})
    before_game, before_state = _tree(game), _tree(state)
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No preset fetch'))
    with pytest.raises(updater.SkinUpdateError):
        updater.install_update(selected, game, state)
    assert _tree(game) == before_game and _tree(state) == before_state


@pytest.mark.parametrize('message', (
    'A newer UI release is available. Use its current updater to install it.',
    'A newer UI update requires its current updater.',
    'A newer UI is selected. Use its current updater to prepare buff layouts.'))
def test_newer_release_diagnostic_has_actionable_fixed_phrase_without_private_text(message):
    diagnostic = updater.error_diagnostic(updater.SkinUpdateError(message + ' Private fixture path'))
    assert diagnostic == ' [SkinUpdateError, A newer UI release requires its current updater]'
    assert 'Private fixture path' not in diagnostic


@pytest.mark.parametrize('tag', ('v1.44.109', 'vantage-ui-v1.44.108'))
def test_vertical_metadata_is_verified_before_either_install(fixture, tmp_path, monkeypatch, tag):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    wrong = updater.parse_release_payload(_retag(_api(), tag))
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: wrong)
    before_game, before_state = _tree(game), _tree(state)
    with pytest.raises(updater.SkinUpdateError, match='fixed native preset tag'):
        updater.install_update(releases['1.44.110'], game, state)
    assert _tree(game) == before_game and _tree(state) == before_state


def test_pair_sums_changes_and_reports_each_warning_once(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        result = real_install(release, *args, **kwargs)
        return replace(result, warnings=('Shared cleanup warning', release.version))
    monkeypatch.setattr(updater, 'install_release', install)
    result = updater.install_update(releases['1.44.110'], game, state, log=lambda _: None)
    assert result.changed_files == 2
    assert result.warnings == ('Shared cleanup warning', '1.44.109', '1.44.110')


def test_pair_preserves_running_game_policy_and_aggregates_cleanup_warning(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, 'game_running', lambda: True)
    before = _tree(game)
    with pytest.raises(updater.SkinUpdateError, match='Close EverQuest'):
        updater.install_update(releases['1.44.110'], game, state, log=lambda _: None)
    assert _tree(game) == before
    result = updater.install_update(releases['1.44.110'], game, state, log=lambda _: None,
                                    allow_game_running=True)
    assert result.action == 'buff-layouts-ready'
    assert result.warnings == ('Older managed UI folder cleanup is deferred while EverQuest is running.',)


def test_pair_prepares_immutable_skins_and_never_writes_hotkeys(fixture, tmp_path, monkeypatch):
    game, legacy, state = fixture
    (game / 'UI_Toon_P1999.ini').write_bytes(b'unchanged window positions')
    (game / 'Toon_P1999.ini').write_bytes(b'unchanged socials')
    before = {name: (game / name).read_bytes() for name in ('UI_Toon_P1999.ini', 'Toon_P1999.ini')}
    pair(tmp_path, monkeypatch)
    progress = []
    result = updater.prepare_buff_layouts(game, state, log=lambda _: None,
                                         progress=lambda stage, percent, *_: progress.append(percent))
    assert result.action == 'buff-layouts-ready' and result.version == '1.44.110'
    assert result.changed_files == 2
    assert _registry(game)['previous'] == 'VantageUI-v1.44.109'
    assert _registry(game)['active'] == 'VantageUI-v1.44.110'
    assert progress == sorted(progress) and progress[-1] == 100
    for orientation, version in updater.BUFF_LAYOUT_VERSIONS.items():
        assert (game / 'uifiles' / updater.folder_name(version) / 'EQUI_Test.xml').read_bytes() == orientation.encode()
    assert {name: (game / name).read_bytes() for name in before} == before
    snapshots = {version: _tree(game / 'uifiles' / updater.folder_name(version))
                 for version in updater.BUFF_LAYOUT_VERSIONS.values()}
    assert updater.prepare_buff_layouts(game, state, log=lambda _: None).changed_files == 0
    assert snapshots == {version: _tree(game / 'uifiles' / updater.folder_name(version))
                         for version in updater.BUFF_LAYOUT_VERSIONS.values()}


def test_normal_downgrade_remains_refused_and_preset_exception_is_narrow(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    result = updater.install_release(releases['1.44.110'], game, state, log=lambda _: None)
    assert result.action == 'installed'
    assert set(_registry(game)['managed']) == {'VantageUI-v1.44.110'}
    with pytest.raises(updater.SkinUpdateError, match='older release'):
        updater.install_release(releases['1.44.109'], game, state, log=lambda _: None)
    assert updater.prepare_buff_layouts(game, state, log=lambda _: None).version == '1.44.110'
    other = _release(tmp_path, monkeypatch, version='1.44.101', schema=2)
    with pytest.raises(updater.SkinUpdateError, match='fixed native buff presets'):
        updater.install_release(other, game, state, prepare_buff_preset=True)


def test_modified_horizontal_is_not_downgraded_or_replaced(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    updater.install_release(releases['1.44.110'], game, state, log=lambda _: None)
    path = game / 'uifiles' / 'VantageUI-v1.44.110' / 'EQUI_Test.xml'
    path.write_bytes(b'my personal edits')
    before = _tree(game / 'uifiles')
    with pytest.raises(updater.SkinUpdateError):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert _tree(game / 'uifiles') == before


def test_newer_selection_refuses_old_pair_before_network_or_write(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    release = _release(tmp_path, monkeypatch, version='1.44.111', schema=2)
    updater.install_release(release, game, state, log=lambda _: None)
    before = _tree(game / 'uifiles')
    monkeypatch.setattr(updater, 'check_release_version', lambda *_: pytest.fail('No network for obsolete pair'))
    with pytest.raises(updater.SkinUpdateError, match='newer UI'):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert _tree(game / 'uifiles') == before


@pytest.mark.parametrize('checked_version', (None, '1.44.109', '1.44.110'))
def test_second_failure_does_not_claim_ready_or_damage_first(
        fixture, tmp_path, monkeypatch, checked_version):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    progress = []
    def install(release, *args, **kwargs):
        if release.version == '1.44.110':
            raise updater.SkinUpdateError('Fixture interrupted second install')
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError, match='second install'):
        kwargs = {'log': lambda _: None,
                  'progress': lambda stage, percent, *_: progress.append(percent)}
        if checked_version is None:
            updater.prepare_buff_layouts(game, state, **kwargs)
        else:
            updater.install_update(releases[checked_version], game, state, **kwargs)
    assert progress == sorted(progress) and progress[-1] < 100
    assert updater.installed_version(game) == '1.44.109'
    assert (game / 'uifiles' / 'VantageUI-v1.44.109' / 'EQUI_Test.xml').read_bytes() == b'vertical'


def test_final_ready_gate_rechecks_both_trees_after_second_install(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    progress = []
    def install(release, *args, **kwargs):
        result = real_install(release, *args, **kwargs)
        if release.version == '1.44.110':
            (game / 'uifiles' / 'VantageUI-v1.44.109' / 'EQUI_Test.xml').write_bytes(b'concurrent edits')
        return result
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError):
        updater.prepare_buff_layouts(game, state, log=lambda _: None,
                                     progress=lambda stage, percent, *_: progress.append(percent))
    assert progress == sorted(progress) and progress[-1] < 100
    assert updater.installed_version(game) == '1.44.110'
    assert (game / 'uifiles' / 'VantageUI-v1.44.109' / 'EQUI_Test.xml').read_bytes() == b'concurrent edits'


def test_prepared_presets_survive_normal_future_cleanup(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    pair(tmp_path, monkeypatch)
    updater.prepare_buff_layouts(game, state, log=lambda _: None)
    for version in ('1.44.111', '1.44.112'):
        release = _release(tmp_path, monkeypatch, version=version, schema=2)
        updater.install_release(release, game, state, log=lambda _: None)
    assert set(_registry(game)['managed']) == {
        'VantageUI-v1.44.109', 'VantageUI-v1.44.110', 'VantageUI-v1.44.111', 'VantageUI-v1.44.112'}


def test_migrating_old_prepared_pair_preserves_registered_folders(fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    old_versions = tuple(f'1.44.{patch}' for patch in range(102, 109))
    for version in old_versions:
        release = _release(tmp_path, monkeypatch, version=version, schema=2)
        updater.install_release(release, game, state, log=lambda _: None)
    old = {version: _tree(game / 'uifiles' / updater.folder_name(version))
           for version in old_versions}
    pair(tmp_path, monkeypatch)
    updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert set(_registry(game)['managed']) == {
        updater.folder_name(version) for version in (*old_versions, '1.44.109', '1.44.110')}
    assert old == {version: _tree(game / 'uifiles' / updater.folder_name(version)) for version in old}


def test_preset_flag_does_not_allow_a_future_selection_to_prepare_old_vertical(
        fixture, tmp_path, monkeypatch):
    game, _, state = fixture
    old_release = _release(tmp_path, monkeypatch, version='1.44.111', schema=2)
    updater.install_release(old_release, game, state, log=lambda _: None)
    releases = pair(tmp_path, monkeypatch)
    before = _tree(game / 'uifiles')
    with pytest.raises(updater.SkinUpdateError, match='newer UI'):
        updater.install_release(releases['1.44.109'], game, state, log=lambda _: None,
                                prepare_buff_preset=True)
    assert _tree(game / 'uifiles') == before


@pytest.mark.parametrize('existing_vertical', (False, True))
@pytest.mark.parametrize('old_version', ('1.44.105', '1.44.106', '1.44.107', '1.44.108'))
def test_migrating_old_horizontal_upgrades_vertical_then_horizontal(
        fixture, tmp_path, monkeypatch, existing_vertical, old_version):
    game, _, state = fixture
    releases = pair(tmp_path, monkeypatch)
    pair_download = updater._download
    if existing_vertical:
        old_vertical = _release(tmp_path, monkeypatch, version='1.44.104', schema=2)
        updater.install_release(old_vertical, game, state, log=lambda _: None)
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
    assert order == ['1.44.109', '1.44.110']
    assert result.version == '1.44.110' and result.action == 'buff-layouts-ready'
    assert result.changed_files == 2
    assert progress == sorted(progress) and progress[-1] == 100
    expected = {updater.folder_name(old_version), 'VantageUI-v1.44.109', 'VantageUI-v1.44.110'}
    if existing_vertical:
        expected.add('VantageUI-v1.44.104')
    assert set(_registry(game)['managed']) == expected
    assert _tree(game / 'uifiles' / updater.folder_name(old_version)) == old_tree
    if existing_vertical:
        assert _tree(game / 'uifiles' / 'VantageUI-v1.44.104') == vertical_tree


@pytest.mark.parametrize('old_version', ('1.44.105', '1.44.106', '1.44.107', '1.44.108'))
@pytest.mark.parametrize('failed_version', ('1.44.109', '1.44.110'))
def test_migration_interruption_does_not_claim_ready_or_damage_old_horizontal(
        fixture, tmp_path, monkeypatch, old_version, failed_version):
    game, _, state = fixture
    old_release = _release(tmp_path, monkeypatch, version=old_version, schema=2)
    updater.install_release(old_release, game, state, log=lambda _: None)
    old_tree = _tree(game / 'uifiles' / updater.folder_name(old_version))
    pair(tmp_path, monkeypatch)
    real_install = updater.install_release
    def install(release, *args, **kwargs):
        if release.version == failed_version:
            raise updater.SkinUpdateError('Fixture interrupted buff preparation')
        return real_install(release, *args, **kwargs)
    monkeypatch.setattr(updater, 'install_release', install)
    with pytest.raises(updater.SkinUpdateError, match='interrupted buff'):
        updater.prepare_buff_layouts(game, state, log=lambda _: None)
    assert updater.installed_version(game) == (
        old_version if failed_version == '1.44.109' else '1.44.109')
    assert _tree(game / 'uifiles' / updater.folder_name(old_version)) == old_tree
