import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from vantage.helpers import application, config
from vantage.helpers.application import VantageApp
from vantage.helpers.log_dispatch import LogDispatchHealth


PRIVATE_MESSAGE = 'PRIVATE_CHAT_MUST_NOT_BE_SAVED'


def fail(*args, **kwargs):
    raise RuntimeError(PRIVATE_MESSAGE)


class Feature:
    def __init__(self, name, owner):
        self.name = name
        self.owner = owner
        self.broken = False
        self.calls = []

    def parse(self, timestamp, text):
        self.calls.append((timestamp, text, self._active_character,
                           self._character_context.character,
                           self.owner._log_status))
        if self.broken:
            fail()


class DispatchHarness:
    _parse = VantageApp._parse
    _unpack_log_record = staticmethod(VantageApp._unpack_log_record)
    _dispatch_log_parser = staticmethod(VantageApp._dispatch_log_parser)
    _ingest_log_character_context = VantageApp._ingest_log_character_context
    _save_log_character_profiles = VantageApp._save_log_character_profiles
    _log_activity = VantageApp._log_activity
    _report_log_dispatch_health = VantageApp._report_log_dispatch_health
    _log_health_check = VantageApp._log_health_check
    log_dispatch_health = VantageApp.log_dispatch_health

    def __init__(self, tmp_path):
        self._log_dispatch = LogDispatchHealth(tmp_path / 'health.json')
        self._log_dispatch_notice_at = float('-inf')
        self._log_dispatch_had_errors = False
        self._log_status = 'WAITING'
        self._toggled = True
        self._log_reader = None
        self._last_log_activity = None
        self._latest_log_activity = None
        self.notices = []
        self.statuses = []
        self.context_changed = False
        self._character_context = SimpleNamespace(
            ingest=lambda character, server, text: (
                SimpleNamespace(character=character, server=server, pet_name=''),
                self.context_changed),
            snapshot=lambda: {})
        self._camp_sessions = SimpleNamespace(ingest=lambda *args: None)
        self._parsers = [Feature(name, self) for name in ('spells', 'maps', 'combat')]

    def _set_log_status(self, status, message='', notify=False):
        self.statuses.append(status)
        self._log_status = status

    def _queue_quickbar_notice(self, *args, **kwargs):
        self.notices.append((args, kwargs))

    def _deliver_chat_notification(self, *args):
        return True


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'classify_chat_notification', lambda *a, **k: None)
    monkeypatch.setattr(config, 'save', lambda: None)
    return DispatchHarness(tmp_path)


def event(character='Holyflux'):
    return datetime.datetime.now(), PRIVATE_MESSAGE, character, 'P1999Green'


@pytest.mark.parametrize('component', [
    'Character context', 'Chat classification', 'Chat notification',
    'Camp tracking', 'Feature: spells', 'Character profile save',
])
def test_a_failed_consumer_does_not_drop_later_features_or_next_line(
        app, monkeypatch, component):
    if component == 'Character context':
        monkeypatch.setattr(app._character_context, 'ingest', fail)
    elif component == 'Chat classification':
        monkeypatch.setattr(application, 'classify_chat_notification', fail)
    elif component == 'Chat notification':
        monkeypatch.setattr(application, 'classify_chat_notification', lambda *a, **k: object())
        monkeypatch.setattr(app, '_deliver_chat_notification', fail)
    elif component == 'Camp tracking':
        monkeypatch.setattr(app._camp_sessions, 'ingest', fail)
    elif component == 'Feature: spells':
        app._parsers[0].broken = True
    else:
        app.context_changed = True
        monkeypatch.setattr(config, 'save', fail)

    app._parse(event())
    app._parse(event('Wildflux'))
    assert all(len(feature.calls) == 2 for feature in app._parsers)
    assert all(feature.calls[-1][2:4] == ('Wildflux', 'Wildflux')
               for feature in app._parsers)
    health = app.log_dispatch_health()
    assert health['events_received'] == health['events_completed'] == 2
    assert health['events_with_errors'] == 2
    assert health['active_errors'][0]['component'] == component
    assert health['active_errors'][0]['count'] == 2
    assert app._log_status == 'DEGRADED'
    assert len(app.notices) == 1
    assert PRIVATE_MESSAGE not in json.dumps(health)
    assert PRIVATE_MESSAGE not in app._log_dispatch.path.read_text()
    assert PRIVATE_MESSAGE not in str(app.notices)


def test_failed_context_result_does_not_reuse_previous_character(app, monkeypatch):
    monkeypatch.setattr(app._character_context, 'ingest', lambda *args: None)
    app._parse(event('Newtoon'))
    assert all(feature.calls[0][2:4] == ('Newtoon', 'Newtoon')
               for feature in app._parsers)
    assert app.log_dispatch_health()['active_errors'][0]['component'] == 'Character context'


