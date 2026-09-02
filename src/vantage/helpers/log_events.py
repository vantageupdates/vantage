"""Shared recognition for authoritative EverQuest log events."""

import re


KILL_PATTERNS = (
    re.compile(r"^You have slain (?P<mob>.+?)[!.]?$", re.IGNORECASE),
    re.compile(
        r"^(?P<mob>.+?) has been slain by .+?[!.]?$", re.IGNORECASE),
)


def extract_killed_mob(text):
    """Return the mob named by an EQ death line, if present."""
    line = str(text or '').strip()
    for matcher in KILL_PATTERNS:
        match = matcher.match(line)
        if match:
            return match.group('mob').strip()
    return None
