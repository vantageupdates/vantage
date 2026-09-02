"""Event-driven EverQuest/P99 combat aggregation.

The engine retains parsed statistics, not duplicate raw log lines.  It accepts
classic P99 combat text and keeps the same major views players expect from a
full parser: fight navigation, damage, tanking, spells, healing and session
rollups.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import datetime
import re


MELEE = re.compile(
    r"^(?P<attacker>You|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?P<verb>hit|hits|slash|slashes|crush|crushes|pierce|pierces|"
    r"kick|kicks|bash|bashes|backstab|backstabs|bite|bites|claw|claws|"
    r"maul|mauls|punch|punches) (?P<target>.+?) for "
    r"(?P<damage>\d+) points? of damage\.$",
    re.IGNORECASE,
)
NON_MELEE = re.compile(
    r"^(?P<target>.+?) was hit by non-melee for (?P<damage>\d+) "
    r"points? of damage\.$", re.IGNORECASE)
DOT = re.compile(
    r"^(?P<target>.+?) has taken (?P<damage>\d+) damage from your "
    r"(?P<spell>.+?)\.$", re.IGNORECASE)
MISS = re.compile(
    r"^(?P<attacker>You|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?:try|tries) to (?P<verb>hit|slash|crush|pierce|kick|bash|backstab) "
    r"(?P<target>.+?), but miss(?:es)?!$", re.IGNORECASE)
SIMPLE_MISS = re.compile(
    r"^(?P<attacker>You|[A-Za-z][A-Za-z'` .-]*?) miss(?:es)? "
    r"(?P<target>.+?)!$", re.IGNORECASE)
DEFENSE = re.compile(
    r"^(?P<tank>You|YOU|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?P<kind>dodge|dodges|parry|parries|block|blocks|riposte|ripostes) "
    r"(?P<attacker>.+?)(?:'s attack)?[!.]$", re.IGNORECASE)
MELEE_DEFENDED = re.compile(
    r"^(?P<attacker>.+?) (?:try|tries) to "
    r"(?P<verb>slash|bash|hit|crush|punch|frenz(?:y)?|pierce|claw|kick|"
    r"bite|backstab|strike|maul|gore|slice|smash|sting|rend|slam|shoot|"
    r"stab|burn|learn|sweep)(?:y on)? (?P<target>.+?), but "
    r"(?:.+? )?(?P<lucky>luckily )?"
    r"(?P<kind>dodges?|blocks?|parr(?:y|ies)|ripostes?)"
    r"(?: with \w+ (?P<shield>shield|staff))?!"
    r"(?: \((?P<tag>.+)\))?$", re.IGNORECASE)
DEFENSE_OUTCOME = re.compile(
    r"^(?P<attacker>.+?) (?:try|tries) to "
    r"(?P<verb>slash|bash|hit|crush|punch|frenz(?:y)?|pierce|claw|kick|"
    r"bite|backstab|strike|maul|gore|slice|smash|sting|rend|slam|shoot|"
    r"stab|burn|learn|sweep)(?:y on)? (?P<target>.+?), but "
    r"(?:.+? )?(?P<outcome>miss(?:es)?!|magical skin absorbs the blow!|"
    r"do(?:es)? no damage\.|INVULNERABLE!)"
    r"(?: \((?P<tag>.+)\))?$", re.IGNORECASE)
SPELL_ABSORBED = re.compile(
    r"^(?P<target>.+?)(?:'s | )magical skin absorbs "
    r"(?P<attacker>.+?)(?:'s | )spell\.$", re.IGNORECASE)
STRIKETHROUGH = re.compile(
    r"^Your opponent strikes through your defenses!$", re.IGNORECASE)
HEAL = re.compile(
    r"^(?P<healer>You|[A-Za-z][A-Za-z'` .-]*?) (?:(?:have|has) )?heal(?:ed|s) "
    r"(?P<target>.+?) for (?P<amount>\d+) (?:hit )?points?[!.]$",
    re.IGNORECASE)
HEALED_YOU = re.compile(
    r"^(?P<healer>[A-Za-z][A-Za-z'` .-]*?) has healed you for "
    r"(?P<amount>\d+) (?:hit )?points?[!.]$", re.IGNORECASE)
BEGIN_CAST = re.compile(
    r"^(?P<caster>You|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?:begin|begins) casting (?P<spell>.+?)\.$", re.IGNORECASE)
GENERIC_CAST = re.compile(
    r"^(?P<caster>[A-Za-z][A-Za-z'` .-]*?) "
    r"begins? (?:casting|to cast) (?:a |an )?spell\.$", re.IGNORECASE)
SPELL_RESISTS = (
    re.compile(
        r"^Your target resisted (?:the )?(?P<spell>.+?)(?: spell)?[.!]$",
        re.IGNORECASE),
    re.compile(
        r"^(?P<target>.+?) (?:has )?resisted (?:the|your) "
        r"(?P<spell>.+?)(?: spell)?[.!]$", re.IGNORECASE),
)
SPELL_REFLECT = re.compile(
    r"^(?P<caster>.+?)'s (?:(?P<spell>.+?) )?spell has been "
    r"reflected by (?P<target>.+?)\.$", re.IGNORECASE)
SPELL_BLOCK = re.compile(
    r"^(?:(?P<target>.+?) )?(?:has )?(?:blocked your spell|"
    r"spell did not take hold)[.!]$", re.IGNORECASE)
OTHER_SPELL_BLOCK = re.compile(
    r"^(?P<caster>.+?)'s spell did not take hold[.!]$", re.IGNORECASE)
SPELL_FIZZLE = re.compile(
    r"^(?:(?P<caster>.+?)'s|Your) spell fizzles!$", re.IGNORECASE)
SPELL_INTERRUPT = re.compile(
    r"^(?:(?P<caster>.+?)'s|Your) spell is interrupted[.!]$",
    re.IGNORECASE)
SONG_FIZZLE = re.compile(
    r"^(?:(?P<caster>You) miss|(?P<other>.+?) misses) a note, "
    r"bringing (?:your|their|his|her) song to a close!$", re.IGNORECASE)
CRITICAL = re.compile(
    r"^(?P<attacker>You|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?:scores?|lands?|delivers?) (?P<kind>a critical hit|"
    r"a crippling blow|a finishing blow|a deadly strike|a critical blast)"
    r"!{1,2}(?:\s*\((?P<reported>[\d,]+)\))?$", re.IGNORECASE)
KILLS = (
    re.compile(r"^You have slain (?P<target>.+?)[!.]$", re.IGNORECASE),
    re.compile(
        r"^(?P<target>.+?) has been slain by (?P<killer>.+?)[!.]$",
        re.IGNORECASE),
)
CHAT = re.compile(
    r"^(?P<speaker>.+?) (?P<channel>tells you|tells? the group|"
    r"tells? the guild|tells? the raid|tells? the fellowship|"
    r"tells? your party|tells? your guild|tells? your raid|"
    r"tells? your fellowship|says?|auctions?|shouts?|oocs?),? "
    r"'(?P<message>.*)'$", re.IGNORECASE)
CHAT_DESTINATION = re.compile(
    r"^(?P<speaker>.+?) (?P<verb>tell|tells|told) "
    r"(?P<destination>[^,]+),? '(?P<message>.*)'$", re.IGNORECASE)
PET_LEADER = re.compile(
    r"^(?P<pet>.+?) says,? 'My leader is (?P<owner>.+?)\.'$",
    re.IGNORECASE)
LOOT = re.compile(
    r"^(?:--)?(?P<looter>You|[A-Za-z][A-Za-z'` .-]*?) "
    r"(?:have|has) looted (?:(?P<count>\d+)\s+|an?\s+|the\s+)?"
    r"(?P<item>.+?)(?: from (?P<source>.+?))?\.(?:--)?$", re.IGNORECASE)
FACTION = re.compile(
    r"^Your faction standing with (?P<faction>.+?) "
    r"(?:(?:has been )?adjusted by (?P<delta>-?\d+)|"
    r"(?P<change>got better|got worse|could not possibly get any better|"
    r"could not possibly get any worse))\.$", re.IGNORECASE)
COIN_PATTERNS = (
    ("Corpse", re.compile(
        r"^You receive (?P<amount>.+?) from the corpse\.?$", re.IGNORECASE)),
    ("Group split", re.compile(
        r"^You receive (?P<amount>.+?) as your split\.?$", re.IGNORECASE)),
    ("Vendor", re.compile(
        r"^You receive (?P<amount>.+?) from (?P<source>\S+) for the "
        r"(?P<item>.+?)\(s\)\.?$", re.IGNORECASE)),
    ("Item sale", re.compile(
        r"^You received (?P<amount>.+?) from that item\.?$", re.IGNORECASE)),
)
COIN_VALUES = {"platinum": 1000, "gold": 100, "silver": 10, "copper": 1}
COIN_PARTS = re.compile(
    r"(?P<count>\d+)\s+(?P<denomination>platinum|gold|silver|copper)",
    re.IGNORECASE)
RANDOM_ROLLER = re.compile(
    r"^\*\*A Magic Die is rolled by (?P<player>.+?)\.$", re.IGNORECASE)
RANDOM_VALUE = re.compile(
    r"^\*\*It could have been any number from (?P<low>\d+) to "
    r"(?P<high>\d+), but this time it turned up (?:a )?(?P<value>\d+)\.$",
    re.IGNORECASE)

# Only combat-looking lines are eligible for the optional unmatched parser
# diagnostic.  Chat is excluded separately before this expression is used, so
# enabling diagnostics never turns the buffer into a second chat archive.
COMBAT_DIAGNOSTIC_HINT = re.compile(
    r"\b(?:hit|hits|damage|slash|crush|pierce|kick|bash|backstab|miss|"
    r"dodge|parry|block|riposte|spell|casting|fizzle|interrupt|resist|"
    r"reflect|heal|critical|crippling|finishing|deadly|slain)\b",
    re.IGNORECASE)


def attack_type(verb):
    value = str(verb or "Melee").casefold()
    for stem, label in (
            ("backstab", "Backstab"), ("slash", "Slashing"),
            ("crush", "Crushing"), ("pierce", "Piercing"),
            ("kick", "Kick"), ("bash", "Bash"), ("bite", "Bite"),
            ("claw", "Claw"), ("maul", "Maul"),
            ("punch", "Hand to Hand"), ("frenz", "Frenzy"),
            ("gore", "Gore"), ("slice", "Slice"), ("smash", "Smash"),
            ("sting", "Sting"), ("rend", "Rend"), ("slam", "Slam"),
            ("shoot", "Shoot"), ("stab", "Stab"), ("burn", "Burn"),
            ("learn", "Learn"), ("sweep", "Sweep"),
            ("strike", "Strike"), ("hit", "Hit")):
        if value.startswith(stem):
            return label
    return "Melee"


@dataclass
class AttackBreakdown:
    name: str
    damage: int = 0
    hits: int = 0
    min_hit: int = 0
    max_hit: int = 0

    def add(self, amount):
        amount = max(0, int(amount))
        self.damage += amount
        self.hits += 1
        self.min_hit = amount if not self.min_hit else min(self.min_hit, amount)
        self.max_hit = max(self.max_hit, amount)


@dataclass
class DamageModifierStats:
    """Matched critical reports and their following real damage lines.

    Classic EQ can print a critical amount separately from the actual hit.
    Keeping both values is the same evidence GamParse uses for its Damage Mod
    page; an empty report is never converted into an estimated modifier.
    """

    attack_type: str
    critical_type: str
    samples: int = 0
    reported_damage: int = 0
    actual_damage: int = 0

    def add(self, reported, actual):
        reported = max(0, int(reported or 0))
        actual = max(0, int(actual or 0))
        if not reported or not actual:
            return False
        self.samples += 1
        self.reported_damage += reported
        self.actual_damage += actual
        return True

    @property
    def reported_average(self):
        return self.reported_damage / self.samples if self.samples else 0.0

    @property
    def actual_average(self):
        return self.actual_damage / self.samples if self.samples else 0.0

    @property
    def modifier_percent(self):
        if not self.reported_damage:
            return 0.0
        return (self.actual_damage / self.reported_damage - 1.0) * 100.0

    def merge(self, other):
        self.samples += other.samples
        self.reported_damage += other.reported_damage
        self.actual_damage += other.actual_damage


@dataclass
class AttackerStats:
    name: str
    damage: int = 0
    hits: int = 0
    max_hit: int = 0
    min_hit: int = 0
    attempts: int = 0
    misses: int = 0
    criticals: int = 0
    first_at: datetime.datetime | None = None
    last_at: datetime.datetime | None = None
    by_type: dict = field(default_factory=dict)
    critical_types: dict = field(default_factory=dict)
    damage_modifiers: dict = field(default_factory=dict)
    source_names: set = field(default_factory=set)

    def __post_init__(self):
        # Preserve the real actors behind a displayed ``Owner + pets`` row.
        # GamParse uses those identities to merge both outgoing and incoming
        # statistics without losing the individual pet/owner relationship.
        if not self.source_names:
            self.source_names.add(self.name)

    def add(
            self, amount, kind="Melee", timestamp=None, critical=False,
            critical_type="", reported_critical=0):
        amount = max(0, int(amount))
        self.damage += amount
        self.hits += 1
        self.attempts += 1
        self.min_hit = amount if not self.min_hit else min(self.min_hit, amount)
        self.max_hit = max(self.max_hit, amount)
        critical_name = str(critical_type or "").strip()
        is_critical = bool(critical or critical_name)
        self.criticals += int(is_critical)
        if is_critical:
            critical_name = critical_name or "Critical"
            self.critical_types[critical_name] = (
                self.critical_types.get(critical_name, 0) + 1)
            if int(reported_critical or 0) > 0:
                key = (str(kind), critical_name)
                modifier = self.damage_modifiers.setdefault(
                    key, DamageModifierStats(str(kind), critical_name))
                modifier.add(reported_critical, amount)
        if timestamp is not None:
            self.first_at = self.first_at or timestamp
            self.last_at = timestamp if self.last_at is None else max(
                self.last_at, timestamp)
        breakdown = self.by_type.setdefault(kind, AttackBreakdown(kind))
        breakdown.add(amount)

    def miss(self, timestamp=None):
        self.attempts += 1
        self.misses += 1
        # GamParse QuickDPS measures from the first damaging hit to the last
        # damaging hit; misses affect accuracy but not active DPS time.

    @property
    def accuracy(self):
        return (self.hits / self.attempts * 100.0) if self.attempts else 0.0

    @property
    def active_duration(self):
        if not self.first_at or not self.last_at:
            return 1.0
        # GamParse QuickDPS.Duration is inclusive: End - Start + 1.
        return max(
            1.0, (self.last_at - self.first_at).total_seconds() + 1.0)

    def merge(self, other):
        self.source_names.update(other.source_names or {other.name})
        self.damage += other.damage
        self.hits += other.hits
        self.attempts += other.attempts
        self.misses += other.misses
        self.criticals += other.criticals
        for name, count in other.critical_types.items():
            self.critical_types[name] = self.critical_types.get(name, 0) + count
        for key, values in other.damage_modifiers.items():
            self.damage_modifiers.setdefault(
                key, DamageModifierStats(
                    values.attack_type, values.critical_type)).merge(values)
        if other.min_hit:
            self.min_hit = other.min_hit if not self.min_hit else min(
                self.min_hit, other.min_hit)
        self.max_hit = max(self.max_hit, other.max_hit)
        if other.first_at:
            self.first_at = other.first_at if not self.first_at else min(
                self.first_at, other.first_at)
        if other.last_at:
            self.last_at = other.last_at if not self.last_at else max(
                self.last_at, other.last_at)
        for name, values in other.by_type.items():
            target = self.by_type.setdefault(name, AttackBreakdown(name))
            target.damage += values.damage
            target.hits += values.hits
            if values.min_hit:
                target.min_hit = values.min_hit if not target.min_hit else min(
                    target.min_hit, values.min_hit)
            target.max_hit = max(target.max_hit, values.max_hit)


@dataclass
class TankStats:
    name: str
    damage: int = 0
    hits: int = 0
    min_hit: int = 0
    max_hit: int = 0
    attempts: int = 0
    misses: int = 0
    dodges: int = 0
    parries: int = 0
    blocks: int = 0
    ripostes: int = 0
    invulnerable: int = 0
    absorbed: int = 0
    real_hits: int = 0
    strikethroughs: int = 0
    hit_counts: dict = field(default_factory=dict)
    by_type: dict = field(default_factory=dict)

    def _bucket(self, kind):
        kind = str(kind or "Melee").strip() or "Melee"
        return self.by_type.setdefault(kind, TankStats(kind))

    def _hit(self, amount):
        amount = max(0, int(amount))
        self.damage += amount
        self.hits += 1
        self.real_hits += 1
        self.attempts += 1
        self.min_hit = amount if not self.min_hit else min(self.min_hit, amount)
        self.max_hit = max(self.max_hit, amount)
        self.hit_counts[amount] = self.hit_counts.get(amount, 0) + 1

    def hit(self, amount, kind=""):
        self._hit(amount)
        if kind:
            self._bucket(kind)._hit(amount)

    def _avoid(self, kind):
        self.attempts += 1
        folded = str(kind).casefold()
        if folded.startswith("dodge"):
            self.dodges += 1
        elif folded.startswith("parr"):
            self.parries += 1
        elif folded.startswith("block"):
            self.blocks += 1
        elif folded.startswith("riposte"):
            self.ripostes += 1
        else:
            self.misses += 1

    def avoid(self, kind, attack=""):
        self._avoid(kind)
        if attack:
            self._bucket(attack)._avoid(kind)

    def _absorb(self):
        self.attempts += 1
        self.hits += 1
        self.absorbed += 1

    def absorb(self, attack=""):
        self._absorb()
        if attack:
            self._bucket(attack)._absorb()

    def _invulnerable(self):
        self.attempts += 1
        self.invulnerable += 1

    def invulnerable_hit(self, attack=""):
        self._invulnerable()
        if attack:
            self._bucket(attack)._invulnerable()

    def strikethrough(self, attack=""):
        self.strikethroughs += 1
        if attack:
            self._bucket(attack).strikethroughs += 1

    @property
    def defended(self):
        return self.dodges + self.parries + self.blocks + self.ripostes

    @property
    def avoided(self):
        """Compatibility alias; misses are reported separately by GamParse."""
        return self.defended

    @property
    def average_hit(self):
        return self.damage / self.real_hits if self.real_hits else 0.0

    @property
    def accuracy(self):
        chances = self.hits + self.misses
        return self.hits / chances * 100.0 if chances else 0.0

    @property
    def defended_percent(self):
        chances = max(0, self.attempts - self.invulnerable)
        return self.defended / chances * 100.0 if chances else 0.0

    def defense_rates(self):
        """Return current GamParse-style sequential chance denominators.

        The current binary removes invulnerability and misses first, followed
        by riposte, parry, dodge, and block for the standard class order.
        """
        attempts = self.attempts
        invuln_chances = attempts
        after_invuln = max(0, attempts - self.invulnerable)
        after_miss = max(0, after_invuln - self.misses)
        after_riposte = max(0, after_miss - self.ripostes)
        after_parry = max(0, after_riposte - self.parries)
        after_dodge = max(0, after_parry - self.dodges)
        return {
            "Invulnerable": (self.invulnerable, invuln_chances),
            "Missed": (self.misses, after_invuln),
            "Riposted": (self.ripostes, after_miss),
            "Parried": (self.parries, after_riposte),
            "Dodged": (self.dodges, after_parry),
            "Blocked": (self.blocks, after_dodge),
            "Defended": (self.defended, after_invuln),
            "Absorbed": (self.absorbed, self.hits),
            "Hits": (self.real_hits, self.hits),
        }

    def hit_count_rates(self):
        """Return the original tanking hit-count view denominators.

        Unlike the breakdown grid, this view tests active defenses before the
        opponent miss. Its Hits row includes absorbed hit outcomes, while Real
        Hits excludes them.
        """
        attempts = self.attempts
        after_invuln = max(0, attempts - self.invulnerable)
        after_riposte = max(0, after_invuln - self.ripostes)
        after_parry = max(0, after_riposte - self.parries)
        after_dodge = max(0, after_parry - self.dodges)
        after_block = max(0, after_dodge - self.blocks)
        return {
            "Invulnerable": (self.invulnerable, attempts),
            "Riposted": (self.ripostes, after_invuln),
            "Parried": (self.parries, after_riposte),
            "Dodged": (self.dodges, after_parry),
            "Blocked": (self.blocks, after_dodge),
            "Defended": (self.defended, after_invuln),
            "Missed": (self.misses, after_block),
            "Hits": (self.hits, after_invuln),
            "Absorbed": (self.absorbed, self.hits),
            "Real Hits": (self.real_hits, attempts),
        }

    def merge(self, other):
        for key in (
                "damage", "hits", "attempts", "misses", "dodges",
                "parries", "blocks", "ripostes", "invulnerable",
                "absorbed", "real_hits", "strikethroughs"):
            setattr(self, key, getattr(self, key) + getattr(other, key))
        if other.min_hit:
            self.min_hit = other.min_hit if not self.min_hit else min(
                self.min_hit, other.min_hit)
        self.max_hit = max(self.max_hit, other.max_hit)
        for amount, count in other.hit_counts.items():
            self.hit_counts[amount] = self.hit_counts.get(amount, 0) + count
        for name, values in other.by_type.items():
            self.by_type.setdefault(name, TankStats(name)).merge(values)

    def to_dict(self):
        return {
            "name": self.name,
            "damage": self.damage,
            "hits": self.hits,
            "real_hits": self.real_hits,
            "min_hit": self.min_hit,
            "max_hit": self.max_hit,
            "attempts": self.attempts,
            "misses": self.misses,
            "dodges": self.dodges,
            "parries": self.parries,
            "blocks": self.blocks,
            "ripostes": self.ripostes,
            "invulnerable": self.invulnerable,
            "absorbed": self.absorbed,
            "strikethroughs": self.strikethroughs,
            "hit_counts": dict(self.hit_counts),
            "by_type": {
                name: values.to_dict() for name, values in self.by_type.items()},
        }


@dataclass
class SpellStats:
    name: str
    casts: int = 0
    damage: int = 0
    ticks: int = 0
    direct_damage: int = 0
    direct_hits: int = 0
    direct_max: int = 0
    dot_damage: int = 0
    dot_ticks: int = 0
    dot_max: int = 0
    resists: int = 0
    fizzles: int = 0
    interrupts: int = 0
    reflects: int = 0
    blocks: int = 0
    specials: int = 0

    def damage_event(self, amount, is_dot=False):
        amount = max(0, int(amount))
        self.damage += amount
        if is_dot:
            self.ticks += 1
            self.dot_damage += amount
            self.dot_ticks += 1
            self.dot_max = max(self.dot_max, amount)
        else:
            self.direct_damage += amount
            self.direct_hits += 1
            self.direct_max = max(self.direct_max, amount)

    def merge(self, other):
        for key in (
                "casts", "damage", "ticks", "direct_damage",
                "direct_hits", "dot_damage", "dot_ticks", "resists",
                "fizzles", "interrupts", "reflects", "blocks",
                "specials"):
            setattr(self, key, getattr(self, key) + getattr(other, key))
        self.direct_max = max(self.direct_max, other.direct_max)
        self.dot_max = max(self.dot_max, other.dot_max)


@dataclass
class SpellCastEvent:
    timestamp: datetime.datetime
    caster: str
    spell: str
    outcome: str = "Cast"
    detail: str = ""


@dataclass
class HealStats:
    name: str
    healing: int = 0
    heals: int = 0
    max_heal: int = 0
    by_target: dict = field(default_factory=dict)

    def add(self, amount, target="Unknown"):
        amount = max(0, int(amount))
        self.healing += amount
        self.heals += 1
        self.max_heal = max(self.max_heal, amount)
        target = str(target or "Unknown")
        values = self.by_target.setdefault(
            target, {"healing": 0, "heals": 0, "max_heal": 0})
        values["healing"] += amount
        values["heals"] += 1
        values["max_heal"] = max(values["max_heal"], amount)

    def merge(self, other):
        self.healing += other.healing
        self.heals += other.heals
        self.max_heal = max(self.max_heal, other.max_heal)
        for target, values in other.by_target.items():
            merged = self.by_target.setdefault(
                target, {"healing": 0, "heals": 0, "max_heal": 0})
            merged["healing"] += values["healing"]
            merged["heals"] += values["heals"]
            merged["max_heal"] = max(
                merged["max_heal"], values["max_heal"])


@dataclass
class ChatEvent:
    timestamp: datetime.datetime
    channel: str
    speaker: str
    message: str
    character: str = ""
    server: str = ""


def chat_channel(speaker, raw_channel='', destination=''):
    """Normalize EQ chat into GamParse-style channels and tell threads."""
    speaker = str(speaker or '').strip()
    raw_channel = str(raw_channel or '').strip()
    destination = str(destination or '').strip()
    folded = raw_channel.casefold()
    if 'tell' in folded and 'you' in folded:
        return f"Tell · {speaker}"
    for token, label in (
            ('guild', 'Guild'), ('group', 'Group'), ('party', 'Group'),
            ('raid', 'Raid'), ('fellowship', 'Fellowship')):
        if token in folded:
            return label
    if folded.startswith('say'):
        return 'Say'
    if folded.startswith('auction'):
        return 'Auction'
    if folded.startswith('shout'):
        return 'Shout'
    if folded.startswith('ooc'):
        return 'OOC'
    if destination:
        clean_destination = destination.strip()
        destination_folded = clean_destination.casefold()
        for token, label in (
                ('your guild', 'Guild'), ('the guild', 'Guild'),
                ('your party', 'Group'), ('the group', 'Group'),
                ('your raid', 'Raid'), ('the raid', 'Raid'),
                ('your fellowship', 'Fellowship'),
                ('the fellowship', 'Fellowship')):
            if destination_folded == token:
                return label
        # Joined channels are logged as names such as General:1. Everything
        # else in the destination form is an individual tell conversation.
        if re.search(r':\d+$', clean_destination):
            return clean_destination
        return f"Tell · {clean_destination}"
    return raw_channel.rstrip('s').title() or 'Chat'


@dataclass
class LootEvent:
    timestamp: datetime.datetime
    looter: str
    item: str
    count: int = 1
    source: str = ""
    zone: str = ""
    character: str = ""
    server: str = ""


@dataclass
class CoinEvent:
    timestamp: datetime.datetime
    amount: str
    copper: int
    kind: str
    source: str = ""
    item: str = ""
    zone: str = ""
    character: str = ""
    server: str = ""


@dataclass
class FactionEvent:
    timestamp: datetime.datetime
    faction: str
    change: str
    zone: str = ""
    delta: int = 0
    character: str = ""
    server: str = ""


@dataclass
class RandomEvent:
    timestamp: datetime.datetime
    player: str
    low: int
    high: int
    value: int


def build_random_sets(
        events, duplicate_policy="first", gap_seconds=20,
        break_before=None):
    """Group /random rolls by range and time, then resolve duplicates.

    EverQuest emits each roll as a small two-line log event and provides no
    explicit set identifier.  A range-specific inactivity gap therefore ends
    a set.  Manual split timestamps let the UI correct unusual raid workflows
    without changing or duplicating the original parsed rolls.
    """
    policy = str(duplicate_policy or "first").casefold()
    if policy not in {"first", "highest", "latest"}:
        policy = "first"
    gap = max(1, int(gap_seconds or 20))
    breaks = set(break_before or ())
    ordered = sorted(
        list(events or ()), key=lambda event: event.timestamp)
    groups = []
    active = {}
    for event in ordered:
        key = (int(event.low), int(event.high))
        current = active.get(key)
        must_split = bool(
            current and (
                event.timestamp in breaks or
                (event.timestamp - current[-1].timestamp).total_seconds() > gap))
        if current is None or must_split:
            current = []
            groups.append(current)
            active[key] = current
        current.append(event)

    results = []
    for rolls in groups:
        if not rolls:
            continue
        eligible = {}
        counts = defaultdict(int)
        for event in rolls:
            player_key = event.player.casefold()
            counts[player_key] += 1
            previous = eligible.get(player_key)
            if previous is None:
                eligible[player_key] = event
            elif policy == "latest":
                eligible[player_key] = event
            elif policy == "highest" and event.value > previous.value:
                eligible[player_key] = event
        chosen = list(eligible.values())
        winning_value = max((event.value for event in chosen), default=None)
        winners = sorted(
            (event.player for event in chosen
             if event.value == winning_value), key=str.casefold)
        results.append({
            "started": rolls[0].timestamp,
            "ended": rolls[-1].timestamp,
            "low": int(rolls[0].low),
            "high": int(rolls[0].high),
            "rolls": len(rolls),
            "players": len(eligible),
            "duplicates": sum(max(0, count - 1) for count in counts.values()),
            "winner": " / ".join(winners) if winners else "—",
            "winning_value": winning_value,
            "events": tuple(rolls),
        })
    return list(reversed(results))


@dataclass
class CombatEvent:
    timestamp: datetime.datetime
    kind: str
    actor: str = ""
    target: str = ""
    amount: int = 0
    detail: str = ""


@dataclass(frozen=True)
class ParseDiagnostic:
    """One bounded, local explanation of a combat parser decision."""

    timestamp: datetime.datetime
    category: str
    actor: str = ""
    target: str = ""
    amount: int = 0
    action: str = ""
    outcome: str = ""
    detail: str = ""
    source: str = ""


@dataclass
class Encounter:
    target: str
    started_at: datetime.datetime
    last_at: datetime.datetime
    zone: str = ""
    attackers: dict = field(default_factory=dict)
    tanks: dict = field(default_factory=dict)
    spells: dict = field(default_factory=dict)
    caster_spells: dict = field(default_factory=dict)
    spell_casts: deque = field(default_factory=lambda: deque(maxlen=5000))
    healers: dict = field(default_factory=dict)
    events: deque = field(default_factory=lambda: deque(maxlen=5000))
    killed: bool = False
    damage_started_at: datetime.datetime | None = None
    damage_last_at: datetime.datetime | None = None

    def touch_damage(self, timestamp):
        self.damage_started_at = (
            timestamp if self.damage_started_at is None else
            min(self.damage_started_at, timestamp))
        self.damage_last_at = (
            timestamp if self.damage_last_at is None else
            max(self.damage_last_at, timestamp))

    def add(
            self, timestamp, attacker, amount, kind="Melee",
            critical_type="", reported_critical=0):
        self.last_at = max(self.last_at, timestamp)
        self.touch_damage(timestamp)
        stats = self.attackers.setdefault(attacker, AttackerStats(attacker))
        stats.add(
            amount, kind, timestamp,
            critical_type=critical_type,
            reported_critical=reported_critical)
        if str(self.target).casefold() in ("you", "yourself"):
            self.tanks.setdefault("You", TankStats("You")).hit(amount, kind)

    def add_miss(self, timestamp, attacker):
        self.last_at = max(self.last_at, timestamp)
        self.attackers.setdefault(attacker, AttackerStats(attacker)).miss(timestamp)

    def event(self, timestamp, kind, actor="", target="", amount=0, detail=""):
        self.last_at = max(self.last_at, timestamp)
        self.events.append(CombatEvent(
            timestamp, kind, actor, target, int(amount or 0), detail))

    @property
    def total_damage(self):
        return sum(stats.damage for stats in self.attackers.values())

    @property
    def total_healing(self):
        return sum(stats.healing for stats in self.healers.values())

    @property
    def duration(self):
        starts = [
            stats.first_at for stats in self.attackers.values()
            if stats.first_at is not None]
        ends = [
            stats.last_at for stats in self.attackers.values()
            if stats.last_at is not None]
        if self.damage_started_at is not None:
            starts.append(self.damage_started_at)
        if self.damage_last_at is not None:
            ends.append(self.damage_last_at)
        if starts and ends:
            # GamParse Fight.Duration is inclusive: End - Start + 1.
            return max(1.0, (max(ends) - min(starts)).total_seconds() + 1.0)
        return max(1.0, (self.last_at - self.started_at).total_seconds() + 1.0)

    @property
    def dps(self):
        return self.total_damage / self.duration

    @property
    def player_count(self):
        return len(self.attackers)

    @property
    def your_dps(self):
        stats = self.attackers.get("You")
        return stats.damage / self.duration if stats else 0.0


class CombatTracker:
    """Keeps active and recently completed parsed fights in bounded memory."""

    def __init__(self, timeout=12, max_history=250, pet_links=None):
        self.timeout = max(3, int(timeout))
        self.active = {}
        self.completed = deque(maxlen=max_history)
        self._completed_undo = deque(maxlen=20)
        self.session_attackers = {}
        self.session_tanks = {}
        self.session_spells = {}
        self.session_caster_spells = {}
        self.session_spell_casts = deque(maxlen=20000)
        self.session_healers = {}
        self.chat = deque(maxlen=20000)
        self.loot = deque(maxlen=2000)
        self.coins = deque(maxlen=3000)
        self.faction = deque(maxlen=3000)
        self.randoms = deque(maxlen=3000)
        self.diagnostics = deque(maxlen=5000)
        self.diagnostics_enabled = False
        self.diagnostics_revision = 0
        self.pet_links = {}
        self.pet_revision = 0
        for pet, owner in (pet_links or {}).items():
            self.register_pet(pet, owner, "Saved")
        self._last_spell = ""
        self._last_spells = {}
        self._pending_criticals = {}
        self._pending_random = None
        self.current_zone = ""

    def set_diagnostics_enabled(self, enabled):
        """Enable bounded raw parser evidence without collecting past lines."""
        self.diagnostics_enabled = bool(enabled)
        return self.diagnostics_enabled

    def clear_diagnostics(self):
        if not self.diagnostics:
            return False
        self.diagnostics.clear()
        self.diagnostics_revision += 1
        return True

    def _diagnostic(
            self, timestamp, category, source, actor="", target="",
            amount=0, action="", outcome="", detail=""):
        if not self.diagnostics_enabled:
            return False
        self.diagnostics.appendleft(ParseDiagnostic(
            timestamp=timestamp,
            category=str(category or "Unmatched"),
            actor=str(actor or ""),
            target=str(target or ""),
            amount=max(0, int(amount or 0)),
            action=str(action or ""),
            outcome=str(outcome or ""),
            detail=str(detail or ""),
            source=str(source or "")))
        self.diagnostics_revision += 1
        return True

    def register_pet(self, pet, owner, source="Log"):
        pet = str(pet or "").strip()
        owner = str(owner or "").strip()
        if not pet or not owner or pet.casefold() == owner.casefold():
            return False
        key = pet.casefold()
        value = self.pet_links.get(key)
        if value and value["owner"].casefold() == owner.casefold():
            return False
        self.pet_links[key] = {
            "pet": pet, "owner": owner, "source": str(source or "Log")}
        self.pet_revision += 1
        return True

    def remove_pet(self, pet):
        if self.pet_links.pop(str(pet or "").casefold(), None) is None:
            return False
        self.pet_revision += 1
        return True

    def pet_rows(self):
        return sorted(
            self.pet_links.values(),
            key=lambda value: (value["owner"].casefold(), value["pet"].casefold()))

    def display_attackers(self, encounter, merge_pets=True):
        if not encounter or not merge_pets:
            return list(encounter.attackers.values()) if encounter else []
        merged = {}
        owners = {
            value["owner"].casefold(): value["owner"]
            for value in self.pet_links.values()}
        for name, stats in encounter.attackers.items():
            link = self.pet_links.get(name.casefold())
            owner = link["owner"] if link else owners.get(name.casefold())
            display = f"{owner} + pets" if owner else name
            merged.setdefault(display, AttackerStats(display)).merge(stats)
        return list(merged.values())

    def parse_damage(self, text):
        match = DOT.match(text)
        if match:
            values = match.groupdict()
            return (
                "You", values["target"], int(values["damage"]),
                f"DoT · {values['spell']}", values["spell"])
        match = NON_MELEE.match(text)
        if match:
            values = match.groupdict()
            return "You", values["target"], int(values["damage"]), "Direct Damage", self._last_spell
        match = MELEE.match(text)
        if match:
            values = match.groupdict()
            return (
                values["attacker"], values["target"], int(values["damage"]),
                attack_type(values["verb"]), "")
        return None

    def _encounter(self, target, timestamp):
        key = target.casefold()
        encounter = self.active.get(key)
        if encounter is None:
            encounter = Encounter(
                target, timestamp, timestamp, zone=self.current_zone)
            self.active[key] = encounter
        return encounter

    def _tank_encounter(self, attacker, tank, timestamp):
        """Resolve a defensive line without treating NPC defense as tanking."""
        attacker = str(attacker or "").strip()
        tank = self._caster_name(tank)
        if tank == "You":
            return self._encounter(attacker, timestamp)
        encounter = self._current_for_non_damage()
        if (encounter and attacker and
                encounter.target.casefold() == attacker.casefold()):
            return encounter
        return None

    def _tank_stats(self, encounter, tank):
        tank = self._caster_name(tank)
        if not encounter:
            return None, None
        fight_stats = encounter.tanks.setdefault(tank, TankStats(tank))
        session_stats = self.session_tanks.setdefault(tank, TankStats(tank))
        return fight_stats, session_stats

    @staticmethod
    def _caster_name(value):
        value = str(value or "You").strip()
        return "You" if value.casefold() in {"you", "your"} else value

    @staticmethod
    def _caster_spell(collection, caster, name):
        spells = collection.setdefault(caster, {})
        return spells.setdefault(name, SpellStats(name))

    def _add_spell_event(
            self, encounter, name, field_name, amount=1, caster="You"):
        name = str(name or "Unknown spell").strip()
        caster = self._caster_name(caster)
        for collection in (encounter.spells, self.session_spells):
            stats = collection.setdefault(name, SpellStats(name))
            setattr(stats, field_name, getattr(stats, field_name) + amount)
        for collection in (
                encounter.caster_spells, self.session_caster_spells):
            stats = self._caster_spell(collection, caster, name)
            setattr(stats, field_name, getattr(stats, field_name) + amount)

    def _add_spell_damage(self, encounter, name, amount, is_dot=False):
        name = str(name or "Unknown spell").strip()
        for collection in (encounter.spells, self.session_spells):
            collection.setdefault(
                name, SpellStats(name)).damage_event(amount, is_dot)

    def _current_for_non_damage(self):
        return self.current()

    def _record_spell_cast(self, timestamp, caster, spell):
        caster = self._caster_name(caster)
        spell = str(spell or "Unknown spell").strip()
        self._last_spells[caster.casefold()] = spell
        if caster == "You":
            self._last_spell = spell
        encounter = self._current_for_non_damage()
        if encounter:
            self._add_spell_event(
                encounter, spell, "casts", caster=caster)
        else:
            self.session_spells.setdefault(spell, SpellStats(spell)).casts += 1
            self._caster_spell(
                self.session_caster_spells, caster, spell).casts += 1
        record = SpellCastEvent(timestamp, caster, spell)
        self.session_spell_casts.append(record)
        if encounter:
            encounter.spell_casts.append(record)
            encounter.event(
                timestamp, "Cast", caster, encounter.target, 0, spell)
        return encounter

    def _last_spell_for(self, caster="You"):
        caster = self._caster_name(caster)
        return self._last_spells.get(
            caster.casefold(), self._last_spell if caster == "You" else "")

    def _record_spell_outcome(
            self, timestamp, outcome, field_name, caster="You", spell="",
            detail=""):
        caster = self._caster_name(caster)
        spell = str(spell or self._last_spell_for(caster) or
                    "Unknown spell").strip()
        encounter = self._current_for_non_damage()
        if encounter:
            self._add_spell_event(
                encounter, spell, field_name, caster=caster)
        else:
            stats = self.session_spells.setdefault(spell, SpellStats(spell))
            setattr(stats, field_name, getattr(stats, field_name) + 1)
            caster_stats = self._caster_spell(
                self.session_caster_spells, caster, spell)
            setattr(
                caster_stats, field_name,
                getattr(caster_stats, field_name) + 1)
        matched = None
        for record in reversed(self.session_spell_casts):
            if record.caster.casefold() != caster.casefold():
                continue
            if spell != "Unknown spell" and record.spell.casefold() != spell.casefold():
                continue
            age = (timestamp - record.timestamp).total_seconds()
            if age < 0 or age > 30:
                continue
            if record.outcome == "Cast":
                matched = record
                break
        if matched:
            matched.outcome = outcome
            matched.detail = str(detail or "")
        if encounter:
            encounter.event(
                timestamp, outcome, caster, encounter.target, 0,
                spell if not detail else f"{spell} · {detail}")
        return encounter

    @staticmethod
    def _critical_type(value):
        folded = str(value or "").casefold()
        if "crippl" in folded:
            return "Crippling"
        if "finishing" in folded:
            return "Finishing"
        if "deadly" in folded:
            return "Deadly"
        return "Critical"

    def _remember_critical(self, timestamp, attacker, kind, reported=0):
        attacker = self._caster_name(attacker)
        self._pending_criticals[attacker.casefold()] = (
            timestamp, self._critical_type(kind), int(reported or 0))
        return attacker

    def _consume_critical(self, timestamp, attacker):
        key = self._caster_name(attacker).casefold()
        pending = self._pending_criticals.pop(key, None)
        if not pending:
            return "", 0
        reported_at, critical_type, reported = pending
        age = (timestamp - reported_at).total_seconds()
        if age < 0 or age > 3:
            return "", 0
        return critical_type, reported

    def ingest(self, timestamp, text):
        changed = False
        diagnostic_matched = False
        critical = CRITICAL.match(text)
        if critical:
            values = critical.groupdict()
            attacker = self._remember_critical(
                timestamp, values["attacker"], values["kind"],
                int((values.get("reported") or "0").replace(",", "")))
            encounter = self._current_for_non_damage()
            if encounter:
                critical_type = self._critical_type(values["kind"])
                reported = int(
                    (values.get("reported") or "0").replace(",", ""))
                encounter.event(
                    timestamp, critical_type, attacker, encounter.target,
                    reported, "Reported critical" if reported else
                    "Critical report without a visible amount")
            critical_type = self._critical_type(values["kind"])
            reported = int(
                (values.get("reported") or "0").replace(",", ""))
            self._diagnostic(
                timestamp, "Melee", text, actor=attacker,
                target=encounter.target if encounter else "",
                amount=reported, action=critical_type,
                outcome="Critical report",
                detail=("Reported amount" if reported else
                        "No amount visible in the log"))
            diagnostic_matched = True
            changed = True
        if text.startswith("You have entered "):
            self.current_zone = text[17:].rstrip(".")
        pet_leader = PET_LEADER.match(text)
        if pet_leader:
            values = pet_leader.groupdict()
            changed = self.register_pet(
                values["pet"], values["owner"], "Pet leader") or changed
        chat = CHAT.match(text)
        destination_chat = None if chat else CHAT_DESTINATION.match(text)
        if chat or destination_chat:
            values = (chat or destination_chat).groupdict()
            channel = chat_channel(
                values["speaker"], values.get("channel", ''),
                values.get("destination", ''))
            self.chat.appendleft(ChatEvent(
                timestamp, channel, values["speaker"], values["message"]))
            changed = True
        loot = LOOT.match(text)
        if loot:
            values = loot.groupdict()
            self.loot.appendleft(LootEvent(
                timestamp, values["looter"], values["item"],
                max(1, int(values.get("count") or 1)),
                str(values.get("source") or ""), self.current_zone))
            changed = True
        for coin_kind, coin_pattern in COIN_PATTERNS:
            coin = coin_pattern.match(text)
            if not coin:
                continue
            values = coin.groupdict()
            amount = values["amount"]
            copper = sum(
                int(part.group("count")) *
                COIN_VALUES[part.group("denomination").casefold()]
                for part in COIN_PARTS.finditer(amount))
            if copper:
                self.coins.appendleft(CoinEvent(
                    timestamp, amount, copper, coin_kind,
                    str(values.get("source") or ""),
                    str(values.get("item") or ""), self.current_zone))
                changed = True
            break
        faction = FACTION.match(text)
        if faction:
            values = faction.groupdict()
            delta = int(values.get("delta") or 0)
            change = (
                f"{delta:+d}" if values.get("delta") is not None else
                str(values.get("change") or "").title())
            self.faction.appendleft(FactionEvent(
                timestamp, values["faction"], change,
                self.current_zone, delta))
            changed = True
        roller = RANDOM_ROLLER.match(text)
        if roller:
            self._pending_random = (timestamp, roller.group("player").strip())
            changed = True
        random_value = RANDOM_VALUE.match(text)
        if random_value and self._pending_random:
            rolled_at, player = self._pending_random
            values = random_value.groupdict()
            self.randoms.appendleft(RandomEvent(
                timestamp if timestamp else rolled_at, player,
                int(values["low"]), int(values["high"]),
                int(values["value"])))
            self._pending_random = None
            changed = True
        damage = self.parse_damage(text)
        if damage:
            attacker, target, amount, kind, spell_name = damage
            critical_type, reported_critical = self._consume_critical(
                timestamp, attacker)
            incoming_encounter = self._tank_encounter(
                attacker, target, timestamp)
            incoming = incoming_encounter is not None
            if incoming:
                # Incoming damage belongs to the opponent fight.  Treating
                # a PC as a separate opponent inflates outgoing DPS and loses
                # GamParse's per-player "Dmg to PC" value for that mob.
                encounter = incoming_encounter
                tank = self._caster_name(target)
                encounter.touch_damage(timestamp)
                encounter.tanks.setdefault(
                    tank, TankStats(tank)).hit(amount, kind)
                self.session_tanks.setdefault(
                    tank, TankStats(tank)).hit(amount, kind)
                encounter.event(
                    timestamp, "Incoming", attacker, tank, amount, kind)
            else:
                encounter = self._encounter(target, timestamp)
                encounter.add(
                    timestamp, attacker, amount, kind,
                    critical_type, reported_critical)
                self.session_attackers.setdefault(
                    attacker, AttackerStats(attacker)).add(
                        amount, kind, timestamp,
                        critical_type=critical_type,
                        reported_critical=reported_critical)
                detail = kind
                if critical_type:
                    detail += f" · {critical_type}"
                    if reported_critical:
                        detail += f" · reported {reported_critical:,}"
                encounter.event(
                    timestamp, "Damage", attacker, target, amount, detail)
            if spell_name and not incoming:
                # A cast line normally precedes the first damage line that
                # creates the fight. Attribute that pending cast to the new
                # encounter without counting it twice in the session.
                fight_spell = encounter.spells.setdefault(
                    spell_name, SpellStats(spell_name))
                session_spell = self.session_spells.get(spell_name)
                if not fight_spell.casts and session_spell and session_spell.casts:
                    fight_spell.casts = 1
                fight_caster_spell = self._caster_spell(
                    encounter.caster_spells, "You", spell_name)
                session_caster_spell = self.session_caster_spells.get(
                    "You", {}).get(spell_name)
                if (not fight_caster_spell.casts and session_caster_spell and
                        session_caster_spell.casts):
                    fight_caster_spell.casts = 1
                # The cast may have occurred just before the first damage line
                # created the encounter. Reuse the same record rather than
                # manufacturing a second cast.
                if not encounter.spell_casts:
                    for record in reversed(self.session_spell_casts):
                        if (record.caster == "You" and
                                record.spell.casefold() == spell_name.casefold() and
                                0 <= (timestamp - record.timestamp).total_seconds() <= 30):
                            encounter.spell_casts.append(record)
                            break
                self._add_spell_damage(
                    encounter, spell_name, amount,
                    is_dot=kind.startswith("DoT ·"))
            if kind.startswith("DoT ·"):
                category = "DoT"
                action = spell_name or kind[len("DoT · "):]
            elif kind == "Direct Damage":
                category = "Direct Damage"
                action = spell_name or "Unknown spell"
            else:
                category = "Melee"
                action = kind
            detail = "Incoming" if incoming else "Outgoing"
            if critical_type:
                detail += f" · {critical_type}"
                if reported_critical:
                    detail += f" · report {reported_critical:,}"
            self._diagnostic(
                timestamp, category, text, actor=attacker, target=target,
                amount=amount, action=action, outcome="Hit", detail=detail)
            diagnostic_matched = True
            changed = True

        defended = MELEE_DEFENDED.match(text)
        defense_outcome = DEFENSE_OUTCOME.match(text)
        if defended:
            values = defended.groupdict()
            tank = self._caster_name(values["target"])
            attack_name = attack_type(values["verb"])
            kind = "block" if values.get("shield") else values["kind"]
            encounter = self._tank_encounter(
                values["attacker"], tank, timestamp)
            fight_stats, session_stats = self._tank_stats(encounter, tank)
            if fight_stats:
                fight_stats.avoid(kind, attack_name)
                session_stats.avoid(kind, attack_name)
                encounter.last_at = max(encounter.last_at, timestamp)
                encounter.event(
                    timestamp, "Avoided", tank, values["attacker"], 0,
                    f"{kind.title()} · {attack_name}")
            detail = attack_name
            if values.get("lucky"):
                detail += " · Lucky"
            self._diagnostic(
                timestamp, "Defense", text, actor=tank,
                target=values["attacker"], action=kind.title(),
                outcome="Avoided", detail=detail)
            diagnostic_matched = True
            changed = True
        elif defense_outcome:
            values = defense_outcome.groupdict()
            tank = self._caster_name(values["target"])
            attack_name = attack_type(values["verb"])
            result = values["outcome"].casefold()
            encounter = self._tank_encounter(
                values["attacker"], tank, timestamp)
            fight_stats, session_stats = self._tank_stats(encounter, tank)
            if "invulnerable" in result:
                label = "Invulnerable"
                if fight_stats:
                    fight_stats.invulnerable_hit(attack_name)
                    session_stats.invulnerable_hit(attack_name)
            elif "absorbs" in result or "no damage" in result:
                label = "Absorbed"
                if fight_stats:
                    fight_stats.absorb(attack_name)
                    session_stats.absorb(attack_name)
            else:
                label = "Miss"
                if fight_stats:
                    fight_stats.avoid("miss", attack_name)
                    session_stats.avoid("miss", attack_name)
                else:
                    encounter = self._encounter(values["target"], timestamp)
                    encounter.add_miss(timestamp, values["attacker"])
                    self.session_attackers.setdefault(
                        values["attacker"], AttackerStats(
                            values["attacker"])).miss(timestamp)
            if encounter:
                encounter.last_at = max(encounter.last_at, timestamp)
                encounter.event(
                    timestamp, "Avoided" if label == "Miss" else label,
                    tank, values["attacker"], 0,
                    attack_name)
            self._diagnostic(
                timestamp, "Defense", text, actor=tank,
                target=values["attacker"], action=attack_name,
                outcome=label)
            diagnostic_matched = True
            changed = True

        miss = None if defense_outcome else (
            MISS.match(text) or SIMPLE_MISS.match(text))
        if miss:
            values = miss.groupdict()
            if values["target"].casefold() in ("you", "yourself"):
                encounter = self._encounter(values["attacker"], timestamp)
                attack_name = attack_type(values.get("verb") or "Melee")
                encounter.tanks.setdefault(
                    "You", TankStats("You")).avoid("miss", attack_name)
                self.session_tanks.setdefault(
                    "You", TankStats("You")).avoid("miss", attack_name)
                encounter.event(
                    timestamp, "Avoided", values["attacker"], "You", 0,
                    "Miss")
            else:
                encounter = self._encounter(values["target"], timestamp)
                encounter.add_miss(timestamp, values["attacker"])
                self.session_attackers.setdefault(
                    values["attacker"], AttackerStats(values["attacker"])).miss(
                        timestamp)
                encounter.event(
                    timestamp, "Miss", values["attacker"],
                    values["target"], 0, "Miss")
            incoming_miss = values["target"].casefold() in ("you", "yourself")
            self._diagnostic(
                timestamp, "Defense" if incoming_miss else "Melee", text,
                actor=values["attacker"], target=values["target"],
                action=attack_type(values.get("verb") or "Melee"),
                outcome="Miss",
                detail="Incoming" if incoming_miss else "Outgoing")
            diagnostic_matched = True
            changed = True

        defense = DEFENSE.match(text)
        if defense:
            values = defense.groupdict()
            tank = self._caster_name(values["tank"])
            encounter = self._tank_encounter(
                values["attacker"], tank, timestamp)
            if encounter:
                encounter.tanks.setdefault(
                    tank, TankStats(tank)).avoid(values["kind"], "Melee")
                self.session_tanks.setdefault(
                    tank, TankStats(tank)).avoid(values["kind"], "Melee")
                encounter.last_at = max(encounter.last_at, timestamp)
                encounter.event(
                    timestamp, "Avoided", tank, values["attacker"], 0,
                    values["kind"].title())
                changed = True
            self._diagnostic(
                timestamp, "Defense", text, actor=tank,
                target=values["attacker"], action=values["kind"].title(),
                outcome="Avoided",
                detail="Active fight" if encounter else "No active fight")
            diagnostic_matched = True

        spell_absorbed = SPELL_ABSORBED.match(text)
        if spell_absorbed:
            values = spell_absorbed.groupdict()
            tank = self._caster_name(values["target"])
            encounter = self._tank_encounter(
                values["attacker"], tank, timestamp)
            fight_stats, session_stats = self._tank_stats(encounter, tank)
            if fight_stats:
                fight_stats.absorb("Direct Damage")
                session_stats.absorb("Direct Damage")
                encounter.last_at = max(encounter.last_at, timestamp)
                encounter.event(
                    timestamp, "Absorbed", tank, values["attacker"], 0,
                    "Direct Damage")
            self._diagnostic(
                timestamp, "Defense", text, actor=tank,
                target=values["attacker"], action="Direct Damage",
                outcome="Absorbed")
            diagnostic_matched = True
            changed = True

        if STRIKETHROUGH.match(text):
            encounter = self._current_for_non_damage()
            fight_stats, session_stats = self._tank_stats(encounter, "You")
            if fight_stats:
                fight_stats.strikethrough()
                session_stats.strikethrough()
                encounter.event(
                    timestamp, "Strikethrough", encounter.target, "You")
            self._diagnostic(
                timestamp, "Defense", text, actor="You",
                target=encounter.target if encounter else "Opponent",
                action="Strikethrough", outcome="Defense bypassed",
                detail="Visible legacy log notice")
            diagnostic_matched = True
            changed = True

        cast = BEGIN_CAST.match(text)
        if cast:
            values = cast.groupdict()
            self._record_spell_cast(
                timestamp, values.get("caster") or "You", values["spell"])
            self._diagnostic(
                timestamp, "Spells", text,
                actor=self._caster_name(values.get("caster") or "You"),
                target=self.current().target if self.current() else "",
                action=values["spell"], outcome="Cast")
            diagnostic_matched = True
            changed = True
        else:
            generic_cast = GENERIC_CAST.match(text)
            if generic_cast:
                self._record_spell_cast(
                    timestamp, generic_cast.group("caster"), "Unknown spell")
                self._diagnostic(
                    timestamp, "Spells", text,
                    actor=self._caster_name(generic_cast.group("caster")),
                    target=self.current().target if self.current() else "",
                    action="Unknown spell", outcome="Cast",
                    detail="Spell name is not visible in this log line")
                diagnostic_matched = True
                changed = True

        fizzle = SPELL_FIZZLE.match(text)
        song_fizzle = SONG_FIZZLE.match(text)
        interrupted = SPELL_INTERRUPT.match(text)
        reflected = SPELL_REFLECT.match(text)
        blocked = SPELL_BLOCK.match(text) or OTHER_SPELL_BLOCK.match(text)
        resisted = None
        for pattern in SPELL_RESISTS:
            resisted = pattern.match(text)
            if resisted:
                break
        if fizzle or song_fizzle:
            values = (fizzle or song_fizzle).groupdict()
            caster = values.get("caster") or values.get("other") or "You"
            self._record_spell_outcome(
                timestamp, "Fizzle", "fizzles", caster=caster,
                detail="Song" if song_fizzle else "Spell")
            spell = self._last_spell_for(caster) or "Unknown spell"
            self._diagnostic(
                timestamp, "Spells", text, actor=self._caster_name(caster),
                target=self.current().target if self.current() else "",
                action=spell, outcome="Fizzle",
                detail="Song" if song_fizzle else "Spell")
            diagnostic_matched = True
            changed = True
        elif interrupted:
            caster = interrupted.groupdict().get("caster") or "You"
            self._record_spell_outcome(
                timestamp, "Interrupt", "interrupts", caster=caster)
            self._diagnostic(
                timestamp, "Spells", text, actor=self._caster_name(caster),
                target=self.current().target if self.current() else "",
                action=self._last_spell_for(caster) or "Unknown spell",
                outcome="Interrupt")
            diagnostic_matched = True
            changed = True
        elif reflected:
            values = reflected.groupdict()
            self._record_spell_outcome(
                timestamp, "Reflect", "reflects",
                caster=values.get("caster") or "You",
                spell=values.get("spell") or "",
                detail=f"Reflected by {values.get('target') or 'target'}")
            caster = values.get("caster") or "You"
            spell = values.get("spell") or self._last_spell_for(caster)
            self._diagnostic(
                timestamp, "Spells", text, actor=self._caster_name(caster),
                target=values.get("target") or "", action=spell or "Unknown spell",
                outcome="Reflect",
                detail=f"Reflected by {values.get('target') or 'target'}")
            diagnostic_matched = True
            changed = True
        elif blocked:
            values = blocked.groupdict()
            caster = values.get("caster") or "You"
            self._record_spell_outcome(
                timestamp, "Blocked", "blocks", caster=caster,
                detail="Did not take hold")
            self._diagnostic(
                timestamp, "Spells", text, actor=self._caster_name(caster),
                target=values.get("target") or (
                    self.current().target if self.current() else ""),
                action=self._last_spell_for(caster) or "Unknown spell",
                outcome="Blocked", detail="Did not take hold")
            diagnostic_matched = True
            changed = True
        elif resisted:
            values = resisted.groupdict()
            self._record_spell_outcome(
                timestamp, "Resist", "resists", caster="You",
                spell=values.get("spell") or "",
                detail=(f"Resisted by {values.get('target')}"
                         if values.get("target") else "Target resisted"))
            self._diagnostic(
                timestamp, "Spells", text, actor="You",
                target=values.get("target") or (
                    self.current().target if self.current() else ""),
                action=(values.get("spell") or self._last_spell_for("You") or
                        "Unknown spell"), outcome="Resist",
                detail=(f"Resisted by {values.get('target')}"
                        if values.get("target") else "Target resisted"))
            diagnostic_matched = True
            changed = True

        heal = HEAL.match(text)
        if heal:
            values = heal.groupdict()
            self._add_heal(
                timestamp, values["healer"], int(values["amount"]),
                values["target"])
            self._diagnostic(
                timestamp, "Healing", text, actor=values["healer"],
                target=values["target"], amount=int(values["amount"]),
                action="Visible heal", outcome="Success")
            diagnostic_matched = True
            changed = True
        else:
            heal = HEALED_YOU.match(text)
            if heal:
                values = heal.groupdict()
                self._add_heal(
                    timestamp, values["healer"], int(values["amount"]),
                    "You")
                self._diagnostic(
                    timestamp, "Healing", text, actor=values["healer"],
                    target="You", amount=int(values["amount"]),
                    action="Visible heal", outcome="Success")
                diagnostic_matched = True
                changed = True

        killed_target = None
        for pattern in KILLS:
            match = pattern.match(text)
            if match:
                killed_target = match.group("target").strip()
                break
        if killed_target:
            encounter = self.finalize_target(
                killed_target, timestamp, killed=True)
            if encounter:
                encounter.event(
                    timestamp, "Kill", "You", encounter.target)
            changed = True
        if (self.diagnostics_enabled and not diagnostic_matched and
                not (chat or destination_chat) and
                COMBAT_DIAGNOSTIC_HINT.search(text)):
            self._diagnostic(
                timestamp, "Unmatched", text, action="Not classified",
                outcome="Review", detail="Combat-like line was not classified")
        self.expire(timestamp)
        return changed

    def _add_heal(self, timestamp, healer, amount, target="Unknown"):
        healer = "You" if healer.casefold() == "you" else healer
        self.session_healers.setdefault(
            healer, HealStats(healer)).add(amount, target)
        encounter = self._current_for_non_damage()
        if encounter:
            encounter.last_at = max(encounter.last_at, timestamp)
            encounter.healers.setdefault(
                healer, HealStats(healer)).add(amount, target)
            encounter.event(
                timestamp, "Heal", healer, target, amount, "Visible heal")

    def finalize_target(self, target, timestamp, killed=False):
        folded = target.casefold()
        candidates = [
            key for key in self.active
            if key == folded or folded in key or key in folded]
        if not candidates:
            return None
        key = max(candidates, key=lambda candidate: self.active[candidate].last_at)
        encounter = self.active.pop(key)
        encounter.last_at = max(encounter.last_at, timestamp)
        encounter.killed = killed
        self._completed_undo.clear()
        self.completed.appendleft(encounter)
        return encounter

    def expire(self, now):
        stale = [
            key for key, encounter in self.active.items()
            if (now - encounter.last_at).total_seconds() > self.timeout]
        if stale:
            self._completed_undo.clear()
        for key in stale:
            self.completed.appendleft(self.active.pop(key))

    def current(self):
        if not self.active:
            return None
        return max(self.active.values(), key=lambda encounter: encounter.last_at)

    def last(self):
        return self.completed[0] if self.completed else None

    def combine(self, encounters, name="Selected fights"):
        encounters = [encounter for encounter in encounters if encounter]
        if not encounters:
            return None
        combined = Encounter(
            name,
            min(encounter.started_at for encounter in encounters),
            max(encounter.last_at for encounter in encounters),
            zone=(
                next(iter({encounter.zone for encounter in encounters}))
                if len({encounter.zone for encounter in encounters}) == 1
                else "Multiple zones"),
            killed=all(encounter.killed for encounter in encounters))
        for encounter in encounters:
            for player, stats in encounter.attackers.items():
                combined.attackers.setdefault(
                    player, AttackerStats(player)).merge(stats)
            for player, stats in encounter.tanks.items():
                combined.tanks.setdefault(player, TankStats(player)).merge(stats)
            for spell, stats in encounter.spells.items():
                combined.spells.setdefault(spell, SpellStats(spell)).merge(stats)
            for caster, caster_spells in encounter.caster_spells.items():
                for spell, stats in caster_spells.items():
                    self._caster_spell(
                        combined.caster_spells, caster, spell).merge(stats)
            combined.spell_casts.extend(encounter.spell_casts)
            for healer, stats in encounter.healers.items():
                combined.healers.setdefault(healer, HealStats(healer)).merge(stats)
            combined.events.extend(encounter.events)
        combined.events = deque(
            sorted(combined.events, key=lambda event: event.timestamp)[-5000:],
            maxlen=5000)
        combined.spell_casts = deque(
            sorted(
                combined.spell_casts,
                key=lambda event: event.timestamp)[-5000:],
            maxlen=5000)
        return combined

    def _checkpoint_completed(self):
        self._completed_undo.append([
            (encounter, encounter.target) for encounter in self.completed])

    @property
    def can_undo_completed_change(self):
        return bool(self._completed_undo)

    def combine_completed(self, indices, name="", by_target=False):
        """Combine selected completed fights and retain one-step-safe history."""
        completed = list(self.completed)
        indices = sorted({
            int(index) for index in indices
            if isinstance(index, int) and 0 <= index < len(completed)})
        if len(indices) < 2:
            return []
        selected = [completed[index] for index in indices]
        groups = []
        if by_target:
            grouped = {}
            for encounter in selected:
                grouped.setdefault(encounter.target.casefold(), []).append(encounter)
            groups = [values for values in grouped.values() if len(values) >= 2]
            if not groups:
                return []
        else:
            groups = [selected]
        removed = {id(encounter) for group in groups for encounter in group}
        combined = []
        for group in groups:
            label = (
                f"{group[0].target} · {len(group)} fights"
                if by_target else str(name or f"Combined · {len(group)} fights"))
            combined.append(self.combine(group, label))
        self._checkpoint_completed()
        rebuilt = [
            encounter for encounter in completed if id(encounter) not in removed]
        rebuilt.extend(combined)
        rebuilt.sort(key=lambda encounter: encounter.last_at, reverse=True)
        self.completed = deque(rebuilt, maxlen=self.completed.maxlen)
        return combined

    def rename_completed(self, index, name):
        """Rename one completed fight without changing its parsed data."""
        completed = list(self.completed)
        if not isinstance(index, int) or not 0 <= index < len(completed):
            return False
        name = str(name or '').strip()[:120]
        if not name or completed[index].target == name:
            return False
        self._checkpoint_completed()
        completed[index].target = name
        return True

    def undo_completed_change(self):
        """Undo the most recent manual combine or rename operation."""
        if not self._completed_undo:
            return False
        snapshot = self._completed_undo.pop()
        for encounter, target in snapshot:
            encounter.target = target
        self.completed = deque(
            (encounter for encounter, _target in snapshot),
            maxlen=self.completed.maxlen)
        return True

    def session(self):
        encounters = list(self.completed) + list(self.active.values())
        if not encounters and not any((
                self.session_attackers, self.session_spells,
                self.session_healers, self.session_tanks)):
            return None
        now = datetime.datetime.now()
        started = min(
            (encounter.started_at for encounter in encounters), default=now)
        ended = max((encounter.last_at for encounter in encounters), default=now)
        zones = {encounter.zone for encounter in encounters if encounter.zone}
        session = Encounter(
            "Session", started, ended,
            zone=next(iter(zones)) if len(zones) == 1 else
            "Multiple zones" if zones else "")
        for name, stats in self.session_attackers.items():
            session.attackers.setdefault(name, AttackerStats(name)).merge(stats)
        for name, stats in self.session_tanks.items():
            session.tanks.setdefault(name, TankStats(name)).merge(stats)
        for name, stats in self.session_spells.items():
            session.spells.setdefault(name, SpellStats(name)).merge(stats)
        for caster, caster_spells in self.session_caster_spells.items():
            for spell, stats in caster_spells.items():
                self._caster_spell(
                    session.caster_spells, caster, spell).merge(stats)
        session.spell_casts.extend(self.session_spell_casts)
        for name, stats in self.session_healers.items():
            session.healers.setdefault(name, HealStats(name)).merge(stats)
        for encounter in sorted(encounters, key=lambda value: value.started_at):
            session.events.extend(encounter.events)
        return session

    def reset_session(self, include_activity=True):
        self.active.clear()
        self.completed.clear()
        self._completed_undo.clear()
        self.session_attackers.clear()
        self.session_tanks.clear()
        self.session_spells.clear()
        self.session_caster_spells.clear()
        self.session_spell_casts.clear()
        self.session_healers.clear()
        if include_activity:
            self.chat.clear()
            self.loot.clear()
            self.coins.clear()
            self.faction.clear()
            self.randoms.clear()
        self._last_spell = ""
        self._last_spells.clear()
        self._pending_criticals.clear()
        self._pending_random = None
        self.current_zone = ""


def session_duration(encounters):
    encounters = list(encounters)
    if not encounters:
        return 1.0
    return max(
        1.0,
        max(e.last_at for e in encounters).timestamp() -
        min(e.started_at for e in encounters).timestamp())
