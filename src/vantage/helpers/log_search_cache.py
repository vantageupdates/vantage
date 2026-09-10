"""Incremental, local-only search index for Project 1999 log files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import re
import sqlite3


SCHEMA_VERSION = 1
MAX_LOG_FILES = 4096
MAX_LINE_BYTES = 64 * 1024
LOG_NAME_RX = re.compile(r"^eqlog_(?P<body>.+)\.txt$", re.IGNORECASE)
LOG_LINE_RX = re.compile(
    r"^\[(?P<stamp>[A-Z][a-z]{2} [A-Z][a-z]{2} +\d{1,2} "
    r"\d{2}:\d{2}:\d{2} \d{4})\]\s*(?P<message>.*)$")


@dataclass(frozen=True)
class IndexSummary:
    files: int
    indexed_lines: int
    added_lines: int
    characters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SearchResult:
    timestamp: str
    character: str
    server: str
    category: str
    message: str
    source: str


def log_identity(filename):
    """Extract the log owner without trusting arbitrary filenames."""
    match = LOG_NAME_RX.fullmatch(Path(str(filename)).name)
    if not match:
        return "Unknown", "Unknown"
    body = match.group("body")
    if "_" not in body:
        return body or "Unknown", "Unknown"
    character, server = body.rsplit("_", 1)
    return character or "Unknown", server or "Unknown"


def classify_log_message(message):
    text = str(message or "")
    folded = text.casefold()
    if any(marker in folded for marker in (
            " tells you, '", " you told ", "you told ", " says, '",
            " auctions, '", " shouts, '", " says out of character, '",
            " tells the guild, '", " tells the group, '",
            " tells the raid, '")):
        return "conversation"
    if any(marker in folded for marker in (
            "you have been slain", " has been slain by ", " has died",
            "you died", " slain you")):
        return "death"
    if any(marker in folded for marker in (
            "you have looted", " has looted ", "you receive ",
            "you have received")):
        return "loot"
    if (folded.startswith("you have entered ") or
            "you have entered " in folded):
        return "zone"
    if any(marker in folded for marker in (
            " hits ", " slashes ", " crushes ", " pierces ",
            " punches ", " kicks ", " was hit by ", " for ")
            ) and any(ch.isdigit() for ch in folded):
        return "combat"
    return "system"


def parse_log_line(raw):
    text = str(raw or "").rstrip("\r\n")
    match = LOG_LINE_RX.match(text)
    if not match:
        return "", 0.0, text
    try:
        parsed = datetime.strptime(
            match.group("stamp"), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return "", 0.0, match.group("message")
    return parsed.isoformat(timespec="seconds"), parsed.timestamp(), \
        match.group("message")


class LogSearchCache:
    """SQLite-backed cache; original EQ logs remain strictly read-only."""

    def __init__(self, database_path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in (0, SCHEMA_VERSION):
            connection.executescript(
                "DROP TABLE IF EXISTS entries; DROP TABLE IF EXISTS files;")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                source TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                identity TEXT NOT NULL,
                indexed_offset INTEGER NOT NULL,
                character TEXT NOT NULL,
                server TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                byte_offset INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                epoch REAL NOT NULL,
                character TEXT NOT NULL,
                server TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                UNIQUE(source, byte_offset)
            );
            CREATE INDEX IF NOT EXISTS entries_owner
                ON entries(character, server, epoch DESC);
            CREATE INDEX IF NOT EXISTS entries_category
                ON entries(category, epoch DESC);
            CREATE INDEX IF NOT EXISTS entries_time ON entries(epoch DESC);
        """)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return connection

    @staticmethod
    def _validated_root(directory):
        root = Path(directory).expanduser().resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Choose the EverQuest Logs folder")
        return root

    @staticmethod
    def _files(root):
        found = []
        for path in root.rglob("*.txt"):
            if (path.is_symlink() or not path.is_file() or
                    not LOG_NAME_RX.fullmatch(path.name)):
                continue
            try:
                path.resolve(strict=True).relative_to(root)
            except (OSError, ValueError):
                continue
            found.append(path)
            if len(found) > MAX_LOG_FILES:
                raise ValueError(
                    f"More than {MAX_LOG_FILES:,} EverQuest logs were found; "
                    "archive older logs outside the Logs folder")
        return tuple(sorted(found, key=lambda item: str(item).casefold()))

    def index_directory(self, directory, progress=None):
        root = self._validated_root(directory)
        paths = self._files(root)
        added = 0
        with self._connect() as connection:
            known = {
                row[0]: row[1:]
                for row in connection.execute(
                    "SELECT source,size,mtime_ns,identity,indexed_offset "
                    "FROM files")}
            active = set()
            for position, path in enumerate(paths, 1):
                source = path.relative_to(root).as_posix()
                active.add(source)
                stat = path.stat()
                identity = f"{stat.st_dev}:{stat.st_ino}"
                previous = known.get(source)
                offset = int(previous[3]) if previous else 0
                if (previous and (previous[2] != identity or
                                  stat.st_size < offset)):
                    connection.execute(
                        "DELETE FROM entries WHERE source=?", (source,))
                    offset = 0
                character, server = log_identity(path.name)
                last_complete = offset
                batch = []
                with path.open("rb") as stream:
                    stream.seek(offset)
                    while True:
                        line_offset = stream.tell()
                        raw = stream.readline(MAX_LINE_BYTES + 1)
                        if not raw:
                            break
                        if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
                            while raw and not raw.endswith(b"\n"):
                                raw = stream.readline(MAX_LINE_BYTES + 1)
                            last_complete = stream.tell()
                            continue
                        if not raw.endswith(b"\n"):
                            break
                        last_complete = stream.tell()
                        timestamp, epoch, message = parse_log_line(
                            raw.decode("utf-8", errors="replace"))
                        batch.append((
                            source, line_offset, timestamp, epoch, character,
                            server, classify_log_message(message), message))
                        if len(batch) >= 1000:
                            before = connection.total_changes
                            connection.executemany(
                                "INSERT OR IGNORE INTO entries "
                                "(source,byte_offset,timestamp,epoch,character,"
                                "server,category,message) VALUES (?,?,?,?,?,?,?,?)",
                                batch)
                            added += connection.total_changes - before
                            batch.clear()
                if batch:
                    before = connection.total_changes
                    connection.executemany(
                        "INSERT OR IGNORE INTO entries "
                        "(source,byte_offset,timestamp,epoch,character,server,"
                        "category,message) VALUES (?,?,?,?,?,?,?,?)", batch)
                    added += connection.total_changes - before
                connection.execute(
                    "INSERT OR REPLACE INTO files "
                    "(source,size,mtime_ns,identity,indexed_offset,character,server) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (source, stat.st_size, stat.st_mtime_ns, identity,
                     last_complete, character, server))
                connection.commit()
                if progress:
                    progress(position, len(paths), source)
            for source in set(known) - active:
                connection.execute("DELETE FROM entries WHERE source=?", (source,))
                connection.execute("DELETE FROM files WHERE source=?", (source,))
            connection.commit()
            line_count = int(connection.execute(
                "SELECT COUNT(*) FROM entries").fetchone()[0])
            characters = tuple(connection.execute(
                "SELECT DISTINCT character,server FROM files "
                "ORDER BY character COLLATE NOCASE,server COLLATE NOCASE"))
        return IndexSummary(len(paths), line_count, added, characters)

    def profiles(self):
        with self._connect() as connection:
            return tuple(connection.execute(
                "SELECT DISTINCT character,server FROM files "
                "ORDER BY character COLLATE NOCASE,server COLLATE NOCASE"))

    def search(self, query="", *, character="", server="", category="",
               since_epoch=0.0, limit=1000):
        conditions = []
        parameters = []
        query = str(query or "").strip()
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%") \
                .replace("_", "\\_")
            conditions.append("message LIKE ? ESCAPE '\\' COLLATE NOCASE")
            parameters.append(f"%{escaped}%")
        if character:
            conditions.append("character=? COLLATE NOCASE")
            parameters.append(str(character))
        if server:
            conditions.append("server=? COLLATE NOCASE")
            parameters.append(str(server))
        if category:
            conditions.append("category=?")
            parameters.append(str(category))
        if since_epoch:
            conditions.append("epoch>=?")
            parameters.append(float(since_epoch))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        maximum = max(1, min(5000, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT timestamp,character,server,category,message,source "
                f"FROM entries{where} ORDER BY epoch DESC,id DESC LIMIT ?",
                (*parameters, maximum + 1)).fetchall()
        return tuple(SearchResult(*row) for row in rows[:maximum]), \
            len(rows) > maximum
