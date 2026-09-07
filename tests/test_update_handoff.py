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

dialog = UpdateDialog(app._update_controller)
dialog.info = info
dialog.staged_path = str(staged)
dialog.open_ui_after_restart.setChecked(True)
QTimer.singleShot(0, dialog.install)
app.exec()

with open(config._filename, encoding='utf-8') as source:
    persisted = json.load(source)
rows = persisted['spells']['active_timer_state']
print(json.dumps({
    'spawned': len(spawned),
    'open_ui_flag': '--open-vantage-ui' in spawned[0],
    'names_after_quit': sorted(row['spell']['name'] for row in rows),
    'rows_after_quit': rows,
}))
"""


RESTORE_SCRIPT = r"""
import json
import time

from vantage.helpers import config
from vantage.helpers.application import VantageApp

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
}))
app.quit()
"""


def _run(script, profile):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(profile)
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

    # Make the second process prove that absolute deadlines age during the
    # update/restart interval instead of restarting full-duration timers.
    time.sleep(1.1)
    restored = _run(RESTORE_SCRIPT, profile)

    assert restored['names'] == ['Update Mob Debuff', 'Update Self Buff']
    assert restored['targets'] == ['__you__', 'a crystalline devourer']
    assert restored['characters'] == ['Mindflux']
    assert restored['servers'] == ['Green']
    assert restored['mob_marker'] == 'B'
    assert restored['mob_alias'] == 'West ramp'
    assert restored['mob_named'] is True
    assert 0 < restored['remaining']['Update Self Buff'] < 300
    assert 0 < restored['remaining']['Update Mob Debuff'] < 240


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
    monkeypatch.setattr(update_apply.sys, 'executable', str(source))
    monkeypatch.setattr(
        update_apply, '_launch_target',
        lambda path, **kwargs: launches.append((path, kwargs)))
    result = update_apply.apply_staged_update([
        '--apply-update', '--target', str(target), '--wait-pid', '0',
        '--digest', 'sha256:' + digest, '--from-version', '1.44.54',
        '--open-vantage-ui'])
    assert result == 0
    assert launches[0][1]['open_vantage_ui'] is True
    assert launches[0][1]['updated_from'] == '1.44.54'

    launches.clear()
    result = update_apply.apply_staged_update([
        '--apply-update', '--target', str(target), '--wait-pid', '0',
        '--digest', 'sha256:' + '0' * 64, '--from-version', '1.44.54',
        '--open-vantage-ui'])
    assert result == 1
    assert launches and launches[0][1].get('open_vantage_ui', False) is False


def test_checkpoint_does_not_report_success_when_fresh_process_would_read_stale(
        monkeypatch, tmp_path):
    from vantage.helpers import config
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
