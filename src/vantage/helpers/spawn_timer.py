"""Pure state machine for persistent Project 1999 spawn timers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import time
import uuid


PHASE_IDLE = "idle"
PHASE_RESPAWN = "respawn"
PHASE_COMBAT = "combat"
PHASE_AVAILABLE = "available"

TIMER_MODE_SPAWN = "spawn"
TIMER_MODE_COUNTDOWN = "countdown"
TIMER_MODE_COOLDOWN = "cooldown"
TIMER_MODES = {
    TIMER_MODE_SPAWN, TIMER_MODE_COUNTDOWN, TIMER_MODE_COOLDOWN}
TIMER_DELIVERIES = {"legacy", "sound", "tts", "off"}
TIMER_TTS_DEFAULT = "{timer}: {state}"
TIMER_NOTIFICATION_TOKEN_RX = re.compile(
    r"\{(timer|name|state|zone|event|seconds)\}", re.IGNORECASE)
MAX_DEATH_MOBS = 24
MAX_DEATH_MOB_NAME_LENGTH = 128


def normalize_death_mobs(values):
    """Return a bounded, stable list of mob/placeholder match phrases."""
    if not isinstance(values, (list, tuple)):
        return []
    result = []
    seen = set()
    for value in values:
        name = " ".join(str(value or "").split())[
            :MAX_DEATH_MOB_NAME_LENGTH]
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
        if len(result) >= MAX_DEATH_MOBS:
            break
    return result


def death_mob_name_matches(expected_name, actual_name):
    """Match a full name or a distinctive multi-word phrase.

    EverQuest death lines expose the complete NPC name. A saved full name
    therefore remains exact, while a phrase of two or more words may match a
    contiguous part of that name (for example ``Kennel Master`` matches
    ``Kennel Master Al`ele``). Single-word entries stay exact so generic words
    such as ``master`` cannot restart unrelated timers.
    """
    expected = " ".join(str(expected_name or "").split()).casefold()
    actual = " ".join(str(actual_name or "").split()).casefold()
    if not expected or not actual:
        return False
    if expected == actual:
        return True
    expected_tokens = re.findall(r"[^\W_]+", expected, re.UNICODE)
    actual_tokens = re.findall(r"[^\W_]+", actual, re.UNICODE)
    if len(expected_tokens) < 2 or len(expected_tokens) > len(actual_tokens):
        return False
    width = len(expected_tokens)
    return any(
        actual_tokens[index:index + width] == expected_tokens
        for index in range(len(actual_tokens) - width + 1))


def zone_timer_visible(timer_zone, selected_zone):
    """Show all in overview, otherwise require an exact assigned zone."""
    timer_zone = str(timer_zone or "").strip().casefold()
    selected_zone = str(selected_zone or "").strip().casefold()
    return not selected_zone or bool(
        timer_zone and timer_zone == selected_zone)


def reset_stale_persisted_timers(settings, now=None):
    """Preserve every saved countdown regardless of how long Vantage was off.

    Older releases cleared live countdown state after a configurable clean
    shutdown gap. Absolute deadlines already make that unnecessary: on startup
    ``tick()`` advances each timer through the time that elapsed offline.  Keep
    this compatibility hook so old configs migrate without losing a timer.
    """
    settings["last_session_closed_at"] = 0.0
    return False


@dataclass
class TimerEvent:
    kind: str
    timer_id: str
    name: str
    message: str


@dataclass
class SpawnTimerState:
    """A timestamp-based timer that survives sleep, zoning and restarts."""

    name: str
    respawn_seconds: int
    kill_seconds: int = 60
    warning_seconds: int = 30
    color: str = "#B38C52"
    smart: bool = True
    zone: str = ""
    mob_pattern: str = ""
    # New timers use full names or distinctive multi-word phrases.
    # ``mob_pattern`` remains solely so saved pre-list timers can keep their
    # established regular-expression behavior.
    death_mobs: list[str] = field(default_factory=list)
    # None inherits the central Smart Timer route, an empty string is an
    # explicit silent override, and a URI is this timer's sound override.
    sound_path: str | None = None
    volume: int = 85
    # Legacy rows keep the historical Smart Timer route and sound override.
    # Newly edited rows can choose exactly one per-timer delivery. A single
    # state-aware template stays compact while covering warning and ready/end.
    delivery: str = "legacy"
    tts_text: str = TIMER_TTS_DEFAULT
    tts_voice: str = ""
    tts_pitch: int = 0
    source: str = ""
    automatic: bool = False
    # ``spawn`` keeps the original kill/respawn cycle. ``countdown`` is a
    # one-shot general timer and ``cooldown`` is a reusable one-phase timer.
    # Keeping spawn as the default makes every existing saved row compatible.
    timer_mode: str = TIMER_MODE_SPAWN
    timer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    phase: str = PHASE_IDLE
    running: bool = False
    phase_started_at: float | None = None
    deadline: float | None = None
    paused_remaining: float | None = None
    cycles: int = 0
    warning_sent: bool = False

    def __post_init__(self):
        self.name = (self.name or "Spawn").strip()
        self.respawn_seconds = max(1, int(self.respawn_seconds))
        self.kill_seconds = max(1, int(self.kill_seconds))
        self.warning_seconds = max(0, int(self.warning_seconds))
        self.volume = max(0, min(100, int(self.volume)))
        self.color = self.color if re.fullmatch(r"#[0-9a-fA-F]{6}", self.color or "") else "#B38C52"
        if self.sound_path is not None:
            self.sound_path = str(self.sound_path)[:500]
        self.delivery = str(self.delivery or "legacy").strip().casefold()
        if self.delivery == "voice":
            self.delivery = "tts"
        if self.delivery not in TIMER_DELIVERIES:
            self.delivery = "legacy"
        self.tts_text = str(self.tts_text or "")[:300]
        self.tts_voice = str(self.tts_voice or "")[:160]
        try:
            self.tts_pitch = max(-10, min(10, int(self.tts_pitch)))
        except (TypeError, ValueError):
            self.tts_pitch = 0
        self.death_mobs = normalize_death_mobs(self.death_mobs)
        self.timer_mode = str(self.timer_mode or TIMER_MODE_SPAWN).casefold()
        if self.timer_mode not in TIMER_MODES:
            self.timer_mode = TIMER_MODE_SPAWN

    @classmethod
    def from_dict(cls, values):
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})

    def to_dict(self):
        return asdict(self)

    def start(self, now=None):
        """Manually start a fresh respawn cycle."""
        now = time.time() if now is None else float(now)
        self.phase = PHASE_RESPAWN
        self.running = True
        self.phase_started_at = now
        self.deadline = now + self.respawn_seconds
        self.paused_remaining = None
        self.warning_sent = False

    def restart(self, now=None):
        """Restart the full respawn countdown immediately."""
        self.start(now)

    def mark_killed(self, now=None):
        """Anchor the next respawn to a user/log-confirmed kill."""
        now = time.time() if now is None else float(now)
        self.cycles += 1
        self.start(now)

    def mark_spawned(self, now=None):
        """Anchor the estimated combat phase to a confirmed spawn."""
        now = time.time() if now is None else float(now)
        self.running = True
        self.phase_started_at = now
        self.warning_sent = False
        if self.smart:
            self.phase = PHASE_COMBAT
            self.deadline = now + self.kill_seconds
        else:
            self.phase = PHASE_AVAILABLE
            self.deadline = None

    def pause(self, now=None):
        if not self.running:
            return
        now = time.time() if now is None else float(now)
        self.paused_remaining = max(0.0, self.deadline - now) if self.deadline else None
        self.running = False

    def resume(self, now=None):
        if self.running or self.phase == PHASE_IDLE:
            return
        now = time.time() if now is None else float(now)
        if self.paused_remaining is not None:
            duration = self.paused_remaining
            self.phase_started_at = now
            self.deadline = now + duration
        self.running = True
        self.paused_remaining = None

    def reset(self):
        self.phase = PHASE_IDLE
        self.running = False
        self.phase_started_at = None
        self.deadline = None
        self.paused_remaining = None
        self.warning_sent = False

    def tick(self, now=None):
        """Advance through every missed phase and return meaningful events."""
        now = time.time() if now is None else float(now)
        events = []
        if not self.running or self.phase in (PHASE_IDLE, PHASE_AVAILABLE):
            return events

        if (self.phase == PHASE_RESPAWN and self.deadline and not self.warning_sent
                and 0 < self.deadline - now <= self.warning_seconds):
            self.warning_sent = True
            events.append(TimerEvent(
                "warning", self.timer_id, self.name,
                f"{self.name}: " + (
                    f"spawn in {max(1, int(self.deadline - now))} s"
                    if self.timer_mode == TIMER_MODE_SPAWN else
                    f"ends in {max(1, int(self.deadline - now))} s")
            ))

        safety = 0
        while self.deadline is not None and now >= self.deadline and safety < 10000:
            safety += 1
            transition_at = self.deadline
            if self.phase == PHASE_RESPAWN:
                if self.timer_mode != TIMER_MODE_SPAWN:
                    self.cycles += 1
                    self.phase = PHASE_AVAILABLE
                    self.running = False
                    self.phase_started_at = transition_at
                    self.deadline = None
                    self.warning_sent = False
                    kind = (
                        "ready" if self.timer_mode == TIMER_MODE_COOLDOWN
                        else "complete")
                    message = (
                        f"{self.name}: ready"
                        if self.timer_mode == TIMER_MODE_COOLDOWN else
                        f"{self.name}: timer complete")
                    events.append(TimerEvent(
                        kind, self.timer_id, self.name, message))
                    break
                events.append(TimerEvent(
                    "spawn", self.timer_id, self.name,
                    f"{self.name}: spawn available"
                ))
                self.phase_started_at = transition_at
                self.warning_sent = False
                if self.smart:
                    self.phase = PHASE_COMBAT
                    self.deadline = transition_at + self.kill_seconds
                else:
                    self.phase = PHASE_AVAILABLE
                    self.deadline = None
            elif self.phase == PHASE_COMBAT:
                self.cycles += 1
                events.append(TimerEvent(
                    "auto_kill", self.timer_id, self.name,
                    f"{self.name}: estimated kill; next respawn started"
                ))
                self.phase = PHASE_RESPAWN
                self.phase_started_at = transition_at
                self.deadline = transition_at + self.respawn_seconds
                self.warning_sent = False
            else:
                break
        return events

    def remaining(self, now=None):
        now = time.time() if now is None else float(now)
        if not self.running and self.paused_remaining is not None:
            return max(0.0, self.paused_remaining)
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - now)

    def phase_duration(self):
        if self.phase == PHASE_RESPAWN:
            return self.respawn_seconds
        if self.phase == PHASE_COMBAT:
            return self.kill_seconds
        return 1

    def progress_percent(self, now=None):
        if self.phase == PHASE_AVAILABLE:
            return 100
        remaining = self.remaining(now)
        if remaining is None:
            return 0
        return max(0, min(100, round((1 - remaining / self.phase_duration()) * 100)))

    def matches_kill(self, mob_name, zone=""):
        if self.timer_mode != TIMER_MODE_SPAWN:
            return False
        if self.zone and zone and self.zone.casefold() != zone.casefold():
            return False
        mob_name = " ".join(str(mob_name or "").split())
        if self.death_mobs:
            return any(
                death_mob_name_matches(expected, mob_name)
                for expected in self.death_mobs)
        pattern = self.mob_pattern.strip()
        if not pattern:
            # A new timer with no explicit entries still has a useful, safe
            # default: its label matches one complete mob name, never a
            # substring such as "Frenzy" matching "Frenzy PH".
            return self.name.casefold() == mob_name.casefold()
        try:
            return re.search(pattern, mob_name, re.IGNORECASE) is not None
        except re.error:
            return pattern.casefold() in mob_name.casefold()


def timer_notification_state(event_kind):
    """Return concise user-facing state text for a timer event."""
    return {
        "warning": "ending soon",
        "spawn": "spawn ready",
        "complete": "complete",
        "ready": "ready",
    }.get(str(event_kind or "").casefold(), str(event_kind or "timer event"))


def render_timer_notification_text(template, timer, event_kind, seconds=None):
    """Resolve bounded Smart Timer speech tokens without executing content."""
    values = {
        "timer": str(getattr(timer, "name", "Timer") or "Timer"),
        "name": str(getattr(timer, "name", "Timer") or "Timer"),
        "state": timer_notification_state(event_kind),
        "zone": str(getattr(timer, "zone", "") or "all zones"),
        "event": str(event_kind or "timer event"),
        "seconds": str(max(0, int(seconds or 0))),
    }
    source = str(template or TIMER_TTS_DEFAULT)[:300]
    return TIMER_NOTIFICATION_TOKEN_RX.sub(
        lambda match: values[match.group(1).casefold()], source).strip()


def format_seconds(value):
    value = max(0, int(value or 0))
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def parse_duration_input(value, single_unit="minutes"):
    """Parse friendly timer input while making bare numbers unambiguous.

    Examples: ``3`` -> three minutes, ``3:50`` -> three minutes and
    fifty seconds, and ``1:03:50`` -> one hour, three minutes, fifty seconds.
    Short unit forms such as ``90s``, ``3m`` and ``1.5h`` are also accepted.
    """
    text = str(value or "").strip().lower().replace(",", ".")
    if not text:
        return 0
    unit = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smh])", text)
    if unit:
        multiplier = {"s": 1, "m": 60, "h": 3600}[unit.group(2)]
        return max(0, round(float(unit.group(1)) * multiplier))
    if ":" not in text:
        try:
            multiplier = 60 if single_unit == "minutes" else 1
            return max(0, round(float(text) * multiplier))
        except ValueError:
            return 0
    parts = text.split(":")
    if len(parts) not in (2, 3) or any(
            not re.fullmatch(r"\d+", part.strip()) for part in parts):
        return 0
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds
