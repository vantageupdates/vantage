"""Compact, chat-safe Smart Timer handoff codes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
import re
import secrets
import time
import zlib

from vantage.helpers.spawn_timer import (
    MAX_DEATH_MOB_NAME_LENGTH,
    MAX_DEATH_MOBS,
    PHASE_AVAILABLE,
    PHASE_COMBAT,
    PHASE_IDLE,
    PHASE_RESPAWN,
    SpawnTimerState,
    normalize_death_mobs,
)


TIMER_SHARE_PREFIX = "VTS1:"
TIMER_SHARE_V2_PREFIX = "VTS2:"
TIMER_SHARE_PREFIXES = (TIMER_SHARE_PREFIX, TIMER_SHARE_V2_PREFIX)
TIMER_SHARE_CODE_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?P<prefix>{'|'.join(map(re.escape, TIMER_SHARE_PREFIXES))})"
    r"(?P<token>[A-Za-z0-9_-]{16,2048})")
MAX_TIMER_SHARE_CODE_CHARS = 232
MAX_TIMER_SHARE_AGE_SECONDS = 24 * 60 * 60
MAX_TIMER_SHARE_RECORDS = 32
MAX_COMPRESSED_BYTES = 4096
MAX_DECOMPRESSED_BYTES = 16384

_PHASE_TO_CODE = {
    PHASE_IDLE: 0,
    PHASE_RESPAWN: 1,
    PHASE_COMBAT: 2,
    PHASE_AVAILABLE: 3,
}
_CODE_TO_PHASE = {value: key for key, value in _PHASE_TO_CODE.items()}


class TimerShareError(ValueError):
    """A damaged, expired, or unsupported timer handoff code."""


@dataclass(frozen=True)
class SharedTimerRecord:
    name: str
    zone: str
    respawn_seconds: int
    kill_seconds: int
    warning_seconds: int
    color: str
    smart: bool
    phase: str
    running: bool
    remaining_seconds: int | None
    cycles: int
    warning_sent: bool
    death_mobs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimerSharePacket:
    generated_at: int
    packet_id: str
    timers: tuple[SharedTimerRecord, ...]
    age_seconds: int
    future_clock_skew_seconds: int = 0


@dataclass(frozen=True)
class TimerShareExport:
    generated_at: int
    codes: tuple[str, ...]
    packet_ids: tuple[str, ...]
    timer_count: int


def extract_timer_share_codes(text):
    """Return every complete Vantage timer code embedded in a log line."""
    return tuple(
        f"{match.group('prefix')}{match.group('token')}"
        for match in TIMER_SHARE_CODE_RE.finditer(str(text or "")))


def _safe_text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _compact_timer(timer, generated_at):
    name = _safe_text(getattr(timer, "name", "Spawn"), 64) or "Spawn"
    zone = _safe_text(getattr(timer, "zone", ""), 64)
    color = str(getattr(timer, "color", "#B38C52") or "#B38C52")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = "#B38C52"
    phase = str(getattr(timer, "phase", PHASE_IDLE) or PHASE_IDLE)
    phase_code = _PHASE_TO_CODE.get(phase, 0)
    running = bool(getattr(timer, "running", False))
    smart = bool(getattr(timer, "smart", True))
    warning_sent = bool(getattr(timer, "warning_sent", False))
    flags = (
        (1 if smart else 0)
        | (2 if running else 0)
        | (4 if warning_sent else 0))
    remaining = timer.remaining(generated_at)
    remaining_value = -1 if remaining is None else max(0, math.ceil(remaining))
    record = [
        name,
        zone,
        max(1, int(getattr(timer, "respawn_seconds", 1))),
        max(1, int(getattr(timer, "kill_seconds", 1))),
        max(0, int(getattr(timer, "warning_seconds", 0))),
        color[1:].upper(),
        flags,
        phase_code,
        remaining_value,
        max(0, int(getattr(timer, "cycles", 0))),
    ]
    death_mobs = normalize_death_mobs(
        getattr(timer, "death_mobs", []))
    # VTS1 remains the default for one name matching the timer label so older
    # Vantage releases can still receive ordinary shared spawn timers. Only
    # custom/multiple exact names require the extended VTS2 record.
    if not death_mobs or (
            len(death_mobs) == 1 and
            death_mobs[0].casefold() == name.casefold()):
        return 1, record
    return 2, [*record, death_mobs]


def _encode_packet(generated_at, packet_id, records, version=1):
    payload = [generated_at, packet_id, records]
    raw = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    compressed = zlib.compress(raw, level=9)
    token = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")
    prefix = TIMER_SHARE_V2_PREFIX if version == 2 else TIMER_SHARE_PREFIX
    return f"{prefix}{token}"


def build_timer_share_codes(
        timers, now=None, max_code_chars=MAX_TIMER_SHARE_CODE_CHARS):
    """Pack timer state into one or more EQ-chat-safe lines.

    Each line is independent so users can send it through `/say`, `/tell`, or
    an external message. The generation timestamp and remaining time are both
    included; the receiver can therefore account for transit delay.
    """
    generated_at = int(time.time() if now is None else float(now))
    packed_records = [_compact_timer(timer, generated_at) for timer in timers]
    if not packed_records:
        raise TimerShareError("There are no timers in the current zone view")
    if len(packed_records) > MAX_TIMER_SHARE_RECORDS:
        raise TimerShareError(
            f"Share at most {MAX_TIMER_SHARE_RECORDS} timers at once")
    maximum = max(96, min(512, int(max_code_chars)))
    codes = []
    packet_ids = []
    current_records = []
    current_version = None
    current_id = secrets.token_urlsafe(6)
    for record_version, record in packed_records:
        if current_records and record_version != current_version:
            codes.append(_encode_packet(
                generated_at, current_id, current_records,
                version=current_version))
            packet_ids.append(current_id)
            current_records = []
            current_id = secrets.token_urlsafe(6)
        current_version = record_version
        candidate = [*current_records, record]
        candidate_code = _encode_packet(
            generated_at, current_id, candidate, version=current_version)
        if len(candidate_code) <= maximum:
            current_records = candidate
            continue
        if not current_records:
            raise TimerShareError(
                f"{record[0]} has too much detail for an EQ chat code")
        codes.append(_encode_packet(
            generated_at, current_id, current_records,
            version=current_version))
        packet_ids.append(current_id)
        current_id = secrets.token_urlsafe(6)
        current_records = [record]
        if len(_encode_packet(
                generated_at, current_id, current_records,
                version=current_version)) > maximum:
            raise TimerShareError(
                f"{record[0]} has too much detail for an EQ chat code")
    if current_records:
        codes.append(_encode_packet(
            generated_at, current_id, current_records,
            version=current_version))
        packet_ids.append(current_id)
    return TimerShareExport(
        generated_at=generated_at,
        codes=tuple(codes),
        packet_ids=tuple(packet_ids),
        timer_count=len(packed_records),
    )


def _bounded_int(value, label, lower, upper):
    if isinstance(value, bool):
        raise TimerShareError(f"Invalid {label}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise TimerShareError(f"Invalid {label}") from error
    if not lower <= parsed <= upper:
        raise TimerShareError(f"Invalid {label}")
    return parsed


def _decompress_token(token):
    if not 16 <= len(token) <= 2048:
        raise TimerShareError("Timer share code is incomplete")
    padding = "=" * (-len(token) % 4)
    try:
        compressed = base64.b64decode(
            token + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise TimerShareError("Timer share code is damaged") from error
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise TimerShareError("Timer share code is too large")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_DECOMPRESSED_BYTES + 1)
    except zlib.error as error:
        raise TimerShareError("Timer share code is damaged") from error
    if (len(raw) > MAX_DECOMPRESSED_BYTES or decoder.unconsumed_tail
            or not decoder.eof):
        raise TimerShareError("Timer share code expands beyond the safe limit")
    try:
        return json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TimerShareError("Timer share code is damaged") from error


def decode_timer_share_code(code, received_at=None):
    """Validate one code and return its timer records plus transit age."""
    text = str(code or "").strip()
    prefix = next((
        candidate for candidate in TIMER_SHARE_PREFIXES
        if text.startswith(candidate)), None)
    if prefix is None:
        raise TimerShareError("Unsupported timer share code")
    version = 2 if prefix == TIMER_SHARE_V2_PREFIX else 1
    payload = _decompress_token(text[len(prefix):])
    if not isinstance(payload, list) or len(payload) != 3:
        raise TimerShareError("Unsupported timer share code")
    generated_at = _bounded_int(
        payload[0], "generation time", 1, 4_102_444_800)
    packet_id = str(payload[1] or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,16}", packet_id):
        raise TimerShareError("Invalid timer share identifier")
    rows = payload[2]
    if (not isinstance(rows, list) or not rows
            or len(rows) > MAX_TIMER_SHARE_RECORDS):
        raise TimerShareError("Invalid timer count")

    received = int(time.time() if received_at is None else float(received_at))
    raw_age = received - generated_at
    if raw_age > MAX_TIMER_SHARE_AGE_SECONDS:
        raise TimerShareError("Timer share code expired after 24 hours")
    age = max(0, raw_age)
    future_skew = max(0, -raw_age)
    records = []
    for row in rows:
        expected_fields = 11 if version == 2 else 10
        if not isinstance(row, list) or len(row) != expected_fields:
            raise TimerShareError("Invalid timer record")
        name = _safe_text(row[0], 64)
        zone = _safe_text(row[1], 64)
        if not name:
            raise TimerShareError("A shared timer is missing its name")
        respawn = _bounded_int(
            row[2], "respawn time", 1, 7 * 24 * 60 * 60)
        kill = _bounded_int(row[3], "kill time", 1, 24 * 60 * 60)
        warning = _bounded_int(row[4], "warning time", 0, respawn)
        color_text = str(row[5] or "").upper()
        if not re.fullmatch(r"[0-9A-F]{6}", color_text):
            raise TimerShareError("Invalid timer color")
        flags = _bounded_int(row[6], "timer flags", 0, 7)
        phase_code = _bounded_int(row[7], "timer phase", 0, 3)
        remaining_value = _bounded_int(
            row[8], "remaining time", -1, 7 * 24 * 60 * 60)
        cycles = _bounded_int(row[9], "timer cycles", 0, 1_000_000)
        if version == 2:
            raw_death_mobs = row[10]
            if (not isinstance(raw_death_mobs, list) or
                    not raw_death_mobs or
                    len(raw_death_mobs) > MAX_DEATH_MOBS or
                    any(not isinstance(value, str) or
                        not value.strip() or
                        len(value) > MAX_DEATH_MOB_NAME_LENGTH
                        for value in raw_death_mobs)):
                raise TimerShareError("Invalid death detection list")
            death_mobs = normalize_death_mobs(raw_death_mobs)
            if len(death_mobs) != len(raw_death_mobs):
                raise TimerShareError("Invalid death detection list")
        else:
            death_mobs = [name]
        running = bool(flags & 2)
        phase = _CODE_TO_PHASE[phase_code]
        remaining = None if remaining_value < 0 else remaining_value
        if phase == PHASE_IDLE and running:
            raise TimerShareError("An idle shared timer cannot be running")
        if phase in (PHASE_RESPAWN, PHASE_COMBAT) and remaining is None:
            raise TimerShareError("A running phase is missing its remaining time")
        records.append(SharedTimerRecord(
            name=name,
            zone=zone,
            respawn_seconds=respawn,
            kill_seconds=kill,
            warning_seconds=warning,
            color=f"#{color_text}",
            smart=bool(flags & 1),
            phase=phase,
            running=running,
            remaining_seconds=remaining,
            cycles=cycles,
            warning_sent=bool(flags & 4),
            death_mobs=tuple(death_mobs),
        ))
    return TimerSharePacket(
        generated_at=generated_at,
        packet_id=packet_id,
        timers=tuple(records),
        age_seconds=age,
        future_clock_skew_seconds=future_skew,
    )


def shared_record_to_state(record, packet, received_at, volume=85):
    """Rebuild a local timer and advance it through time spent in transit."""
    received = float(received_at)
    timer = SpawnTimerState(
        name=record.name,
        respawn_seconds=record.respawn_seconds,
        kill_seconds=record.kill_seconds,
        warning_seconds=record.warning_seconds,
        color=record.color,
        smart=record.smart,
        zone=record.zone,
        mob_pattern="",
        death_mobs=list(record.death_mobs) or [record.name],
        sound_path="builtin:spawn-horn",
        volume=volume,
        source="Shared timer",
        automatic=False,
    )
    timer.phase = record.phase
    timer.running = record.running
    timer.cycles = record.cycles
    timer.warning_sent = record.warning_sent
    remaining = record.remaining_seconds
    if timer.phase == PHASE_IDLE:
        timer.running = False
        return timer
    if not timer.running:
        timer.paused_remaining = remaining
        timer.deadline = (
            None if remaining is None else received + remaining)
        return timer
    if remaining is None:
        timer.deadline = None
        timer.phase_started_at = received
        return timer
    timer.deadline = received + remaining - packet.age_seconds
    timer.phase_started_at = timer.deadline - timer.phase_duration()
    if timer.deadline <= received:
        # tick() walks every missed smart phase from the original deadline,
        # so a delayed tell produces the same current timer as the sender.
        timer.tick(received)
    return timer
