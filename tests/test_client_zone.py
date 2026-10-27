"""Only completed debug-log transitions can provide a fallback map zone."""
from datetime import datetime
import os
from pathlib import Path

import pytest

from vantage.helpers.client_zone import (
    ClientZoneTracker, INITIAL_READ_BYTES, INCREMENTAL_READ_BYTES, MAX_LINE_BYTES)


def entry(message, second=12):
    return f'2026-10-27 10:08:{second:02d}\t{message}\r\n'.encode()


def transition(character='Holyflux', zone='East Commonlands', second=12):
    return (entry(f'Waiting to connect to zone... Character {character}', second) +
            entry('ZONING', second) +
            entry(f'Player = {character}, zone = {zone}', second + 1) +
            entry('Initializing zone.', second + 5) +
            entry('Zone initialized.', second + 6))


def append(path, data):
    with path.open('ab') as stream:
        stream.write(data)


@pytest.fixture
def tracker(tmp_path):
    path = tmp_path / 'dbg.txt'
    return ClientZoneTracker(tmp_path), path


def test_real_debug_sequence_confirms_only_after_ready(tracker):
    reader, path = tracker
    path.write_bytes(transition().split(entry('Zone initialized.', 18))[0])
    assert reader.poll() is None
    append(path, entry('Zone initialized.', 18))
    record = reader.poll()
    assert record['character'] == 'Holyflux'
    assert record['zone'] == 'East Commonlands'
    assert record['timestamp'] == datetime(2026, 10, 27, 10, 8, 18)
    assert record['identity'] == (path.stat().st_dev, path.stat().st_ino)
    assert record['path'] == str(path)
    assert record['offset'] == path.stat().st_size
    assert record['source'] == 'client_debug'
    assert 'server' not in record and 'text' not in record


@pytest.mark.parametrize('ready', [
    'Zone initialized.', 'Zone Connect -- Received MSG_READY_ENTER_WORLD',
])
def test_each_ready_marker_confirms_a_pending_player(tracker, ready):
    reader, path = tracker
    path.write_bytes(entry('Player = Holyflux, zone = North Ro') + entry(ready))
    assert reader.poll()['zone'] == 'North Ro'


def test_duplicate_ready_and_unrelated_ui_reload_keep_same_revision(tracker):
    reader, path = tracker
    path.write_bytes(transition())
    record = reader.poll()
    append(path, entry('Loading zone specific files.', 19) +
           entry('Zone initialized.', 20) +
           entry('Zone Connect -- Received MSG_READY_ENTER_WORLD', 20) +
           entry('Zone Connect -- Sending out a MSG_READY_ENTER_WORLD.', 20))
    assert reader.poll() == record
    assert reader.poll() == record


@pytest.mark.parametrize('message', [
    'ZONING', 'Waiting to connect to zone... Character Holyflux',
])
def test_zoning_invalidates_current_and_pending(tracker, message):
    reader, path = tracker
    path.write_bytes(transition())
    assert reader.poll()
    append(path, entry(message, 21))
    assert reader.poll() is None
    append(path, entry('Zone initialized.', 22))
    assert reader.poll() is None
    append(path, entry('Player = Holyflux, zone = North Ro', 23))
    assert reader.poll() is None
    append(path, entry(message, 24) + entry('Zone initialized.', 25))
    assert reader.poll() is None


def test_transitions_between_characters_and_same_second_events(tracker):
    reader, path = tracker
    path.write_bytes(transition())
    first = reader.poll()
    append(path, entry('ZONING', 18) +
           entry('Player = Mindflux, zone = North Ro', 18) +
           entry('Zone initialized.', 18))
    second = reader.poll()
    assert second['character'] == 'Mindflux'
    assert second['zone'] == 'North Ro'
    assert second['timestamp'] == first['timestamp']
    assert second['offset'] > first['offset']
    assert second['captured_at'] >= first['captured_at']


def test_multiple_transitions_in_initial_tail_keep_only_last_completed_one(tracker):
    reader, path = tracker
    path.write_bytes(transition() + transition('Mindflux', "Veeshan's Peak", 22))
    record = reader.poll()
    assert record['character'] == 'Mindflux'
    assert record['zone'] == "Veeshan's Peak"
    assert record['offset'] == path.stat().st_size
    append(path, entry('Player = Spiritflux, zone = North Ro', 30))
    assert reader.poll() is None


def test_partial_crlf_is_retained_and_offset_tracks_confirmation(tracker):
    reader, path = tracker
    path.write_bytes(entry('Player = Holyflux, zone = East Commonlands')[:-1])
    assert reader.poll() is None
    append(path, b'\n' + entry('Zone initialized.', 18)[:-2])
    assert reader.poll() is None
    append(path, b'\r')
    assert reader.poll() is None
    append(path, b'\n')
    assert reader.poll()['offset'] == path.stat().st_size


def test_only_strict_timestamped_complete_records_are_recognized(tracker):
    reader, path = tracker
    path.write_bytes(
        b'Player = Holyflux, zone = North Ro\r\n' +
        entry('Zone initialized.') +
        b'2026-99-27 10:08:12\tPlayer = Holyflux, zone = North Ro\r\n' +
        entry('Zone initialized.') +
        entry('Some text Player = Holyflux, zone = North Ro') +
        entry('Zone initialized.') +
        entry('Player = Holyflux, zone = North Ro').replace(b'\r\n', b'\n') +
        entry('Zone initialized.'))
    assert reader.poll() is None


