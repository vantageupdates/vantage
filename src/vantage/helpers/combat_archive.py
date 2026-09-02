"""Durable, user-controlled storage for parsed combat encounters."""

from __future__ import annotations

from collections import deque
import datetime
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from vantage.helpers.combat import (
    AttackBreakdown, AttackerStats, CombatEvent, DamageModifierStats,
    Encounter, HealStats, SpellCastEvent, SpellStats, TankStats)
from vantage.helpers.portable import data_dir


@dataclass(frozen=True)
class CombatSummary:
    archive_id: int
    target: str
    started_at: datetime.datetime
    last_at: datetime.datetime
    zone: str
    character: str
    server: str
    killed: bool
    player_count: int
    your_dps: float
    total_damage: int
    duration: float

    @property
    def dps(self):
        return self.total_damage / max(1.0, self.duration)


def _timestamp(value):
    return (
        value.isoformat(sep=" ", timespec="microseconds")
        if isinstance(value, datetime.datetime) else str(value or ""))


def _parse_timestamp(value):
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _tank_payload(stats):
    return {
        "name": stats.name,
        "damage": stats.damage,
        "hits": stats.hits,
        "min_hit": stats.min_hit,
        "max_hit": stats.max_hit,
        "attempts": stats.attempts,
        "misses": stats.misses,
        "dodges": stats.dodges,
        "parries": stats.parries,
        "blocks": stats.blocks,
        "ripostes": stats.ripostes,
        "invulnerable": stats.invulnerable,
        "absorbed": stats.absorbed,
        "real_hits": stats.real_hits,
        "strikethroughs": stats.strikethroughs,
        "hit_counts": {str(key): value for key, value in stats.hit_counts.items()},
        "by_type": {
            name: _tank_payload(values) for name, values in stats.by_type.items()},
    }


def _tank_from_payload(values):
    values = values if isinstance(values, dict) else {}
    stats = TankStats(str(values.get("name") or "Unknown"))
    for key in (
            "damage", "hits", "min_hit", "max_hit", "attempts", "misses",
            "dodges", "parries", "blocks", "ripostes", "invulnerable",
            "absorbed", "real_hits", "strikethroughs"):
        setattr(stats, key, int(values.get(key, 0) or 0))
    stats.hit_counts = {
        int(amount): int(count) for amount, count in
        (values.get("hit_counts") or {}).items()}
    stats.by_type = {
        str(name): _tank_from_payload(item) for name, item in
        (values.get("by_type") or {}).items()}
    return stats


def encounter_payload(encounter):
    """Convert one parsed encounter to portable JSON-compatible data."""
    attackers = []
    for stats in encounter.attackers.values():
        attackers.append({
            "name": stats.name,
            "damage": stats.damage,
            "hits": stats.hits,
            "max_hit": stats.max_hit,
            "min_hit": stats.min_hit,
            "attempts": stats.attempts,
            "misses": stats.misses,
            "criticals": stats.criticals,
            "first_at": _timestamp(stats.first_at),
            "last_at": _timestamp(stats.last_at),
            "by_type": {
                name: {
                    "name": values.name, "damage": values.damage,
                    "hits": values.hits, "min_hit": values.min_hit,
                    "max_hit": values.max_hit}
                for name, values in stats.by_type.items()},
            "critical_types": dict(stats.critical_types),
            "damage_modifiers": [
                {
                    "attack_type": values.attack_type,
                    "critical_type": values.critical_type,
                    "samples": values.samples,
                    "reported_damage": values.reported_damage,
                    "actual_damage": values.actual_damage,
                }
                for values in stats.damage_modifiers.values()],
            "source_names": sorted(stats.source_names),
        })
    spell_fields = tuple(SpellStats.__dataclass_fields__)
    payload = {
        "target": encounter.target,
        "started_at": _timestamp(encounter.started_at),
        "last_at": _timestamp(encounter.last_at),
        "zone": encounter.zone,
        "killed": bool(encounter.killed),
        "damage_started_at": _timestamp(encounter.damage_started_at),
        "damage_last_at": _timestamp(encounter.damage_last_at),
        "attackers": attackers,
        "tanks": [_tank_payload(stats) for stats in encounter.tanks.values()],
        "spells": [
            {key: getattr(stats, key) for key in spell_fields}
            for stats in encounter.spells.values()],
        "caster_spells": {
            caster: [
                {key: getattr(stats, key) for key in spell_fields}
                for stats in spells.values()]
            for caster, spells in encounter.caster_spells.items()},
        "spell_casts": [{
            "timestamp": _timestamp(event.timestamp), "caster": event.caster,
            "spell": event.spell, "outcome": event.outcome,
            "detail": event.detail} for event in encounter.spell_casts],
        "healers": [{
            "name": stats.name, "healing": stats.healing,
            "heals": stats.heals, "max_heal": stats.max_heal,
            "by_target": stats.by_target} for stats in encounter.healers.values()],
        "events": [{
            "timestamp": _timestamp(event.timestamp), "kind": event.kind,
            "actor": event.actor, "target": event.target,
            "amount": event.amount, "detail": event.detail}
            for event in encounter.events],
    }
    return payload


