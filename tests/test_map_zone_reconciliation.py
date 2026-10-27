"""Periodic log context repairs missed zoning without replaying stale state."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.parsers.maps.window import detect_log_zone


@pytest.mark.parametrize('line', [
    'You have entered East Commonlands.',
    'You have zoned into East Commonlands.',
    'You have zoned to East Commonlands.',
    'YOU HAVE ZONED INTO EAST COMMONLANDS!',
])
def test_zone_entry_variants(line):
    assert detect_log_zone(line) == ('east commonlands', 'zoning')


SCRIPT = r'''
from datetime import datetime, timedelta
import sys
import time
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from vantage.helpers import config
from vantage.helpers.logreader import LogReaderSignals
from vantage.parsers.maps.window import Maps, MapsSignals

app = QApplication([])
class Settings(QObject):
    config_updated = Signal()
app._signals = {'settings': Settings(), 'maps': MapsSignals(),
                'logreader': LogReaderSignals()}
config.verify_settings()
config.save = lambda: None
maps = Maps()
start = datetime(2026, 10, 27, 12, 0, 0)
def line(text, *, seconds=0, character='Mindflux'):
    maps._active_character = character
    maps._active_server = 'P1999Green'
    maps.parse(start + timedelta(seconds=seconds), text)
def snapshot(text, *, seconds=1, character='Mindflux', offset=200,
             active=True, captured_at=None, inode=99):
    return {'text': text, 'character': character, 'server': 'P1999Green',
            'path': character + '.txt', 'identity': (1, inode),
            'offset': offset, 'timestamp': start + timedelta(seconds=seconds),
            'observed_mtime_ns': 1, 'active': active, 'periodic': True,
            'captured_at': time.monotonic() if captured_at is None else captured_at}
def pulse(context):
    app._signals['logreader'].zone_context.emit(context)
def player():
    line('Your Location is 10, 20, 3')
    assert '__you__' in maps._map._data.players
def zone():
    return maps._map._data.zone

mode = sys.argv[1]
if mode == 'missed_zone':
    line('You have entered The Estate of Unrest.')
    player()
    update = snapshot('You have entered East Commonlands.')
    pulse(update)
    assert zone() == 'east commonlands'
    assert '__you__' not in maps._map._data.players
    assert maps._map.location_overlay._location is None
    assert maps._preview_zone('skyshrine')
    preview = maps._preview_map
    for _ in range(4):
        pulse(update)
    assert maps._preview_map is preview
    player()
    marker = maps._map._data.players['__you__']
    pulse(update)
    assert maps._map._data.players['__you__'] is marker
elif mode == 'stale_live_priority':
    old = snapshot('You have entered The Nektulos Forest.', seconds=10)
    line('You have entered East Commonlands.', seconds=10)
    player()
    marker = maps._map._data.players['__you__']
    pulse(old)
    pulse(snapshot('You have entered The Nektulos Forest.', seconds=5, offset=300))
    pulse(('You have entered The Nektulos Forest.', 'Mindflux', 'P1999Green'))
    assert zone() == 'east commonlands'
    assert maps._map._data.players['__you__'] is marker
    # A reconnect that rediscovers the same event is not new zoning.
    assert maps._preview_zone('skyshrine')
    preview = maps._preview_map
    pulse(snapshot('You have entered East Commonlands.', seconds=10, offset=400))
    assert maps._preview_map is preview
elif mode == 'same_second':
    line('You have entered The Estate of Unrest.')
    update = snapshot('You have entered The Nektulos Forest.', seconds=0)
    pulse(update)
    assert zone() == 'the nektulos forest'
    line('You have entered East Commonlands.')
    pulse(update)
    assert zone() == 'east commonlands'
elif mode == 'active_character':
    line('You have entered The Nektulos Forest.')
    other = snapshot('You have entered The Estate of Unrest.',
                     character='Wildflux', active=False)
    pulse(other)
    assert zone() == 'the nektulos forest'
    assert maps._map_source_identity == ('mindflux', 'p1999green')
    assert maps._map_source_zones[('wildflux', 'p1999green')] == 'estate of unrest'
    pulse(dict(other, active=True))
    assert zone() == 'estate of unrest'
    assert maps._map_source_identity == ('wildflux', 'p1999green')
    pulse(snapshot('You have entered East Commonlands.', seconds=2, active=False))
    assert zone() == 'estate of unrest'
elif mode == 'loading_and_truncation':
    line('You have entered East Commonlands.')
    player()
    old = snapshot('You have entered East Commonlands.', seconds=0, offset=200)
    pending = snapshot('LOADING, PLEASE WAIT...', offset=1000)
    pulse(pending)
    assert '__you__' not in maps._map._data.players
    assert maps._map_source_zones[('mindflux', 'p1999green')] == ''
    pulse(old)
    assert maps._map_source_zones[('mindflux', 'p1999green')] == ''
    # Truncating a log can retain its inode while starting at a lower offset.
    pulse(snapshot('You have entered The Nektulos Forest.', seconds=2, offset=80))
    assert zone() == 'the nektulos forest'
    pulse(pending)
    assert maps._map_source_zones[('mindflux', 'p1999green')] == 'the nektulos forest'
elif mode == 'legacy_bootstrap':
    pulse(('You have entered The Estate of Unrest.', 'Mindflux', 'P1999Green'))
    assert zone() == 'estate of unrest'
    pulse(('You have entered The Nektulos Forest.', 'Wildflux', 'P1999Green'))
    assert zone() == 'estate of unrest'
    assert maps._map_source_identity == ('mindflux', 'p1999green')
elif mode == 'unsupported_zone':
    line('You have entered East Commonlands.')
    player()
    pulse(snapshot('You have zoned into Unsupported Testing Zone.'))
    assert '__you__' not in maps._map._data.players
    assert maps._map_source_zones[('mindflux', 'p1999green')] == ''
    line('Your Location is 9000, 8000, 4', seconds=2)
    assert '__you__' not in maps._map._data.players
elif mode == 'bounded_cache':
    line('You have entered East Commonlands.', seconds=10)
    for number in range(40):
        pulse(snapshot('You have entered The Estate of Unrest.',
                       character=f'Alt{number}', active=False))
    assert len(maps._map_source_zones) == 32
    assert ('mindflux', 'p1999green') in maps._map_live_zone_events
    pulse(snapshot('You have entered The Nektulos Forest.', seconds=5))
    assert zone() == 'east commonlands'
maps.close()
app.quit()
print('ZONE RECONCILIATION PASSED')
'''


@pytest.mark.parametrize('mode', [
    'missed_zone', 'stale_live_priority', 'same_second', 'active_character',
    'loading_and_truncation', 'legacy_bootstrap', 'unsupported_zone', 'bounded_cache',
])
def test_zone_context_reconciliation(tmp_path, mode):
    result = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT, mode],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path),
                 QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ZONE RECONCILIATION PASSED' in result.stdout


LIVE_READER_SCRIPT = r'''
from datetime import datetime, timedelta
import os
from pathlib import Path
import time
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
from vantage.helpers import config

logs = Path(os.environ['VANTAGE_DATA_DIR']) / 'Logs'
logs.mkdir()
path = logs / 'eqlog_Mindflux_P1999Green.txt'
start = datetime.now().replace(microsecond=0)
def entry(text, seconds=0):
    stamp = (start + timedelta(seconds=seconds)).strftime('%a %b %d %H:%M:%S %Y')
    return f'[{stamp}] {text}\r\n'.encode()
def append(text, seconds=0):
    with path.open('ab') as stream:
        stream.write(entry(text, seconds))
def wait_until(condition, timeout=3500):
    deadline = time.monotonic() + timeout / 1000
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(25)
    assert condition(), 'Timed out waiting for the real Qt/log-reader flow'

path.write_bytes(entry('You have entered The Estate of Unrest.'))
config.data['general'].update(eq_log_dir=str(logs), update_check=False,
                             audio_muted=True, log_archive_enabled=False)
app = VantageApp([])
maps = app._parsers_dict['maps']
maps.show()
reader = app._log_reader
assert reader is not None
assert reader._zone_context_timer.interval() == 2000
wait_until(lambda: maps._map._data.zone == 'estate of unrest')
reader._zone_context_timer.stop()
append('Your Location is 10, 20, 3', 1)
wait_until(lambda: '__you__' in maps._map._data.players)
old_marker = maps._map._data.players['__you__']
skipped = []
original_parse = maps.parse
def miss_one_zone(timestamp, text):
    if text == 'You have entered East Commonlands.':
        skipped.append(text)
        return
    original_parse(timestamp, text)
maps.parse = miss_one_zone
append('You have entered East Commonlands.', 2)
wait_until(lambda: len(skipped) == 1)
assert reader._stats[str(path)]['last_read'] == path.stat().st_size
assert maps._map._data.zone == 'estate of unrest'
assert maps._map._data.players['__you__'] is old_marker

# The normal two-second timer must repair the skipped parser event without
# moving the reader's cursor backwards or replaying the entry as a live line.
reader._zone_context_timer.start()
wait_until(lambda: maps._map._data.zone == 'east commonlands')
assert skipped == ['You have entered East Commonlands.']
assert '__you__' not in maps._map._data.players
assert maps._map.location_overlay._location is None
append('Your Location is 100, 200, 3', 3)
wait_until(lambda: '__you__' in maps._map._data.players)
marker = maps._map._data.players['__you__']
assert (marker.location.x, marker.location.y) == (-200, -100)
checks = reader._zone_context_checks
wait_until(lambda: reader._zone_context_checks > checks)
assert maps._map._data.players['__you__'] is marker
assert maps._preview_zone('skyshrine')
preview = maps._preview_map
checks = reader._zone_context_checks
wait_until(lambda: reader._zone_context_checks > checks)
assert maps._preview_map is preview
assert maps._map._data.players['__you__'] is marker
assert skipped == ['You have entered East Commonlands.']
reader.stop()
app.quit_vantage(confirm=False)
print('LIVE READER ZONE RECOVERY PASSED')
'''


def test_real_app_recovers_missed_map_dispatch_on_zone_heartbeat(tmp_path):
    result = subprocess.run(
        [sys.executable, '-B', '-c', LIVE_READER_SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path),
                 QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LIVE READER ZONE RECOVERY PASSED' in result.stdout
