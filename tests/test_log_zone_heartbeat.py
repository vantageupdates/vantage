"""Zone recovery must not replay activity or steal another log's cursor."""
import builtins
import os

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers.logreader import (
    LogReader, LogReaderSignals, ZONE_CONTEXT_SCAN_BYTES)


def entry(text):
    return ('[Tue Oct 27 07:00:01 2026] ' + text + '\r\n').encode()


@pytest.fixture
def linked(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous = getattr(app, '_signals', {})
    signals = LogReaderSignals()
    app._signals = {'logreader': signals}
    path = tmp_path / 'eqlog_Example_P1999Green.txt'
    path.write_bytes(entry('You have entered East Commonlands.'))
    reader = LogReader(str(tmp_path))
    events, contexts = [], []
    signals.new_line.connect(events.append)
    signals.zone_context.connect(contexts.append)
    reader._bootstrap_context()
    contexts.clear()
    yield reader, path, events, contexts, signals
    reader.stop()
    reader.deleteLater()
    app.processEvents()
    app._signals = previous


def test_zone_is_repeated_without_replaying_any_log_event(linked):
    reader, path, events, contexts, _ = linked
    cursor = reader._stats[str(path)]['last_read']
    reader._check_zone_context()
    reader._check_zone_context()
    assert not events
    assert len(contexts) == 2
    assert contexts[0]['text'] == 'You have entered East Commonlands.'
    assert contexts[0]['captured_at'] == contexts[1]['captured_at']
    assert contexts[0]['offset'] == contexts[1]['offset'] == cursor
    assert contexts[0]['active'] and contexts[0]['periodic']
    assert reader._stats[str(path)]['last_read'] == cursor


@pytest.mark.parametrize('text', [
    'You have entered Nektulos Forest.',
    'You have zoned into Nektulos Forest.',
    'You have zoned to Nektulos Forest.',
    'LOADING, PLEASE WAIT...',
    'There are 3 players in Nektulos Forest.',
])
def test_snapshot_survives_a_dropped_live_dispatch(linked, text):
    reader, path, events, contexts, signals = linked
    signals.new_line.disconnect(events.append)
    with path.open('ab') as stream:
        stream.write(entry(text))
    reader._poll()
    reader._check_zone_context()
    assert not events
    assert contexts[-1]['text'] == text
    assert contexts[-1]['offset'] == path.stat().st_size


def test_zone_heartbeat_also_recovers_unread_bytes_when_other_watches_stop(linked):
    reader, path, events, contexts, _ = linked
    reader._poll_timer.stop()
    reader._recovery_timer.stop()
    reader._watcher.removePath(str(path))
    with path.open('ab') as stream:
        stream.write(entry('You have entered Nektulos Forest.'))
    reader._check_zone_context()
    assert [event[1] for event in events] == ['You have entered Nektulos Forest.']
    assert contexts[-1]['text'] == 'You have entered Nektulos Forest.'
    assert contexts[-1]['offset'] == path.stat().st_size
    reader._check_zone_context()
    assert len(events) == 1


def test_append_during_recovery_does_not_replace_latest_zone_with_old_tail(linked, monkeypatch):
    reader, path, _events, contexts, _ = linked
    with path.open('ab') as stream:
        stream.write(entry('Ordinary chat.'))
    original = reader._file_changed_safe_wrap
    def append_during_drain(changed_path):
        with path.open('ab') as stream:
            stream.write(entry('You have entered Nektulos Forest.'))
        return original(changed_path)
    monkeypatch.setattr(reader, '_file_changed_safe_wrap', append_during_drain)
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered Nektulos Forest.'
    assert contexts[-1]['offset'] == path.stat().st_size


def test_partial_zone_does_not_replace_last_completed_zone(linked):
    reader, path, _events, contexts, _ = linked
    old_end = path.stat().st_size
    with path.open('ab') as stream:
        stream.write(entry('You have entered Nektulos Forest.')[:-2])
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered East Commonlands.'
    assert contexts[-1]['offset'] == old_end
    with path.open('ab') as stream:
        stream.write(b'\r\n')
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered Nektulos Forest.'


def test_quiet_active_zone_is_not_replaced_by_another_characters_chat(linked):
    reader, path, _events, contexts, _ = linked
    alt = path.parent / 'eqlog_Alt_P1999Blue.txt'
    alt.write_bytes(entry('You have entered Lower Guk.'))
    reader._poll()
    with path.open('ab') as stream:
        stream.write(entry('Your Location is 1, 2, 3'))
    reader._poll()
    with alt.open('ab') as stream:
        stream.write(entry("Someone tells you, 'Hello'"))
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['character'] == 'Example'
    assert contexts[-1]['server'] == 'P1999Green'


@pytest.mark.parametrize('replace', [False, True])
def test_rotation_or_truncation_drops_old_context(linked, replace):
    reader, path, _events, contexts, _ = linked
    reader._watcher.removePath(str(path))
    content = entry('LOADING, PLEASE WAIT...')
    if replace:
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(content)
        os.replace(replacement, path)
    else:
        path.write_bytes(content)
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'LOADING, PLEASE WAIT...'
    assert contexts[-1]['offset'] == len(content)


def test_lookup_walks_back_past_the_tail_without_moving_live_cursor(linked):
    reader, path, events, contexts, _ = linked
    reader.stop()
    path.write_bytes(entry('You have entered Skyshrine.') +
                     entry('A long but ordinary combat message.') *
                     (ZONE_CONTEXT_SCAN_BYTES // 50 * 3))
    reader = LogReader(str(path.parent))
    try:
        reader._bootstrap_context()
        cursor = reader._stats[str(path)]['last_read']
        assert not reader._zone_contexts
        for _ in range(7):
            reader._check_zone_context()
            if contexts and isinstance(contexts[-1], dict):
                break
        assert contexts[-1]['text'] == 'You have entered Skyshrine.'
        assert reader._stats[str(path)]['last_read'] == cursor
        assert not events
    finally:
        reader.stop()
        reader.deleteLater()


def test_historical_zone_line_split_between_scan_pages_is_not_lost(linked):
    original_reader, path, events, contexts, _ = linked
    original_reader.stop()
    zone = entry('You have entered Skyshrine.')
    # Put the marker across a backwards page boundary, not at the file start.
    page = ZONE_CONTEXT_SCAN_BYTES
    prefix = b'x' * (page - 20) + b'\n'
    suffix_size = 2 * page + 20 - len(zone)
    suffix = (entry('Other chat.') * (suffix_size // 20 + 1))[:suffix_size]
    path.write_bytes(prefix + zone + suffix)
    reader = LogReader(str(path.parent))
    try:
        reader._bootstrap_context()
        for _ in range(8):
            reader._check_zone_context()
            if contexts and isinstance(contexts[-1], dict):
                break
        assert contexts[-1]['text'] == 'You have entered Skyshrine.'
        assert contexts[-1]['offset'] == len(prefix) + len(zone)
        assert not events
    finally:
        reader.stop()
        reader.deleteLater()


def test_same_size_rewrite_does_not_certify_an_obsolete_zone(linked):
    reader, path, events, contexts, _ = linked
    reader._check_zone_context()
    contexts.clear()
    size = path.stat().st_size
    path.write_bytes(b'ordinary chat'.ljust(size - 2, b' ') + b'\r\n')
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    reader._poll()
    reader._check_zone_context()
    assert not contexts and not events
    assert str(path) not in reader._zone_contexts


def test_touching_a_log_does_not_replay_any_cast_or_chat(linked):
    reader, path, events, contexts, _ = linked
    reader._check_zone_context()
    contexts.clear()
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    reader._poll()
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered East Commonlands.'
    assert not events


def test_temporary_read_failure_retries_and_keeps_the_snapshot(linked, monkeypatch):
    reader, path, events, contexts, _ = linked
    original = builtins.open
    def locked(name, *args, **kwargs):
        if str(name) == str(path):
            raise PermissionError('temporary sharing violation')
        return original(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', locked)
        reader._check_zone_context()
    assert not contexts
    reader._check_zone_context()
    assert contexts[-1]['text'] == 'You have entered East Commonlands.'
    assert not events


def test_unchanged_file_check_reuses_verified_context_without_reopening(linked, monkeypatch):
    reader, path, events, contexts, _ = linked
    reader._check_zone_context()
    contexts.clear()
    original = builtins.open
    def no_reopen(name, *args, **kwargs):
        assert str(name) != str(path), 'Unchanged log was scanned again'
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', no_reopen)
    reader._check_zone_context()
    assert len(contexts) == 1 and not events


def test_real_timer_reconciles_and_stop_prevents_future_callbacks(linked):
    reader, _path, _events, contexts, signals = linked
    reader._zone_context_timer.setInterval(20)
    QTest.qWait(65)
    assert any(isinstance(context, dict) for context in contexts)
    signals.zone_context.connect(lambda _context: reader.stop())
    reader._check_zone_context()
    count = len(contexts)
    reader._check_zone_context()
    reader.repair()
    QTest.qWait(45)
    assert len(contexts) == count
    assert not reader._zone_context_timer.isActive()
