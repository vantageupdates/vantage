"""Small local SQLite archive for parsed EverQuest chat messages."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

from vantage.helpers.portable import data_dir


class ChatArchive:
    """Persist chat outside the EXE while keeping reads and storage bounded."""

    def __init__(self, path=None, max_rows=100_000):
        self.path = Path(path) if path else data_dir("chat-history.sqlite")
        self.max_rows = max(1_000, min(1_000_000, int(max_rows)))
        self.error = ""
        self._database = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._database = sqlite3.connect(self.path, timeout=2.0)
            self._database.execute("PRAGMA journal_mode=WAL")
            self._database.execute("PRAGMA synchronous=NORMAL")
            self._database.execute("""
                CREATE TABLE IF NOT EXISTS chat_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    message TEXT NOT NULL,
                    character TEXT NOT NULL DEFAULT '',
                    server TEXT NOT NULL DEFAULT ''
                )
            """)
            self._database.execute("""
                CREATE INDEX IF NOT EXISTS chat_events_time
                ON chat_events(timestamp DESC)
            """)
            self._database.execute("""
                CREATE INDEX IF NOT EXISTS chat_events_channel
                ON chat_events(channel, timestamp DESC)
            """)
            self._database.execute("""
                DELETE FROM chat_events WHERE id IN (
                    SELECT id FROM chat_events
                    ORDER BY id DESC LIMIT -1 OFFSET ?
                )
            """, (self.max_rows,))
            self._database.commit()
        except (OSError, sqlite3.Error) as error:
            self.error = str(error)
            self.close()

    @property
    def available(self):
        return self._database is not None

    def append(
            self, timestamp, channel, speaker, message,
            character="", server=""):
        if self._database is None:
            return False
        if isinstance(timestamp, datetime.datetime):
            timestamp = timestamp.isoformat(sep=" ", timespec="seconds")
        try:
            self._database.execute("""
                INSERT INTO chat_events (
                    timestamp, channel, speaker, message, character, server)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                str(timestamp), str(channel), str(speaker), str(message),
                str(character or ""), str(server or "")))
            self._database.commit()
            return True
        except sqlite3.Error as error:
            self.error = str(error)
            return False

    def recent(self, limit=20_000):
        """Return newest-first tuples suitable for the in-memory browser."""
        if self._database is None:
            return []
        limit = max(1, min(self.max_rows, int(limit)))
        try:
            rows = self._database.execute("""
                SELECT timestamp, channel, speaker, message, character, server
                FROM chat_events ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        parsed = []
        for timestamp, channel, speaker, message, character, server in rows:
            try:
                stamp = datetime.datetime.fromisoformat(timestamp)
            except (TypeError, ValueError):
                continue
            parsed.append((
                stamp, channel, speaker, message, character, server))
        return parsed

    def count(self):
        if self._database is None:
            return 0
        try:
            return int(self._database.execute(
                "SELECT COUNT(*) FROM chat_events").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.error = str(error)
            return 0

    def close(self):
        database, self._database = self._database, None
        if database is not None:
            try:
                database.close()
            except sqlite3.Error:
                pass