def encounter_from_payload(payload):
    """Rebuild every parsed statistic needed by the Combat workspace."""
    payload = payload if isinstance(payload, dict) else {}
    started = _parse_timestamp(payload.get("started_at")) or datetime.datetime.now()
    ended = _parse_timestamp(payload.get("last_at")) or started
    encounter = Encounter(
        str(payload.get("target") or "Unknown"), started, ended,
        zone=str(payload.get("zone") or ""),
        killed=bool(payload.get("killed", False)))
    encounter.damage_started_at = _parse_timestamp(
        payload.get("damage_started_at"))
    encounter.damage_last_at = _parse_timestamp(payload.get("damage_last_at"))
    for values in payload.get("attackers") or ():
        stats = AttackerStats(str(values.get("name") or "Unknown"))
        for key in (
                "damage", "hits", "max_hit", "min_hit", "attempts",
                "misses", "criticals"):
            setattr(stats, key, int(values.get(key, 0) or 0))
        stats.first_at = _parse_timestamp(values.get("first_at"))
        stats.last_at = _parse_timestamp(values.get("last_at"))
        stats.by_type = {
            str(name): AttackBreakdown(
                str(item.get("name") or name), int(item.get("damage", 0) or 0),
                int(item.get("hits", 0) or 0), int(item.get("min_hit", 0) or 0),
                int(item.get("max_hit", 0) or 0))
            for name, item in (values.get("by_type") or {}).items()}
        stats.critical_types = {
            str(name): int(count) for name, count in
            (values.get("critical_types") or {}).items()}
        stats.damage_modifiers = {}
        for item in values.get("damage_modifiers") or ():
            modifier = DamageModifierStats(
                str(item.get("attack_type") or "Melee"),
                str(item.get("critical_type") or "Critical"),
                int(item.get("samples", 0) or 0),
                int(item.get("reported_damage", 0) or 0),
                int(item.get("actual_damage", 0) or 0))
            stats.damage_modifiers[(
                modifier.attack_type, modifier.critical_type)] = modifier
        stats.source_names = {
            str(name) for name in (values.get("source_names") or ()) if str(name)}
        if not stats.source_names:
            stats.source_names.add(stats.name)
        encounter.attackers[stats.name] = stats
    encounter.tanks = {
        stats.name: stats for stats in (
            _tank_from_payload(values) for values in payload.get("tanks") or ())}
    spell_fields = tuple(SpellStats.__dataclass_fields__)

    def spell_stats(values):
        values = values if isinstance(values, dict) else {}
        return SpellStats(**{
            key: (str(values.get(key) or "Unknown") if key == "name" else
                  int(values.get(key, 0) or 0))
            for key in spell_fields})

    encounter.spells = {
        stats.name: stats for stats in map(spell_stats, payload.get("spells") or ())}
    encounter.caster_spells = {}
    for caster, spells in (payload.get("caster_spells") or {}).items():
        encounter.caster_spells[str(caster)] = {
            stats.name: stats for stats in map(spell_stats, spells or ())}
    encounter.spell_casts = deque((
        SpellCastEvent(
            _parse_timestamp(values.get("timestamp")) or started,
            str(values.get("caster") or ""), str(values.get("spell") or ""),
            str(values.get("outcome") or "Cast"),
            str(values.get("detail") or ""))
        for values in payload.get("spell_casts") or ()), maxlen=5000)
    for values in payload.get("healers") or ():
        stats = HealStats(
            str(values.get("name") or "Unknown"),
            int(values.get("healing", 0) or 0),
            int(values.get("heals", 0) or 0),
            int(values.get("max_heal", 0) or 0),
            dict(values.get("by_target") or {}))
        encounter.healers[stats.name] = stats
    encounter.events = deque((
        CombatEvent(
            _parse_timestamp(values.get("timestamp")) or started,
            str(values.get("kind") or ""), str(values.get("actor") or ""),
            str(values.get("target") or ""),
            int(values.get("amount", 0) or 0), str(values.get("detail") or ""))
        for values in payload.get("events") or ()), maxlen=5000)
    return encounter


