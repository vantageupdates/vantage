"""Local inventory snapshots and linked notes for Items & Notes."""

from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from vantage.helpers.portable import data_dir


MAX_DUMP_BYTES = 12 * 1024 * 1024
MAX_DUMP_ROWS = 50_000
MAX_HISTORY = 5
MAX_NOTES = 250
MAX_NOTE_BYTES = 256 * 1024
MAX_DUMP_SCAN_FILES = 50_000
DUMP_SUFFIXES = {".txt", ".tsv", ".csv"}
REFERENCE_RE = re.compile(
    r"@\[(Item|Quest|Zone):\s*([^\]\r\n]{1,240})\]", re.IGNORECASE)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def character_from_filename(path):
    """Infer a useful profile name from P99's usual dump filename."""
    stem = Path(path).stem.strip()
    stem = re.sub(r"(?i)[-_ ]inventory(?:[-_ ].*)?$", "", stem).strip("-_ ")
    return stem or "Imported character"


def classify_location(value):
    """Reduce EQ dump locations to stable filters without losing raw text."""
    text = str(value or "").strip()
    folded = text.casefold()
    if "shared" in folded and "bank" in folded:
        return "Shared Bank"
    if "bank" in folded:
        return "Bank"
    if any(token in folded for token in ("charm", "ear", "head", "face",
                                         "neck", "shoulder", "arm", "back",
                                         "wrist", "range", "hand", "primary",
                                         "secondary", "finger", "chest",
                                         "leg", "feet", "waist")):
        return "Equipped"
    if "slot" in folded or "pack" in folded or "bag" in folded:
        return "Bags" if any(char.isdigit() for char in folded) else "Inventory"
    return "Inventory"


def _read_dump_text(path):
    target = Path(path)
    size = target.stat().st_size
    if size > MAX_DUMP_BYTES:
        raise ValueError("Inventory dump is larger than 12 MB")
    payload = target.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("Inventory dump text encoding is not supported")


def _looks_like_inventory_dump(path):
    """Recognize a dump from its header without parsing or retaining it."""
    try:
        target = Path(path)
        if (target.is_symlink() or not target.is_file() or
                target.suffix.casefold() not in DUMP_SUFFIXES):
            return False
        size = target.stat().st_size
        if size <= 0 or size > MAX_DUMP_BYTES:
            return False
        payload = target.open("rb").read(4096)
    except OSError:
        return False
    text = None
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeError:
            continue
    if text is None:
        return False
    first = next((line for line in text.splitlines() if line.strip()), "")
    if not first:
        return False
    dialect = "\t" if "\t" in first else ","
    headings = {
        value.strip().strip('"').casefold()
        for value in first.split(dialect)}
    return {"location", "name"}.issubset(headings)