def test_online_is_only_reported_after_feature_dispatch_and_recovery_is_recorded(app):
    app._parsers[0].broken = True
    app._parse(event())
    assert all(feature.calls[0][-1] == 'WAITING' for feature in app._parsers)
    assert app._log_status == 'DEGRADED'
    app._parsers[0].broken = False
    app._parse(event())
    assert app._log_status == 'ONLINE'
    assert app.log_dispatch_health()['active_errors'] == []
    assert app.log_dispatch_health()['recent_events'][-1]['event'] == 'recovered'
    assert app.log_dispatch_health()['events_with_errors'] == 1


def test_notice_and_status_failures_cannot_escape_or_prevent_more_dispatch(app, monkeypatch):
    app._parsers[0].broken = True
    monkeypatch.setattr(app, '_set_log_status', fail)
    monkeypatch.setattr(app, '_queue_quickbar_notice', fail)
    for _ in range(3):
        app._parse(event())
    assert all(len(feature.calls) == 3 for feature in app._parsers)
    assert app.log_dispatch_health()['events_completed'] == 3
    assert {entry['component'] for entry in app.log_dispatch_health()['active_errors']} == {
        'Feature: spells', 'Log status', 'Log notice'}


def test_status_failure_after_updating_label_is_retried_and_recovers(app, monkeypatch):
    original = app._set_log_status
    def broken_status(*args, **kwargs):
        original(*args, **kwargs)
        fail()
    monkeypatch.setattr(app, '_set_log_status', broken_status)
    app._parsers[0].broken = True
    app._parse(event())
    assert app._log_status == 'DEGRADED'
    monkeypatch.setattr(app, '_set_log_status', original)
    app._parsers[0].broken = False
    app._parse(event())
    app._parse(event())
    assert app._log_status == 'ONLINE'
    assert app.log_dispatch_health()['active_errors'] == []