def test_old_or_unmatched_ready_does_not_confirm_a_new_zone(tracker):
    reader, path = tracker
    path.write_bytes(entry('Zone initialized.') +
                     entry('Zone Connect -- Received MSG_READY_ENTER_WORLD'))
    assert reader.poll() is None
    append(path, entry('Player = Holyflux, zone = North Ro', 20) +
           entry('Zone initialized.', 19))
    assert reader.poll() is None
    append(path, entry('Zone initialized.', 20))
    assert reader.poll()['zone'] == 'North Ro'


def test_unchanged_file_is_not_reopened_and_returned_record_is_defensive(tracker, monkeypatch):
    reader, path = tracker
    path.write_bytes(transition())
    record = reader.poll()
    record['zone'] = 'Mutated outside the tracker'
    def forbidden(*_args, **_kwargs):
        raise AssertionError('An unchanged log must not be reopened')
    monkeypatch.setattr(Path, 'open', forbidden)
    assert reader.poll()['zone'] == 'East Commonlands'


@pytest.mark.parametrize('replacement', ['truncate', 'replace', 'rewrite_same_size'])
def test_replacement_never_returns_old_context(tracker, replacement):
    reader, path = tracker
    path.write_bytes(transition())
    old = reader.poll()
    if replacement == 'truncate':
        path.write_bytes(entry('Zone initialized.'))
    elif replacement == 'replace':
        other = path.with_suffix('.new')
        other.write_bytes(entry('Zone initialized.'))
        os.replace(other, path)
    else:
        previous = path.stat()
        path.write_bytes(b'x' * previous.st_size)
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
    assert reader.poll() is None
    append(path, b'\r\n' + transition('Mindflux', 'North Ro', 30))
    fresh = reader.poll()
    assert fresh['character'] == 'Mindflux'
    assert fresh['zone'] == 'North Ro'
    assert fresh['captured_at'] >= old['captured_at']


def test_missing_or_unreadable_file_clears_current_and_recovers(tracker, monkeypatch):
    reader, path = tracker
    assert reader.poll() is None
    path.write_bytes(transition())
    assert reader.poll()
    path.unlink()
    assert reader.poll() is None
    path.write_bytes(transition('Mindflux', 'North Ro'))
    assert reader.poll()['character'] == 'Mindflux'
    append(path, entry('Ordinary debug output.', 21))
    original_open = Path.open
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('busy test file')
        return original_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    assert reader.poll() is None
    monkeypatch.setattr(Path, 'open', original_open)
    assert reader.poll()['character'] == 'Mindflux'


def test_initial_read_is_bounded_to_tail_and_ignores_old_zone(tracker):
    reader, path = tracker
    path.write_bytes(transition() + b'x' * (INITIAL_READ_BYTES + 50) + b'\r\n')
    assert reader.poll() is None
    assert reader._offset == path.stat().st_size
    assert len(reader._partial) <= MAX_LINE_BYTES
    append(path, transition('Mindflux', 'North Ro'))
    assert reader.poll()['zone'] == 'North Ro'


@pytest.mark.parametrize('prefix, expected_zone', [
    (b'Old complete record\r\n', 'North Ro'),
    (b'An unfinished record prefix ', None),
])
def test_initial_tail_preserves_only_a_player_at_a_real_line_boundary(
        tracker, prefix, expected_zone):
    reader, path = tracker
    events = (entry('Player = Holyflux, zone = North Ro') +
              entry('Zone initialized.', 18))
    tail = events + b'x' * (INITIAL_READ_BYTES - len(events) - 2) + b'\r\n'
    assert len(tail) == INITIAL_READ_BYTES
    path.write_bytes(prefix + tail)
    record = reader.poll()
    if expected_zone:
        assert record['zone'] == expected_zone
        assert record['offset'] == len(prefix) + len(events)
    else:
        assert record is None


def test_incremental_read_is_bounded_and_cross_chunk_lines_are_preserved(tracker):
    reader, path = tracker
    path.write_bytes(transition())
    original = reader.poll()
    prefix = b'x' * (INCREMENTAL_READ_BYTES - 10) + b'\r\n'
    append(path, prefix + transition('Mindflux', 'North Ro'))
    before = reader._offset
    assert reader.poll() == original
    assert reader._offset - before == INCREMENTAL_READ_BYTES
    assert reader._offset < path.stat().st_size
    assert reader.poll()['zone'] == 'North Ro'


def test_oversized_partial_line_cannot_inject_a_player_or_grow_buffer(tracker):
    reader, path = tracker
    path.write_bytes(b'')
    assert reader.poll() is None
    append(path, b'x' * (INCREMENTAL_READ_BYTES * 2))
    assert reader.poll() is None
    assert reader.poll() is None
    assert not reader._partial
    append(path, entry('Player = Holyflux, zone = North Ro') +
           entry('Zone initialized.'))
    assert reader.poll() is None
    append(path, transition('Mindflux', 'East Commonlands'))
    assert reader.poll()['character'] == 'Mindflux'


def test_only_selected_directory_dbg_file_is_considered(tmp_path):
    selected = tmp_path / 'Logs'
    selected.mkdir()
    (tmp_path / 'dbg.txt').write_bytes(transition())
    (selected / 'eqlog_Holyflux_P1999Green.txt').write_bytes(transition())
    assert ClientZoneTracker(selected).poll() is None


def test_replacement_during_read_does_not_certify_old_file(tracker, monkeypatch):
    reader, path = tracker
    path.write_bytes(transition())
    original_stat = Path.stat
    calls = []
    def replacing_stat(self, *args, **kwargs):
        if self == path:
            calls.append(True)
            if len(calls) == 2:
                replacement = path.with_suffix('.new')
                replacement.write_bytes(entry('Zone initialized.'))
                os.replace(replacement, path)
        return original_stat(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', replacing_stat)
    assert reader.poll() is None
    monkeypatch.setattr(Path, 'stat', original_stat)
    assert reader.poll() is None
