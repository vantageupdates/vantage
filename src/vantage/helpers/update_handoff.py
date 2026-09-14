"""Bounded, update-only recovery handoff for active spell timers."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import tempfile
import time

from vantage.helpers.portable import data_dir
from vantage.helpers.timer_sync import sanitize_timer_rows, timer_identity


SPELL_HANDOFF_SCHEMA = 1
SPELL_HANDOFF_MAX_BYTES = 1024 * 1024
SPELL_HANDOFF_MAX_ROWS = 512
SPELL_HANDOFF_MAX_AGE_SECONDS = 24 * 60 * 60
SPELL_HANDOFF_FILENAME = "update-spell-handoff.json"

_ROW_FIELDS = {
    "deadline", "target", "target_created_order", "target_activity_order",
    "target_named", "target_marker", "target_alias", "character", "server",
    "warning_played", "spell",
}
_SPELL_FIELDS = {
    "id", "name", "runtime_key", "duration_seconds", "duration",
    "duration_formula", "pvp_duration", "pvp_duration_formula", "type",
    "spell_icon", "skill", "resist_type", "effect_text_you",
    "effect_text_other", "effect_text_worn_off", "source_item", "item_only",
    "runtime_level", "shared_buff_family", "external_detection_note",
}


def spell_handoff_path():
    return data_dir(SPELL_HANDOFF_FILENAME)


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _safe_clock(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def _bounded_rows(rows, now=None):
    """Return only restorable fields and timers still alive at ``now``."""
    now = _safe_clock(now) or time.time()
    bounded = []
    for source in sanitize_timer_rows(rows)[:SPELL_HANDOFF_MAX_ROWS]:
        deadline = _safe_clock(source.get("deadline"))
        if deadline <= now:
            continue
        row = {
            key: source[key] for key in _ROW_FIELDS - {"spell"}
            if key in source
        }
        spell_source = source.get("spell", {})
        row["spell"] = {
            key: spell_source[key] for key in _SPELL_FIELDS
            if key in spell_source
        }
        # Sanitization above proved the row has a stable timer identity.
        if timer_identity(row):
            bounded.append(row)
    return bounded


def write_spell_handoff(rows, *, path=None, now=None):
    """Atomically write an exact, credential-free update recovery snapshot."""
    destination = Path(path) if path is not None else spell_handoff_path()
    created_at = _safe_clock(now) or time.time()
    cleaned = _bounded_rows(rows, created_at)
    payload = {
        "schema": SPELL_HANDOFF_SCHEMA,
        "created_at": created_at,
        "rows": cleaned,
        "rows_sha256": hashlib.sha256(_json_bytes(cleaned)).hexdigest(),
    }
    raw = _json_bytes(payload)
    if len(raw) > SPELL_HANDOFF_MAX_BYTES:
        raise ValueError("Active spell update handoff is too large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=destination.parent,
                prefix=".update-spell-handoff-", suffix=".tmp") as handle:
            temporary = handle.name
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return cleaned


def read_spell_handoff(*, updated_from="", path=None, now=None):
    """Read a validated handoff only during a confirmed post-update launch."""
    if not str(updated_from or "").strip():
        return None
    source = Path(path) if path is not None else spell_handoff_path()
    try:
        if not source.is_file() or source.stat().st_size > SPELL_HANDOFF_MAX_BYTES:
            return None
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != \
            SPELL_HANDOFF_SCHEMA:
        return None
    created_at = _safe_clock(payload.get("created_at"))
    current = _safe_clock(now) or time.time()
    if (not created_at or created_at > current + 300 or
            current - created_at > SPELL_HANDOFF_MAX_AGE_SECONDS):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > SPELL_HANDOFF_MAX_ROWS:
        return None
    expected_digest = str(payload.get("rows_sha256") or "")
    if not hmac.compare_digest(
            expected_digest, hashlib.sha256(_json_bytes(rows)).hexdigest()):
        return None
    cleaned = _bounded_rows(rows, current)
    # Reject unknown/malformed live rows rather than accepting a partial file.
    live_source_count = sum(
        1 for row in rows
        if isinstance(row, dict) and _safe_clock(row.get("deadline")) > current)
    if len(cleaned) != live_source_count:
        return None
    return cleaned


def _rows_match(expected, restored, now=None):
    now = _safe_clock(now) or time.time()
    left = {timer_identity(row): row for row in _bounded_rows(expected, now)}
    right = {timer_identity(row): row for row in _bounded_rows(restored, now)}
    if not left.keys() == right.keys():
        return False
    return all(
        abs(float(left[key]["deadline"]) -
            float(right[key]["deadline"])) <= 2.0
        for key in left)


def consume_spell_handoff(expected, restored, *, path=None, now=None):
    """Remove the sidecar only after the new process proves restoration."""
    source = Path(path) if path is not None else spell_handoff_path()
    current = read_spell_handoff(
        updated_from="verified-update", path=source, now=now)
    if (current is None or
            not _rows_match(expected, current, now) or
            not _rows_match(expected, restored, now)):
        return False
    try:
        source.unlink()
    except OSError:
        return False
    return True
