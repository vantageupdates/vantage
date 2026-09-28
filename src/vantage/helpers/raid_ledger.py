"""Private, bounded raid evidence captured from the local EverQuest log."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from vantage.helpers.portable import data_dir


VERIFIED = "Verified"
MISSING = "Missing"
PENDING = "Pending"
NOT_CHECKED = "Not checked"
CHECK_STATES = frozenset((VERIFIED, MISSING, PENDING, NOT_CHECKED))


def normalized_timestamp(value):
    """Return a stable ISO timestamp while preserving local-log wall time."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    text = str(value or "").strip()
    if text:
        return text[:64]
    return datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")


def parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def remote_raid_id(raid):
    raid = raid if isinstance(raid, dict) else {}
    for key in ("RaidId", "Id", "id", "ID"):
        value = raid.get(key)
        if value not in (None, ""):
            return str(value).strip()[:128]
    return ""


def remote_raid_name(raid):
    raid = raid if isinstance(raid, dict) else {}
    return " ".join(str(
        raid.get("Name") or raid.get("RaidName") or raid.get("EventName") or
        "OpenDKP raid").split())[:256]


def remote_raid_timestamp(raid):
    raid = raid if isinstance(raid, dict) else {}
    for key in (
            "Timestamp", "RaidDate", "StartTimestamp", "StartTime",
            "StartDate", "Date", "CreatedAt"):
        parsed = parse_timestamp(raid.get(key))
        if parsed is not None:
            return parsed
    return None


def raid_time_matches(session, raid, early_hours=2, late_hours=8):
    """Require the remote timestamp to be plausibly inside this local raid."""
    remote = remote_raid_timestamp(raid)
    started = parse_timestamp(session.get("started_at"))
    ended = parse_timestamp(session.get("ended_at"))
    if remote is None or started is None:
        return False
    if ended is None or ended < started:
        ended = started + timedelta(hours=6)
    return (started - timedelta(hours=early_hours) <= remote <=
            ended + timedelta(hours=late_hours))


_MEMBER_CONTAINERS = frozenset((
    "ticks", "raidticks", "attendance", "attendees", "members",
    "characters", "players", "participants", "models"))
_NAME_KEYS = (
    "CharacterName", "PlayerName", "MemberName", "ToonName", "characterName")
_DKP_KEYS = (
    "DKP", "Dkp", "Value", "Amount", "DKPAwarded", "Awarded")


def remote_tick_evidence(payload, character):
    """Return ``(matching rows, summed DKP)`` from flexible raid-detail shapes."""
    wanted = " ".join(str(character or "").split()).casefold()
    if not wanted:
        return [], None
    matches = []
    seen = set()
    tick_amounts = []

    # Current OpenDKP raid details attribute Value to the parent tick and put
    # each attendee under Ticks[].Characters[]. Preserve that relationship so
    # the toon's DKP is the sum of ticks where that toon actually appears.
    root = payload if isinstance(payload, dict) else {}
    ticks = root.get("Ticks") or root.get("ticks") or []
    if isinstance(ticks, list):
        for tick in ticks[:5000]:
            if not isinstance(tick, dict):
                continue
            characters = tick.get("Characters") or tick.get("characters") or []
            if not isinstance(characters, list):
                continue
            present = any(
                " ".join(str(next((
                    (member or {}).get(key) for key in
                    ("Name", *_NAME_KEYS) if (member or {}).get(key)), "")
                ).split()
                ).casefold() == wanted
                for member in characters if isinstance(member, dict))
            if not present:
                continue
            matches.append(tick)
            try:
                tick_amounts.append(float(tick.get("Value")))
            except (TypeError, ValueError):
                pass
        if matches:
            return matches, (sum(tick_amounts) if tick_amounts else None)

    def visit(value, member_context=False):
        if isinstance(value, list):
            for item in value[:5000]:
                visit(item, member_context)
            return
        if not isinstance(value, dict):
            return
        name = next((value.get(key) for key in _NAME_KEYS if value.get(key)), None)
        if name is None and member_context:
            name = value.get("Name")
        normalized = " ".join(str(name or "").split()).casefold()
        if normalized == wanted:
            marker = json.dumps(value, sort_keys=True, default=str)
            if marker not in seen:
                seen.add(marker)
                matches.append(value)
        for key, child in value.items():
            child_context = str(key).replace("_", "").casefold() in _MEMBER_CONTAINERS
            if isinstance(child, (list, dict)):
                visit(child, member_context or child_context)

    visit(payload)
    amounts = []
    for row in matches:
        for key in _DKP_KEYS:
            if row.get(key) in (None, ""):
                continue
            try:
                amounts.append(float(row[key]))
            except (TypeError, ValueError):
                pass
            break
    return matches, (sum(amounts) if amounts else None)


