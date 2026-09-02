"""Bounded, log-authoritative EverQuest character and pet context.

The recognizers mirror the exact local-log handlers studied in EQTool.  No
process memory, server API, window input, or guessed character data is used.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import re

from vantage.helpers.spell_catalog import p99_unique_spell_profiles


LEVEL_GAIN = re.compile(
    r"^You have gained a level! Welcome to level (?P<level>\d+)!?$",
    re.IGNORECASE)
YOU_CAST = re.compile(
    r"^You begin casting (?P<spell>.+?)\.$", re.IGNORECASE)
YOU_MEMORIZED = re.compile(
    r"^You have finished memorizing (?P<spell>.+?)\.$", re.IGNORECASE)
YOU_FORGET = re.compile(
    r"^You forget (?P<spell>.+?)\.$", re.IGNORECASE)
YOU_JOIN = re.compile(
    r"^You notify (?P<leader>[\w`' -]+) that you agree to join the group\.$",
    re.IGNORECASE)
YOU_INVITE = re.compile(
    r"^You invite [\w`' -]+ to join your group\.$", re.IGNORECASE)
LEADER_CHANGED = re.compile(
    r"^(?P<leader>[\w`' -]+) (?:is|are) now the leader of your group\.$",
    re.IGNORECASE)
ZONE_ENTERED = re.compile(
    r"^You have entered (?P<zone>.+?)\.$", re.IGNORECASE)

PET_CREATION = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'At your service Master\.'$",
    re.IGNORECASE)
PET_RECLAIMED = re.compile(
    r"^(?P<pet>[\w`' -]+) disperses\.$", re.IGNORECASE)
PET_LEADER = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'My leader is "
    r"(?P<leader>[\w`' -]+)\.'$", re.IGNORECASE)
PET_DEATH = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'Sorry to have failed you, "
    r"oh Great One\.'$", re.IGNORECASE)
PET_GET_LOST = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'As you wish, oh great one\.'$",
    re.IGNORECASE)
PET_ATTACK = re.compile(
    r"^(?P<pet>[\w`' -]+) tells you, 'Attacking .+? Master\.'$",
    re.IGNORECASE)
PET_FOLLOW = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'Following you, Master\.'$",
    re.IGNORECASE)
PET_POSITION = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? 'Changing position, Master\.'$",
    re.IGNORECASE)
PET_GUARD = re.compile(
    r"^(?P<pet>[\w`' -]+) says,? "
    r"'Guarding with my life\.\.oh splendid one\.'$", re.IGNORECASE)

PET_SUMMON_SPELLS = frozenset(name.casefold() for name in (
    "Cavorting Bones", "Leering Corpse", "Bone Walk", "Convoke Shadow",
    "Restless Bones", "Animate Dead", "Haunting Corpse", "Summon Dead",
    "Invoke Shadow", "Malignant Dead", "Cackling Bones", "Invoke Death",
    "Minion of Shadows", "Servant of Bones", "Emissary of Thule",
    "Companion Spirit", "Vigilant Spirit", "Guardian Spirit",
    "Frenzied Spirit", "Spirit of the Howler", "Pendril's Animation",
    "Juli`s Animation", "Mircyl's Animation", "Kilan`s Animation",
    "Shalee`s Animation", "Sisna`s Animation", "Sagar`s Animation",
    "Uleen`s Animation", "Boltran`s Animation", "Aanya's Animation",
    "Yegoreff`s Animation", "Kintaz`s Animation", "Zumaik`s Animation",
    "Vocarate: Earth", "Vocarate: Fire", "Vocarate: Air",
    "Vocarate: Water", "Dyzil's Deafening Decoy",
    "Greater Vocaration: Earth", "Greater Vocaration: Fire",
    "Greater Vocaration: Air", "Greater Vocaration: Water",
    "Monster Summoning I", "Monster Summoning II", "Monster Summoning III",
    "Manifest Elements",
)) | frozenset(
    f"{base}: {element}".casefold()
    for base in (
        "Elementalkin", "Elementaling", "Elemental", "Minor Summoning",
        "Lesser Summoning", "Summoning", "Greater Summoning",
        "Minor Conjuration", "Lesser Conjuration", "Conjuration",
        "Greater Conjuration")
    for element in ("Air", "Earth", "Fire", "Water"))


@dataclass
class CharacterContext:
    character: str = ""
    server: str = ""
    level: int = 0
    player_class: str = ""
    group_leader: str = ""
    pet_name: str = ""
    pet_state: str = ""
    pet_spell: str = ""
    zone: str = ""
    saved_you_spells: list = field(default_factory=list)
    source: str = "Local EQ log"
    revision: int = 0
    _pending_pet_spell: str = field(default="", repr=False, compare=False)

    def portable_dict(self):
        values = asdict(self)
        values.pop("_pending_pet_spell", None)
        return values


class CharacterContextTracker:
    """Track at most a small number of log profiles for long sessions."""

    def __init__(self, saved=None, max_profiles=32):
        self.max_profiles = max(1, int(max_profiles))
        self._profiles = OrderedDict()
        for key, values in list((saved or {}).items())[-self.max_profiles:]:
            if not isinstance(values, dict):
                continue
            context = CharacterContext(
                character=str(values.get("character") or "")[:64],
                server=str(values.get("server") or "")[:64],
                level=max(0, min(65, self._safe_int(
                    values.get("level"), 0))),
                player_class=str(values.get("player_class") or "")[:32],
                group_leader=str(values.get("group_leader") or "")[:64],
                pet_name=str(values.get("pet_name") or "")[:64],
                pet_state=str(values.get("pet_state") or "")[:32],
                pet_spell=str(values.get("pet_spell") or "")[:96],
                zone=str(values.get("zone") or "")[:96],
                saved_you_spells=self._normalize_saved_you_spells(
                    values.get("saved_you_spells", [])),
                revision=max(0, self._safe_int(
                    values.get("revision"), 0)),
            )
            self._profiles[str(key)] = context

    @staticmethod
    def _safe_int(value, fallback):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @classmethod
    def _normalize_saved_you_spells(cls, value):
        if not isinstance(value, list):
            return []
        normalized = []
        for item in value[:128]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:96]
            seconds = max(0, min(
                7 * 24 * 60 * 60,
                cls._safe_int(item.get("seconds"), 0)))
            if name and seconds:
                normalized.append({"name": name, "seconds": seconds})
        return normalized

    @staticmethod
    def profile_key(character, server):
        return f"{str(server or '').strip().casefold()}|{str(character or '').strip().casefold()}"

    def context(self, character, server=""):
        key = self.profile_key(character, server)
        context = self._profiles.get(key)
        if context is None:
            context = CharacterContext(
                character=str(character or "").strip()[:64],
                server=str(server or "").strip()[:64])
            self._profiles[key] = context
            while len(self._profiles) > self.max_profiles:
                self._profiles.popitem(last=False)
        else:
            self._profiles.move_to_end(key)
        return context

    @staticmethod
    def _change(context, **values):
        changed = False
        for key, value in values.items():
            if getattr(context, key) != value:
                setattr(context, key, value)
                changed = True
        if changed:
            context.revision += 1
        return changed

    def set_level(self, character, server, level):
        context = self.context(character, server)
        level = max(1, min(65, int(level)))
        return context, self._change(context, level=level)

    def store_you_spells_if_empty(self, character, server, spells):
        """Mirror EQTool: preserve a camp snapshot only when none is pending."""
        context = self.context(character, server)
        if context.saved_you_spells:
            return context, False
        saved = self._normalize_saved_you_spells(spells)
        return context, self._change(context, saved_you_spells=saved)

    def take_saved_you_spells(self, character, server):
        """Return and clear the one-shot camp snapshot restored at welcome."""
        context = self.context(character, server)
        saved = [dict(item) for item in context.saved_you_spells]
        changed = self._change(context, saved_you_spells=[])
        return context, saved, changed

    def ingest(self, character, server, text):
        context = self.context(character, server)
        line = str(text or "").strip()
        changed = False

        level = LEVEL_GAIN.match(line)
        if level:
            value = max(1, min(65, int(level.group("level"))))
            if value > context.level:
                changed = self._change(context, level=value) or changed

        spell_match = (
            YOU_CAST.match(line) or YOU_MEMORIZED.match(line) or
            YOU_FORGET.match(line))
        if spell_match:
            spell = spell_match.group("spell").strip()
            profile = p99_unique_spell_profiles().get(spell.casefold())
            values = {}
            if profile:
                player_class, required_level = profile
                if not context.player_class:
                    values["player_class"] = player_class
                if required_level > context.level:
                    values["level"] = required_level
            if values:
                changed = self._change(context, **values) or changed
            if YOU_CAST.match(line) and spell.casefold() in PET_SUMMON_SPELLS:
                context._pending_pet_spell = spell
                changed = self._change(
                    context, pet_spell=spell, pet_state="Summoning") or changed

        if (not context.player_class and
                re.match(r"^You backstabs? .+", line, re.IGNORECASE)):
            changed = self._change(context, player_class="Rogue") or changed
        if (not context.player_class and line in {
                "You mend your wounds and heal some damage.",
                "You have failed to mend your wounds."}):
            changed = self._change(context, player_class="Monk") or changed

        join = YOU_JOIN.match(line)
        leader = LEADER_CHANGED.match(line)
        if join:
            changed = self._change(
                context, group_leader=join.group("leader").strip()) or changed
        elif YOU_INVITE.match(line):
            changed = self._change(context, group_leader="You") or changed
        elif leader:
            changed = self._change(
                context, group_leader=leader.group("leader").strip()) or changed
        elif line in {
                "Your group has been disbanded.",
                "You have been removed from the group."}:
            changed = self._change(context, group_leader="") or changed

        zone = ZONE_ENTERED.match(line)
        if zone:
            new_zone = zone.group("zone").strip()
            if new_zone.casefold() != context.zone.casefold():
                context._pending_pet_spell = ""
                changed = self._change(
                    context, zone=new_zone, pet_name="", pet_state="",
                    pet_spell="") or changed

        creation = PET_CREATION.match(line)
        reclaimed = PET_RECLAIMED.match(line)
        pet_leader = PET_LEADER.match(line)
        pet_death = PET_DEATH.match(line)
        pet_lost = PET_GET_LOST.match(line)
        pet_attack = PET_ATTACK.match(line)
        pet_follow = PET_FOLLOW.match(line)
        pet_position = PET_POSITION.match(line)
        pet_guard = PET_GUARD.match(line)
        if creation and context._pending_pet_spell:
            context._pending_pet_spell = ""
            changed = self._change(
                context, pet_name=creation.group("pet").strip(),
                pet_state="Active") or changed
        elif pet_leader:
            owner = pet_leader.group("leader").strip()
            if (not context.character or owner.casefold() in {
                    "you", context.character.casefold()}):
                changed = self._change(
                    context, pet_name=pet_leader.group("pet").strip(),
                    pet_state="Active") or changed
        elif pet_attack:
            changed = self._change(
                context, pet_name=pet_attack.group("pet").strip(),
                pet_state="Attacking") or changed
        elif pet_follow and self._same_pet(context, pet_follow):
            changed = self._change(context, pet_state="Following") or changed
        elif pet_position and self._same_pet(context, pet_position):
            changed = self._change(context, pet_state="Position changed") or changed
        elif pet_guard and self._same_pet(context, pet_guard):
            changed = self._change(context, pet_state="Guarding") or changed
        elif ((reclaimed and self._same_pet(context, reclaimed)) or
              (pet_death and self._same_pet(context, pet_death)) or
              (pet_lost and self._same_pet(context, pet_lost))):
            context._pending_pet_spell = ""
            changed = self._change(
                context, pet_name="", pet_state="", pet_spell="") or changed

        if line in {
                "You don't have a pet to command!",
                "Your charm spell has worn off.",
                "LOADING, PLEASE WAIT..."} or line.startswith(
                    "You have been slain by"):
            context._pending_pet_spell = ""
            changed = self._change(
                context, pet_name="", pet_state="", pet_spell="") or changed
        if line == "Welcome to EverQuest!":
            context._pending_pet_spell = ""
            changed = self._change(
                context, group_leader="", pet_name="", pet_state="",
                pet_spell="") or changed

        return context, changed

    @staticmethod
    def _same_pet(context, match):
        return bool(
            context.pet_name and
            context.pet_name.casefold() == match.group("pet").strip().casefold())

    def snapshot(self):
        return {
            key: context.portable_dict()
            for key, context in self._profiles.items()
        }
