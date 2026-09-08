"""Retention policy tests. Destructive operations run only in tmp_path fixtures."""
from pathlib import Path
import pytest
from vantage.helpers import ui_skin_updater as updater
from tests.test_ui_skin_updater import fixture
from tests.test_ui_skin_versioned import _install, _registry, _folder, _tree

@pytest.mark.parametrize('active,previous,versions,retired,expected', [
    ('','',[],[],set()),
    ('1.2.3','',['1.2.3'],[],{'1.2.3'}),
    ('1.2.4','1.2.3',['1.2.3','1.2.4'],[],{'1.2.3','1.2.4'}),
    ('1.2.11','1.2.10',['1.2.9','1.2.8','1.2.11','1.2.10'],[],{'1.2.9','1.2.10','1.2.11'}),
    ('1.2.11','1.2.8',['1.2.9','1.2.8','1.2.11','1.2.10'],[],{'1.2.8','1.2.10','1.2.11'}),
    ('1.2.11','1.2.10',['1.2.9','1.2.8','1.2.11','1.2.10'],['1.2.9'],{'1.2.8','1.2.10','1.2.11'}),
    ('1.2.9','1.2.11',['1.2.7','1.2.8','1.2.9','1.2.11'],[],{'1.2.7','1.2.8','1.2.9','1.2.11'}),
])
def test_keep_plan_uses_numeric_registered_versions_without_filesystem_access(
        monkeypatch,active,previous,versions,retired,expected):
    name=lambda v: updater.folder_name(v) if v else ''
    registry={'active':name(active),'previous':name(previous),
              'managed':{name(v):{'quarantine':'.vantage-ui-retired-'+'a'*32 if v in retired else ''}
                         for v in versions}}
    def forbidden(*args,**kwargs):
        raise AssertionError('Retention planning must not inspect skin directories')
    for method in ('iterdir','glob','rglob','stat','lstat','read_bytes'):
        monkeypatch.setattr(Path,method,forbidden)
    assert updater._retained_folders(registry)=={name(v) for v in expected}

def test_deferred_backlog_cleans_to_three_and_is_idempotent(fixture,tmp_path,monkeypatch):
    game,legacy,state=fixture
    untouched=game/'uifiles'/'VantageUI-v0.1.0'
    untouched.mkdir();(untouched/'private.xml').write_bytes(b'unmanaged data')
    ini=game/'UI_Personal.ini';ini.write_bytes(b'personal layout')
    monkeypatch.setattr(updater,'game_running',lambda:True)
    for patch in range(3,11):
        _install(tmp_path,monkeypatch,game,state,f'1.2.{patch}',allow_game_running=True)
    snapshots={v:_tree(_folder(game,v)) for v in ('1.2.8','1.2.9','1.2.10')}
    assert len(_registry(game)['managed'])==8
    monkeypatch.setattr(updater,'game_running',lambda:False)
    logs=[]
    updater.recover_pending(game,state,log=logs.append)
    assert set(_registry(game)['managed'])=={updater.folder_name(v) for v in snapshots}
    assert _registry(game)['active']=='VantageUI-v1.2.10'
    assert _registry(game)['previous']=='VantageUI-v1.2.9'
    assert sum(line.startswith('Removed unchanged older managed folder') for line in logs)==5
    assert all(not _folder(game,f'1.2.{v}').exists() for v in range(3,8))
    assert all(_tree(_folder(game,v))==data for v,data in snapshots.items())
    assert (untouched/'private.xml').read_bytes()==b'unmanaged data'
    assert ini.read_bytes()==b'personal layout' and legacy.is_dir()
    before=_registry(game)
    updater.recover_pending(game,state,log=lambda _:None)
    assert _registry(game)==before

def test_rollback_preserves_both_fallback_payloads(fixture,tmp_path,monkeypatch):
    game,_,state=fixture
    for v in ('1.2.3','1.2.4','1.2.5','1.2.6'):
        _install(tmp_path,monkeypatch,game,state,v)
    snapshots={v:_tree(_folder(game,v)) for v in ('1.2.4','1.2.5','1.2.6')}
    updater.rollback_last(game,state,log=lambda _:None)
    updater.recover_pending(game,state,log=lambda _:None)
    assert updater.installed_version(game)=='1.2.5'
    assert _registry(game)['previous']=='VantageUI-v1.2.6'
    assert all(_tree(_folder(game,v))==data for v,data in snapshots.items())