class CombatArchive:
    """SQLite archive that deletes encounters only on an explicit user action."""

    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir("combat-history.sqlite")
        self.error = ""
        self._database = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._database = sqlite3.connect(self.path, timeout=3.0)
            self._database.execute("PRAGMA journal_mode=WAL")
            self._database.execute("PRAGMA synchronous=NORMAL")
            self._database.executescript("""
                CREATE TABLE IF NOT EXISTS encounters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    started_at TEXT NOT NULL,
                    last_at TEXT NOT NULL,
                    target TEXT NOT NULL,
                    zone TEXT NOT NULL DEFAULT '',
                    character TEXT NOT NULL DEFAULT '',
                    server TEXT NOT NULL DEFAULT '',
                    killed INTEGER NOT NULL DEFAULT 0,
                    player_count INTEGER NOT NULL DEFAULT 0,
                    your_dps REAL NOT NULL DEFAULT 0,
                    total_damage INTEGER NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 1,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS encounters_time
                    ON encounters(last_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS encounters_target
                    ON encounters(target COLLATE NOCASE);
            """)
            columns = {
                row[1] for row in self._database.execute(
                    "PRAGMA table_info(encounters)").fetchall()}
            for name, definition in (
                    ("player_count", "INTEGER NOT NULL DEFAULT 0"),
                    ("your_dps", "REAL NOT NULL DEFAULT 0"),
                    ("total_damage", "INTEGER NOT NULL DEFAULT 0"),
                    ("duration", "REAL NOT NULL DEFAULT 1")):
                if name not in columns:
                    self._database.execute(
                        f"ALTER TABLE encounters ADD COLUMN {name} {definition}")
            self._database.commit()
        except (OSError, sqlite3.Error) as error:
            self.error = str(error)
            self.close()

    @property
    def available(self):
        return self._database is not None

    @staticmethod
    def _encoded(encounter, character="", server=""):
        payload = encounter_payload(encounter)
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        identity = json.dumps({
            "character": str(character or ""), "server": str(server or ""),
            "payload": payload}, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False)
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return payload, encoded, fingerprint

    def append(self, encounter, character="", server="", commit=True):
        if self._database is None:
            return None
        character = str(character or getattr(encounter, "archive_character", "") or "")
        server = str(server or getattr(encounter, "archive_server", "") or "")
        payload, encoded, fingerprint = self._encoded(encounter, character, server)
        try:
            self._database.execute("""
                INSERT OR IGNORE INTO encounters (
                    fingerprint, started_at, last_at, target, zone,
                    character, server, killed, player_count, your_dps,
                    total_damage, duration, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fingerprint, payload["started_at"], payload["last_at"],
                payload["target"], payload["zone"], character, server,
                int(payload["killed"]), int(encounter.player_count),
                float(encounter.your_dps), int(encounter.total_damage),
                float(encounter.duration), encoded))
            row = self._database.execute(
                "SELECT id FROM encounters WHERE fingerprint = ?",
                (fingerprint,)).fetchone()
            if commit:
                self._database.commit()
            archive_id = int(row[0]) if row else None
            if archive_id is not None:
                encounter.archive_id = archive_id
                encounter.archive_character = character
                encounter.archive_server = server
            return archive_id
        except sqlite3.Error as error:
            self.error = str(error)
            return None

    def load_all(self):
        if self._database is None:
            return []
        try:
            rows = self._database.execute(
                "SELECT id, character, server, payload FROM encounters "
                "ORDER BY last_at DESC, id DESC").fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        encounters = []
        for archive_id, character, server, encoded in rows:
            try:
                encounter = encounter_from_payload(json.loads(encoded))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            encounter.archive_id = int(archive_id)
            encounter.archive_character = str(character or "")
            encounter.archive_server = str(server or "")
            encounter.archived_from_previous_session = True
            encounters.append(encounter)
        return encounters

    def summaries(self):
        """Return the complete lightweight fight list without decoding payloads."""
        if self._database is None:
            return []
        try:
            rows = self._database.execute("""
                SELECT id, target, started_at, last_at, zone, character,
                       server, killed, player_count, your_dps,
                       total_damage, duration
                FROM encounters ORDER BY last_at DESC, id DESC
            """).fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        summaries = []
        for row in rows:
            started = _parse_timestamp(row[2])
            ended = _parse_timestamp(row[3])
            if started is None or ended is None:
                continue
            summaries.append(CombatSummary(
                int(row[0]), str(row[1]), started, ended, str(row[4] or ""),
                str(row[5] or ""), str(row[6] or ""), bool(row[7]),
                int(row[8] or 0), float(row[9] or 0), int(row[10] or 0),
                max(1.0, float(row[11] or 1))))
        return summaries

    def load(self, archive_ids):
        """Decode only selected encounters, preserving the requested order."""
        if self._database is None:
            return []
        ids = [int(value) for value in archive_ids if value is not None]
        if not ids:
            return []
        try:
            placeholders = ",".join("?" for _value in ids)
            rows = self._database.execute(
                f"SELECT id, character, server, payload FROM encounters "
                f"WHERE id IN ({placeholders})", ids).fetchall()
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        by_id = {}
        for archive_id, character, server, encoded in rows:
            try:
                encounter = encounter_from_payload(json.loads(encoded))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            encounter.archive_id = int(archive_id)
            encounter.archive_character = str(character or "")
            encounter.archive_server = str(server or "")
            by_id[int(archive_id)] = encounter
        return [by_id[archive_id] for archive_id in ids if archive_id in by_id]

    def load_recent(self, limit=250):
        if self._database is None:
            return []
        limit = max(1, int(limit or 250))
        try:
            ids = [row[0] for row in self._database.execute(
                "SELECT id FROM encounters ORDER BY last_at DESC, id DESC LIMIT ?",
                (limit,)).fetchall()]
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        return self.load(ids)

    def delete(self, archive_ids):
        if self._database is None:
            return False
        ids = sorted({int(value) for value in archive_ids if value is not None})
        if not ids:
            return False
        try:
            placeholders = ",".join("?" for _value in ids)
            self._database.execute(
                f"DELETE FROM encounters WHERE id IN ({placeholders})", ids)
            self._database.commit()
            return True
        except sqlite3.Error as error:
            self.error = str(error)
            return False

    def replace_all(self, encounters):
        if self._database is None:
            return False
        try:
            self._database.execute("BEGIN")
            self._database.execute("DELETE FROM encounters")
            for encounter in encounters:
                encounter.archive_id = None
                if self.append(encounter, commit=False) is None:
                    raise sqlite3.DatabaseError(
                        self.error or "Could not save encounter")
            self._database.commit()
            return True
        except sqlite3.Error as error:
            self.error = str(error)
            self._database.rollback()
            return False

    def replace_selected(self, archive_ids, encounters):
        """Atomically replace selected rows and return the new archive ids."""
        if self._database is None:
            return []
        ids = sorted({int(value) for value in archive_ids if value is not None})
        try:
            self._database.execute("BEGIN")
            if ids:
                placeholders = ",".join("?" for _value in ids)
                self._database.execute(
                    f"DELETE FROM encounters WHERE id IN ({placeholders})", ids)
            added = []
            for encounter in encounters:
                encounter.archive_id = None
                archive_id = self.append(encounter, commit=False)
                if archive_id is None:
                    raise sqlite3.DatabaseError(
                        self.error or "Could not save encounter")
                added.append(archive_id)
            self._database.commit()
            return added
        except sqlite3.Error as error:
            self.error = str(error)
            self._database.rollback()
            return []

    def clear(self):
        if self._database is None:
            return False
        try:
            self._database.execute("DELETE FROM encounters")
            self._database.commit()
            return True
        except sqlite3.Error as error:
            self.error = str(error)
            return False

    def count(self):
        if self._database is None:
            return 0
        try:
            return int(self._database.execute(
                "SELECT COUNT(*) FROM encounters").fetchone()[0])
        except sqlite3.Error as error:
            self.error = str(error)
            return 0

    def close(self):
        database, self._database = self._database, None
        if database is not None:
            try:
                database.close()
            except sqlite3.Error:
                pass
