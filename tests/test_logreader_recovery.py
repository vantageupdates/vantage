import os

import pytest
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
    reader._bootstrap_context()
    assert not events and not contexts
