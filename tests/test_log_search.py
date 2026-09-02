import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vantage.parsers.combat import LogSearchWorker, _reverse_log_lines


def _app():
    return QApplication.instance() or QApplication([])


def _run(worker):
    _app()
    output = []
    worker.finished.connect(
        lambda rows, error, truncated: output.append(
            (rows, error, truncated)))
    worker.run()
    assert len(output) == 1
    return output[0]


def test_reverse_log_reader_does_not_load_or_reorder_lines(tmp_path):
    path = tmp_path / "eqlog_Test.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert list(_reverse_log_lines(path)) == ["three", "two", "one"]


def test_log_search_supports_reverse_regex_limits_and_time_range(tmp_path):
    path = tmp_path / "eqlog_Test.txt"
    path.write_text(
        "[Sun Aug 30 10:00:00 2026] Alice hits a bat for 5 points of damage.\n"
        "[Sun Aug 30 11:00:00 2026] Bob auctions, 'WTS Manastone 450k'\n"
        "[Sun Aug 30 12:00:00 2026] Alice hits a rat for 9 points of damage.\n",
        encoding="utf-8")

    rows, error, truncated = _run(LogSearchWorker(
        tmp_path, r"Alice hits a (?:bat|rat)", regex=True,
        reverse=True, limit=1,
        since=datetime.datetime(2026, 8, 30, 11, 30)))
    assert error == ""
    assert truncated is True
    assert len(rows) == 1
    assert "rat" in rows[0][2]
    assert rows[0][1] == "—"


def test_log_search_reports_invalid_regex(tmp_path):
    (tmp_path / "eqlog_Test.txt").write_text("anything\n", encoding="utf-8")
    rows, error, truncated = _run(LogSearchWorker(
        tmp_path, "(", regex=True))
    assert rows == []
    assert "Invalid regular expression" in error
    assert truncated is False

