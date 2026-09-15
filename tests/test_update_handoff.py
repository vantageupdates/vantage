import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


INSTALL_SCRIPT = r"""
import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QTimer
import semver

from vantage.helpers import config, updater
from vantage.helpers.application import VantageApp
from vantage.helpers.updater import UpdateDialog
from vantage.parsers.spells import Spell

app = VantageApp([])
spells = app._parsers_dict['spells']
container = spells._spell_container
started = datetime.datetime.now()
self_buff = Spell(
    name='Update Self Buff', runtime_key='spell:update-self',
    duration_seconds=300, duration=50, duration_formula=0, type=1,
    spell_icon=42, skill=4, effect_text_you='You feel updated.',
    effect_text_other=' feels updated.',
    effect_text_worn_off='Your update fades.')
mob_debuff = Spell(
    name='Update Mob Debuff', runtime_key='spell:update-mob',
    duration_seconds=240, duration=40, duration_formula=0, type=0,
    spell_icon=17, skill=5, effect_text_you='',
    effect_text_other="'s update slows.",
    effect_text_worn_off='The update wears off.')
faded = Spell(
    name='Already Faded', runtime_key='spell:faded',
    duration_seconds=600, duration=100, duration_formula=0, type=1)
expired = Spell(
    name='Already Expired', runtime_key='spell:expired',
    duration_seconds=600, duration=100, duration_formula=0, type=1)
container.add_spell(
    self_buff, started, '__you__', 'Mindflux', 'Green')
container.add_spell(
    mob_debuff, started, 'a crystalline devourer', 'Mindflux', 'Green')
mob = container.get_spell_target_by_name('a crystalline devourer')
mob.instance_marker = 'B'
mob.alias = 'West ramp'
mob.is_named = True
container.add_spell(faded, started, '__you__', 'Mindflux', 'Green')
container.add_spell(expired, started, '__you__', 'Mindflux', 'Green')
self_target = container.get_spell_target_by_name('__you__')
next(widget for widget in self_target.spell_widgets()
     if widget.spell.name == 'Already Faded').mark_faded(
         started + datetime.timedelta(seconds=1), play_sound=False)
next(widget for widget in self_target.spell_widgets()
     if widget.spell.name == 'Already Expired').end_time = (
         started - datetime.timedelta(seconds=1))

staged = Path(config._filename).parent / 'verified-Vantage.exe'
target = Path(config._filename).parent / 'Vantage.exe'
payload = b'MZ' + b'vantage-update-regression'
staged.write_bytes(payload)
target.write_bytes(b'MZold')
digest = hashlib.sha256(payload).hexdigest()
info = SimpleNamespace(
    version=semver.VersionInfo.parse('99.0.0'),
    digest='sha256:' + digest)
spawned = []
updater.sys.frozen = True
updater.sys.executable = str(target)
updater.subprocess.Popen = lambda command, **kwargs: spawned.append(command)

# Reproduce the real shutdown race: after the updater owns a verified handoff,
# a late UI/sync teardown observes an empty container and writes that stale
# state just before QApplication.aboutToQuit performs its final checkpoint.
real_checkpoint_for_update = app.checkpoint_for_update
def checkpoint_then_teardown():
    complete = real_checkpoint_for_update()
    if complete:
        container.snapshot_runtime_state = lambda: []
        config.data['spells']['active_timer_state'] = []
        config.save()
    return complete
app.checkpoint_for_update = checkpoint_then_teardown

dialog = UpdateDialog(app._update_controller)
dialog.info = info
dialog.staged_path = str(staged)
dialog.open_ui_after_restart.setChecked(True)
# A failed install must produce a deterministic assertion, never strand this
# regression subprocess inside the Qt event loop.
QTimer.singleShot(8000, app.quit)
QTimer.singleShot(0, dialog.install)
app.exec()

with open(config._filename, encoding='utf-8') as source:
    persisted = json.load(source)
rows = persisted['spells']['active_timer_state']
print(json.dumps({
    'spawned': len(spawned),
    'open_ui_flag': bool(spawned) and '--open-vantage-ui' in spawned[0],
    'names_after_quit': sorted(row['spell']['name'] for row in rows),
    'rows_after_quit': rows,
}))
"""


