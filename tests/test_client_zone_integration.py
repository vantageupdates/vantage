"""Recover a zone omitted from eqlog without /who or game input."""
from datetime import datetime
import builtins
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication

from vantage.helpers.logreader import LogReader, LogReaderSignals


def log_entry(text, second=1):
    return f'[Tue Oct 27 10:05:{second:02d} 2026] {text}\r\n'.encode()


def debug_entry(text, second=2):
    return f'2026-10-27 10:05:{second:02d}\t{text}\r\n'.encode()


def debug_zone(character='Example', zone='North Ro', second=2):
    return (debug_entry('ZONING', second) +
            debug_entry(f'Player = {character}, zone = {zone}', second + 1) +
            debug_entry('Zone initialized.', second + 2))


@pytest.fixture
def linked(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous = getattr(app, '_signals', {})
    signals = LogReaderSignals()
    app._signals = {'logreader': signals}
    path = tmp_path / 'eqlog_Example_P1999Green.txt'
    path.write_bytes(log_entry('You have entered Timorous Deep.'))
    reader = LogReader(str(tmp_path))
    events, contexts = [], []
    signals.new_line.connect(events.append)
    signals.zone_context.connect(contexts.append)
    reader._bootstrap_context()
    contexts.clear()
    yield reader, path, tmp_path / 'dbg.txt', events, contexts
    reader.stop()
    reader.deleteLater()
    app.processEvents()
    app._signals = previous


def test_client_zone_fills_missing_chat_log_transition_without_replaying_events(linked):
    reader, path, dbg, events, contexts = linked
    dbg.write_bytes(debug_zone())
    before = path.read_bytes(), dbg.read_bytes()
    reader._check_zone_context()
    update = contexts[-1]
    assert update['text'] == 'You have entered North Ro.'
    assert (update['character'], update['server']) == ('Example', 'P1999Green')
    assert update['source'] == 'client_debug'
    assert update['timestamp'] == datetime(2026, 10, 27, 10, 5, 4)
    assert reader.health_snapshot()['zone_context_source'] == 'EverQuest client'
    reader._check_zone_context()
    assert contexts[-1] == update
    assert not events and before == (path.read_bytes(), dbg.read_bytes())


@pytest.mark.parametrize('character,ready', [('Other', True), ('Example', False)])
def test_other_character_or_unconfirmed_transition_does_not_replace_active_zone(linked, character, ready):
    reader, _path, dbg, events, contexts = linked
    dbg.write_bytes(debug_zone(character) if ready else debug_entry('Player = Example, zone = North Ro'))
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered Timorous Deep.'
    assert contexts[-1]['source'] == 'eq_log'
    assert not events


def test_newer_who_response_remains_authoritative(linked):
    reader, path, dbg, _events, contexts = linked
    dbg.write_bytes(debug_zone())
    reader._check_zone_context()
    with path.open('ab') as stream:
        stream.write(log_entry('There are 2 players in East Freeport.', 10))
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'There are 2 players in East Freeport.'
    assert contexts[-1]['source'] == 'eq_log'


def test_new_client_character_uses_its_unique_known_server_profile(linked):
    reader, path, dbg, _events, contexts = linked
    alt = path.parent / 'eqlog_Alt_P1999Blue.txt'
    alt.write_bytes(log_entry('Ordinary old chat.'))
    reader._poll()
    dbg.write_bytes(debug_zone('Alt'))
    reader._check_zone_context()
    assert (contexts[-1]['character'], contexts[-1]['server']) == ('Alt', 'P1999Blue')
    assert contexts[-1]['source'] == 'client_debug'


def test_old_client_character_cannot_take_over_newer_live_location(linked):
    reader, path, dbg, _events, contexts = linked
    alt = path.parent / 'eqlog_Alt_P1999Blue.txt'
    alt.write_bytes(log_entry('Ordinary old chat.'))
    reader._poll()
    with path.open('ab') as stream:
        stream.write(log_entry('Your Location is 1, 2, 3', 10))
    reader._poll()
    dbg.write_bytes(debug_zone('Alt'))
    reader._check_zone_context()
    assert contexts[-1]['character'] == 'Example'
    assert contexts[-1]['source'] == 'eq_log'


def test_unread_newer_location_is_drained_before_debug_can_switch_characters(linked):
    reader, path, dbg, events, contexts = linked
    alt = path.parent / 'eqlog_Alt_P1999Blue.txt'
    alt.write_bytes(log_entry('Ordinary old chat.'))
    reader._poll()
    events.clear()
    reader._poll_timer.stop()
    reader._recovery_timer.stop()
    reader._watcher.removePaths(reader._watcher.files())
    with path.open('ab') as stream:
        stream.write(log_entry('Your Location is 1, 2, 3', 10))
    dbg.write_bytes(debug_zone('Alt'))
    reader._check_zone_context()
    reader._check_zone_context()
    assert reader._zone_active_path == str(path)
    assert reader._stats[str(path)]['last_read'] == path.stat().st_size
    assert [event[1] for event in events] == ['Your Location is 1, 2, 3']
    assert contexts[-1]['character'] == 'Example'


def test_disappearing_log_before_bootstrap_does_not_break_the_heartbeat(linked):
    previous, path, dbg, _events, contexts = linked
    previous.stop()
    dbg.write_bytes(debug_zone())
    reader = LogReader(str(path.parent))
    try:
        reader._watcher.removePath(str(path))
        path.unlink()
        contexts.clear()
        reader._check_zone_context()
        assert not contexts
        assert not reader._checking_zone_context
    finally:
        reader.stop()
        reader.deleteLater()


def test_same_name_on_two_servers_does_not_guess_the_debug_server(linked):
    reader, path, dbg, _events, contexts = linked
    other = path.parent / 'eqlog_Example_P1999Blue.txt'
    other.write_bytes(log_entry('Ordinary old chat.'))
    reader._poll()
    dbg.write_bytes(debug_zone())
    reader._check_zone_context()
    assert contexts[-1]['source'] == 'eq_log'
    assert contexts[-1]['text'] == 'You have entered Timorous Deep.'


@pytest.mark.parametrize('normal_second, expected', [(1, 'client_debug'), (10, None)])
def test_sharing_violation_still_respects_known_normal_freshness(linked, monkeypatch, normal_second, expected):
    reader, path, dbg, _events, contexts = linked
    if normal_second > 1:
        with path.open('ab') as stream:
            stream.write(log_entry('There are 2 players in East Freeport.', normal_second))
        reader._poll()
    dbg.write_bytes(debug_zone())
    contexts.clear()
    original = builtins.open
    def locked(name, *args, **kwargs):
        if str(name) == str(path):
            raise PermissionError('temporary sharing violation')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', locked)
    reader._check_zone_context()
    if expected:
        assert contexts[-1]['source'] == expected
    else:
        assert not contexts


SCRIPT = r'''
from datetime import datetime, timedelta
import os, time
from pathlib import Path
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp

logs = Path(os.environ['VANTAGE_DATA_DIR']) / 'Logs'
logs.mkdir()
path = logs / 'eqlog_Example_P1999Green.txt'
dbg = logs / 'dbg.txt'
start = datetime.now().replace(microsecond=0) - timedelta(seconds=30)
def eq(text, second):
    return f'[{(start+timedelta(seconds=second)).strftime("%a %b %d %H:%M:%S %Y")}] {text}\r\n'.encode()
def client(zone, second):
    def row(text, delta):
        return f'{(start+timedelta(seconds=delta)).isoformat(sep=" ")}\t{text}\r\n'.encode()
    return row('ZONING', second)+row(f'Player = Example, zone = {zone}', second+1)+row('Zone initialized.',second+2)
def append(file, data):
    with file.open('ab') as stream: stream.write(data)
def wait(condition):
    end=time.monotonic()+4
    while not condition() and time.monotonic()<end: QTest.qWait(25)
    assert condition(), 'Map did not update through its actual zone timer'

path.write_bytes(eq('You have entered Timorous Deep.',0))
config.data['general'].update(eq_log_dir=str(logs), update_check=False,
                             audio_muted=True, log_archive_enabled=False)
app=VantageApp([])
reader=app._log_reader
maps=app._parsers_dict['maps']
wait(lambda: maps._map._data.zone == 'timorous deep')
delivered=[]
app._signals['logreader'].new_line.connect(delivered.append)
assert reader._zone_context_timer.interval()==2000
dbg.write_bytes(client('North Ro',3))
wait(lambda: maps._map._data.zone=='northern desert of ro')
assert not delivered, 'Debug context must not fabricate game events'
assert '__you__' not in maps._map._data.players
append(path,eq('Your Location is 100, 200, 3',6))
wait(lambda: '__you__' in maps._map._data.players)
marker=maps._map._data.players['__you__']
assert (marker.location.x,marker.location.y)==(-200,-100)
checks=reader._zone_context_checks
wait(lambda: reader._zone_context_checks>checks)
assert maps._map._data.players['__you__'] is marker
assert maps._preview_zone('skyshrine')
preview=maps._preview_map
checks=reader._zone_context_checks
wait(lambda: reader._zone_context_checks>checks)
assert maps._preview_map is preview

# Older chat-log context delivered late cannot put an old /loc on the new map.
maps._active_character='Example';maps._active_server='P1999Green'
maps.parse(start+timedelta(seconds=1),'You have entered Timorous Deep.')
maps.parse(start+timedelta(seconds=1),'Your Location is -12000, 4300, 3')
assert maps._map._data.zone=='northern desert of ro'
assert maps._map._data.players['__you__'] is marker
assert maps._preview_map is preview

append(dbg,client('East Commonlands',10))
wait(lambda: maps._map._data.zone=='east commonlands')
assert maps._preview_map is None
assert '__you__' not in maps._map._data.players
append(path,eq('Your Location is 300, 400, 3',13))
wait(lambda: '__you__' in maps._map._data.players)
assert (maps._map._data.players['__you__'].location.x,
        maps._map._data.players['__you__'].location.y)==(-400,-300)

# A later genuine /who can correct an old client log without more repeats.
append(path,eq('There are 2 players in East Freeport.',20))
wait(lambda: maps._map._data.zone=='east freeport')
checks=reader._zone_context_checks
wait(lambda: reader._zone_context_checks>checks)
assert maps._map._data.zone=='east freeport'
assert reader.health_snapshot()['zone_context_source']=='EQ log'
reader.stop()
app.quit_vantage(confirm=False)
print('CLIENT ZONE RECOVERY PASSED')
'''


def test_full_app_updates_from_client_log_without_any_who_command(tmp_path):
    result = subprocess.run([sys.executable, '-B', '-c', SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ,VANTAGE_DATA_DIR=str(tmp_path),
                 QT_QPA_PLATFORM='offscreen',PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True,text=True,timeout=45)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'CLIENT ZONE RECOVERY PASSED' in result.stdout