class RaidLedger:
    """SQLite-backed local raid sessions; the EQ log remains authoritative."""

    def __init__(self, path=None, max_sessions=500, max_ticks=10_000,
                 max_snapshots=2_000):
        self.path = Path(path) if path else data_dir("raid-ledger.sqlite")
        self.max_sessions = max(25, min(5000, int(max_sessions)))
        self.max_ticks = max(100, min(100_000, int(max_ticks)))
        self.max_snapshots = max(25, min(20_000, int(max_snapshots)))
        self.error = ""
        self._database = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._database = sqlite3.connect(self.path, timeout=3.0)
            self._database.row_factory = sqlite3.Row
            self._database.execute("PRAGMA journal_mode=WAL")
            self._database.execute("PRAGMA synchronous=NORMAL")
            self._database.execute("PRAGMA foreign_keys=ON")
            self._database.executescript("""
                CREATE TABLE IF NOT EXISTS raid_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL DEFAULT '',
                    character TEXT NOT NULL,
                    server TEXT NOT NULL DEFAULT '',
                    zone TEXT NOT NULL DEFAULT '',
                    mobs TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    waiting_for_who INTEGER NOT NULL DEFAULT 1,
                    remote_raid_id TEXT NOT NULL DEFAULT '',
                    manual_remote INTEGER NOT NULL DEFAULT 0,
                    remote_name TEXT NOT NULL DEFAULT '',
                    verification_status TEXT NOT NULL DEFAULT 'Not checked',
                    tick_count INTEGER NOT NULL DEFAULT 0,
                    dkp_total REAL,
                    last_checked TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS raid_ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES raid_sessions(id)
                        ON DELETE CASCADE,
                    timestamp TEXT NOT NULL,
                    speaker TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'log',
                    UNIQUE(session_id, timestamp, speaker, message, source)
                );
                CREATE TABLE IF NOT EXISTS raid_rosters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES raid_sessions(id)
                        ON DELETE CASCADE,
                    captured_at TEXT NOT NULL,
                    zone TEXT NOT NULL DEFAULT '',
                    members_json TEXT NOT NULL,
                    member_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, captured_at, members_json)
                );
                CREATE INDEX IF NOT EXISTS raid_sessions_character_time
                    ON raid_sessions(character, server, started_at DESC);
                CREATE INDEX IF NOT EXISTS raid_ticks_session_time
                    ON raid_ticks(session_id, timestamp);
                CREATE INDEX IF NOT EXISTS raid_rosters_session_time
                    ON raid_rosters(session_id, captured_at);
            """)
            columns = {
                row[1] for row in self._database.execute(
                    "PRAGMA table_info(raid_sessions)").fetchall()}
            if "manual_remote" not in columns:
                self._database.execute(
                    "ALTER TABLE raid_sessions ADD COLUMN "
                    "manual_remote INTEGER NOT NULL DEFAULT 0")
            self._prune()
            self._database.commit()
        except (OSError, sqlite3.Error) as error:
            self.error = str(error)
            self.close()

    @property
    def available(self):
        return self._database is not None

    @staticmethod
    def _identity(character, server):
        return (" ".join(str(character or "").split())[:64],
                " ".join(str(server or "").split())[:64])

    def _execute(self, statement, values=()):
        if self._database is None:
            return None
        try:
            cursor = self._database.execute(statement, values)
            self._database.commit()
            return cursor
        except sqlite3.Error as error:
            self.error = str(error)
            return None

    def _prune(self):
        if self._database is None:
            return
        self._database.execute("""
            DELETE FROM raid_sessions WHERE id IN (
                SELECT id FROM raid_sessions ORDER BY id DESC LIMIT -1 OFFSET ?)
        """, (self.max_sessions,))
        for table, limit in (("raid_ticks", self.max_ticks),
                             ("raid_rosters", self.max_snapshots)):
            self._database.execute(f"""
                DELETE FROM {table} WHERE id IN (
                    SELECT id FROM {table} ORDER BY id DESC LIMIT -1 OFFSET ?)
            """, (limit,))

    def active_session(self, character, server=""):
        if self._database is None:
            return None
        character, server = self._identity(character, server)
        try:
            row = self._database.execute("""
                SELECT * FROM raid_sessions
                WHERE character = ? COLLATE NOCASE
                  AND server = ? COLLATE NOCASE AND ended_at = ''
                ORDER BY id DESC LIMIT 1
            """, (character, server)).fetchone()
        except sqlite3.Error as error:
            self.error = str(error)
            return None
        return dict(row) if row is not None else None

    def start_session(self, timestamp, character, server="", zone=""):
        character, server = self._identity(character, server)
        if not character:
            return None
        active = self.active_session(character, server)
        if active is not None:
            return active
        cursor = self._execute("""
            INSERT INTO raid_sessions (
                started_at, character, server, zone, waiting_for_who)
            VALUES (?, ?, ?, ?, 1)
        """, (normalized_timestamp(timestamp), character, server,
              " ".join(str(zone or "").split())[:128]))
        if cursor is None:
            return None
        self._prune()
        self._database.commit()
        return self.session(cursor.lastrowid)

    def end_session(self, session_id, timestamp):
        cursor = self._execute("""
            UPDATE raid_sessions SET ended_at = ?
            WHERE id = ? AND ended_at = ''
        """, (normalized_timestamp(timestamp), int(session_id)))
        return bool(cursor and cursor.rowcount)

    def session(self, session_id):
        if self._database is None:
            return None
        try:
            row = self._database.execute(
                "SELECT * FROM raid_sessions WHERE id = ?",
                (int(session_id),)).fetchone()
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.error = str(error)
            return None
        return dict(row) if row is not None else None

    def sessions(self, limit=500, character="", server=""):
        if self._database is None:
            return []
        limit = max(1, min(self.max_sessions, int(limit)))
        clauses, values = [], []
        if character:
            clauses.append("character = ? COLLATE NOCASE")
            values.append(str(character))
        if server:
            clauses.append("server = ? COLLATE NOCASE")
            values.append(str(server))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        try:
            rows = self._database.execute(
                "SELECT * FROM raid_sessions" + where +
                " ORDER BY started_at DESC, id DESC LIMIT ?",
                (*values, limit)).fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        return [dict(row) for row in rows]

    def update_session(self, session_id, *, zone=None, mobs=None, notes=None):
        fields, values = [], []
        for key, value, limit in (
                ("zone", zone, 128), ("mobs", mobs, 1000),
                ("notes", notes, 8000)):
            if value is not None:
                fields.append(f"{key} = ?")
                values.append(str(value).strip()[:limit])
        if not fields:
            return False
        cursor = self._execute(
            f"UPDATE raid_sessions SET {', '.join(fields)} WHERE id = ?",
            (*values, int(session_id)))
        return bool(cursor and cursor.rowcount)

    def link_remote(self, session_id, remote_id):
        remote_id = " ".join(str(remote_id or "").split())[:128]
        cursor = self._execute("""
            UPDATE raid_sessions
            SET remote_raid_id = ?, manual_remote = 1, remote_name = '',
                verification_status = 'Not checked', dkp_total = NULL,
                last_checked = ''
            WHERE id = ?
        """, (remote_id, int(session_id)))
        return bool(cursor and cursor.rowcount)

    def set_check(self, session_id, status, *, remote_id="", remote_name="",
                  tick_count=0, dkp_total=None, checked_at=None):
        status = status if status in CHECK_STATES else NOT_CHECKED
        checked = "" if status in (PENDING, NOT_CHECKED) else normalized_timestamp(
            checked_at or datetime.now().astimezone())
        cursor = self._execute("""
            UPDATE raid_sessions SET verification_status = ?,
                remote_raid_id = CASE WHEN ? <> '' THEN ? ELSE remote_raid_id END,
                remote_name = ?, tick_count = ?, dkp_total = ?, last_checked = ?
            WHERE id = ?
        """, (status, str(remote_id), str(remote_id), str(remote_name)[:256],
              max(0, int(tick_count or 0)), dkp_total, checked,
              int(session_id)))
        return bool(cursor and cursor.rowcount)

    def add_tick(self, session_id, timestamp, speaker="", message="RAID TICK",
                 source="log"):
        cursor = self._execute("""
            INSERT OR IGNORE INTO raid_ticks (
                session_id, timestamp, speaker, message, source)
            VALUES (?, ?, ?, ?, ?)
        """, (int(session_id), normalized_timestamp(timestamp),
              " ".join(str(speaker or "").split())[:64],
              " ".join(str(message or "").split())[:512],
              str(source or "log")[:16]))
        if cursor is not None and cursor.rowcount:
            self._prune()
            self._database.commit()
            return True
        return False

    def add_roster(self, session_id, timestamp, zone, members):
        normalized = sorted({
            " ".join(str(member or "").split())[:64]
            for member in members if str(member or "").strip()
        }, key=str.casefold)
        payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        cursor = self._execute("""
            INSERT OR IGNORE INTO raid_rosters (
                session_id, captured_at, zone, members_json, member_count)
            VALUES (?, ?, ?, ?, ?)
        """, (int(session_id), normalized_timestamp(timestamp),
              " ".join(str(zone or "").split())[:128], payload,
              len(normalized)))
        if cursor is not None and cursor.rowcount:
            self._database.execute(
                "UPDATE raid_sessions SET waiting_for_who = 0 WHERE id = ?",
                (int(session_id),))
            self._prune()
            self._database.commit()
            return True
        return False

    def evidence(self, session_id):
        if self._database is None:
            return {"ticks": [], "rosters": []}
        try:
            ticks = [dict(row) for row in self._database.execute("""
                SELECT timestamp, speaker, message, source FROM raid_ticks
                WHERE session_id = ? ORDER BY timestamp, id
            """, (int(session_id),)).fetchall()]
            rosters = []
            for row in self._database.execute("""
                SELECT captured_at, zone, members_json, member_count
                FROM raid_rosters WHERE session_id = ?
                ORDER BY captured_at, id
            """, (int(session_id),)).fetchall():
                item = dict(row)
                try:
                    item["members"] = json.loads(item.pop("members_json"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["members"] = []
                rosters.append(item)
            return {"ticks": ticks, "rosters": rosters}
        except sqlite3.Error as error:
            self.error = str(error)
            return {"ticks": [], "rosters": []}

    def close(self):
        database, self._database = self._database, None
        if database is not None:
            try:
                database.close()
            except sqlite3.Error:
                pass
