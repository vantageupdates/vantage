"""Conflict-safe reconciliation for active spell timers shared by devices."""

from __future__ import annotations

import copy
import json
import math
import time


MAX_TIMER_ROWS = 512
MAX_TIMER_CLOCKS = 1024
MAX_TIMER_IDENTITY_LENGTH = 720
TIMER_SYNC_SCHEMA = 1
SHARED_RUNTIME_FAMILIES = {
    "regeneration": "regeneration",
    "chloroplast": "regeneration",
    "regrowth": "regeneration",
    "pack chloroplast": "regeneration",
    "regrowth of the grove": "regeneration",
    "regeneration effect (rank unknown)": "regeneration",
}


def _fold(value, limit):
    return " ".join(str(value or "").split()).casefold()[:limit]


def timer_identity(row):
    """Return a stable identity for one profile, target instance and effect."""
    if not isinstance(row, dict):
        return ""
    spell = row.get("spell") if isinstance(row.get("spell"), dict) else {}
    target = _fold(row.get("target") or "__you__", 128)
    marker = _fold(row.get("target_marker"), 16)
    if not marker and not target.startswith("__"):
        try:
            marker = f"order:{max(0, int(row.get('target_created_order', 0)))}"
        except (TypeError, ValueError, OverflowError):
            marker = "order:0"
    family = _fold(spell.get("shared_buff_family"), 128)
    name = _fold(spell.get("name"), 256)
    runtime = family or SHARED_RUNTIME_FAMILIES.get(name) or _fold(
        spell.get("runtime_key") or name, 256)
    if not runtime:
        return ""
    identity = (
        _fold(row.get("server"), 80),
        _fold(row.get("character"), 80),
        target,
        marker,
        runtime,
    )
    return json.dumps(identity, ensure_ascii=True, separators=(",", ":"))[
        :MAX_TIMER_IDENTITY_LENGTH]