RESTORE_SCRIPT = r"""
import json
import time

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.update_handoff import spell_handoff_path

persisted = list(config.data['spells']['active_timer_state'])
app = VantageApp([])
spells = app._parsers_dict['spells']
rows = spells._spell_container.snapshot_runtime_state()
print(json.dumps({
    'names': sorted(row['spell']['name'] for row in rows),
    'targets': sorted(row['target'] for row in rows),
    'characters': sorted(set(row['character'] for row in rows)),
    'servers': sorted(set(row['server'] for row in rows)),
    'mob_marker': next(row['target_marker'] for row in rows
                       if row['target'] == 'a crystalline devourer'),
    'mob_alias': next(row['target_alias'] for row in rows
                      if row['target'] == 'a crystalline devourer'),
    'mob_named': next(row['target_named'] for row in rows
                      if row['target'] == 'a crystalline devourer'),
    'remaining': {
        row['spell']['name']: round(row['deadline'] - time.time(), 1)
        for row in rows},
    'persisted_deadlines': {
        row['spell']['name']: row['deadline'] for row in persisted},
    'handoff_consumed': not spell_handoff_path().exists(),
}))
app.quit()
"""


COUNT_RESTORE_SCRIPT = r"""
import json

from vantage.helpers.application import VantageApp
from vantage.helpers.update_handoff import spell_handoff_path

app = VantageApp([])
rows = app._parsers_dict['spells']._spell_container.snapshot_runtime_state()
print(json.dumps({
    'names': sorted(row['spell']['name'] for row in rows),
    'handoff_exists': spell_handoff_path().exists(),
}))
app.quit()
"""


def _run(script, profile, *, updated_from=''):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(profile)
    if updated_from:
        env['VANTAGE_UPDATED_FROM'] = updated_from
    else:
        env.pop('VANTAGE_UPDATED_FROM', None)
    completed = subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_real_update_dialog_quit_and_fresh_process_restore_all_active_spells(
        tmp_path):
    profile = tmp_path / 'profile'
    installed = _run(INSTALL_SCRIPT, profile)

    assert installed['spawned'] == 1
    assert installed['open_ui_flag'] is True
    assert installed['names_after_quit'] == [
        'Update Mob Debuff', 'Update Self Buff']
    assert {row['target'] for row in installed['rows_after_quit']} == {
        '__you__', 'a crystalline devourer'}

    # Reproduce the observed field failure where the ordinary config did not
    # retain its update-time rows. The dedicated handoff must still carry the
    # exact verified checkpoint into the replacement executable.
    config_file = profile / 'vantage.config.json'
    stale = json.loads(config_file.read_text(encoding='utf-8'))
    stale['spells']['active_timer_state'] = []
    config_file.write_text(json.dumps(stale), encoding='utf-8')

    # Make the second process prove that absolute deadlines age during the
    # update/restart interval instead of restarting full-duration timers.
    time.sleep(1.1)
    restored = _run(
        RESTORE_SCRIPT, profile, updated_from='1.44.85')

    assert restored['names'] == ['Update Mob Debuff', 'Update Self Buff']
    assert restored['targets'] == ['__you__', 'a crystalline devourer']
    assert restored['characters'] == ['Mindflux']
    assert restored['servers'] == ['Green']
    assert restored['mob_marker'] == 'B'
    assert restored['mob_alias'] == 'West ramp'
    assert restored['mob_named'] is True
    assert restored['handoff_consumed'] is True
    assert 0 < restored['remaining']['Update Self Buff'] < 300
    assert 0 < restored['remaining']['Update Mob Debuff'] < 240


