"""Bounded, literal chat keyword rules for Smart Timer actions."""

from __future__ import annotations

import re
import uuid


MAX_KEYWORD_RULES = 64
MAX_KEYWORD_PHRASE = 160
KEYWORD_ACTIONS = ("start", "reset", "pause", "resume", "stop", "create")
_PLACEHOLDER_RX = re.compile(
    r"(%T|\{timer\}|\{name\}|\{duration\})", re.IGNORECASE)
_OWN_SAY_RX = re.compile(r"^You say, '(?P<message>.*)'$", re.IGNORECASE)


def normalize_keyword_phrase(value):
    return " ".join(str(value or "").split())[:MAX_KEYWORD_PHRASE]


def validate_keyword_rule(value, *, known_timer_ids=None):
    source = value if isinstance(value, dict) else {}
    phrase = normalize_keyword_phrase(source.get("phrase"))
    placeholders = [value.casefold() for value in _PLACEHOLDER_RX.findall(phrase)]
    literal = _PLACEHOLDER_RX.sub("", phrase)
    if not phrase:
        raise ValueError("Enter a literal chat phrase.")
    if len(re.findall(r"[^\W_]", literal, re.UNICODE)) < 3:
        raise ValueError("Add at least three literal letters or numbers.")
    action = str(source.get("action") or "").strip().casefold()
    if action not in KEYWORD_ACTIONS:
        raise ValueError("Choose Start, Reset, Pause, Resume, Stop, or Create.")
    if action == "create":
        name_tokens = [token for token in placeholders
                       if token in ("%t", "{name}")]
        if len(name_tokens) != 1 or "{timer}" in placeholders:
            raise ValueError("Create needs exactly one %T or {name} token.")
        if placeholders.count("{duration}") > 1:
            raise ValueError("Use {duration} at most once.")
        if len(placeholders) != len(name_tokens) + placeholders.count("{duration}"):
            raise ValueError("Create supports only %T/{name} and {duration}.")
    elif len(placeholders) > 1 or any(
            token in ("{name}", "{duration}") for token in placeholders):
        raise ValueError("Use only one %T or {timer} placeholder for this action.")
    matches = list(_PLACEHOLDER_RX.finditer(phrase))
    if any(left.end() == right.start() for left, right in zip(matches, matches[1:])):
        raise ValueError("Separate placeholders with literal text or spaces.")
    timer_id = str(source.get("timer_id") or "").strip()[:96]
    if placeholders:
        timer_id = ""
    elif not timer_id:
        raise ValueError("Choose the exact timer this phrase controls.")
    if known_timer_ids is not None and timer_id and timer_id not in known_timer_ids:
        raise ValueError("The selected timer no longer exists.")
    captures_duration = action == "create" and "{duration}" in placeholders
    if captures_duration:
        # The chat message supplies the duration.  Keep a harmless normalized
        # value so an old or malformed hidden default cannot block the rule.
        create_seconds = 400
    else:
        try:
            create_seconds = int(source.get("create_seconds", 400))
        except (TypeError, ValueError, OverflowError):
            create_seconds = 0
        if action == "create" and not 1 <= create_seconds <= 30 * 24 * 60 * 60:
            raise ValueError("Choose a default duration from 1 second to 30 days.")
    return {
        "id": str(source.get("id") or uuid.uuid4().hex)[:64],
        "enabled": bool(source.get("enabled", False)),
        "phrase": phrase,
        "action": action,
        "timer_id": timer_id,
        "all_matches": bool(source.get("all_matches", False)) if placeholders else False,
        "create_seconds": create_seconds if action == "create" else 400,
        "allow_unassigned": bool(source.get("allow_unassigned", False))
        if action == "create" else False,
    }


def normalize_keyword_rules(values, *, known_timer_ids=None):
    result = []
    seen = set()
    for value in values if isinstance(values, list) else ():
        try:
            rule = validate_keyword_rule(
                value, known_timer_ids=known_timer_ids)
        except ValueError:
            continue
        signature = normalize_keyword_phrase(rule["phrase"]).casefold()
        if signature in seen:
            continue
        seen.add(signature)
        result.append(rule)
        if len(result) >= MAX_KEYWORD_RULES:
            break
    return result


def own_say_message(text):
    match = _OWN_SAY_RX.fullmatch(str(text or "").strip())
    return match.group("message").strip() if match else ""


def match_keyword_phrase(phrase, message):
    """Match an escaped literal template and return its one optional capture."""
    phrase = normalize_keyword_phrase(phrase)
    message = " ".join(str(message or "").split()).strip()
    placeholders = list(_PLACEHOLDER_RX.finditer(phrase))
    if not message:
        return None
    if not placeholders:
        return {} if phrase.casefold() == message.casefold() else None
    pieces = []
    position = 0
    keys = []
    for index, placeholder in enumerate(placeholders):
        pieces.append(re.escape(phrase[position:placeholder.start()]).replace(
            r"\ ", r"\s+"))
        token = placeholder.group().casefold()
        key = {
            "%t": "target", "{timer}": "timer", "{name}": "name",
            "{duration}": "duration",
        }[token]
        keys.append(key)
        pattern = r"\d+(?::\d+){0,2}" if key == "duration" else r".+?"
        pieces.append(rf"(?P<{key}>{pattern})")
        position = placeholder.end()
    pieces.append(re.escape(phrase[position:]).replace(r"\ ", r"\s+"))
    match = re.fullmatch("".join(pieces), message, re.IGNORECASE)
    if not match:
        return None
    result = {}
    for key in keys:
        captured = " ".join(match.group(key).split()).strip()
        if key != "duration":
            captured = captured.rstrip(".!? ")
        if not captured:
            return None
        result[key] = captured
    return result
