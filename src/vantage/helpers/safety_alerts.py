"""Bounded, read-only AFK attack and death-loop detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import datetime
import re


ATTACK_VERBS = (
    r"hit|slash|pierce|crush|claw|bite|sting|maul|gore|punch|kick|"
    r"backstab|bash|slice|strike"
)
INCOMING_HIT_RX = re.compile(
    rf"^(?P<attacker>[\w`' .-]+?) "
    rf"(?:hits|slashes|pierces|crushes|claws|bites|stings|mauls|gores|"
    rf"punches|kicks|backstabs|bashes|slices|strikes) "
    rf"(?:You|YOU) for \d+ points? of damage\.$", re.IGNORECASE)
INCOMING_MISS_RX = re.compile(
    rf"^(?P<attacker>[\w`' .-]+?) tries to (?:{ATTACK_VERBS}) "
    rf"(?:You|YOU), but .+$", re.IGNORECASE)
OUTGOING_MELEE_RX = re.compile(
    rf"^You (?:(?:{ATTACK_VERBS}) |try to (?:{ATTACK_VERBS}) )",
    re.IGNORECASE)
OUTGOING_NON_MELEE_RX = re.compile(
    r"^.+? was hit by non-melee for \d+ points? of damage\.$",
    re.IGNORECASE)
OUTGOING_CAST_RX = re.compile(
    r"^You begin casting .+?\.$", re.IGNORECASE)
OUTGOING_COMMS_RX = re.compile(
    r"^You (?:tell|tells|told|say|says|auction|auctions|shout|shouts|"
    r"ooc|oocs)\b", re.IGNORECASE)
PLAYER_DEATH_RX = re.compile(
    r"^(?:You have been slain by .+?[!.]?|You died\.)$", re.IGNORECASE)


@dataclass(frozen=True)
class SafetyAlert:
    kind: str
    message: str
    attacker: str = ""
    death_count: int = 0


class SafetyAlertState:
    """Replicates EQTool's local safety rules without controlling the game."""

    def __init__(self, death_threshold=4, window_seconds=120,
                 attack_cooldown_seconds=5):
        self.deaths = deque(maxlen=20)
        self.last_attack_alert = None
        self.attack_cooldown_seconds = max(
            1, int(attack_cooldown_seconds))
        self.configure(death_threshold, window_seconds)

    def configure(self, death_threshold=4, window_seconds=120):
        self.death_threshold = max(2, min(20, int(death_threshold)))
        self.window_seconds = max(30, min(600, int(window_seconds)))
        return self

    @staticmethod
    def _timestamp(value):
        return value if isinstance(value, datetime.datetime) else \
            datetime.datetime.now()

    def _prune(self, timestamp):
        while (self.deaths and
               (timestamp - self.deaths[0]).total_seconds() >
               self.window_seconds):
            self.deaths.popleft()

    def ingest(self, timestamp, text, game_focused=False):
        timestamp = self._timestamp(timestamp)
        line = str(text or "").strip()
        self._prune(timestamp)
        alerts = []

        incoming = INCOMING_HIT_RX.match(line) or INCOMING_MISS_RX.match(line)
        if incoming and incoming.group("attacker").casefold() != "you":
            elapsed = (
                float("inf") if self.last_attack_alert is None else
                (timestamp - self.last_attack_alert).total_seconds())
            if not game_focused and elapsed >= self.attack_cooldown_seconds:
                attacker = incoming.group("attacker").strip() or "something"
                self.last_attack_alert = timestamp
                alerts.append(SafetyAlert(
                    "afk_attacked",
                    f"AFK · You are being attacked by {attacker}",
                    attacker=attacker))

        if (OUTGOING_MELEE_RX.match(line) or
                OUTGOING_NON_MELEE_RX.match(line) or
                OUTGOING_CAST_RX.match(line) or
                OUTGOING_COMMS_RX.match(line)):
            self.deaths.clear()

        if PLAYER_DEATH_RX.match(line):
            self.deaths.append(timestamp)
            if len(self.deaths) >= self.death_threshold:
                alerts.append(SafetyAlert(
                    "death_loop",
                    f"DEATH LOOP · {len(self.deaths)} deaths in "
                    f"{self.window_seconds} seconds with no player activity",
                    death_count=len(self.deaths)))
        return tuple(alerts)

