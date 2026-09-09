"""Safe Google Sheets URL normalization and bounded CSV parsing for guild data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 128
MAX_CELL_CHARS = 4096
_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_GID = re.compile(r"^[0-9]{1,20}$")
_KNOWN_HEADERS = {
    "attendance", "bids", "bounty pay", "capacity", "character", "class",
    "date", "dkp", "event", "item", "item id", "level", "limit", "loot",
    "name", "notes", "price", "quantity", "raid", "rank", "slot", "status",
    "turn in location", "updated", "winner",
}
_INVENTORY_SLOTS = {
    "head", "face", "ear", "neck", "shoulders", "arms", "back", "wrist",
    "range", "hands", "primary", "secondary", "finger", "chest", "legs",
    "feet", "waist", "ammo",
}


@dataclass(frozen=True)
class SpreadsheetData:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    kind: str
    truncated: bool = False


def normalize_google_sheet_url(value):
    """Convert a public Google Sheets edit/pub URL into its read-only CSV URL."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Enter a Google Sheets URL")
    parsed = urlparse(raw)
    if (parsed.scheme.casefold() != "https" or
            str(parsed.hostname or "").casefold() != "docs.google.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Use a public https://docs.google.com/spreadsheets link")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[:2] != ["spreadsheets", "d"]:
        raise ValueError("This is not a Google Sheets spreadsheet link")
    published = parts[2] == "e"
    if published:
        if len(parts) < 4:
            raise ValueError("This published Google Sheets link is incomplete")
        sheet_id = parts[3]
    else:
        sheet_id = parts[2]
    if not _SHEET_ID.fullmatch(sheet_id):
        raise ValueError("This Google Sheets ID is invalid")
    query = parse_qs(parsed.query)
    gid = str((query.get("gid") or [""])[0]).strip()
    if gid and not _GID.fullmatch(gid):
        raise ValueError("This Google Sheets tab ID is invalid")
    if published:
        path = f"/spreadsheets/d/e/{sheet_id}/pub"
        output_query = {"output": "csv"}
    else:
        path = f"/spreadsheets/d/{sheet_id}/export"
        output_query = {"format": "csv"}
    if gid:
        output_query["gid"] = gid
    return urlunparse((
        "https", "docs.google.com", path, "", urlencode(output_query), ""))


def _trimmed_rows(text):
    parsed = []
    truncated = False
    for index, raw_row in enumerate(csv.reader(io.StringIO(text))):
        if index >= MAX_ROWS:
            truncated = True
            break
        row = [" ".join(str(cell).replace("\x00", "").split())[:MAX_CELL_CHARS]
               for cell in raw_row[:MAX_COLUMNS]]
        while row and not row[-1]:
            row.pop()
        if row and any(row):
            parsed.append(row)
    if not parsed:
        raise ValueError("The spreadsheet has no visible rows")
    return parsed, truncated


def _inventory_shape(rows):
    samples = rows[: min(12, len(rows))]
    matches = 0
    for row in samples:
        if len(row) < 5:
            continue
        slot = row[1].casefold().split("-", 1)[0]
        item_id = row[3].replace(",", "")
        quantity = row[4].replace(",", "")
        if (slot in _INVENTORY_SLOTS or slot.startswith("general")) and \
                item_id.isdigit() and quantity.isdigit():
            matches += 1
    return matches >= max(2, min(4, len(samples) // 2))


def _header_row(row):
    normalized = {cell.casefold().strip(" :*_") for cell in row if cell}
    return len(normalized.intersection(_KNOWN_HEADERS)) >= 2


def _unique_headers(values, count):
    result = []
    used = set()
    for index in range(count):
        base = (values[index] if index < len(values) else "").strip()
        base = base or f"Column {index + 1}"
        name = base
        suffix = 2
        while name.casefold() in used:
            name = f"{base} {suffix}"
            suffix += 1
        used.add(name.casefold())
        result.append(name[:120])
    return result


def parse_spreadsheet_csv(payload):
    """Parse a bounded public CSV while preserving unknown guild-specific shapes."""
    raw = bytes(payload or b"")
    if not raw:
        raise ValueError("The spreadsheet returned no data")
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The spreadsheet is larger than Vantage's 8 MB limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("The spreadsheet is not valid UTF-8 CSV") from error
    rows, truncated = _trimmed_rows(text)
    width = min(MAX_COLUMNS, max(len(row) for row in rows))
    if _inventory_shape(rows):
        standard = [
            "Character", "Slot", "Item", "Item ID", "Quantity", "Capacity",
            "Updated"]
        headers = _unique_headers(standard, width)
        data_rows = rows
        kind = "Inventory"
    elif _header_row(rows[0]):
        headers = _unique_headers(rows[0], width)
        data_rows = rows[1:]
        kind = "Table"
    else:
        headers = _unique_headers([], width)
        data_rows = rows
        kind = "Custom"
    normalized = tuple(
        tuple((row + [""] * width)[:width]) for row in data_rows)
    return SpreadsheetData(tuple(headers), normalized, kind, truncated)
