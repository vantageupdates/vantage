"""Local P99 threat estimation from observable EverQuest log events.

The classic client does not expose the server's hate list.  This module keeps
an intentionally local estimate: weapon attempts, selected combat skills,
configured procs, and a small set of well-understood spell effects.  No game
memory, process injection, or network threat sharing is used.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import datetime
import re


WEAPON_TYPES = (
    ("1hs", "1H Slashing"),
    ("1hp", "1H Piercing"),
    ("1hb", "1H Blunt"),
    ("2hs", "2H Slashing"),
    ("2hp", "2H Piercing"),
    ("2hb", "2H Blunt"),
    ("h2h", "Hand to Hand"),
    ("shield", "Shield / no attacks"),
    ("none", "Empty"),
)

TYPE_VERBS = {
    "1hs": {"hit", "slash"},
    "2hs": {"hit", "slash"},
    "1hp": {"hit", "pierce"},
    "2hp": {"hit", "pierce"},
    "1hb": {"hit", "crush"},
    "2hb": {"hit", "crush"},
    "h2h": {"hit", "punch"},
}


@dataclass
class Weapon:
    name: str = "Unconfigured"
    weapon_type: str = "none"
    damage: int = 0
    delay: int = 0
    damage_bonus: int = 0
    proc_threat: int = 0
    proc_landed: str = ""
    proc_resisted: str = ""

    @classmethod
    def from_mapping(cls, value):
        value = value if isinstance(value, dict) else {}
        weapon_type = str(value.get("type", "none")).casefold()
        if weapon_type not in {item[0] for item in WEAPON_TYPES}:
            weapon_type = "none"
        return cls(
            name=str(value.get("name", "Unconfigured")).strip() or "Unconfigured",
            weapon_type=weapon_type,
            damage=max(0, int(value.get("damage", 0) or 0)),
            delay=max(0, int(value.get("delay", 0) or 0)),
            damage_bonus=max(0, int(value.get("damage_bonus", 0) or 0)),
            proc_threat=int(value.get("proc_threat", 0) or 0),
            proc_landed=str(value.get("proc_landed", "") or "").strip(),
            proc_resisted=str(value.get("proc_resisted", "") or "").strip(),
        )

    def to_mapping(self):
        return {
            "name": self.name,
            "type": self.weapon_type,
            "damage": self.damage,
            "delay": self.delay,
            "damage_bonus": self.damage_bonus,
            "proc_threat": self.proc_threat,
            "proc_landed": self.proc_landed,
            "proc_resisted": self.proc_resisted,
        }

    @property
    def configured(self):
        return self.weapon_type not in ("none", "shield") and self.damage > 0

    @property
    def two_handed(self):
        return self.weapon_type.startswith("2h")

    def matches(self, verb):
        return str(verb).casefold() in TYPE_VERBS.get(self.weapon_type, set())

    def swing_threat(self, off_hand=False):
        if not self.configured:
            return 0.0
        if self.two_handed:
            return float(self.damage + self.damage_bonus)
        return float(self.damage + (12 if off_hand else 11))


@dataclass
class ThreatTarget:
    name: str
    started_at: datetime.datetime
    last_at: datetime.datetime
    total: float = 0.0
    main_swings: int = 0
    off_swings: int = 0
    tied_swings: int = 0
    procs: int = 0
    skill_threat: float = 0.0
    spell_threat: float = 0.0
    killed: bool = False

    def add(self, amount, source="other"):
        amount = float(amount)
        self.total = max(0.0, self.total + amount)
        if source == "skill":
            self.skill_threat += amount
        elif source == "spell":
            self.spell_threat += amount

    @property
    def duration(self):
        return max(1.0, (self.last_at - self.started_at).total_seconds())

    @property
    def threat_per_minute(self):
        return self.total / self.duration * 60.0

    @property
    def equal_flux(self):
        return int(self.total / 50)


SWING_HIT = re.compile(
    r"^You (?P<verb>hit|slash|crush|pierce|punch) (?P<target>.+?) for "
    r"\d+ points? of damage\.$", re.IGNORECASE)
SWING_MISS = re.compile(
    r"^You (?:try to )?(?P<verb>hit|slash|crush|pierce|punch)(?:es)? "
    r"(?P<target>.+?)(?:, but miss(?:es)?!|!)$", re.IGNORECASE)
SKILL_HIT = re.compile(
    r"^You (?P<skill>kick|bash) (?P<target>.+?) for \d+ points? of damage\.$",
    re.IGNORECASE)
SKILL_MISS = re.compile(
    r"^You try to (?P<skill>kick|bash) (?P<target>.+?), but miss(?:es)?!$",
    re.IGNORECASE)
DISARM = re.compile(r"^You disarmed (?P<target>.+?)!$", re.IGNORECASE)
CAST = re.compile(r"^You begin casting (?P<spell>.+?)\.$", re.IGNORECASE)
RESIST = re.compile(
    r"^Your target resisted the (?P<spell>.+?) spell\.$", re.IGNORECASE)
KILLS = (
    re.compile(r"^You have slain (?P<target>.+?)[!.]$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?) has been slain by .+?[!.]$", re.IGNORECASE),
)


SPELL_THREAT = {
    "flame lick": 1200,
    "enveloping roots": 1310,
    "jolt": -500,
    "cinder jolt": -500,
    "clinging darkness": 400,
}

SPELL_LANDING = (
    (re.compile(r"^(?P<target>.+?) is surrounded by flickering flames\.$",
                re.IGNORECASE), "flame lick"),
    (re.compile(r"^(?P<target>.+?)'s feet become entwined\.$",
                re.IGNORECASE), "enveloping roots"),
    (re.compile(r"^(?P<target>.+?)'s head snaps back\.$",
                re.IGNORECASE), "jolt_or_cinder"),
    (re.compile(r"^(?P<target>.+?) is surrounded by darkness\.$",
                re.IGNORECASE), "clinging darkness"),
)


class ThreatEstimator:
    """Bounded, local estimate of the player's threat by target."""

    def __init__(self, settings=None, max_targets=250):
        self.max_targets = max(25, int(max_targets))
        self.targets = OrderedDict()
        self.current_target = ""
        self.pending_spell = ""
        self.pending_spell_at = None
        self.pending_unknown = 0.0
        self.last_error = ""
        self.configure(settings or {})

    def configure(self, settings):
        settings = settings if isinstance(settings, dict) else {}
        self.enabled = bool(settings.get("enabled", True))
        self.main = Weapon.from_mapping(settings.get("main_hand"))
        self.off = Weapon.from_mapping(settings.get("off_hand"))
        self.main_rate = max(
            0.05, min(0.95, float(settings.get("same_type_main_rate", 55)) / 100.0))

    @property
    def configured(self):
        return self.main.configured

    def reset(self):
        self.targets.clear()
        self.current_target = ""
        self.pending_spell = ""
        self.pending_spell_at = None
        self.pending_unknown = 0.0
        self.last_error = ""

    def _target(self, name, timestamp):
        clean = str(name or "Unknown target").strip()
        key = clean.casefold()
        target = self.targets.get(key)
        if target is None:
            target = ThreatTarget(clean, timestamp, timestamp)
            self.targets[key] = target
            while len(self.targets) > self.max_targets:
                self.targets.popitem(last=False)
        else:
            target.last_at = max(target.last_at, timestamp)
            self.targets.move_to_end(key)
        self.current_target = key
        if self.pending_unknown:
            target.add(self.pending_unknown, "spell")
            self.pending_unknown = 0.0
        return target

    def current(self):
        return self.targets.get(self.current_target)

    def recent(self):
        return list(reversed(self.targets.values()))

    def _apply_to_current_or_pending(self, amount, timestamp, source="spell"):
        target = self.current()
        if target:
            target.last_at = max(target.last_at, timestamp)
            target.add(amount, source)
        else:
            self.pending_unknown += float(amount)

    def _weapon_for_verb(self, verb):
        main_matches = self.main.matches(verb)
        off_matches = self.off.matches(verb)
        if main_matches and off_matches:
            return "tied"
        if main_matches:
            return "main"
        if off_matches:
            return "off"
        return ""

    def _swing(self, timestamp, verb, target_name):
        target = self._target(target_name, timestamp)
        slot = self._weapon_for_verb(verb)
        if slot == "tied":
            target.tied_swings += 1
            target.main_swings = int(round(target.tied_swings * self.main_rate))
            target.off_swings = target.tied_swings - target.main_swings
            amount = (
                self.main.swing_threat(False) * self.main_rate +
                self.off.swing_threat(True) * (1.0 - self.main_rate))
            target.add(amount)
        elif slot == "main":
            target.main_swings += 1
            target.add(self.main.swing_threat(False))
        elif slot == "off":
            target.off_swings += 1
            target.add(self.off.swing_threat(True))
        elif self.configured:
            self.last_error = (
                f"{verb.title()} does not match the configured weapon types")
        return target

    @staticmethod
    def _proc_match(pattern, text, current_name=""):
        pattern = str(pattern or "").strip()
        if not pattern:
            return False
        expected = pattern.replace("{target}", current_name)
        return expected.casefold() in text.casefold()

    def _procs(self, timestamp, text):
        target = self.current()
        current_name = target.name if target else ""
        for weapon in (self.main, self.off):
            if not weapon.proc_threat:
                continue
            if (self._proc_match(weapon.proc_landed, text, current_name) or
                    self._proc_match(weapon.proc_resisted, text, current_name)):
                if target:
                    target.last_at = max(target.last_at, timestamp)
                    target.procs += 1
                    target.add(weapon.proc_threat)
                else:
                    self.pending_unknown += weapon.proc_threat
                return True
        return False

    def _spell_landing(self, timestamp, text):
        for pattern, spell in SPELL_LANDING:
            match = pattern.match(text)
            if not match:
                continue
            pending = self.pending_spell.casefold()
            if spell == "jolt_or_cinder":
                if pending not in ("jolt", "cinder jolt"):
                    return False
                spell = pending
            elif pending and pending != spell:
                return False
            target = self._target(match.group("target"), timestamp)
            target.add(SPELL_THREAT[spell], "spell")
            self.pending_spell = ""
            self.pending_spell_at = None
            return True
        return False

    def ingest(self, timestamp, text):
        """Ingest one timestamp-free EQ log message; return True when changed."""
        if not self.enabled:
            return False
        timestamp = timestamp or datetime.datetime.now()
        text = str(text or "").strip()
        if not text:
            return False

        if text.startswith("You have entered ") or text == "You have been slain!":
            self.current_target = ""
            self.pending_unknown = 0.0
            self.pending_spell = ""
            return False

        for pattern in KILLS:
            killed = pattern.match(text)
            if killed:
                key = killed.group("target").strip().casefold()
                target = self.targets.get(key)
                if target:
                    target.last_at = max(target.last_at, timestamp)
                    target.killed = True
                if self.current_target == key:
                    self.current_target = ""
                return bool(target)

        cast = CAST.match(text)
        if cast:
            self.pending_spell = cast.group("spell").strip()
            self.pending_spell_at = timestamp
            return False

        resist = RESIST.match(text)
        if resist:
            spell = resist.group("spell").strip().casefold()
            amount = SPELL_THREAT.get(spell)
            if amount is not None:
                self._apply_to_current_or_pending(amount, timestamp)
                self.pending_spell = ""
                self.pending_spell_at = None
                return True

        if self._spell_landing(timestamp, text):
            return True
        if self._procs(timestamp, text):
            return True

        skill = SKILL_HIT.match(text) or SKILL_MISS.match(text)
        if skill:
            values = skill.groupdict()
            amount = 5 if values["skill"].casefold() == "kick" else 7
            target = self._target(values["target"], timestamp)
            target.add(amount, "skill")
            return True
        disarm = DISARM.match(text)
        if disarm:
            target = self._target(disarm.group("target"), timestamp)
            target.add(20, "skill")
            return True
        if text.casefold() == "your attempt to disarm failed.":
            self._apply_to_current_or_pending(20, timestamp, "skill")
            return True

        swing = SWING_HIT.match(text) or SWING_MISS.match(text)
        if swing:
            values = swing.groupdict()
            self._swing(timestamp, values["verb"], values["target"])
            return True
        return False