def test_notice_failure_is_retried_after_cooldown_and_recovers(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(application.time, 'monotonic', lambda: clock[0])
    original = app._queue_quickbar_notice
    monkeypatch.setattr(app, '_queue_quickbar_notice', fail)
    app._parsers[0].broken = True
    app._parse(event())
    monkeypatch.setattr(app, '_queue_quickbar_notice', original)
    app._parsers[0].broken = False
    clock[0] += 61
    app._parse(event())
    app._parse(event())
    assert app._log_status == 'ONLINE'
    assert app.log_dispatch_health()['active_errors'] == []
    assert any(entry['event'] == 'recovered' and entry['component'] == 'Log notice'
               for entry in app.log_dispatch_health()['recent_events'])


def test_health_reporting_failure_still_completes_current_and_next_event(app, monkeypatch):
    monkeypatch.setattr(app, '_report_log_dispatch_health', fail)
    app._parse(event())
    app._parse(event())
    assert all(len(feature.calls) == 2 for feature in app._parsers)
    assert app.log_dispatch_health()['events_completed'] == 2
    assert app.log_dispatch_health()['active_errors'][0]['component'] == 'Log health reporting'


def test_diagnostic_write_failure_keeps_in_memory_evidence_and_dispatch(app, monkeypatch):
    app._parsers[0].broken = True
    monkeypatch.setattr('vantage.helpers.log_dispatch.os.replace', fail)
    app._parse(event())
    app._parse(event())
    assert all(len(feature.calls) == 2 for feature in app._parsers)
    health = app.log_dispatch_health()
    assert health['diagnostic_write_error'] == 'RuntimeError'
    assert health['active_errors'][0]['component'] == 'Feature: spells'
    assert not list(app._log_dispatch.path.parent.glob('.log-dispatch-*.tmp'))


def test_invalid_record_is_diagnosed_and_following_record_recovers(app):
    app._parse(('bad',))
    assert all(not feature.calls for feature in app._parsers)
    assert app._log_status == 'DEGRADED'
    app._parse(event())
    assert all(len(feature.calls) == 1 for feature in app._parsers)
    assert app._log_status == 'ONLINE'


def test_notices_and_diagnostic_history_are_bounded_under_flapping_failures(app):
    for index in range(250):
        app._parsers[0].broken = index % 2 == 0
        app._parse(event())
    health = app.log_dispatch_health()
    assert health['events_completed'] == 250
    assert health['events_with_errors'] == 125
    assert len(health['recent_events']) == 100
    assert len(app.notices) == 1


def test_watchdog_repairs_reader_without_replacing_it_or_replaying_events(app):
    repairs = []
    reader = SimpleNamespace(repair=lambda: repairs.append('repair'))
    app._log_reader = reader
    app._log_health_check()
    assert repairs == ['repair']
    assert app._log_reader is reader
    assert app.log_dispatch_health()['events_received'] == 0
    app._toggled = False
    app._log_health_check()
    assert repairs == ['repair']


def test_watchdog_failure_is_diagnosed_and_does_not_escape(app):
    app._log_reader = SimpleNamespace(repair=fail)
    app._log_health_check()
    assert app._log_status == 'DEGRADED'
    assert app.log_dispatch_health()['active_errors'][0]['component'] == 'Log watcher'


def test_watchdog_can_recover_sole_status_error_after_notice_cooldown(app):
    app._log_dispatch.failed('Log status', RuntimeError(PRIVATE_MESSAGE))
    app._log_dispatch_notice_at = float('-inf')
    app._log_status = 'DEGRADED'
    app._log_health_check()
    assert app.log_dispatch_health()['active_errors'] == []
    assert app._log_status == 'ONLINE'
    assert not any(args[0] == 'Log processing needs attention'
                   for args, _kwargs in app.notices)


def test_watchdog_reporting_failure_remains_isolated(app, monkeypatch):
    app._log_dispatch.failed('Feature: maps', RuntimeError(PRIVATE_MESSAGE))
    monkeypatch.setattr(app, '_report_log_dispatch_health', fail)
    app._log_health_check()
    assert {entry['component'] for entry in app.log_dispatch_health()['active_errors']} == {
        'Feature: maps', 'Log health reporting'}


def test_hidden_feature_receives_log_and_toggle_failure_does_not_block_rest(app):
    first = app._parsers[0]
    first.toggle = fail
    app._parse((datetime.datetime.now(), 'toggle_spells', 'Holyflux', 'P1999Green'))
    assert len(app._parsers[1].calls) == len(app._parsers[2].calls) == 1
    assert app.log_dispatch_health()['active_errors'][0]['component'] == 'Feature: spells'


def test_native_reader_keeps_real_buff_consumer_alive_after_map_exception(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = r'''
import datetime
import json
from pathlib import Path
from PySide6.QtTest import QTest
from native_audit_fixture import isolate
isolate()
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.logreader import LogReader
app = VantageApp([])
app._toggled = True
app._log_status = 'WAITING'
spells = app._parsers_dict['spells']
spells.show()
config.data['spells']['use_casting_window'] = False
config.data['spells']['use_custom_triggers'] = False
config.data['spells']['fade_sound_enabled'] = False
maps = app._parsers_dict['maps']
original_parse = maps.parse
def broken_map(*args):
    raise RuntimeError('PRIVATE_CHAT_MUST_NOT_BE_SAVED')
maps.parse = broken_map
directory = Path(config.data['general']['eq_log_dir'])
path = directory / 'eqlog_Holyflux_P1999Green.txt'
path.write_text('')
reader = LogReader(str(directory))
try:
    stamp = datetime.datetime.now().strftime('%a %b %d %H:%M:%S %Y')
    with path.open('a') as stream:
        stream.write(f'[{stamp}] You begin casting Bravery.\n')
        stream.write(f'[{stamp}] Friendly looks brave.\n')
    QTest.qWait(400)
    target = spells._spell_container.get_spell_target_by_name('Friendly')
    assert target is not None and target.isVisible()
    assert target.spell_widget('bravery') is not None
    failed = app.log_dispatch_health()
    assert failed['events_completed'] == 2
    assert failed['active_errors'][0]['component'] == 'Feature: maps'
    assert app._log_status == 'DEGRADED'
    maps.parse = original_parse
    with path.open('a') as stream:
        stream.write(f'[{stamp}] You have entered Nektulos Forest.\n')
    QTest.qWait(400)
    recovered = app.log_dispatch_health()
    assert recovered['events_completed'] == 3
    assert recovered['active_errors'] == []
    assert app._log_status == 'ONLINE'
    assert maps._map._data.zone == 'the nektulos forest'
    assert target.spell_widget('bravery') is not None
    assert 'PRIVATE_CHAT_MUST_NOT_BE_SAVED' not in json.dumps(recovered)
    print(json.dumps({'completed': recovered['events_completed'],
                      'errors': failed['events_with_errors'],
                      'buff_survived': True, 'map_recovered': True}))
finally:
    reader.stop()
    app.quit()
'''
    env = os.environ.copy()
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join((str(root / 'tests'), str(root / 'src')))
    completed = subprocess.run(
        [sys.executable, '-B', '-c', script], cwd=root, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {'completed': 3, 'errors': 2,
                      'buff_survived': True, 'map_recovered': True}
