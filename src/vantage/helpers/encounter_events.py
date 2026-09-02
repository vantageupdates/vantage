"""Exact local-log encounter events studied from the EQTool workflow."""

from __future__ import annotations

from dataclasses import dataclass
import re


RING_WAR_START = "Seneschal Aldikar shouts, TROOPS, TAKE YOUR POSITIONS!"
RING_WAR_SCHEDULE_SOURCE = "Vantage · Ring War schedule"
QUAKE_LINES = frozenset({
    "You feel you should get somewhere safe as soon as possible.",
    "The gods have awoken to unleash their wrath across Norrath.",
    (
        "An unsettling silence smothers the land. Not a complete silence, "
        "but somehow quieter for it, the way a thick blanket of snow muffles "
        "the noise of the world. The chill of it pierces your bones, and you "
        "know, danger approaches."
    ),
    "You feel the need to get somewhere safe quickly.",
})
FTE_RX = re.compile(
    r"^(?P<npc>.+?) engages (?P<player>[^!]+)!$", re.IGNORECASE)


@dataclass(frozen=True)
class EncounterEvent:
    kind: str
    message: str
    player: str = ""
    npc: str = ""


@dataclass(frozen=True)
class RingWarMilestone:
    wave: int
    label: str
    seconds: int
    is_break: bool = False

    @property
    def timer_name(self):
        return f"Ring War · Wave {self.wave} · {self.label}"


def parse_encounter_event(text):
    """Return only an exact FTE, quake, or Ring War log event."""
    line = str(text or "").strip()
    if line == RING_WAR_START:
        return EncounterEvent("ring_war", "Ring War · troops take positions")
    if line in QUAKE_LINES:
        return EncounterEvent("quake", "Server quake detected from the EQ log")
    match = FTE_RX.match(line)
    if match:
        player = match.group("player").strip()
        npc = match.group("npc").strip()
        return EncounterEvent(
            "fte", f"{player} FTE {npc}", player=player, npc=npc)
    return None


def ring_war_milestones():
    """Return the exact cumulative 3×7 wave schedule used by EQTool."""
    elapsed = 0
    milestones = []
    for wave in range(1, 4):
        for round_number in range(1, 8):
            elapsed += 210
            milestones.append(RingWarMilestone(
                wave, f"Round {round_number}", elapsed))
        elapsed += 300
        if wave == 3:
            elapsed += 9
        milestones.append(RingWarMilestone(
            wave, "Break", elapsed, is_break=True))
    return tuple(milestones)