def discover_inventory_dumps(eq_root, max_files=MAX_DUMP_SCAN_FILES):
    """Find every readable P99 inventory dump below one EverQuest folder.

    Symbolic/reparse directory links are never followed, and files are only
    recognized by the expected Location/Name header. This searches nested
    folders without accidentally treating logs, maps, or UI text as dumps.
    """
    try:
        root = Path(eq_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    if not root.is_dir():
        return []
    found = []
    scanned = 0
    try:
        walker = os.walk(root, topdown=True, followlinks=False)
        for directory, subdirectories, filenames in walker:
            current = Path(directory)
            subdirectories[:] = [
                name for name in subdirectories
                if not (current / name).is_symlink()]
            for filename in filenames:
                candidate = current / filename
                if candidate.suffix.casefold() not in DUMP_SUFFIXES:
                    continue
                scanned += 1
                if scanned > max(1, int(max_files)):
                    return sorted(
                        found, key=lambda value: (
                            -value["modified"], value["relative"].casefold()))
                if not _looks_like_inventory_dump(candidate):
                    continue
                try:
                    details = candidate.stat()
                    relative = str(candidate.relative_to(root))
                except (OSError, ValueError):
                    continue
                found.append({
                    "path": str(candidate.resolve()),
                    "relative": relative,
                    "character": character_from_filename(candidate),
                    "modified": float(details.st_mtime),
                    "size": int(details.st_size),
                })
    except OSError:
        pass
    return sorted(
        found,
        key=lambda value: (-value["modified"], value["relative"].casefold()))


def parse_inventory_dump(path, character=""):
    """Parse P99/EQ tab-delimited Location, Name, ID, Count, Slots rows."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError("Choose an existing inventory dump file")
    text = _read_dump_text(target)
    lines = text.splitlines()
    if not lines:
        raise ValueError("The inventory dump is empty")
    dialect = csv.excel_tab if "\t" in lines[0] else csv.excel
    reader = csv.DictReader(lines, dialect=dialect)
    aliases = {
        str(name or "").strip().casefold(): name for name in (reader.fieldnames or [])}
    required = {"location", "name"}
    if not required.issubset(aliases):
        raise ValueError(
            "This is not a P99 inventory dump (Location and Name are required)")
    profile = str(character or character_from_filename(target)).strip()[:80]
    rows = []
    for index, raw in enumerate(reader):
        if index >= MAX_DUMP_ROWS:
            raise ValueError("Inventory dump has more than 50,000 rows")
        name = str(raw.get(aliases["name"], "") or "").strip()
        location = str(raw.get(aliases["location"], "") or "").strip()
        if not name:
            continue
        try:
            count = max(1, min(2_000_000_000, int(
                str(raw.get(aliases.get("count", ""), "1") or "1").strip())))
        except ValueError:
            count = 1
        item_id = str(raw.get(aliases.get("id", ""), "") or "").strip()
        slots = str(raw.get(aliases.get("slots", ""), "") or "").strip()
        rows.append({
            "key": uuid.uuid4().hex,
            "name": name[:240],
            "item_id": item_id[:40],
            "quantity": count,
            "location": location[:160],
            "group": classify_location(location),
            "slots": slots[:80],
        })
    if not rows:
        raise ValueError("No item rows were found in this inventory dump")
    return {
        "character": profile,
        "source": target.name,
        "source_path": str(target),
        "imported_at": _now(),
        "items": rows,
    }


def reference_token(kind, label):
    kind = str(kind or "").strip().title()
    label = re.sub(r"[\]\r\n]+", " ", str(label or "")).strip()
    if kind not in {"Item", "Quest", "Zone"} or not label:
        raise ValueError("Reference must be an Item, Quest, or Zone")
    return f"@[{kind}: {label[:240]}]"


def references_in(text):
    return tuple((match.group(1).title(), match.group(2).strip())
                 for match in REFERENCE_RE.finditer(str(text or "")))


class ItemJournal:
    """Atomic, bounded per-user storage with one-level edit undo."""

    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir("items-notes.json")
        self.data = {"version": 1, "characters": {}, "history": {}, "notes": []}
        self._undo = None
        self.load()

    def load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(loaded, dict):
            return
        characters = loaded.get("characters", {})
        history = loaded.get("history", {})
        notes = loaded.get("notes", [])
        if isinstance(characters, dict):
            self.data["characters"] = characters
        if isinstance(history, dict):
            self.data["history"] = history
        if isinstance(notes, list):
            self.data["notes"] = notes[:MAX_NOTES]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = ""
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n", delete=False,
                    dir=self.path.parent, prefix=".items-notes-",
                    suffix=".tmp") as output:
                temporary = output.name
                json.dump(self.data, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink(missing_ok=True)

    def import_snapshot(self, snapshot):
        character = str(snapshot.get("character") or "").strip()
        items = snapshot.get("items")
        if not character or not isinstance(items, list) or not items:
            raise ValueError("Inventory snapshot is incomplete")
        self._undo = deepcopy(self.data)
        previous = self.data["characters"].get(character)
        if previous:
            history = self.data["history"].setdefault(character, [])
            history.insert(0, deepcopy(previous))
            del history[MAX_HISTORY:]
        self.data["characters"][character] = deepcopy(snapshot)
        self.save()

    def restore_previous_import(self, character):
        history = self.data["history"].get(character, [])
        if not history:
            return False
        self._undo = deepcopy(self.data)
        current = self.data["characters"].get(character)
        restored = history.pop(0)
        if current:
            history.append(deepcopy(current))
            del history[MAX_HISTORY:]
        self.data["characters"][character] = restored
        self.save()
        return True

    def rows(self, character=""):
        wanted = str(character or "").casefold()
        result = []
        for profile, snapshot in self.data["characters"].items():
            if wanted and profile.casefold() != wanted:
                continue
            for item in snapshot.get("items", []):
                row = deepcopy(item)
                row["character"] = profile
                result.append(row)
        return result

    def _find(self, character, key):
        snapshot = self.data["characters"].get(character, {})
        for index, row in enumerate(snapshot.get("items", [])):
            if row.get("key") == key:
                return snapshot, index, row
        return None, -1, None

    def set_quantity(self, character, key, quantity):
        snapshot, _index, row = self._find(character, key)
        if row is None:
            return False
        self._undo = deepcopy(self.data)
        row["quantity"] = max(1, min(2_000_000_000, int(quantity)))
        snapshot["edited_at"] = _now()
        self.save()
        return True

    def remove_item(self, character, key):
        snapshot, index, row = self._find(character, key)
        if row is None:
            return False
        self._undo = deepcopy(self.data)
        del snapshot["items"][index]
        snapshot["edited_at"] = _now()
        self.save()
        return True

    def undo(self):
        if self._undo is None:
            return False
        current = deepcopy(self.data)
        self.data = self._undo
        self._undo = current
        self.save()
        return True

    def upsert_note(self, note_id, title, text):
        encoded = str(text or "").encode("utf-8")
        if len(encoded) > MAX_NOTE_BYTES:
            raise ValueError("Note is larger than 256 KB")
        note_id = str(note_id or uuid.uuid4().hex)
        note = {
            "id": note_id,
            "title": (str(title or "Untitled note").strip() or "Untitled note")[:160],
            "text": str(text or ""),
            "updated_at": _now(),
        }
        notes = self.data["notes"]
        for index, existing in enumerate(notes):
            if existing.get("id") == note_id:
                notes[index] = note
                break
        else:
            if len(notes) >= MAX_NOTES:
                raise ValueError("The 250-note limit has been reached")
            notes.insert(0, note)
        self.save()
        return note_id

    def delete_note(self, note_id):
        notes = self.data["notes"]
        for index, note in enumerate(notes):
            if note.get("id") == note_id:
                self._undo = deepcopy(self.data)
                del notes[index]
                self.save()
                return True
        return False
