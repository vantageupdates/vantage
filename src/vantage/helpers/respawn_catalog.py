"""Bundled P99 zone respawn catalog used by maps and automatic timers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import re

from vantage.helpers import resource_path


CATALOG_FILE = resource_path('data/timers/p99_zone_respawns.csv')
NAMED_CATALOG_FILE = resource_path('data/timers/p99_named_spawns.csv')
CATALOG_SOURCE = (
    "P99 Respawn DB"
)
CATALOG_SOURCE_URL = "https://github.com/perotan/respawntimer"
NAMED_CATALOG_SOURCE = "P99 Wiki Named Catalog"
NAMED_CATALOG_SOURCE_URL = "https://wiki.project1999.com/Category:Zones"


@dataclass(frozen=True)
class RespawnEntry:
    zone_name: str
    short_name: str
    timer_text: str
    seconds: int | None
    note: str = ""


@dataclass(frozen=True)
class NamedSpawnEntry:
    short_name: str
    npc_name: str
    respawn_seconds: int | None = None


def duration_seconds(value):
    """Parse the catalog's MM:SS, HH:MM:SS and ``N hours`` forms."""
    text = str(value or "").strip().casefold()
    if not text:
        return None
    hours = re.fullmatch(r"(\d+)\s*hours?", text)
    if hours:
        return int(hours.group(1)) * 3600
    parts = text.split(':')
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return None
    values = [int(part) for part in parts]
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    hours_value, minutes, seconds = values
    return hours_value * 3600 + minutes * 60 + seconds


def load_respawn_catalog():
    entries = {}
    try:
        with open(CATALOG_FILE, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                short_name = row.get('short_name', '').strip().casefold()
                if not short_name:
                    continue
                timer_text = row.get('timer', '').strip()
                entries[short_name] = RespawnEntry(
                    zone_name=row.get('zone_name', '').strip(),
                    short_name=short_name,
                    timer_text=timer_text,
                    seconds=duration_seconds(timer_text),
                    note=row.get('note', '').strip(),
                )
    except (OSError, csv.Error):
        return {}
    return entries


RESPAWN_CATALOG = load_respawn_catalog()


def load_named_spawn_catalog():
    """Load the bundled zone-specific P99 Wiki notable-NPC index."""
    entries = {}
    try:
        with open(NAMED_CATALOG_FILE, newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                short_name = row.get('short_name', '').strip().casefold()
                npc_name = row.get('npc_name', '').strip()
                if not short_name or not npc_name:
                    continue
                raw_seconds = row.get('respawn_seconds', '').strip()
                try:
                    seconds = int(raw_seconds) if raw_seconds else None
                except ValueError:
                    seconds = None
                entries[(short_name, npc_name.casefold())] = NamedSpawnEntry(
                    short_name=short_name,
                    npc_name=npc_name,
                    respawn_seconds=(seconds if seconds and seconds > 0 else None),
                )
    except (OSError, csv.Error):
        return {}
    return entries


NAMED_SPAWN_CATALOG = load_named_spawn_catalog()


def respawn_for_short_name(short_name):
    return RESPAWN_CATALOG.get(str(short_name or '').strip().casefold())


def named_spawn_for(short_name, npc_name):
    """Return an exact zone/name match; trash mobs intentionally return None."""
    return NAMED_SPAWN_CATALOG.get((
        str(short_name or '').strip().casefold(),
        str(npc_name or '').strip().casefold(),
    ))
