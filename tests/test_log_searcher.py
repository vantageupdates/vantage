from datetime import datetime, timedelta

from vantage.helpers.log_search_cache import (
    LogSearchCache, classify_log_message, log_identity)


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

