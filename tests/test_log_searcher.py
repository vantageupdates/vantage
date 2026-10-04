from datetime import datetime, timedelta

from vantage.helpers.log_search_cache import (
    LogSearchCache, cache_path_for_log_root, classify_log_message,
    linked_logs_directory, log_identity)


def _line(stamp, message):
    return f"[{stamp.strftime('%a %b %d %H:%M:%S %Y')}] {message}\n"


def test_incremental_cache_finds_nested_logs_and_filters_by_character(tmp_path):
    logs = tmp_path / "Logs"
    archive = logs / "archive"
    archive.mkdir(parents=True)
    now = datetime.now().replace(microsecond=0)
    alpha = logs / "eqlog_Alpha_P1999Green.txt"
    beta = archive / "eqlog_Beta_P1999Blue.txt"
    alpha.write_text(
        _line(now - timedelta(minutes=3), "Bob tells you, 'hello there'") +
        _line(now - timedelta(minutes=2), "You have been slain by a dragon!"),
        encoding="utf-8")
    beta.write_text(
        _line(now - timedelta(days=10), "You have looted a Ruby."),
        encoding="utf-8")
    cache = LogSearchCache(tmp_path / "cache.sqlite3")

    first = cache.index_directory(logs)
    assert (first.files, first.indexed_lines, first.added_lines) == (2, 3, 3)
    assert first.characters == (
        ("Alpha", "P1999Green"), ("Beta", "P1999Blue"))

    deaths, truncated = cache.search(
        category="death", character="Alpha", server="P1999Green")
    assert not truncated
    assert len(deaths) == 1
    assert deaths[0].message == "You have been slain by a dragon!"
    assert deaths[0].timestamp.startswith(str(now.year))

    with alpha.open("a", encoding="utf-8") as stream:
        stream.write(_line(now, "Alice tells you, 'meet at the tunnel'"))
    second = cache.index_directory(logs)
    assert second.added_lines == 1
    conversation, _ = cache.search(
        "tunnel", category="conversation", since_epoch=(
            now - timedelta(hours=1)).timestamp())
    assert [row.character for row in conversation] == ["Alpha"]
    assert cache.index_directory(logs).added_lines == 0


def test_cache_leaves_incomplete_line_for_the_live_listener_retry(tmp_path):
    logs = tmp_path / "Logs"
    logs.mkdir()
    path = logs / "eqlog_Mindflux_P1999Green.txt"
    path.write_bytes(b"[Wed Sep 10 02:00:00 2026] partial")
    cache = LogSearchCache(tmp_path / "cache.sqlite3")
    assert cache.index_directory(logs).indexed_lines == 0

    with path.open("ab") as stream:
        stream.write(b" message\r\n")
    summary = cache.index_directory(logs)
    results, _ = cache.search("partial message")
    assert summary.added_lines == 1
    assert results[0].character == "Mindflux"


def test_log_categories_and_identity_are_stable():
    assert log_identity("eqlog_Mindflux_P1999Green.txt") == (
        "Mindflux", "P1999Green")
    assert classify_log_message("Rina auctions, 'WTS JBoots'") == "conversation"
    assert classify_log_message("You have entered West Commonlands.") == "zone"
    assert classify_log_message("You have looted a Fine Steel Sword.") == "loot"
    assert classify_log_message("You have been slain by a griffin!") == "death"


def test_shared_cache_path_and_raid_tick_filters_cover_every_linked_log(
        tmp_path, monkeypatch):
    logs = tmp_path / "EverQuest" / "Logs"
    nested = logs / "archive" / "raids"
    nested.mkdir(parents=True)
    now = datetime.now().replace(microsecond=0)
    (logs / "eqlog_Alpha_P1999Green.txt").write_text(
        _line(now - timedelta(hours=2),
              "Raidlead tells the raid, 'RAID TICK'"), encoding="utf-8")
    (nested / "eqlog_Beta_P1999Blue.txt").write_text(
        _line(now - timedelta(days=40),
              "Officer tells the guild, 'Attendance tick'"), encoding="utf-8")
    monkeypatch.setattr(
        "vantage.helpers.log_search_cache.data_dir",
        lambda *parts: tmp_path.joinpath("data", *parts))

    assert linked_logs_directory("", logs.parent) == str(logs.resolve())
    shared_path = cache_path_for_log_root(logs)
    assert shared_path == cache_path_for_log_root(logs.resolve())
    cache = LogSearchCache(shared_path)
    summary = cache.index_directory(logs)
    assert summary.files == 2

    recent, truncated = cache.search(
        "RAID TICK", character="Alpha", server="P1999Green",
        since_epoch=(now - timedelta(days=7)).timestamp())
    assert not truncated
    assert [(row.character, row.server, row.source) for row in recent] == [
        ("Alpha", "P1999Green", "eqlog_Alpha_P1999Green.txt")]
    old, _ = cache.search(
        "Attendance tick", since_epoch=(now - timedelta(days=30)).timestamp())
    assert old == ()