def _valid_clock(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def sanitize_timer_rows(rows):
    """Bound timer state and drop malformed or identity-less entries."""
    result = []
    if not isinstance(rows, list):
        return result
    for raw in rows[:MAX_TIMER_ROWS]:
        if not isinstance(raw, dict) or not isinstance(raw.get("spell"), dict):
            continue
        row = copy.deepcopy(raw)
        if not timer_identity(row):
            continue
        try:
            deadline = float(row.get("deadline", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(deadline) or deadline <= 0:
            continue
        row["deadline"] = deadline
        result.append(row)
    return result


def sanitize_timer_sync_meta(meta):
    """Validate and bound clocks without trusting arbitrary snapshot keys."""
    source = meta if isinstance(meta, dict) else {}
    result = {"schema": TIMER_SYNC_SCHEMA, "versions": {}, "tombstones": {}}
    for field in ("versions", "tombstones"):
        values = source.get(field) if isinstance(source.get(field), dict) else {}
        cleaned = []
        for raw_key, raw_clock in list(values.items())[:MAX_TIMER_CLOCKS * 2]:
            key = str(raw_key or "")[:MAX_TIMER_IDENTITY_LENGTH]
            clock = _valid_clock(raw_clock)
            if key and clock:
                cleaned.append((key, clock))
        cleaned.sort(key=lambda pair: pair[1], reverse=True)
        result[field] = dict(cleaned[:MAX_TIMER_CLOCKS])
    return result


def _next_clock(meta, requested=None):
    clocks = [
        *meta.get("versions", {}).values(),
        *meta.get("tombstones", {}).values(),
    ]
    return max(
        _valid_clock(requested) or time.time(),
        max(clocks, default=0.0) + 0.001,
    )


def _row_changed(previous, current):
    """Ignore harmless sub-second reserialization while detecting recasts."""
    before = copy.deepcopy(previous)
    after = copy.deepcopy(current)
    for value in (before, after):
        value.pop("warning_played", None)
        try:
            value["deadline"] = int(round(float(value.get("deadline", 0))))
        except (TypeError, ValueError, OverflowError):
            value["deadline"] = 0
    return before != after


def _row_map(rows):
    result = {}
    for row in sanitize_timer_rows(rows):
        key = timer_identity(row)
        existing = result.get(key)
        if existing is None or row["deadline"] > existing["deadline"]:
            result[key] = row
    return result


def timer_rows_equal(left, right):
    """Compare timer collections by identity rather than presentation order."""
    return _row_map(left) == _row_map(right)


def record_local_timer_state(previous_rows, current_rows, meta, now=None):
    """Record local additions, recasts and removals with per-effect clocks."""
    previous = _row_map(previous_rows)
    current = _row_map(current_rows)
    result_meta = sanitize_timer_sync_meta(meta)
    versions = result_meta["versions"]
    tombstones = result_meta["tombstones"]
    mutation_clock = None

    def changed_clock():
        nonlocal mutation_clock
        if mutation_clock is None:
            mutation_clock = _next_clock(result_meta, now)
        return mutation_clock

    for key, row in current.items():
        if key not in previous or _row_changed(previous[key], row):
            versions[key] = changed_clock()
        elif key not in versions:
            # A legacy row is an addition, never evidence that another row
            # should be deleted merely because it was absent from a snapshot.
            versions[key] = changed_clock()
        if tombstones.get(key, 0) <= versions.get(key, 0):
            tombstones.pop(key, None)
    for key in previous.keys() - current.keys():
        tombstones[key] = changed_clock()

    return list(current.values()), _prune_meta(result_meta, current)


def _prune_meta(meta, active=None):
    active = active or {}
    versions = meta.get("versions", {})
    tombstones = meta.get("tombstones", {})
    keep_versions = sorted(
        ((key, value) for key, value in versions.items()
         if key in active or value > tombstones.get(key, 0)),
        key=lambda pair: pair[1], reverse=True)[:MAX_TIMER_CLOCKS]
    keep_tombstones = sorted(
        tombstones.items(), key=lambda pair: pair[1], reverse=True
    )[:MAX_TIMER_CLOCKS]
    return {
        "schema": TIMER_SYNC_SCHEMA,
        "versions": dict(keep_versions),
        "tombstones": dict(keep_tombstones),
    }


def merge_timer_state(
        local_rows, local_meta, incoming_rows, incoming_meta,
        incoming_revision=None):
    """Union concurrent timers; only a newer explicit tombstone may delete."""
    local = _row_map(local_rows)
    incoming = _row_map(incoming_rows)
    left = sanitize_timer_sync_meta(local_meta)
    right = sanitize_timer_sync_meta(incoming_meta)
    versions = dict(left["versions"])
    tombstones = dict(left["tombstones"])
    incoming_is_legacy = not bool(
        isinstance(incoming_meta, dict) and
        (incoming_meta.get("versions") or incoming_meta.get("tombstones")))
    legacy_clock = _next_clock(left, incoming_revision) if incoming else 0.0

    for key, value in right["tombstones"].items():
        tombstones[key] = max(tombstones.get(key, 0), value)

    merged = dict(local)
    ordered_keys = list(local)
    for key, row in incoming.items():
        remote_version = right["versions"].get(key, 0)
        if not remote_version and incoming_is_legacy:
            # Legacy snapshots may contribute or refresh a row, but their
            # absence can never erase a timer created elsewhere.
            remote_version = legacy_clock
        local_version = versions.get(key, 0)
        existing = merged.get(key)
        choose_remote = (
            existing is None or
            (incoming_is_legacy and
             row["deadline"] > existing["deadline"]) or
            (not incoming_is_legacy and remote_version > local_version) or
            (not incoming_is_legacy and
             remote_version == local_version and
             row["deadline"] > existing["deadline"]))
        if choose_remote:
            merged[key] = row
            if key not in ordered_keys:
                ordered_keys.append(key)
            versions[key] = max(local_version, remote_version)
        elif not incoming_is_legacy:
            versions[key] = max(local_version, remote_version)

    for key in list(merged):
        winning_version = versions.get(key, 0)
        if tombstones.get(key, 0) > winning_version:
            merged.pop(key, None)

    ordered = [merged[key] for key in ordered_keys if key in merged]
    active = {key: merged[key] for key in merged}
    return ordered[:MAX_TIMER_ROWS], _prune_meta({
        "schema": TIMER_SYNC_SCHEMA,
        "versions": versions,
        "tombstones": tombstones,
    }, active)