def test_fresh_process_recovers_newer_handoff_without_environment_marker_but_not_after_user_save(
        tmp_path):
    from vantage.helpers.update_apply import _stamp_spell_handoff
    from vantage.helpers.update_handoff import write_spell_handoff

    now = time.time()
    live_row = {
        'deadline': now + 600,
        'target': '__you__',
        'target_created_order': 1,
        'target_marker': '',
        'character': 'Spiritflux',
        'server': 'P1999 Green',
        'spell': {
            'name': 'Focus of Spirit',
            'runtime_key': 'focus of spirit',
        },
    }

    recovered_profile = tmp_path / 'missing-marker-recovered'
    recovered_profile.mkdir()
    recovered_config = recovered_profile / 'vantage.config.json'
    write_spell_handoff(
        [live_row], path=recovered_profile / 'update-spell-handoff.json',
        now=now)
    # Reproduce the actual order: QApplication/aboutToQuit writes config after
    # the checkpoint, then the successful updater stamps the sidecar only once
    # the old process is gone and the swap has completed.
    recovered_config.write_text(json.dumps({
        'spells': {'active_timer_state': []},
    }), encoding='utf-8')
    os.utime(recovered_config, (now + 1, now + 1))
    assert _stamp_spell_handoff(
        path=recovered_profile / 'update-spell-handoff.json',
        now=now + 2) is True

    recovered = _run(COUNT_RESTORE_SCRIPT, recovered_profile)
    assert recovered['names'] == ['Focus of Spirit']
    assert recovered['handoff_exists'] is False

    changed_profile = tmp_path / 'missing-marker-user-changed'
    changed_profile.mkdir()
    changed_config = changed_profile / 'vantage.config.json'
    changed_config.write_text(json.dumps({
        'spells': {'active_timer_state': []},
    }), encoding='utf-8')
    write_spell_handoff(
        [live_row], path=changed_profile / 'update-spell-handoff.json',
        now=now)
    assert _stamp_spell_handoff(
        path=changed_profile / 'update-spell-handoff.json',
        now=now + 1) is True
    # A config write after the applied stamp represents normal operation or an
    # explicit removal and must remain authoritative over the stale sidecar.
    os.utime(changed_config, (now + 2, now + 2))

    rejected = _run(COUNT_RESTORE_SCRIPT, changed_profile)
    assert rejected['names'] == []
    assert rejected['handoff_exists'] is True


def test_checkpoint_verification_rejects_stale_disk_without_spawning(
        monkeypatch, tmp_path):
    from vantage.helpers import updater
    from vantage.helpers.updater import UpdateController

    candidate = tmp_path / 'new.exe'
    target = tmp_path / 'Vantage.exe'
    candidate.write_bytes(b'MZnew')
    target.write_bytes(b'MZold')
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    info = SimpleNamespace(digest='sha256:' + digest)

    class _Signal:
        def connect(self, _callback):
            pass

    class _App:
        aboutToQuit = _Signal()

        def checkpoint_for_update(self):
            return False

    spawned = []
    monkeypatch.setattr(updater.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updater.sys, 'executable', str(target))
    monkeypatch.setattr(
        updater.QApplication, 'instance', staticmethod(lambda: _App()))
    monkeypatch.setattr(updater.subprocess, 'Popen', lambda *a, **k: spawned.append(a))
    controller = UpdateController('1.0.0')

    try:
        controller.launch_installer(info, candidate)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError('Unverified state allowed the updater to start')

    assert spawned == []
    assert 'cancelled' in message
    assert 'remains open' in message


def test_launch_installer_forwards_one_shot_vantageui_handoff(
        monkeypatch, tmp_path):
    from vantage.helpers import updater
    from vantage.helpers.updater import UpdateController

    candidate = tmp_path / 'new.exe'
    target = tmp_path / 'Vantage.exe'
    candidate.write_bytes(b'MZnew')
    target.write_bytes(b'MZold')
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    info = SimpleNamespace(digest='sha256:' + digest)

    class _Signal:
        def connect(self, _callback):
            pass
    class _App:
        aboutToQuit = _Signal()
        def checkpoint_for_update(self):
            return True

    spawned = []
    monkeypatch.setattr(updater.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updater.sys, 'executable', str(target))
    monkeypatch.setattr(
        updater.QApplication, 'instance', staticmethod(lambda: _App()))
    monkeypatch.setattr(
        updater.subprocess, 'Popen',
        lambda command, **kwargs: spawned.append((command, kwargs)))
    controller = UpdateController('1.0.0')
    controller.launch_installer(
        info, candidate, open_vantage_ui=True)
    assert '--open-vantage-ui' in spawned[0][0]


def test_installer_spawn_failure_cancels_frozen_spell_handoff(
        monkeypatch, tmp_path):
    import pytest
    from vantage.helpers import updater
    from vantage.helpers.updater import UpdateController

    candidate = tmp_path / 'new.exe'
    target = tmp_path / 'Vantage.exe'
    candidate.write_bytes(b'MZnew')
    target.write_bytes(b'MZold')
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    info = SimpleNamespace(digest='sha256:' + digest)

    class _Signal:
        @staticmethod
        def connect(_callback):
            pass

    class _App:
        cancelled = False
        aboutToQuit = _Signal()

        @staticmethod
        def checkpoint_for_update():
            return True

        def cancel_update_handoff(self):
            self.cancelled = True

    app = _App()
    monkeypatch.setattr(updater.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updater.sys, 'executable', str(target))
    monkeypatch.setattr(
        updater.QApplication, 'instance', staticmethod(lambda: app))
    monkeypatch.setattr(
        updater.subprocess, 'Popen',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError('Windows refused to start updater')))

    with pytest.raises(OSError, match='refused'):
        UpdateController('1.0.0').launch_installer(info, candidate)
    assert app.cancelled is True


