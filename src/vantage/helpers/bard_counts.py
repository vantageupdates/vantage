"""P99 Bard AE hit/resist burst accounting from exact local log text."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time


TRACK_WINDOW_SECONDS = 1.5
MINIMUM_ANONYMOUS_BURST = 2
TRACKED_SONGS = frozenset({
    "chords of dissonance",
    "denon's disruptive discord",
    "selo's chords of cessation",
    "selo's assonant strane",
})
RESIST = re.compile(
    r"^Your target resisted(?: the)? (?P<spell>.+?)(?: spell)?\.$",
    re.IGNORECASE)
WINCES = re.compile(r"\bwinces\.$", re.IGNORECASE)
UNIQUE_LANDINGS = (
    ("is bound by silver strands of music", "Selo's Assonant Strane"),
    ("is bound in chords of music", "Selo's Chords of Cessation"),
)


def normalize_spell_name(name):
    value = str(name or "").strip()
    for source in ("`", "‘", "’"):
        value = value.replace(source, "'")
    value = value.replace("“", '"').replace("”", '"')
    return " ".join(value.split())


@dataclass(frozen=True)
class BardCountSummary:
    timestamp: object
    text: str
    total: int
    hits: int
    resists: int
    spell_name: str = ""
    source: str = "Exact local EQ log · 1.5-second burst"


@dataclass
class _Session:
    timestamp: object
    last_timestamp: object
    last_wall: float
    spell_name: str = ""
    hits: int = 0
    resists: int = 0
    has_unattributed: bool = False


class BardAeCounter:
    """Keep a hard-bounded set of short hit/resist sessions."""

    def __init__(self, max_sessions=32):
        self.max_sessions = max(1, int(max_sessions))
        self.sessions = []

    def reset(self):
        self.sessions.clear()

    def ingest(self, timestamp, text, now=None):
        wall = time.monotonic() if now is None else float(now)
        summaries = self.flush(wall)
        line = str(text or "")

        resist = RESIST.match(line)
        if resist:
            spell = normalize_spell_name(resist.group("spell"))
            if spell.casefold() in TRACKED_SONGS:
                summaries.extend(self._attach(
                    timestamp, wall, spell, resists=1))
            return summaries

        folded = line.casefold()
        for landing, spell in UNIQUE_LANDINGS:
            if landing in folded:
                summaries.extend(self._attach(
                    timestamp, wall, spell, hits=1))
                return summaries

        if WINCES.search(line):
            summaries.extend(self._attach(
                timestamp, wall, "", hits=1, unattributed=True))
        return summaries

    def _attach(
            self, timestamp, wall, spell_name, hits=0, resists=0,
            unattributed=False):
        normalized = normalize_spell_name(spell_name)
        session = None
        if normalized:
            session = self._recent(timestamp, normalized)
            if session is None:
                session = self._recent(timestamp, "", anonymous_only=True)
                if session:
                    session.spell_name = normalized
        else:
            session = self._recent(timestamp)

        if session is None:
            session = _Session(timestamp, timestamp, wall, normalized)
            self.sessions.append(session)
        session.hits += int(hits)
        session.resists += int(resists)
        session.has_unattributed = bool(
            session.has_unattributed or unattributed)
        session.last_timestamp = timestamp
        session.last_wall = wall

        overflow = []
        while len(self.sessions) > self.max_sessions:
            oldest = self.sessions.pop(0)
            summary = self._finalize(oldest)
            if summary:
                overflow.append(summary)
        return overflow

    def _recent(self, timestamp, spell_name=None, anonymous_only=False):
        normalized = normalize_spell_name(spell_name).casefold() \
            if spell_name is not None else None
        for session in reversed(self.sessions):
            try:
                age = abs((timestamp - session.last_timestamp).total_seconds())
            except (AttributeError, TypeError):
                age = 0
            if age > TRACK_WINDOW_SECONDS:
                continue
            current = normalize_spell_name(session.spell_name).casefold()
            if anonymous_only and current:
                continue
            if normalized is not None and current != normalized:
                continue
            return session
        return None

    def flush(self, now=None):
        wall = time.monotonic() if now is None else float(now)
        ready = [
            session for session in self.sessions
            if wall - session.last_wall >= TRACK_WINDOW_SECONDS]
        if not ready:
            return []
        ready_ids = {id(session) for session in ready}
        self.sessions[:] = [
            session for session in self.sessions
            if id(session) not in ready_ids]
        return [
            summary for session in ready
            if (summary := self._finalize(session)) is not None]

    @staticmethod
    def _finalize(session):
        total = session.hits + session.resists
        if total <= 0:
            return None
        if not session.spell_name and total < MINIMUM_ANONYMOUS_BURST:
            return None
        parts = [f"{total} Total"]
        if session.hits:
            parts.append(
                f"{session.hits} Hit" + ("" if session.hits == 1 else "s"))
        if session.resists:
            parts.append(
                f"{session.resists} Resist" +
                ("" if session.resists == 1 else "s"))
        named = (
            session.spell_name
            if session.spell_name and not session.has_unattributed else "")
        text = " | ".join(parts)
        if named:
            text = f"{named}: {text}"
        return BardCountSummary(
            session.last_timestamp, text, total, session.hits,
            session.resists, named)
