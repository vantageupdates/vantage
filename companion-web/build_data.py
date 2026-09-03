"""Build the static, offline-friendly Vantage Companion catalogs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen


PIGPARSE_URL = "https://pigparse.azurewebsites.net/api/item/getall/Green"
P99_DB_URL = "https://p99planner.com/data/p99.sqlite.gz"
USER_AGENT = "Vantage-Companion-Data/1.44.34"
ROOT = Path(__file__).resolve().parents[1]
STAT_FIELDS = (
    "ac", "hp", "mana", "astr", "asta", "adex", "aagi", "aint",
    "awis", "acha", "mr", "fr", "cr", "dr", "pr", "attack",
    "haste", "regen", "manaregen",
)
EFFECT_FIELDS = (
    ("Click", "clickName"), ("Proc", "procName"),
    ("Worn", "wornName"), ("Focus", "focusName"),
    ("Bard", "bardName"),
)
CLASS_COLUMNS = (
    (104, "Warrior"), (105, "Cleric"), (106, "Paladin"),
    (107, "Ranger"), (108, "Shadow Knight"), (109, "Druid"),
    (110, "Monk"), (111, "Bard"), (112, "Rogue"),
    (113, "Shaman"), (114, "Necromancer"), (115, "Wizard"),
    (116, "Magician"), (117, "Enchanter"),
)
PLAYER_SPELL_CLASSES = {
    "Bard", "Cleric", "Druid", "Enchanter", "Magician",
    "Necromancer", "Paladin", "Ranger", "Shadow Knight", "Shaman",
    "Wizard",
}


def item_key(value):
    return re.sub(r"['’`]", "", str(value or "").strip().casefold())


def get_json(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def get_bytes(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response:
        return response.read()


def load_eras(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items", payload)
        return {
            item_key(name): str(era).casefold()
            for name, era in rows.items()
            if str(era).casefold() in {"classic", "kunark", "velious"}
        }
    except (OSError, TypeError, ValueError):
        return {}


def price_index(rows):
    indexed = {}
    for row in rows if isinstance(rows, list) else ():
        name = str(row.get("n") or "").strip()
        if not name:
            continue
        key = item_key(name)
        current = indexed.get(key)
        score = (int(row.get("t30") or 0), int(float(row.get("a30") or 0)))
        current_score = (
            int(current.get("t30") or 0),
            int(float(current.get("a30") or 0)),
        ) if current else (-1, -1)
        if score >= current_score:
            indexed[key] = row
    return indexed


def load_items(database_path, price_rows, era_path):
    prices = price_index(price_rows)
    eras = load_eras(era_path)
    fields = (
        "id", "peqId", "name", "classes", "races", "slots", "nodrop",
        *STAT_FIELDS, *(field for _label, field in EFFECT_FIELDS),
    )
    query = "SELECT " + ", ".join(fields) + " FROM items ORDER BY name COLLATE NOCASE"
    with sqlite3.connect(database_path) as database:
        rows = database.execute(query).fetchall()
    items = []
    for row in rows:
        values = dict(zip(fields, row))
        name = str(values.get("name") or "").strip()
        if not name or "{{" in name or "}}" in name:
            continue
        price = prices.get(item_key(name), {})
        stats = {
            field: int(values.get(field) or 0)
            for field in STAT_FIELDS if int(values.get(field) or 0)
        }
        effects = [
            {"type": label, "name": str(values.get(field) or "").strip()}
            for label, field in EFFECT_FIELDS
            if str(values.get(field) or "").strip() not in {"", "0"}
        ]
        items.append({
            "name": name,
            "price": int(float(price.get("a30") or 0)),
            "posts": int(price.get("t30") or 0),
            "last": str(price.get("l") or ""),
            "classes": int(values.get("classes") or 0),
            "races": int(values.get("races") or 0),
            "slots": int(values.get("slots") or 0),
            # The classic database is inverted: zero means NO DROP.
            "nodrop": int(values.get("nodrop") or 0) == 0,
            "era": eras.get(item_key(name), ""),
            "id": int(values.get("id") or 0),
            "peqId": int(values.get("peqId") or 0),
            "stats": stats,
            "effects": effects,
            "wiki": "https://wiki.project1999.com/" + quote(
                name.replace(" ", "_"), safe="_()'-"),
        })
    return items


def load_spells(path):
    by_name = {}
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            values = line.rstrip("\r\n").split("^")
            if len(values) <= 144:
                continue
            name = values[1].strip()
            if not name:
                continue
            profiles = []
            for column, class_name in CLASS_COLUMNS:
                if class_name not in PLAYER_SPELL_CLASSES:
                    continue
                try:
                    level = int(values[column])
                except (TypeError, ValueError):
                    continue
                if 1 <= level <= 60:
                    profiles.append([class_name, level])
            if not profiles:
                continue
            try:
                spell_id = int(values[0])
            except (TypeError, ValueError):
                spell_id = 0
            try:
                icon_id = int(values[144])
            except (TypeError, ValueError):
                icon_id = 0
            try:
                mana = int(values[19])
            except (TypeError, ValueError):
                mana = 0
            try:
                cast_ms = int(values[13])
            except (TypeError, ValueError):
                cast_ms = 0
            messages = [
                " ".join(str(values[index] or "").split())
                for index in (6, 8) if str(values[index] or "").strip()
            ]
            mechanics = []
            if mana > 0:
                mechanics.append(f"Mana {mana}")
            if cast_ms > 0:
                mechanics.append(f"Cast {cast_ms / 1000:g}s")
            if mechanics:
                messages.append(" · ".join(mechanics))
            key = name.casefold()
            current = by_name.get(key)
            if current:
                merged = {class_name: level for class_name, level in current["levels"]}
                for class_name, level in profiles:
                    merged[class_name] = min(level, merged.get(class_name, level))
                profiles = [[class_name, merged[class_name]] for _column, class_name in CLASS_COLUMNS
                            if class_name in merged]
            by_name[key] = {
                "id": current["id"] if current and current["id"] else spell_id,
                "name": name,
                "levels": profiles,
                "icon": current["icon"] if current and current["icon"] else icon_id,
                "summary": " ".join(messages) or (
                    current["summary"] if current else "Bundled P99 spell data"),
                "wiki": "https://wiki.project1999.com/" + quote(
                    name.replace(" ", "_"), safe="_()'-"),
            }
    return sorted(by_name.values(), key=lambda row: row["name"].casefold())


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument(
        "--eras", type=Path,
        default=ROOT / "data" / "market" / "item_eras.json")
    parser.add_argument(
        "--spells", type=Path,
        default=ROOT / "data" / "spells" / "spells_us.txt")
    args = parser.parse_args()

    temporary = None
    database_path = args.sqlite
    if not database_path:
        temporary = tempfile.TemporaryDirectory(prefix="vantage-companion-")
        database_path = Path(temporary.name) / "p99.sqlite"
        database_path.write_bytes(gzip.decompress(get_bytes(P99_DB_URL)))

    prices = get_json(PIGPARSE_URL)
    items = load_items(database_path, prices, args.eras)
    spells = load_spells(args.spells)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(args.output / "items.json", {"items": items})
    write_json(args.output / "spells.json", {"spells": spells})
    write_json(args.output / "meta.json", {
        "generatedAt": generated_at,
        "server": "Project 1999 Green",
        "priceSource": "PigParse Green",
        "itemSource": "P99 Planner / Project 1999 Wiki snapshot",
        "spellSource": "Bundled P99 classic spell data",
        "itemCount": len(items),
        "pricedItemCount": sum(bool(row["price"]) for row in items),
        "spellCount": len(spells),
        "limitations": (
            "Prices are the latest published PigParse snapshot and may be stale "
            "while offline. Timers, zone sync, and EQ Live require a running "
            "Vantage session on the PC."),
    })
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
