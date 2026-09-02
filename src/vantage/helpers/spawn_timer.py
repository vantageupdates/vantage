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


def zone_timer_visible(timer_zone, selected_zone):
    """Global rows are visible everywhere; zoned rows match the chosen view."""
    timer_zone = str(timer_zone or "").strip().casefold()
    selected_zone = str(selected_zone or "").strip().casefold()
    return not selected_zone or not timer_zone or timer_zone == selected_zone


def reset_stale_persisted_timers(settings, now=None):
    """Reset saved countdowns after a long clean shutdown, keeping rows.

    A zero close timestamp means the previous session did not report a clean
    shutdown (or predates this feature), so its timers are preserved.
    """
    now = time.time() if now is None else float(now)
    try:
        hours = max(1, min(48, int(settings.get("clear_after_hours", 4))))
    except (TypeError, ValueError):
        hours = 4
    try:
        closed_at = max(0.0, float(settings.get(
            "last_session_closed_at", 0.0)))
    except (TypeError, ValueError):
        closed_at = 0.0
    items = settings.get("items", [])
    expired = bool(
        isinstance(items, list) and items and closed_at > 0 and
        max(0.0, now - closed_at) >= hours * 3600)
    if expired:
        for values in items:
            if not isinstance(values, dict):
                continue
            values.update({
                "phase": PHASE_IDLE,
                "running": False,
                "phase_started_at": None,
                "deadline": None,
                "paused_remaining": None,
                "cycles": 0,
                "warning_sent": False,
            })
    # Zero while running prevents a crash from being mistaken for a long,
    # clean shutdown on the next start.
    settings["last_session_closed_at"] = 0.0
    return expired


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
    sound_path: str = ""
    volume: int = 85
    source: str = ""
    automatic: bool = False
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
                f"{self.name}: spawn in {max(1, int(self.deadline - now))} s"
            ))

        safety = 0
        while self.deadline is not None and now >= self.deadline and safety < 10000:
            safety += 1
            transition_at = self.deadline
            if self.phase == PHASE_RESPAWN:
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
        if self.zone and zone and self.zone.casefold() != zone.casefold():
            return False
        pattern = (self.mob_pattern or self.name).strip()
        if not pattern:
            return False
        try:
            return re.search(pattern, mob_name, re.IGNORECASE) is not None
        except re.error:
            return pattern.casefold() in mob_name.casefold()


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