def test_update_apply_sets_handoff_only_for_successful_swap(monkeypatch, tmp_path):
    from vantage.helpers import update_apply

    target = tmp_path / 'Vantage.exe'
    target.write_bytes(b'MZtarget')
    launches = []
    monkeypatch.setattr(
        update_apply.subprocess, 'Popen',
        lambda command, **kwargs: launches.append((command, kwargs)))
    monkeypatch.setenv('VANTAGE_OPEN_UI_AFTER_UPDATE', 'stale')
    update_apply._launch_target(
        target, updated_from='1.0.0', open_vantage_ui=True)
    assert launches[-1][1]['env']['VANTAGE_OPEN_UI_AFTER_UPDATE'] == '1'

    launches.clear()
    update_apply._launch_target(
        target, error='failed', open_vantage_ui=True)
    assert 'VANTAGE_OPEN_UI_AFTER_UPDATE' not in launches[-1][1]['env']


def test_update_apply_parser_forwards_handoff_only_after_verified_success(
        monkeypatch, tmp_path):
    from vantage.helpers import update_apply

    source = tmp_path / 'staged' / 'Vantage.exe'
    source.parent.mkdir()
    source.write_bytes(b'MZverified-new')
    target = tmp_path / 'installed' / 'Vantage.exe'
    target.parent.mkdir()
    target.write_bytes(b'MZold')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    launches = []
    stamps = []
    monkeypatch.setattr(update_apply.sys, 'executable', str(source))
    monkeypatch.setattr(
        update_apply, '_launch_target',
        lambda path, **kwargs: launches.append((path, kwargs)))
    monkeypatch.setattr(
        update_apply, '_stamp_spell_handoff', lambda: stamps.append(True))
    result = update_apply.apply_staged_update([
        '--apply-update', '--target', str(target), '--wait-pid', '0',
        '--digest', 'sha256:' + digest, '--from-version', '1.44.54',
        '--open-vantage-ui'])
    assert result == 0
    assert launches[0][1]['open_vantage_ui'] is True
    assert launches[0][1]['updated_from'] == '1.44.54'
    assert stamps == [True]

    launches.clear()
    result = update_apply.apply_staged_update([
        '--apply-update', '--target', str(target), '--wait-pid', '0',
        '--digest', 'sha256:' + '0' * 64, '--from-version', '1.44.54',
        '--open-vantage-ui'])
    assert result == 1
    assert launches and launches[0][1].get('open_vantage_ui', False) is False
    assert stamps == [True]


def test_checkpoint_does_not_report_success_when_fresh_process_would_read_stale(
        monkeypatch, tmp_path):
    from vantage.helpers import config
    from vantage.helpers import application as application_module
    from vantage.helpers.application import VantageApp

    config_file = tmp_path / 'vantage.config.json'
    config_file.write_text(json.dumps({
        'spells': {'active_timer_state': []},
        'timers': {'items': []},
    }), encoding='utf-8')
    live_spell_rows = [{
        'deadline': 9999, 'target': '__you__',
        'spell': {'name': 'Clarity II'}}]
    live_timer_rows = [{'name': 'Frenzy', 'deadline': 8888}]
    monkeypatch.setattr(config, '_filename', str(config_file))
    monkeypatch.setattr(config, 'data', {
        'spells': {'active_timer_state': []},
        'timers': {'items': []},
    })
    monkeypatch.setattr(
        application_module, 'write_spell_handoff', lambda _rows: [])

    class _Geometry:
        def _save_geometry(self):
            pass

    class _Spells:
        def checkpoint_runtime_state(self):
            config.data['spells']['active_timer_state'] = live_spell_rows

    class _Timers:
        def checkpoint_runtime_state(self):
            config.data['timers']['items'] = live_timer_rows

    # Reproduce the old false-positive handoff: the save path returns without
    # raising, but the file the replacement process will load remains stale.
    monkeypatch.setattr(config, 'save', lambda: None)
    host = SimpleNamespace(
        _parsers=[_Geometry()],
        _parsers_dict={'spells': _Spells(), 'timers': _Timers()})

    assert VantageApp.checkpoint_for_update(host) is False
    persisted = json.loads(config_file.read_text(encoding='utf-8'))
    assert persisted['spells']['active_timer_state'] == []
    assert persisted['timers']['items'] == []


