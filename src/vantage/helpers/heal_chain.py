"""Event-driven Complete Heal chain tracking for classic EverQuest logs."""

from collections import defaultdict, deque
from dataclasses import dataclass
import datetime
import re


CHAT = re.compile(
    r"^(?P<speaker>.+?) (?:tells? (?:you|the group|the guild|the raid|"
    r"your party|your group|your guild|your raid)|says?(?: out of character)?|"
    r"auctions?|shouts?|oocs?),? '(?P<message>.*)'$", re.IGNORECASE)
INTERVAL_COMMAND = re.compile(r"!KI\s*([1-9])", re.IGNORECASE)
OTHER_INTERRUPTED = re.compile(
    r"^(?P<cleric>.+?)'s casting is interrupted!$", re.IGNORECASE)
DEFAULT_FORMAT = "### - CH - tankname"
_TANK = r"[A-Za-z][A-Za-z'`-]{0,31}(?:\s+[A-Za-z][A-Za-z'`-]{0,31}){0,3}"
_MARKER = r"[A-Za-z0-9]{1,6}"
_TAG = r"(?:[A-Za-z][A-Za-z0-9]{0,7}\s+)?"
# Ordered call shapes, not a broad search for the word CH. Custom templates
# remain strict filters. These formats also support named pets as heal targets.
_COMMON_CALLS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    rf"^{_TAG}(?P<marker>{_MARKER})\s+(?:-+\s*)?R?CH[\s<>-]+"
    rf"(?P<tank>{_TANK}?)(?:\s*(?:[<>-]\s*)+(?P=marker)?)?\s*$",
    rf"^{_TAG}RCH\s+(?P<marker>{_MARKER})\s+(?:CH\s+)?[-<>]+\s*"
    rf"(?P<tank>{_TANK})\s*$",
    rf"^CH\s*[-<>]+\s*(?P<tank>{_TANK}?)\s*[-<>]+\s*"
    rf"(?P<marker>{_MARKER})\s*$",
))


@dataclass
class HealChainCast:
    started_at: datetime.datetime
    cleric: str
    marker: str
    tank: str
    interrupted: bool = False

    def elapsed(self, now):
        return max(0.0, (now - self.started_at).total_seconds())

    def remaining(self, now, cast_seconds):
        return max(0.0, float(cast_seconds) - self.elapsed(now))


