import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vantage.helpers.logreader import LogReader, LogReaderSignals
from vantage.helpers.log_monitor import LogMonitorDialog


def line(second, text):
    return f"[Fri Jan 02 03:04:{second:02d} 2026] {text}\r\n"


def test_logreader_keeps_an_independent_cursor_and_profile_for_each_log(tmp_path):
    first = tmp_path / "eqlog_Alice_Green.txt"
    second = tmp_path / "eqlog_Bob_Green.txt"
    first.write_text(line(1, "old Alice line"), encoding="utf-8")
    second.write_text(line(1, "old Bob line"), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    previous = getattr(app, "_signals", None)
    signals = LogReaderSignals()
    app._signals = {"logreader": signals}
    events = []
    signals.new_line.connect(events.append)
    reader = LogReader(str(tmp_path))
    try:
        with first.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line(2, "Alice casts a spell."))
        with second.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line(3, "Bob hits a bat."))
        reader._file_changed(str(first))
        reader._file_changed(str(second))

        assert [event[1] for event in events] == [
            "Alice casts a spell.", "Bob hits a bat."]
        assert [event[2] for event in events] == ["Alice", "Bob"]
        assert [event[3] for event in events] == ["Green", "Green"]

        with first.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line(4, "Alice hits a rat."))
        reader._file_changed(str(first))
        assert [event[1] for event in events] == [
            "Alice casts a spell.", "Bob hits a bat.", "Alice hits a rat."]
    finally:
        reader.deleteLater()
        if previous is not None:
            app._signals = previous


def test_profile_monitor_distinguishes_active_quiet_and_stale_logs(tmp_path):
    now = 2_000_000_000
    paths = []
    for name, age in (
            ('eqlog_Active_Green.txt', 15),
            ('eqlog_Quiet_Green.txt', 300),
            ('eqlog_Stale_Green.txt', 1800)):
        path = tmp_path / name
        path.write_text(line(1, name), encoding='utf-8')
        os.utime(path, (now - age, now - age))
        paths.append(path)

    reader = LogReader(str(tmp_path))
    try:
        profiles = reader.profiles(now)
        assert [profile['status'] for profile in profiles] == [
            'ACTIVE', 'QUIET', 'STALE']

        fake_app = type('FakeApp', (), {'_log_reader': reader})()
        dialog = LogMonitorDialog(fake_app)
        dialog.refresh()
        assert dialog.table.rowCount() == 3
        assert dialog.table.toolTip()
        assert dialog.table.item(0, 0).toolTip()
        dialog.close()
    finally:
        reader.deleteLater()
