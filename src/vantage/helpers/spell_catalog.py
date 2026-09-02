"""Small, cached P99 spell-class lookup for combat presentation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from vantage.helpers import resource_path


# spells_us.txt columns 104-117 are the fourteen classes available on P99.
# A value of 255 means that class cannot learn the spell.
P99_CLASS_COLUMNS = (
    (104, "Warrior"),
    (105, "Cleric"),
    (106, "Paladin"),
    (107, "Ranger"),
    (108, "Shadow Knight"),
    (109, "Druid"),
    (110, "Monk"),
    (111, "Bard"),
    (112, "Rogue"),
    (113, "Shaman"),
    (114, "Necromancer"),
    (115, "Wizard"),
    (116, "Magician"),
    (117, "Enchanter"),
)

P99_SPELL_CLASSES = (
    "Bard", "Cleric", "Druid", "Enchanter", "Magician",
    "Necromancer", "Paladin", "Ranger", "Shadow Knight", "Shaman",
    "Wizard",
)


@dataclass(frozen=True)
class P99SpellEntry:
    """Small immutable row derived from the bundled classic spell data."""

    spell_id: int
    name: str
    class_levels: tuple
    icon_id: int = 0
    cast_message: str = ""
    fade_message: str = ""
    mana: int = 0
    cast_time_ms: int = 0

    def level_for(self, class_name):
        target = str(class_name or "").casefold()
        return next((
            level for name, level in self.class_levels
            if name.casefold() == target), 0)

    @property
    def classes_text(self):
        return ", ".join(name for name, _level in self.class_levels)

    @property
    def levels_text(self):
        return ", ".join(
            f"{name} {level}" for name, level in self.class_levels)

    @property
    def effect_hint(self):
        """Compact factual fallback while the Wiki description loads."""
        messages = [
            " ".join(str(value or "").split())
            for value in (self.cast_message, self.fade_message)
            if str(value or "").strip()]
        mechanics = []
        if self.mana > 0:
            mechanics.append(f"Mana {self.mana}")
        if self.cast_time_ms > 0:
            mechanics.append(f"Cast {self.cast_time_ms / 1000:g}s")
        if mechanics:
            messages.append(" · ".join(mechanics))
        return " ".join(messages)


@lru_cache(maxsize=2)
def p99_spell_entries(path=""):
    """Return every player spell with exact bundled class/level metadata."""
    source = Path(path) if path else Path(resource_path(
        "data/spells/spells_us.txt"))
    by_name = {}
    try:
        lines = source.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return tuple()
    with lines:
        for line in lines:
            values = line.rstrip("\r\n").split("^")
            if len(values) <= max(P99_CLASS_COLUMNS[-1][0], 144):
                continue
            name = values[1].strip()
            if not name:
                continue
            profiles = []
            for column, class_name in P99_CLASS_COLUMNS:
                if class_name not in P99_SPELL_CLASSES:
                    continue
                try:
                    level = int(values[column])
                except (TypeError, ValueError):
                    continue
                if 1 <= level <= 60:
                    profiles.append((class_name, level))
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
            cast_message = values[6].strip()
            fade_message = values[8].strip()
            try:
                mana = int(values[19])
            except (TypeError, ValueError):
                mana = 0
            try:
                cast_time_ms = int(values[13])
            except (TypeError, ValueError):
                cast_time_ms = 0
            key = name.casefold()
            current = by_name.get(key)
            if current:
                merged = {
                    class_name: level
                    for class_name, level in current.class_levels}
                for class_name, level in profiles:
                    merged[class_name] = min(level, merged.get(class_name, level))
                profiles = sorted(
                    merged.items(),
                    key=lambda item: P99_SPELL_CLASSES.index(item[0]))
                spell_id = current.spell_id or spell_id
                icon_id = current.icon_id or icon_id
                cast_message = current.cast_message or cast_message
                fade_message = current.fade_message or fade_message
                mana = current.mana or mana
                cast_time_ms = current.cast_time_ms or cast_time_ms
            by_name[key] = P99SpellEntry(
                spell_id, name, tuple(profiles), icon_id,
                cast_message, fade_message, mana, cast_time_ms)
    return tuple(sorted(by_name.values(), key=lambda entry: entry.name.casefold()))


@lru_cache(maxsize=1)
def p99_unique_spell_profiles(path=""):
    """Return unambiguous ``spell -> (class, required level)`` evidence."""
    source = Path(path) if path else Path(resource_path(
        "data/spells/spells_us.txt"))
    result = {}
    try:
        lines = source.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return result
    with lines:
        for line in lines:
            values = line.rstrip("\r\n").split("^")
            if len(values) <= P99_CLASS_COLUMNS[-1][0]:
                continue
            spell = values[1].strip()
            if not spell:
                continue
            candidates = []
            for column, class_name in P99_CLASS_COLUMNS:
                try:
                    level = int(values[column])
                except (TypeError, ValueError):
                    continue
                if 1 <= level <= 60:
                    candidates.append((class_name, level))
            if len(candidates) == 1:
                result[spell.casefold()] = candidates[0]
    return result


@lru_cache(maxsize=1)
def p99_unique_spell_classes(path=""):
    """Return only class identifications supported unambiguously by data."""
    return {
        spell: profile[0]
        for spell, profile in p99_unique_spell_profiles(path).items()
    }


def infer_p99_class(spell_names, path=""):
    """Infer one caster class only when observed unique spells agree."""
    lookup = p99_unique_spell_classes(path)
    candidates = {
        lookup[name.casefold()]
        for name in spell_names
        if str(name).casefold() in lookup
    }
    return next(iter(candidates)) if len(candidates) == 1 else "—"
