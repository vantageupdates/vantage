"""Bounded local history for loot, coin, and faction log events."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

from vantage.helpers.portable import data_dir


class ActivityArchive:
    """Persist GamParse-style activity while the original EQ log stays source."""

    def __init__(self, path=None, max_rows=50_000):
        self.path = Path(path) if path else data_dir("activity-history.sqlite")
        self.max_rows = max(3_000, min(500_000, int(max_rows)))
        self.error = ""
        self._database = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._database = sqlite3.connect(self.path, timeout=2.0)
            self._database.execute("PRAGMA journal_mode=WAL")
            self._database.execute("PRAGMA synchronous=NORMAL")
            self._database.executescript("""
                CREATE TABLE IF NOT EXISTS faction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, faction TEXT NOT NULL,
                    change_text TEXT NOT NULL, delta INTEGER NOT NULL DEFAULT 0,
                    zone TEXT NOT NULL DEFAULT '', character TEXT NOT NULL DEFAULT '',
                    server TEXT NOT NULL DEFAULT '',
                    UNIQUE(timestamp, faction, change_text, zone, character, server)
                );
                CREATE TABLE IF NOT EXISTS loot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, looter TEXT NOT NULL,
                    item TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT '', zone TEXT NOT NULL DEFAULT '',
                    character TEXT NOT NULL DEFAULT '', server TEXT NOT NULL DEFAULT '',
                    UNIQUE(timestamp, looter, item, quantity, source, character, server)
                );
                CREATE TABLE IF NOT EXISTS coin_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, amount TEXT NOT NULL,
                    copper INTEGER NOT NULL, kind TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '', item TEXT NOT NULL DEFAULT '',
                    zone TEXT NOT NULL DEFAULT '', character TEXT NOT NULL DEFAULT '',
                    server TEXT NOT NULL DEFAULT '',
                    UNIQUE(timestamp, amount, copper, kind, source, item, character, server)
                );
                CREATE INDEX IF NOT EXISTS faction_events_time
                    ON faction_events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS loot_events_time
                    ON loot_events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS coin_events_time
                    ON coin_events(timestamp DESC);
            """)
            for table in ("faction_events", "loot_events", "coin_events"):
                self._database.execute(f"""
                    DELETE FROM {table} WHERE id IN (
                        SELECT id FROM {table}
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

    @staticmethod
    def _timestamp(value):
        return (
            value.isoformat(sep=" ", timespec="seconds")
            if isinstance(value, datetime.datetime) else str(value))

    @staticmethod
    def _parse_timestamp(value):
        try:
            return datetime.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def _insert(self, statement, values):
        if self._database is None:
            return False
        try:
            cursor = self._database.execute(statement, values)
            self._database.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as error:
            self.error = str(error)
            return False

    def append_faction(self, event, character="", server=""):
        return self._insert("""
            INSERT OR IGNORE INTO faction_events (
                timestamp, faction, change_text, delta, zone, character, server)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self._timestamp(event.timestamp), event.faction, event.change,
            int(event.delta), event.zone, str(character or ""), str(server or "")))

    def append_loot(self, event, character="", server=""):
        return self._insert("""
            INSERT OR IGNORE INTO loot_events (
                timestamp, looter, item, quantity, source, zone, character, server)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self._timestamp(event.timestamp), event.looter, event.item,
            int(event.count), event.source, event.zone,
            str(character or ""), str(server or "")))

    def append_coin(self, event, character="", server=""):
        return self._insert("""
            INSERT OR IGNORE INTO coin_events (
                timestamp, amount, copper, kind, source, item, zone,
                character, server)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self._timestamp(event.timestamp), event.amount, int(event.copper),
            event.kind, event.source, event.item, event.zone,
            str(character or ""), str(server or "")))

    def _recent(self, table, columns, limit):
        if self._database is None:
            return []
        limit = max(1, min(self.max_rows, int(limit)))
        try:
            rows = self._database.execute(
                f"SELECT timestamp, {columns} FROM {table} "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        parsed = []
        for row in rows:
            timestamp = self._parse_timestamp(row[0])
            if timestamp is not None:
                parsed.append((timestamp, *row[1:]))
        return parsed

    def recent_faction(self, limit=3000):
        return self._recent(
            "faction_events",
            "faction, change_text, zone, delta, character, server", limit)

    def recent_loot(self, limit=2000):
        return self._recent(
            "loot_events",
            "looter, item, quantity, source, zone, character, server", limit)

    def recent_coins(self, limit=3000):
        return self._recent(
            "coin_events",
            "amount, copper, kind, source, item, zone, character, server", limit)

    def close(self):
        database, self._database = self._database, None
        if database is not None:
            try:
                database.close()
            except sqlite3.Error:
                pass
