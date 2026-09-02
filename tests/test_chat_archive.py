import datetime

from vantage.helpers.chat_archive import ChatArchive


def test_chat_archive_persists_profiles_and_returns_newest_first(tmp_path):
    path = tmp_path / "chat.sqlite"
    first = ChatArchive(path)
    stamp = datetime.datetime(2026, 8, 30, 10, 30, 0)
    assert first.available is True
    assert first.append(
        stamp, "Guild", "Alice", "First", "Mindflux", "Green") is True
    assert first.append(
        stamp + datetime.timedelta(seconds=1), "Tell · Bob", "Bob",
        "Second", "Mindflux", "Green") is True
    assert first.count() == 2
    first.close()

    restored = ChatArchive(path)
    rows = restored.recent()
    assert restored.count() == 2
    assert [row[3] for row in rows] == ["Second", "First"]
    assert rows[0][4:] == ("Mindflux", "Green")
    restored.close()


def test_chat_archive_failure_never_breaks_parser_startup(tmp_path):
    path = tmp_path / "not-a-database.sqlite"
    path.write_bytes(b"not a sqlite database")
    archive = ChatArchive(path)
    assert archive.available is False
    assert archive.error
    assert archive.recent() == []
    assert archive.count() == 0
