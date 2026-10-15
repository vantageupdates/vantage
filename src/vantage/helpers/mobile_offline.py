"""Small, display-only offline export contract; never serialize PC state wholesale."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import quote, urlsplit


OFFLINE_FORMAT = "vantage-offline"
OFFLINE_SCHEMA = 1
MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_STANDINGS = 10_000
WIKI_ROOT = "https://wiki.project1999.com/"


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value, limit=160):
    # In particular, do not stringify dictionaries that could contain secrets.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return " ".join(str(value)[:limit * 4].split())[:limit]


def _wiki(name):
    return WIKI_ROOT + quote(name.replace(" ", "_"), safe="") if name else ""


def _sheet_url(value):
    """Keep canonical document links, dropping auth/resource keys and fragments."""
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.hostname != "docs.google.com" or
                url.port not in (None, 443) or url.username or url.password):
            return ""
    except ValueError:
        return ""
    match = re.fullmatch(
        r"/spreadsheets/d/([A-Za-z0-9_-]{10,180})(?:/(?:edit|view|preview|htmlview))?/?",
        url.path)
    if not match:
        return ""
    return "https://docs.google.com/spreadsheets/d/" + match.group(1) + "/edit"


def _rows(value, limit, path, truncated):
    if not isinstance(value, (list, tuple)):
        return ()
    if len(value) > limit and path not in truncated:
        truncated.append(path)
    return value[:limit]


def _fields(row, fields):
    row = _mapping(row)
    return {key: _text(row.get(key), limit) for key, limit in fields.items()}


def _guild(source, truncated):
    source = _mapping(source)
    name = _text(source.get("guild"))
    if not name or name == "No guild selected":
        return None
    standings = [_fields(row, {
        "name": 160, "class": 48, "level": 24, "rank": 96,
        "dkp": 48, "attendance": 48,
    }) for row in _rows(source.get("standings"), MAX_STANDINGS,
                       "guild.standings", truncated) if isinstance(row, dict)]
    loot = []
    for row in _rows(source.get("loot"), 500, "guild.loot", truncated):
        if not isinstance(row, dict):
            continue
        clean = _fields(row, {
            "date": 64, "item": 160, "character": 160, "dkp": 48, "raid": 160})
        clean["wiki_url"] = _wiki(clean["item"])
        loot.append(clean)
    raids = [_fields(row, {
        "date": 64, "name": 160, "items": 48, "awarded": 48, "spent": 48,
    }) for row in _rows(source.get("raids"), 300, "guild.raids", truncated)
        if isinstance(row, dict)]
    sheets = []
    for row in _rows(source.get("sheets"), 32, "guild.sheets", truncated):
        row = _mapping(row)
        url = _sheet_url(row.get("url"))
        if url:
            sheets.append({"name": _text(row.get("name")) or "Guild sheet", "url": url})
    original = source.get("standings")
    total = len(original) if isinstance(original, (list, tuple)) else 0
    supplied_total = source.get("standings_total")
    if isinstance(supplied_total, int) and not isinstance(supplied_total, bool):
        total = max(total, min(1_000_000, supplied_total))
    return {
        "name": name, "slug": _text(source.get("slug"), 96),
        "standings": standings, "standings_total": total,
        "loot": loot, "raids": raids, "sheets": sheets,
    }


def _zone(source, truncated):
    source = _mapping(_mapping(source).get("data"))
    name = _text(source.get("name"))
    if not name:
        return None
    result = _fields(source, {"name": 160, "era": 48, "levels": 64, "summary": 8000})
    result["wiki_url"] = _wiki(name)
    result["unique_items"] = [
        text for item in _rows(source.get("unique_items"), 2000,
                               "zone.unique_items", truncated)
        if (text := _text(item))]
    result["mobs"] = []
    for mob in _rows(source.get("mobs"), 2000, "zone.mobs", truncated):
        if not isinstance(mob, dict):
            continue
        clean = _fields(mob, {
            "name": 160, "level": 48, "class": 48, "race": 64,
            "location": 240, "loot": 1200,
        })
        clean["named"] = mob.get("named") is True
        result["mobs"].append(clean)
    return result


def _quest(source, truncated):
    source = _mapping(source)
    current = _mapping(source.get("current"))
    title = _text(current.get("title"))
    if not title:
        return None
    metadata = _mapping(current.get("metadata"))
    steps = []
    checked = []
    checklist = _mapping(source.get("checklist"))
    checked_keys = {key for key in _rows(checklist.get("checked"), 180,
                                        "quest.checked", truncated)
                    if isinstance(key, str) and len(key) == 16}
    for step in _rows(current.get("steps"), 180, "quest.steps", truncated):
        if not isinstance(step, (str, dict)):
            continue
        raw_text = step if isinstance(step, str) else step.get("text")
        text = _text(raw_text, 4000)
        if not text:
            continue
        kind = "group" if isinstance(step, dict) and step.get("kind") == "group" else "action"
        if (kind == "action" and checklist.get("title") == current.get("title") and
                isinstance(raw_text, str) and hashlib.sha256(
                    raw_text.strip().casefold().encode("utf-8")).hexdigest()[:16] in checked_keys):
            checked.append(len(steps))
        steps.append({"text": text, "kind": kind})
    return {
        "title": title, "summary": _text(current.get("summary"), 12000),
        "wiki_url": _wiki(title),
        "metadata": {key: _text(metadata.get(key), 1000) for key in (
            "Start Zone", "Quest Giver", "Minimum Level", "Classes")
            if _text(metadata.get(key), 1000)},
        "rewards": [text for value in _rows(current.get("rewards"), 200,
                                             "quest.rewards", truncated)
                    if (text := _text(value))],
        "steps": steps, "checked": checked,
    }


def _encode(payload):
    return json.dumps(payload, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def build_offline_snapshot(source, *, source_version="unknown", exported_at=None):
    """Return the versioned, recursively projected contract, capped at 8 MiB."""
    source = _mapping(source)
    truncated = []
    result = {
        "format": OFFLINE_FORMAT, "schema": OFFLINE_SCHEMA,
        "exported_at": (exported_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "source_version": _text(source_version, 48) or "unknown",
        "guild": _guild(source.get("guild"), truncated),
        "zone": _zone(source.get("zones"), truncated),
        "quest": _quest(source.get("quests"), truncated),
        "truncated": truncated,
    }
    # Unicode and multiple maximum-sized sections can exceed the total budget.
    # Preserve a valid file and explicitly identify every shortened collection.
    collections = []
    for section, keys in (("guild", ("standings", "loot", "raids", "sheets")),
                          ("zone", ("unique_items", "mobs")),
                          ("quest", ("rewards", "steps"))):
        if result[section]:
            collections.extend((section + "." + key, result[section][key]) for key in keys)
    while len(_encode(result)) > MAX_EXPORT_BYTES:
        path, rows = max(collections, key=lambda pair: len(_encode(pair[1])))
        if not rows:
            raise ValueError("Offline export exceeds the byte limit")
        del rows[max(0, len(rows) - max(1, len(rows) // 4)):]
        if path not in truncated:
            truncated.append(path)
    if result["quest"]:
        result["quest"]["checked"] = [index for index in result["quest"]["checked"]
                                        if index < len(result["quest"]["steps"])]
    return result


def encode_offline_snapshot(source, *, source_version="unknown"):
    return _encode(build_offline_snapshot(source, source_version=source_version))
