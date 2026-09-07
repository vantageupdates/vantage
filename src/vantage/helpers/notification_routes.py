"""Single-source catalog and semantics for automatic Vantage notices."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import re


@dataclass(frozen=True)
class NotificationRoute:
    key: str
    label: str
    description: str
    default_delivery: str
    default_sound: str
    default_voice: str
    channel: str


_ROUTES = (
    NotificationRoute("spell_fading", "Spell fading",
                      "A tracked spell is close to fading.", "sound",
                      "builtin:soft-tick", "Spell fading", "spells"),
    NotificationRoute("spell_resisted", "Spell resisted",
                      "EverQuest reports that your spell was resisted.", "sound",
                      "builtin:rune-pulse", "Spell resisted", "spells"),
    NotificationRoute("spell_worn_off", "Spell worn off",
                      "A tracked spell effect has ended.", "sound",
                      "builtin:ward-fall", "Spell worn off", "spells"),
    NotificationRoute("tell_message", "Incoming tell",
                      "A private tell from another player; message text is never spoken.",
                      "voice", "builtin:gentle-knock", "Incoming tell", "quickbar"),
    NotificationRoute("hail", "Incoming hail",
                      "Another player hails your active character.", "voice",
                      "builtin:copper-click", "Incoming hail", "quickbar"),
    NotificationRoute("smart_timer", "Smart Timer",
                      "A saved timer reaches its warning or due time.", "sound",
                      "builtin:spawn-horn", "Smart Timer", "timers"),
    NotificationRoute("raid_encounter", "Raid encounter",
                      "An FTE, quake, Ring War, or raid milestone is detected.",
                      "sound", "builtin:warden-bell", "Raid encounter", "timers"),
    NotificationRoute("market_sale", "Market sale",
                      "A watched item appears in a local EC Tunnel auction line.",
                      "sound", "builtin:crystal-ping", "Item for sale", "market"),
    NotificationRoute("death_loop", "Death-loop warning",
                      "Repeated deaths occur without player activity.", "sound",
                      "builtin:danger-double", "Death loop warning", "timers"),
)

NOTIFICATION_ROUTES = MappingProxyType({route.key: route for route in _ROUTES})
DELIVERY_CHOICES = (("Off", "off"), ("Sound", "sound"), ("Voice", "voice"))

_INCOMING_TELL = re.compile(
    r"^(?P<sender>[A-Za-z][\w`' -]{0,79}) tells you, ['\"](?P<body>.*)['\"]$",
    re.IGNORECASE)
_INCOMING_HAIL = re.compile(
    r"^(?P<sender>[A-Za-z][\w`' -]{0,79}) says, ['\"]Hail,\s*"
    r"(?P<target>[A-Za-z][\w`'-]{0,39})[.!]?['\"]$", re.IGNORECASE)
_PET_REPLY = re.compile(r"^(?:Attacking .+ Master\.|Following you, Master\.|"
                        r"Guarding with my life\.?)$", re.IGNORECASE)
_TIMER_SHARE = re.compile(r"\bVTS\d+:[A-Za-z0-9_-]{8,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class ChatNotification:
    route_key: str
    semantic_text: str
    voice_text: str
    sender: str


@dataclass(frozen=True)
class NotificationDeliveryResult:
    route_key: str
    delivery: str
    state: str
    played: bool
    reason: str = ""

    def __bool__(self):
        return self.played


def classify_chat_notification(text, active_character="", pet_names=()):
    """Return a safe player tell/hail notice, excluding local/system traffic."""
    line = str(text or "").strip()
    # All locally sent channels, auction traffic and share packets are excluded
    # before a private-message body can reach any notification surface.
    if (line.casefold().startswith(("you tell ", "you say,", "you auction", "you shout"))
            or " auctions, " in line.casefold() or _TIMER_SHARE.search(line)):
        return None
    match = _INCOMING_TELL.match(line)
    if match:
        sender = match.group("sender").strip()
        body = match.group("body").strip()
        known_pets = {str(name).strip().casefold() for name in pet_names if name}
        if (not sender[:1].isupper() or sender.casefold() in known_pets or
                _PET_REPLY.fullmatch(body)):
            return None
        # System/NPC text is not guessed to be a player notification. Known
        # pets are excluded above; parser callers can supply all current pets.
        return ChatNotification(
            "tell_message", f"Tell from {sender}",
            f"Incoming tell from {sender}", sender)
    match = _INCOMING_HAIL.match(line)
    if match and active_character and (
            match.group("target").casefold() == str(active_character).casefold()):
        sender = match.group("sender").strip()
        if sender.casefold() != str(active_character).casefold():
            return ChatNotification(
                "hail", f"{sender} hailed you", f"Incoming hail from {sender}", sender)
    return None


def normalized_route_settings(settings, route):
    """Validate one persisted route record without mutating the caller."""
    settings = settings if isinstance(settings, dict) else {}
    delivery = str(settings.get("delivery", route.default_delivery)).casefold()
    if delivery not in {value for _label, value in DELIVERY_CHOICES}:
        delivery = route.default_delivery
    raw_sound = settings.get("sound", route.default_sound)
    sound = (str(raw_sound or "")[:500] if isinstance(raw_sound, str)
             else route.default_sound)
    raw_voice = settings.get("voice", "")
    voice = str(raw_voice or "")[:160] if isinstance(raw_voice, str) else ""
    return {"delivery": delivery, "sound": sound, "voice": voice}