def test_update_handoff_preserves_active_pc_authority_until_newer_remote_removal(
        monkeypatch, tmp_path):
    """Cover checkpoint, duplicate quit save, fresh restore, and Device Sync."""
    from vantage.helpers import config
    from vantage.helpers import application as application_module
    from vantage.helpers.application import VantageApp
    from vantage.helpers.device_sync import (
        DeviceSyncController, sign_snapshot)
    from vantage.helpers.timer_sync import record_local_timer_state
    from vantage.helpers.update_handoff import write_spell_handoff

    local_device = (
        'AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH')
    remote_device = (
        'BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB')
    group_id = '0123456789abcdef01234567'
    group_key = 'abcdefghijklmnopqrstuvwxyzABCDEFGH_12345678'
    profile_key = 'spiritflux\0p1999 green'
    config_file = tmp_path / 'vantage.config.json'
    state_file = tmp_path / 'local-state.json'
    shared = tmp_path / 'shared'
    shared.mkdir()
    handoff_file = tmp_path / 'update-spell-handoff.json'
    live_row = {
        'deadline': time.time() + 600,
        'target': '__you__',
        'target_created_order': 1,
        'target_marker': '',
        'character': 'Spiritflux',
        'server': 'P1999 Green',
        'spell': {
            'name': 'Focus of Spirit',
            'runtime_key': 'focus of spirit',
        },
    }
    monkeypatch.setattr(config, '_filename', str(config_file))
    monkeypatch.setattr(config, 'data', {})
    monkeypatch.setattr(
        application_module, 'write_spell_handoff',
        lambda rows: write_spell_handoff(rows, path=handoff_file))
    config.verify_settings()
    config.data['device_sync'].update({
        'enabled': True,
        'device_name': 'Active gaming PC',
        'group_id': group_id,
        'group_secret': group_key,
        'sync_settings': False,
        'sync_active_spells': True,
        'sync_items_notes': False,
        'sync_hotbuttons': False,
    })
    config.data['spells']['active_timer_state'] = []
    config.data['spells']['active_timer_sync'] = {}
    config.data['timers']['items'] = []
    config.save()

    class _Transport:
        def __init__(self, folder):
            self.shared = folder

    class _Activity:
        @staticmethod
        def device_sync_log_activity():
            return {
                'character': 'Spiritflux',
                'server': 'P1999 Green',
                'authority_at': 300.0,
            }

    class _SyncCheckpoint:
        checkpoint_for_update = DeviceSyncController.checkpoint_for_update
        _export_if_changed = DeviceSyncController._export_if_changed
        _snapshot_payload = DeviceSyncController._snapshot_payload
        _content_hash = staticmethod(DeviceSyncController._content_hash)
        _save_state = DeviceSyncController._save_state

        def __init__(self):
            self.transport = _Transport(shared)
            self._state_path = state_file
            self._device_id = local_device
            self._last_local_hash = ''
            self._last_hotbutton_hash = ''
            self._local_modified_at = 0.0
            self._seen = {}
            self._spell_authority = {profile_key: {
                'device': remote_device,
                'authority_at': 250.0,
                'state_at': 260.0,
            }}

        @staticmethod
        def parent():
            return _Activity()

    class _Geometry:
        @staticmethod
        def _save_geometry():
            pass

    class _Spells:
        calls = 0

        def checkpoint_runtime_state(self):
            self.calls += 1
            # The second call models aboutToQuit observing a temporarily
            # incomplete rendered container after the verified checkpoint.
            visible = [live_row] if self.calls == 1 else []
            rows, metadata = record_local_timer_state(
                config.data['spells']['active_timer_state'], visible,
                config.data['spells']['active_timer_sync'], now=300.0)
            config.data['spells']['active_timer_state'] = rows
            config.data['spells']['active_timer_sync'] = metadata
            config.save()

    class _Timers:
        @staticmethod
        def checkpoint_view_geometries():
            pass

        @staticmethod
        def checkpoint_runtime_state():
            pass

    spells = _Spells()
    sync = _SyncCheckpoint()
    host = SimpleNamespace(
        _parsers=[_Geometry()],
        _parsers_dict={'spells': spells, 'timers': _Timers()},
        _device_sync_instance=sync)

    assert VantageApp.checkpoint_for_update(host) is True
    # QApplication.aboutToQuit invokes the spell checkpoint once more.
    spells.checkpoint_runtime_state()
    assert [row['spell']['name'] for row in
            config.data['spells']['active_timer_state']] == [
                'Focus of Spirit']
    published = json.loads(
        (shared / f'{local_device}.json').read_text(encoding='utf-8'))
    assert [row['spell']['name'] for row in
            published['spell_timers']['rows']] == ['Focus of Spirit']

    # Model the replacement executable loading the durable config and the
    # authority journal before its first new EQ log line arrives.
    config.load(str(config_file))

    class _FreshController:
        _load_state = DeviceSyncController._load_state
        _save_state = DeviceSyncController._save_state
        _apply_received = DeviceSyncController._apply_received
        _snapshot_payload = DeviceSyncController._snapshot_payload
        _content_hash = staticmethod(DeviceSyncController._content_hash)

        def __init__(self):
            self.transport = _Transport(shared)
            self._state_path = state_file
            self._device_id = local_device
            self._last_local_hash = ''
            self._last_hotbutton_hash = ''
            self._local_modified_at = 0.0
            self._seen = {}
            self._spell_authority = {}

        @staticmethod
        def peers():
            return [{'id': remote_device}]

        @staticmethod
        def parent():
            return None

    fresh = _FreshController()
    fresh._load_state()
    assert fresh._spell_authority[profile_key]['device'] == local_device
    assert fresh._spell_authority[profile_key]['authority_at'] == 300.0

    def write_remote(authority_at, state_at):
        payload = sign_snapshot({
            'schema': 1,
            'device': remote_device,
            'group': group_id,
            'generated_at': state_at,
            'settings': {},
            'spell_timers': {
                'schema': 1,
                'character': 'Spiritflux',
                'server': 'P1999 Green',
                'authority_at': authority_at,
                'state_at': state_at,
                'rows': [],
            },
        }, group_key)
        (shared / f'{remote_device}.json').write_text(
            json.dumps(payload), encoding='utf-8')

    # A stale remote empty copy must not erase the freshly restored buff.
    write_remote(275.0, 280.0)
    assert fresh._apply_received() == 0
    assert [row['spell']['name'] for row in
            config.data['spells']['active_timer_state']] == [
                'Focus of Spirit']

    # A PC that later observes the character really is authoritative; its
    # empty full profile represents a confirmed removal and must still win.
    write_remote(400.0, 410.0)
    assert fresh._apply_received() == 1
    assert config.data['spells']['active_timer_state'] == []
    assert fresh._spell_authority[profile_key]['device'] == remote_device