class HealChainTracker:
    """Parse CH hotkeys without changing, duplicating, or replaying EQ logs."""

    def __init__(self, hotkey_format="### - CH - tankname", interval=3,
                 cast_seconds=10):
        self.hotkey_format = hotkey_format
        self.interval = interval
        self.cast_seconds = cast_seconds
        self.casts = deque(maxlen=500)
        self.rosters = defaultdict(list)
        self.cycle_last = {}
        self.local_marker = ""
        self.revision = 0
        self._announcement = None
        self.configure(hotkey_format, interval, cast_seconds)

    def configure(self, hotkey_format=None, interval=None, cast_seconds=None):
        if hotkey_format is not None and hotkey_format != self.hotkey_format:
            self.hotkey_format = str(hotkey_format)
            self._announcement = None
        if interval is not None:
            self.interval = max(1, min(9, int(interval)))
        if cast_seconds is not None:
            self.cast_seconds = max(1, min(20, int(cast_seconds)))

    def _announcement_regex(self):
        if self._announcement is not None:
            return self._announcement
        template = self.hotkey_format.strip()
        if template.count("###") != 1 or template.casefold().count("tankname") != 1:
            template = DEFAULT_FORMAT
        parts = re.split(r"(###|tankname)", template, flags=re.IGNORECASE)
        pattern = []
        for part in parts:
            if part == "###":
                pattern.append(rf"(?P<marker>{_MARKER})")
            elif part.casefold() == "tankname":
                pattern.append(rf"(?P<tank>{_TANK})")
            else:
                escaped = re.escape(part)
                pattern.append(escaped.replace(r"\ ", r"\s*"))
        self._announcement = re.compile(
            r"^\s*" + "".join(pattern) + r"\s*$", re.IGNORECASE)
        return self._announcement

    def _match_announcement(self, message):
        matched = self._announcement_regex().fullmatch(message)
        if matched is not None or self.hotkey_format.strip() != DEFAULT_FORMAT:
            return matched
        for pattern in _COMMON_CALLS:
            matched = pattern.fullmatch(message.strip())
            if matched is None:
                continue
            marker = matched.group("marker").upper()
            if (marker.isdecimal() or len(set(marker)) == 1 or
                    marker in ("R11", "R22") or
                    re.fullmatch(r"RAMP\d{1,2}", marker)):
                return matched
        return None

    @staticmethod
    def _increment_marker(marker):
        marker = marker.upper()
        if marker == "R11":
            return "R22"
        if marker == "R22":
            return "R11"
        if marker and len(set(marker)) == 1:
            char = marker[0]
            if "A" <= char <= "Z":
                next_char = "A" if char == "Z" else chr(ord(char) + 1)
            elif "0" <= char <= "9":
                next_char = "0" if char == "9" else str(int(char) + 1)
            else:
                return ""
            return next_char * len(marker)
        if marker.isdecimal():
            return str((int(marker) + 1) % (10 ** len(marker))).zfill(len(marker))
        return ""

    def next_marker(self, tank, current_marker):
        current = current_marker.upper()
        markers = sorted(set(self.rosters.get(tank, [])))
        if markers and current == self.cycle_last.get(tank):
            return markers[0]
        return self._increment_marker(current)

    def next_cleric(self, tank, current_marker):
        """Resolve the predicted marker only from an observed call on this tank."""
        marker = self.next_marker(tank, current_marker)
        return next((cast.cleric for cast in reversed(self.casts)
                     if cast.tank == tank and cast.marker == marker), "")

    def active(self, now=None):
        now = now or datetime.datetime.now()
        return [cast for cast in self.casts
                if cast.remaining(now, self.cast_seconds) > 0]

    def clear(self):
        self.casts.clear()
        self.rosters.clear()
        self.cycle_last.clear()
        self.local_marker = ""
        self.revision += 1

    def _interrupt(self, cleric, timestamp):
        for cast in reversed(self.casts):
            if (not cast.interrupted and
                    0 <= (timestamp - cast.started_at).total_seconds() < self.cast_seconds and
                    cast.cleric.casefold() == cleric.casefold()):
                cast.interrupted = True
                self.revision += 1
                return cast
        return None

    def ingest(self, timestamp, text):
        """Return `(event_name, payload)` when a chain event is recognized."""
        text = text.strip()
        chat = CHAT.fullmatch(text)
        interval = INTERVAL_COMMAND.fullmatch(
            (chat.group("message") if chat else text).strip())
        if interval:
            self.interval = int(interval.group(1))
            self.revision += 1
            return "interval", self.interval

        if text.casefold().rstrip(".") == "clearcch is not online at this time":
            self.clear()
            return "clear", None

        if text.casefold() == "your spell is interrupted.":
            cast = self._interrupt("You", timestamp)
            return ("interrupt", cast) if cast else None
        interrupted = OTHER_INTERRUPTED.match(text)
        if interrupted:
            cast = self._interrupt(interrupted.group("cleric"), timestamp)
            return ("interrupt", cast) if cast else None

        if not chat:
            return None
        announcement = self._match_announcement(chat.group("message"))
        if not announcement:
            return None
        marker = announcement.group("marker").upper()
        tank = announcement.group("tank").strip()
        cleric = chat.group("speaker").strip()
        cast = HealChainCast(timestamp, cleric, marker, tank)
        self.casts.append(cast)
        roster = self.rosters[tank]
        if marker in roster and len(roster) > 1 and marker == sorted(roster)[0]:
            # The first order appearing again reveals where the previous
            # rotation wrapped; until then, continue AAA -> BBB -> CCC.
            self.cycle_last[tank] = sorted(roster)[-1]
        elif marker not in roster:
            roster.append(marker)
        if cleric.casefold() == "you":
            self.local_marker = marker
        self.revision += 1
        return "cast", cast
