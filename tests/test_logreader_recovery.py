import os

import pytest
from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vantage.helpers.logreader import LogReader, LogReaderSignals


def entry(text):
    return ('[Mon Oct 26 03:04:02 2026] ' + text + '\r\n').encode()


@pytest.fixture
def linked(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous = getattr(app, '_signals', None)
    signals = LogReaderSignals()
    app._signals = {'logreader': signals}
    path = tmp_path / 'eqlog_Example_P1999Green.txt'
    path.write_bytes(entry('You have entered The Estate of Unrest.') + entry('Old cast.'))
    reader = LogReader(str(tmp_path))
    events, contexts, characters = [], [], []
    signals.new_line.connect(events.append)
    signals.zone_context.connect(contexts.append)
    signals.character_updated.connect(characters.append)
    yield reader, path, events, contexts, characters
    reader.stop()
    reader.deleteLater()
    app.processEvents()
    app._signals = previous or {}


def test_poll_recovers_dropped_watch_without_replaying_old_casts(linked):
    reader, path, events, contexts, chars = linked
    reader._watcher.removePath(str(path))
    with path.open('ab') as stream:
        stream.write(entry('You have entered South Ro.'))
    reader._poll()
    assert [event[1] for event in events] == ['You have entered South Ro.']
    assert contexts == [('You have entered The Estate of Unrest.', 'Example', 'P1999Green')]
    assert str(path) in reader._watcher.files()
    reader._poll()
    assert len(events) == 1 and chars == ['Example']


def test_bootstrap_only_recovers_zone_not_activity(linked):
    reader, _path, events, contexts, chars = linked
    reader._bootstrap_context()
    assert contexts[0][0] == 'You have entered The Estate of Unrest.'
    assert events == [] and chars == []


def test_rotation_and_partial_write_are_recovered(linked):
    reader, path, events, _contexts, _chars = linked
    replacement = path.with_suffix('.new')
    replacement.write_bytes(entry('You have entered East Commonlands.'))
    # Windows native watches can temporarily hold a delete-sharing handle.
    # Rotation also drops that watch; the recovery poll must repair it.
    reader._watcher.removePath(str(path))
    os.replace(replacement, path)
    reader._poll()
    assert [event[1] for event in events] == ['You have entered East Commonlands.']
    with path.open('ab') as stream:
        stream.write(entry('Your Location is 10, 20, 30')[:-2])
    reader._poll()
    assert len(events) == 1
    with path.open('ab') as stream:
        stream.write(b'\r\n')
    reader._poll()
    assert events[-1][1] == 'Your Location is 10, 20, 30'


def test_failed_open_retries_without_losing_cursor(linked, monkeypatch):
    import builtins
    reader, path, events, _contexts, _chars = linked
    with path.open('ab') as stream:
        stream.write(entry('You have entered Nektulos Forest.'))
    original = builtins.open
    def locked(*args, **kwargs):
        if str(args[0]) == str(path):
            raise PermissionError('temporary sharing violation')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', locked)
        reader._poll()
    assert not events
    reader._poll()
    assert len(events) == 1


def test_large_burst_is_bounded_and_eventually_complete(linked):
    reader, path, events, _contexts, _chars = linked
    with path.open('ab') as stream:
        for index in range(300):
            stream.write(entry(f'Line {index}'))
    reader._poll()
    assert len(events) == 128
    reader._poll()
    reader._poll()
    assert [event[1] for event in events] == [f'Line {index}' for index in range(300)]


def test_new_log_found_even_without_directory_event(linked):
    reader, path, events, _contexts, _chars = linked
    new = path.parent / 'eqlog_Alt_P1999Blue.txt'
    new.write_bytes(entry('You have entered Greater Faydark.'))
    reader._poll()
    assert events[-1][2:] == ('Alt', 'P1999Blue')
    reader.stop()
    assert not reader._poll_timer.isActive()
    assert not reader._watcher.files()


def test_directory_event_delivers_first_new_character_cast_immediately(linked):
    reader, path, events, _contexts, _chars = linked
    new = path.parent / 'eqlog_Alt_P1999Blue.txt'
    # EQ can create and finish its first write before Windows delivers the
    # directory event. Installing a file watch alone misses that first write.
    new.write_bytes(entry('You begin casting Yaulp II.') +
                    entry('You feel an aura of divine strength.'))
    reader._dir_changed(str(path.parent))
    assert [event[1] for event in events] == [
        'You begin casting Yaulp II.', 'You feel an aura of divine strength.']
    assert all(event[2:] == ('Alt', 'P1999Blue') for event in events)
    reader._poll()
    assert len(events) == 2


def test_automatic_recovery_delivers_cast_within_half_second(linked):
    reader, path, events, _contexts, _chars = linked
    # Exercise the real event loop, without explicitly invoking _poll: a
    # dropped native watch must still deliver a short cast before its landing.
    reader._watcher.removePath(str(path))
    elapsed = QElapsedTimer()
    elapsed.start()
    with path.open('ab') as stream:
        stream.write(entry('You begin casting Yaulp II.'))
    while not events and elapsed.elapsed() < 650:
        QTest.qWait(10)
    assert [event[1] for event in events] == ['You begin casting Yaulp II.']
    assert elapsed.elapsed() < 650


def test_native_append_and_queued_burst_deliver_all_cast_lines(linked):
    reader, path, events, _contexts, _chars = linked
    reader._poll_timer.stop()
    reader._recovery_timer.stop()
    expected = ['You begin casting Bravery.'] + [
        f'A rat hits a guard for {index} points of damage.'
        for index in range(300)] + ['You feel brave.']
    with path.open('ab') as stream:
        stream.write(b''.join(entry(text) for text in expected))
    # Only the native file event and queued backlog drain can satisfy this.
    elapsed = QElapsedTimer()
    elapsed.start()
    while len(events) < len(expected) and elapsed.elapsed() < 650:
        QTest.qWait(10)
    assert [event[1] for event in events] == expected
    assert all(event[0].strftime('%H:%M:%S') == '03:04:02' for event in events)


def test_automatic_recovery_retries_a_brief_windows_sharing_violation(
        linked, monkeypatch):
    import builtins
    reader, path, events, _contexts, _chars = linked
    reader._watcher.removePath(str(path))
    reader._poll_timer.stop()
    with path.open('ab') as stream:
        stream.write(entry('You begin casting Bravery.'))
    original = builtins.open
    def locked(*args, **kwargs):
        if str(args[0]) == str(path):
            raise PermissionError('temporary sharing violation')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', locked)
        QTest.qWait(300)
        assert not events
    elapsed = QElapsedTimer()
    elapsed.start()
    while not events and elapsed.elapsed() < 650:
        QTest.qWait(10)
    assert [event[1] for event in events] == ['You begin casting Bravery.']
    assert str(path) in reader._watcher.files()


def test_corrupt_oversized_record_does_not_block_later_zone(linked):
    reader, path, events, _contexts, _chars = linked
    with path.open('ab') as stream:
        stream.write(b'x' * (140 * 1024) + b'\r\n')
        stream.write(entry('You have entered Skyshrine.'))
    for _ in range(4):
        reader._poll()
    assert [event[1] for event in events] == ['You have entered Skyshrine.']


def test_stopped_reader_ignores_queued_watch_callbacks(linked):
    reader, path, events, contexts, _chars = linked
    reader.stop()
    with path.open('ab') as stream:
        stream.write(entry('You have entered Skyshrine.'))
    reader._file_changed_safe_wrap(str(path))
    reader._poll()
    reader._poll_known_files()
    reader._bootstrap_context()
    assert not events and not contexts
    assert not reader._recovery_timer.isActive()


def test_nested_qt_callback_cannot_skip_or_duplicate_cast_batches(linked):
    reader, path, events, _contexts, _chars = linked
    signals = QApplication.instance()._signals['logreader']
    # A synchronous zone signal can enter a nested Qt loop while the first
    # batch is being prepared. A recovery timeout can then reenter the reader.
    signals.zone_context.connect(reader._poll)
    expected = [f'Live event {index}' for index in range(300)]
    with path.open('ab') as stream:
        stream.write(b''.join(entry(text) for text in expected))
    for _ in range(4):
        reader._poll()
    assert [event[1] for event in events] == expected


def test_nested_new_line_callback_preserves_original_log_order(linked):
    reader, path, events, _contexts, _chars = linked
    signals = QApplication.instance()._signals['logreader']
    nested = []
    def process_pending_events(_line):
        if not nested:
            nested.append(True)
            reader._poll_known_files()
    signals.new_line.connect(process_pending_events)
    expected = [f'Live event {index}' for index in range(300)]
    with path.open('ab') as stream:
        stream.write(b''.join(entry(text) for text in expected))
    for _ in range(4):
        reader._poll()
    assert [event[1] for event in events] == expected


def test_stop_during_delivery_cancels_remaining_old_reader_events(linked):
    reader, path, events, _contexts, _chars = linked
    signals = QApplication.instance()._signals['logreader']
    signals.new_line.connect(lambda _line: reader.stop())
    with path.open('ab') as stream:
        stream.write(b''.join(entry(f'Live event {index}') for index in range(300)))
    reader._poll()
    assert [event[1] for event in events] == ['Live event 0']
    assert not reader._drain_timer.isActive()
    assert not reader._watcher.files()


@pytest.mark.parametrize('signal_name', [
    'zone_context', 'server_updated', 'character_updated'])
def test_stop_from_context_signal_never_delivers_or_rewatches(linked, signal_name):
    reader, path, events, _contexts, _chars = linked
    signals = QApplication.instance()._signals['logreader']
    getattr(signals, signal_name).connect(lambda _value: reader.stop())
    with path.open('ab') as stream:
        stream.write(entry('You begin casting Bravery.'))
    reader._poll()
    assert not events
    snapshot = reader.health_snapshot()
    assert snapshot['stopped'] and not any(snapshot['timers'].values())
    assert snapshot['watched_files'] == 0 and not snapshot['directory_watched']


def test_health_snapshot_distinguishes_pending_data_from_quiet_reader(linked):
    reader, path, events, _contexts, _chars = linked
    idle = reader.health_snapshot()
    assert idle['folder'] == str(path.parent)
    assert idle['stopped'] is False and idle['reading'] is False
    assert idle['known_files'] == idle['watched_files'] == 1
    assert idle['pending_bytes'] == idle['events_delivered'] == 0
    assert idle['active_errors'] == []
    with path.open('ab') as stream:
        stream.write(entry('You begin casting Bravery.'))
    pending = reader.health_snapshot()
    assert pending['pending_bytes'] > 0 and not events
    reader._poll()
    live = reader.health_snapshot()
    assert live['pending_bytes'] == 0 and live['events_delivered'] == 1
    assert live['last_checked_at'] > 0 and live['last_delivered_at'] > 0


def test_repair_restores_timers_and_watches_without_skipping_or_replay(linked):
    reader, path, events, _contexts, _chars = linked
    original_cursor = reader._stats[str(path)]['last_read']
    reader._poll_timer.stop()
    reader._recovery_timer.stop()
    reader._watcher.removePath(str(path))
    reader._dir_watcher.removePath(str(path.parent))
    with path.open('ab') as stream:
        stream.write(entry('You have entered Nektulos Forest.'))
    assert reader._stats[str(path)]['last_read'] == original_cursor
    snapshot = reader.repair()
    assert [event[1] for event in events] == ['You have entered Nektulos Forest.']
    assert snapshot['repair_count'] == 1
    assert snapshot['timers']['poll'] and snapshot['timers']['recovery']
    assert snapshot['directory_watched'] and snapshot['watched_files'] == 1
    assert reader._stats[str(path)]['last_read'] == path.stat().st_size
    reader.repair()
    assert len(events) == 1 and reader.health_snapshot()['repair_count'] == 1


def test_repair_never_reconnects_an_intentionally_stopped_reader(linked):
    reader, path, events, _contexts, _chars = linked
    reader.stop()
    with path.open('ab') as stream:
        stream.write(entry('You feel brave.'))
    snapshot = reader.repair()
    assert snapshot['stopped'] is True
    assert not any(snapshot['timers'].values())
    assert snapshot['watched_files'] == snapshot['repair_count'] == 0
    assert not events


def test_io_error_is_visible_until_a_successful_retry(linked, monkeypatch):
    import builtins
    reader, path, events, _contexts, _chars = linked
    with path.open('ab') as stream:
        stream.write(entry('You feel brave.'))
    original = builtins.open
    def locked(*args, **kwargs):
        if str(args[0]) == str(path):
            raise PermissionError('temporary sharing violation')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', locked)
        reader._poll()
        health = reader.health_snapshot()
        assert health['active_errors'][0]['file'] == path.name
        assert 'sharing violation' in health['active_errors'][0]['error']
        assert health['pending_bytes'] > 0 and health['reading'] is False
    reader.repair()
    assert reader.health_snapshot()['active_errors'] == []
    assert [event[1] for event in events] == ['You feel brave.']


def test_sustained_two_character_reads_survive_nested_loops_and_rotation(linked):
    reader, first, events, _contexts, _chars = linked
    second = first.parent / 'eqlog_Alt_P1999Blue.txt'
    second.write_bytes(b'')
    reader._poll()
    expected = {'Example': [], 'Alt': []}
    signals = QApplication.instance()._signals['logreader']
    nested_calls = []
    def nested_event_loop(_line):
        if len(events) % 113:
            return
        nested_calls.append(True)
        loop = QEventLoop()
        QTimer.singleShot(0, reader._poll)
        QTimer.singleShot(2, loop.quit)
        loop.exec()
    signals.new_line.connect(nested_event_loop)
    for cycle in range(16):
        if cycle and cycle % 4 == 0:
            reader._watcher.removePath(str(second))
            replacement = second.with_suffix('.new')
            replacement.write_bytes(b'')
            os.replace(replacement, second)
        if cycle % 3 == 0 and str(first) in reader._watcher.files():
            reader._watcher.removePath(str(first))
        for path, character in ((first, 'Example'), (second, 'Alt')):
            batch = [f'Cycle {cycle} event {index}' for index in range(140)]
            expected[character].extend(batch)
            with path.open('ab') as stream:
                stream.write(b''.join(entry(text) for text in batch))
        target_count = sum(map(len, expected.values()))
        reader._poll()
        elapsed = QElapsedTimer()
        elapsed.start()
        while len(events) < target_count and elapsed.elapsed() < 1500:
            QTest.qWait(10)
        assert len(events) == target_count
    assert nested_calls
    for character, lines in expected.items():
        assert [event[1] for event in events if event[2] == character] == lines
    health = reader.health_snapshot()
    assert health['pending_bytes'] == 0
    assert health['events_delivered'] == 4480
    assert health['active_errors'] == []