def test_any_checkpoint_exception_becomes_safe_domain_failure(monkeypatch):
    from vantage.helpers.application import VantageApp

    class _UnexpectedGeometryFailure:
        def _save_geometry(self):
            raise RuntimeError('unexpected platform plugin failure')

    host = SimpleNamespace(
        _parsers=[_UnexpectedGeometryFailure()], _parsers_dict={})

    assert VantageApp.checkpoint_for_update(host) is False


def test_quick_update_checkpoint_failure_does_not_hide_tray_or_quit():
    from vantage.helpers.application import VantageApp

    class _Controller:
        def launch_installer(self, _info, _path):
            raise RuntimeError(
                'Vantage could not preserve live buffs and timers. The '
                'update was cancelled and Vantage remains open.')

    class _Tray:
        calls = []

        def setVisible(self, visible):
            self.calls.append(bool(visible))

    class _Toast:
        message = ''

        def _failed(self, message):
            self.message = str(message)

    quit_calls = []
    toast = _Toast()
    host = SimpleNamespace(
        _update_controller=_Controller(), _system_tray=_Tray(),
        quit=lambda: quit_calls.append(True))

    assert VantageApp.install_quick_update(
        host, object(), 'verified.exe', toast) is False
    assert host._system_tray.calls == []
    assert quit_calls == []
    assert 'live buffs and timers' in toast.message
    assert 'cancelled' in toast.message
    assert 'remains open' in toast.message
