"""Native, cached UI for PigParse Green market data and local auction lines."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
import gzip
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import statistics
from urllib.parse import quote, unquote
import webbrowser

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QModelIndex, QSize, QSortFilterProxyModel,
    QStringListModel, Signal, Qt, QTimer, QUrl)
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QFont, QPixmap)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QTableView, QTableWidget, QTableWidgetItem, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget)

from vantage.helpers import config, resource_path
from vantage.helpers.icons import game_icon
from vantage.helpers.eq_clipboard import set_eq_clipboard
from vantage.helpers.friends_manager import everquest_root_from_logs
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import ensure_tab_tooltips, scrollable
from vantage.helpers.scaled_dialog import UniformScaleDialog


MARKET_ENDPOINT = "https://pigparse.azurewebsites.net/api/item/getall/Green"
DETAIL_API = "https://pigparse.azurewebsites.net/api/item/getdetails/Green/{item_name}"
DETAIL_URL = "https://pigparse.azurewebsites.net/ItemDetails/{item_id}"
P99_WIKI_URL = "https://wiki.project1999.com/{slug}"
P99_WIKI_API = (
    "https://wiki.project1999.com/api.php?action=parse&page={slug}"
    "&prop=text%7Cwikitext%7Cimages&format=json")
P99_WIKI_IMAGE_URL = "https://wiki.project1999.com/images/{filename}"
PIGPARSE_URL = "https://pigparse.azurewebsites.net/ServerIndex/Green"
P99_PLANNER_URL = "https://p99planner.com/items"
GEAR_META_URL = "https://p99planner.com/data/meta.json"
GEAR_DB_URL = "https://p99planner.com/data/p99.sqlite.gz"
LOCAL_AUCTION_RX = re.compile(
    r"^(?P<seller>[A-Za-z][A-Za-z'`-]*|You) auctions?,?\s+'(?P<message>.*)'$",
    re.IGNORECASE)
ZONE_RX = re.compile(r"^You have entered (?P<zone>.+)\.$", re.IGNORECASE)
CON_MESSAGES = (
    "regards you as an ally",
    "looks upon you warmly",
    "kindly considers you",
    "judges you amiably",
    "regards you indifferently",
    "looks your way apprehensively",
    "glowers at you dubiously",
    "glares at you threateningly",
    "scowls at you, ready to attack",
)


def _announce_accessible(widget, text, assertive=False):
    """Announce meaningful dynamic UI changes without stealing keyboard focus."""
    if not isinstance(widget, QWidget) or not QApplication.instance() or not text:
        return False
    event = QAccessibleAnnouncementEvent(widget, str(text))
    event.setPoliteness(
        QAccessible.AnnouncementPoliteness.Assertive if assertive else
        QAccessible.AnnouncementPoliteness.Polite)
    QAccessible.updateAccessibility(event)
    return True

CLASS_BITS = (
    ("Any class", 0), ("Warrior", 1), ("Cleric", 2),
    ("Paladin", 4), ("Ranger", 8), ("Shadow Knight", 16),
    ("Druid", 32), ("Monk", 64), ("Bard", 128), ("Rogue", 256),
    ("Shaman", 512), ("Necromancer", 1024), ("Wizard", 2048),
    ("Magician", 4096), ("Enchanter", 8192))
RACE_BITS = (
    ("Any race", 0), ("Human", 1), ("Barbarian", 2),
    ("Erudite", 4), ("Wood Elf", 8), ("High Elf", 16),
    ("Dark Elf", 32), ("Half Elf", 64), ("Dwarf", 128),
    ("Troll", 256), ("Ogre", 512), ("Halfling", 1024),
    ("Gnome", 2048), ("Iksar", 4096))
SLOT_BITS = (
    ("Any slot", 0), ("Charm", 1), ("Ear", 2 | 16),
    ("Head", 4), ("Face", 8), ("Neck", 32), ("Shoulders", 64),
    ("Arms", 128), ("Back", 256), ("Wrist", 512 | 1024),
    ("Range", 2048), ("Hands", 4096), ("Primary", 8192),
    ("Secondary", 16384), ("Finger", 32768 | 65536),
    ("Chest", 131072), ("Legs", 262144), ("Feet", 524288),
    ("Waist", 1048576), ("Ammo", 2097152))

STAT_OPTIONS = (
    ("AC", "ac"), ("HP", "hp"), ("Mana", "mana"),
    ("STR", "astr"), ("STA", "asta"), ("DEX", "adex"),
    ("AGI", "aagi"), ("INT", "aint"), ("WIS", "awis"),
    ("CHA", "acha"), ("MR", "mr"), ("FR", "fr"),
    ("CR", "cr"), ("DR", "dr"), ("PR", "pr"),
    ("ATK", "attack"), ("Haste", "haste"),
    ("Regen", "regen"), ("Mana regen", "manaregen"))
STAT_LABELS = dict(STAT_OPTIONS)
STAT_NAMES = {key: label for label, key in STAT_OPTIONS}
EFFECT_OPTIONS = (
    ("Any effect", ""), ("Click", "click"), ("Proc", "proc"),
    ("Worn", "worn"), ("Focus", "focus"), ("Bard", "bard"))
TRADEABILITY_OPTIONS = (
    ("Any binding", ""), ("Droppable", "droppable"),
    ("No Drop", "nodrop"))
ERA_OPTIONS = (
    ("Any era", ""), ("Classic", "classic"),
    ("Kunark", "kunark"), ("Velious", "velious"))
GEAR_COLUMN_DEFAULT_WIDTHS = {
    "name": 220, "effects": 250, "price": 82, "selected": 70,
    "ac": 44, "hp": 48, "mana": 52, "astr": 44, "asta": 44,
    "adex": 44, "aagi": 44, "aint": 44, "awis": 44, "acha": 44}
CORE_STAT_COLUMNS = {
    "ac": 4, "hp": 5, "mana": 6, "astr": 7, "asta": 8,
    "adex": 9, "aagi": 10, "aint": 11, "awis": 12, "acha": 13}
GEAR_DB_FIELDS = (
    "id", "name", "classes", "races", "slots", "nodrop", "ac", "hp", "mana",
    "regen", "manaregen", "astr", "asta", "aagi", "adex", "aint",
    "awis", "acha", "mr", "fr", "cr", "dr", "pr", "attack",
    "haste", "clickName", "procName", "wornName", "focusName",
    "bardName", "peqId")


@dataclass(frozen=True, slots=True)
class GearItem:
    """One compact row from the local P99 equipment index."""

    name: str
    id: int = 0
    peqId: int = 0
    classes: int = 0
    races: int = 0
    slots: int = 0
    nodrop: int = 0
    era: str = ""
    ac: int = 0
    hp: int = 0
    mana: int = 0
    regen: int = 0
    manaregen: int = 0
    astr: int = 0
    asta: int = 0
    aagi: int = 0
    adex: int = 0
    aint: int = 0
    awis: int = 0
    acha: int = 0
    mr: int = 0
    fr: int = 0
    cr: int = 0
    dr: int = 0
    pr: int = 0
    attack: int = 0
    haste: int = 0
    clickName: str = ""
    procName: str = ""
    wornName: str = ""
    focusName: str = ""
    bardName: str = ""

    def stat(self, key):
        return int(getattr(self, str(key), 0) or 0)

    def effects(self, kind=""):
        pairs = (
            ("Click", self.clickName), ("Proc", self.procName),
            ("Worn", self.wornName), ("Focus", self.focusName),
            ("Bard", self.bardName))
        wanted = str(kind or "").casefold()
        return tuple(
            (label, str(value).strip()) for label, value in pairs
            if value and (not wanted or label.casefold() == wanted))

    @property
    def effect_text(self):
        return " · ".join(
            f"{label}: {value}" for label, value in self.effects())

    @property
    def search_text(self):
        binding = "no drop nodrop" if self.nodrop else "droppable tradeable"
        return f"{self.name} {self.effect_text} {binding} {self.era}".casefold()


def load_item_eras(path=None):
    """Load the compact item-to-era index derived from P99 Wiki categories."""
    target = path or resource_path("data/market/item_eras.json")
    try:
        with open(target, encoding="utf-8") as source:
            payload = json.load(source)
        items = payload.get("items", payload)
        if not isinstance(items, dict):
            return {}
        return {
            str(key): str(value).casefold() for key, value in items.items()
            if str(value).casefold() in {"classic", "kunark", "velious"}}
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def load_gear_items(path, era_path=None):
    """Load only sortable/filterable columns from the compressed P99 index."""
    era_index = load_item_eras(era_path)
    columns = ", ".join(GEAR_DB_FIELDS)
    with sqlite3.connect(path) as database:
        rows = database.execute(f"SELECT {columns} FROM items").fetchall()
    items = []
    text_fields = {
        "name", "clickName", "procName", "wornName", "focusName",
        "bardName"}
    numeric_fields = set(GEAR_DB_FIELDS) - text_fields
    for row in rows:
        values = {}
        for field, value in zip(GEAR_DB_FIELDS, row):
            values[field] = (
                int(value or 0) if field in numeric_fields
                else str(value or ""))
        # This classic EQ database field is historically inverted: 0 means
        # NO DROP and 1 means the item may be traded.  Keep GearItem.nodrop as
        # a normal boolean so the filter, table and item card all agree.
        values["nodrop"] = int(values["nodrop"] == 0)
        values["era"] = era_index.get(_item_key(values["name"]), "")
        items.append(GearItem(**values))
    return items


def gear_item_summary_html(item):
    """Readable local stat/effect summary for the native item card."""
    if not isinstance(item, GearItem):
        return "P99 item attributes are unavailable for this listing."
    groups = []
    identity = [
        "NO DROP" if item.nodrop else "Droppable",
        item.era.title() if item.era else "Era not indexed"]
    groups.append(" · ".join(f"<b>{html.escape(value)}</b>" for value in identity))
    for fields in (
            (("AC", "ac"), ("HP", "hp"), ("Mana", "mana")),
            (("STR", "astr"), ("STA", "asta"), ("DEX", "adex"),
             ("AGI", "aagi"), ("INT", "aint"), ("WIS", "awis"),
             ("CHA", "acha")),
            (("MR", "mr"), ("FR", "fr"), ("CR", "cr"),
             ("DR", "dr"), ("PR", "pr"), ("ATK", "attack"),
             ("Haste", "haste"), ("Regen", "regen"),
             ("Mana regen", "manaregen"))):
        values = [
            f"<b>{label}</b> {item.stat(key):+d}"
            for label, key in fields if item.stat(key)]
        if values:
            groups.append(" · ".join(values))
    effects = [
        f"<b>{html.escape(label)}</b> · {html.escape(value)}"
        for label, value in item.effects()]
    if effects:
        groups.append("<br>".join(effects))
    return "<br>".join(groups) or "No numeric stats or effects are listed."


def _cache_file():
    return data_dir("cache") / "pigparse-green-cache.json"


def _gear_cache_file():
    return data_dir("cache") / "p99-item-metadata.sqlite"


def _item_key(name):
    return re.sub(r"['’`]", "", str(name or "").strip().casefold())


def live_auction_watch_matches(message, watch_items):
    """Return watched item names found in a local sale auction message."""
    source = str(message or "").strip()
    folded = source.casefold()
    # A pure WTB line is a request, not an item appearing for sale. Mixed
    # WTS/WTB tunnel macros still contain sale inventory and remain eligible.
    if (re.search(r"\bwtb\b", folded) and
            not re.search(r"\b(?:wts|selling|sell)\b", folded)):
        return []
    haystack = _item_key(source)
    matches = []
    for raw_watch in watch_items or ():
        watch = str(raw_watch or "").strip()
        key = _item_key(watch)
        if key and key in haystack and watch.casefold() not in {
                item.casefold() for item in matches}:
            matches.append(watch)
    return matches


def considered_name(text):
    """Extract the target prefix from EQ's nine exact faction messages."""
    line = str(text or "").strip()
    folded = line.casefold()
    for message in CON_MESSAGES:
        index = folded.find(message)
        if index > 0:
            return line[:index].strip()
    return ""


P99_ITEM_LINK_DELIMITER = "\x12"
P99_CHAT_LIMIT = 255
P99_LINK_RX = re.compile(r"\x12.{45} ?([^\x12]*)\x12")


@dataclass(frozen=True, slots=True)
class AuctionEntry:
    """One item selected for an outgoing WTS or WTB message."""

    id: int
    name: str
    price: str = ""
    quantity: int = 1


def p99_item_link(item_id, display_name):
    """Build the 45-character Titanium item payload used by P99 links."""
    try:
        numeric_id = int(item_id)
    except (TypeError, ValueError) as error:
        raise ValueError("A valid Project 1999 item ID is required") from error
    if not 0 < numeric_id <= 0xFFFFF:
        raise ValueError("Project 1999 item ID is outside the Titanium range")
    name = str(display_name or "").replace(P99_ITEM_LINK_DELIMITER, "")
    name = " ".join(name.replace("\r", " ").replace("\n", " ").split())
    if not name:
        raise ValueError("An item name is required")
    # Titanium payload: action nibble + five-digit item id + five empty
    # augment ids + the remaining reserved fields. The payload is 45 chars.
    payload = "0" + f"{numeric_id:05X}" + ("0" * 39)
    # Titanium requires a literal space between the 45-character tag body and
    # the visible item name. Without it the client consumes the DC2 markers but
    # prints the hexadecimal body as ordinary chat text.
    return (
        f"{P99_ITEM_LINK_DELIMITER}{payload} {name}"
        f"{P99_ITEM_LINK_DELIMITER}")


def normalize_auction_price(value):
    """Return a compact player-facing EQ price such as ``500p`` or ``1.5k``."""
    text = str(value or "").strip().casefold().replace(",", "")
    if not text:
        return ""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k|p|pp)?", text)
    if not match:
        return str(value).strip()
    number, suffix = match.groups()
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return f"{number}{'k' if suffix == 'k' else 'p'}"


def _compact_template_text(value):
    return re.sub(r"[ \t]{2,}", " ", str(value or "")).strip()


def _preview_auction_line(value):
    return P99_LINK_RX.sub(lambda match: f"[{match.group(1)}]", str(value or ""))


def compose_auction_lines(
        entries, trade_type="WTS", message_template="{type} {items} {suffix}",
        item_template="{qty} {item} {price}", separator=" // ", suffix="PST",
        max_length=P99_CHAT_LIMIT, clickable=True):
    """Render and safely pack customized WTS/WTB messages for EQ chat."""
    trade_type = "WTB" if str(trade_type).strip().upper() == "WTB" else "WTS"
    maximum = max(80, int(max_length or P99_CHAT_LIMIT))
    message_template = str(message_template or "{type} {items} {suffix}")
    item_template = str(item_template or "{qty} {item} {price}")
    default_separator = str(separator if separator is not None else " // ")

    custom_separator = None
    items_token = "{items}"
    token_match = re.search(r"\{items:([^{}]*)\}", message_template)
    if token_match:
        custom_separator = token_match.group(1)
        items_token = token_match.group(0)
    joiner = default_separator if custom_separator is None else custom_separator

    rendered_items = []
    for entry in entries or ():
        if not isinstance(entry, AuctionEntry):
            entry = AuctionEntry(*entry)
        plain_name = " ".join(
            str(entry.name or "").replace("\n", " ").split())
        item_text = (
            p99_item_link(entry.id, entry.name)
            if (clickable and trade_type == "WTS" and
                int(entry.id or 0) > 0) else
            plain_name)
        values = {
            "{item}": item_text,
            "{price}": normalize_auction_price(entry.price),
            "{qty}": f"{max(1, int(entry.quantity or 1))}x"
            if int(entry.quantity or 1) > 1 else "",
        }
        rendered = item_template
        for token, replacement in values.items():
            rendered = rendered.replace(token, replacement)
        rendered_items.append(_compact_template_text(rendered))

    def render_message(group):
        rendered = message_template.replace(items_token, joiner.join(group))
        rendered = rendered.replace("{items}", joiner.join(group))
        rendered = rendered.replace("{type}", trade_type)
        rendered = rendered.replace("{suffix}", str(suffix or ""))
        return _compact_template_text(rendered)

    lines = []
    group = []
    for rendered_item in rendered_items:
        candidate = render_message([*group, rendered_item])
        if group and len(candidate) > maximum:
            lines.append(render_message(group))
            group = [rendered_item]
        else:
            group.append(rendered_item)
    if group:
        lines.append(render_message(group))
    return lines


_SOCIAL_KEY_RX = re.compile(
    r"^(Page(?P<page>\d+)Button(?P<button>\d+))"
    r"(?:Name|Color|Line[1-5])\s*=", re.IGNORECASE)


def install_auction_hotbuttons(ini_path, lines):
    """Install linked auction lines into free P99 social buttons safely.

    The Titanium chat editor strips item-link control bytes from ordinary
    clipboard paste. Character INI social lines preserve them, so this is the
    reliable route for generated clickable links.
    """
    target = Path(ini_path).expanduser().resolve(strict=True)
    if not target.is_file() or target.suffix.casefold() != ".ini":
        raise ValueError("Choose a Project 1999 character INI file")
    if not re.search(
            r"_(?:project1999|p1999(?:green|blue|pvp|red))\.ini$",
            target.name, re.IGNORECASE):
        raise ValueError("This does not look like a Project 1999 character INI")

    commands = [
        line if str(line).lstrip().startswith("/") else f"/auction {line}"
        for line in (lines or ()) if str(line).strip()]
    if not commands:
        raise ValueError("Add at least one item before installing a hotbutton")
    chunks = [commands[index:index + 5]
              for index in range(0, len(commands), 5)]

    original = target.read_bytes()
    text = original.decode("cp1252")
    rows = text.splitlines()
    section_start = next((
        index for index, row in enumerate(rows)
        if row.strip().casefold() == "[socials]"), None)
    if section_start is None:
        if rows and rows[-1].strip():
            rows.append("")
        rows.append("[Socials]")
        section_start = len(rows) - 1
    section_end = next((
        index for index in range(section_start + 1, len(rows))
        if rows[index].strip().startswith("[") and
        rows[index].strip().endswith("]")), len(rows))

    vantage_slots = set()
    for row in rows[section_start + 1:section_end]:
        match = re.match(
            r"^(Page\d+Button\d+)Name\s*=\s*VantageWTS\d*\s*$",
            row.strip(), re.IGNORECASE)
        if match:
            vantage_slots.add(match.group(1).casefold())

    kept = []
    occupied = set()
    for row in rows[section_start + 1:section_end]:
        match = _SOCIAL_KEY_RX.match(row.strip())
        prefix = match.group(1).casefold() if match else ""
        if prefix and prefix in vantage_slots:
            continue
        if prefix:
            occupied.add(prefix)
        kept.append(row)

    available = [
        f"Page{page}Button{button}"
        for page in range(2, 11) for button in range(1, 11)
        if f"page{page}button{button}" not in occupied]
    if len(available) < len(chunks):
        raise ValueError("There are not enough empty social buttons on pages 2–10")

    additions = []
    installed = []
    for index, command_group in enumerate(chunks, 1):
        prefix = available[index - 1]
        installed.append(prefix)
        additions.extend((
            f"{prefix}Name=VantageWTS{index}",
            f"{prefix}Color=0"))
        additions.extend(
            f"{prefix}Line{line_number}={command}"
            for line_number, command in enumerate(command_group, 1))
        additions.append("")

    rebuilt_section = kept
    if rebuilt_section and rebuilt_section[-1].strip():
        rebuilt_section.append("")
    rebuilt_section.extend(additions)
    updated = rows[:section_start + 1] + rebuilt_section + rows[section_end:]
    payload = ("\r\n".join(updated).rstrip() + "\r\n").encode("cp1252")

    backup = target.with_suffix(target.suffix + ".vantage-backup")
    shutil.copy2(target, backup)
    temporary = target.with_suffix(target.suffix + ".vantage-tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return tuple(installed), backup


def _wiki_cache_paths(name):
    digest = hashlib.sha256(_item_key(name).encode("utf-8")).hexdigest()[:20]
    cache = data_dir("cache", "wiki-items")
    return cache / f"{digest}.json", cache / f"{digest}.png"


def _wiki_entity_cache_path(target):
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-entities") / f"{digest}.json"


def _plain_wiki_text(value):
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(
        r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda match: match.group(2), text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda match: match.group(1), text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return "\n".join(
        line.strip() for line in text.splitlines() if line.strip())


def _wiki_target_url(target):
    slug = quote(str(target or "").strip().replace(" ", "_"), safe="")
    return P99_WIKI_URL.format(slug=slug)


def _wiki_template_field(source, name):
    match = re.search(
        rf"^\|\s*{re.escape(name)}\s*=\s*(.*?)"
        rf"(?=^\|\s*[A-Za-z_][\w ]*\s*=|^\}}\}}\s*$|\Z)",
        source, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_wiki_drops(source):
    """Return NPC/zone pairs from the Itempage ``dropsfrom`` field."""
    drops_field = _wiki_template_field(source, "dropsfrom")
    if not drops_field:
        return []

    entries = []
    current_zone = None
    for raw_line in drops_field.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        links = re.findall(
            r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", line)
        is_npc = line.startswith("*")
        if not is_npc:
            target = links[0][0].strip() if links else _plain_wiki_text(line)
            label = (links[0][1] or links[0][0]).strip() if links else target
            current_zone = {
                "name": _plain_wiki_text(label),
                "url": _wiki_target_url(target),
                "target": target,
            }
            continue

        plain_line = _plain_wiki_text(line.lstrip("* "))
        if links:
            target, label = links[0]
            npc_name = _plain_wiki_text(label or target)
            npc_url = _wiki_target_url(target)
        else:
            npc_name = plain_line
            npc_url = _wiki_target_url(plain_line)
        if npc_name:
            entries.append({
                "npc": npc_name,
                "npc_url": npc_url,
                "npc_target": target if links else plain_line,
                "zone": (current_zone or {}).get("name", "Zone not listed"),
                "zone_url": (current_zone or {}).get("url", ""),
                "zone_target": (current_zone or {}).get("target", ""),
            })
    return entries


def parse_wiki_item_wikitext(wikitext, fallback_name=""):
    """Extract the classic P99 Wiki itembox without rendering a web page."""
    source = str(wikitext or "")
    box = re.search(
        r"\{\{Itembox\b(?P<body>.*?)(?:\n\}\}|\}\})",
        source, re.IGNORECASE | re.DOTALL)
    if not box:
        box = re.search(
            r"\{\{Itempage\b(?P<body>.*?)(?:\n\}\}|\}\})",
            source, re.IGNORECASE | re.DOTALL)
    body = box.group("body") if box else source

    def field(name):
        match = re.search(
            rf"^\|\s*{re.escape(name)}\s*=\s*(.*?)"
            rf"(?=^\|\s*[A-Za-z_][\w ]*\s*=|\Z)",
            body, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        return match.group(1).strip() if match else ""

    item_name = _plain_wiki_text(field("itemname")) or fallback_name
    image_id = re.sub(r"\D", "", field("lucy_img_ID"))
    stats = _plain_wiki_text(field("statsblock"))
    return {
        "name": item_name,
        "stats": stats or "The page does not contain a stat block.",
        "image": f"Item_{image_id}.png" if image_id else "",
        "drops": _parse_wiki_drops(source),
    }


def _rendered_html_text(value):
    value = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _positive_number(value):
    match = re.search(r"(?<!\d)(\d[\d,]*)", str(value or ""))
    if not match:
        return 0
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return 0


def _average_cell(value):
    numbers = re.findall(r"\d[\d,]*", str(value or ""))
    parsed = [int(number.replace(",", "")) for number in numbers[:2]]
    return (
        parsed[0] if parsed else 0,
        parsed[1] if len(parsed) > 1 else 0,
    )


def parse_wiki_green_auction_html(rendered_html):
    """Extract Green Auction Tracker values from the rendered Wiki page.

    The tracker is injected by a MediaWiki extension and is not present in the
    page's wikitext. Only recent Green values are candidates for comparison;
    the all-time average is retained for context but never used as an estimate.
    """
    source = str(rendered_html or "")
    section_match = re.search(
        r"<div\b[^>]*\bid=[\"']auc_Green[\"'][^>]*>(.*?)"
        r"(?=<div\b[^>]*\bid=[\"']auc_[^\"']+[\"']|\Z)",
        source, re.IGNORECASE | re.DOTALL)
    if not section_match:
        return {}
    section = section_match.group(1)
    stats_match = re.search(
        r"<table\b[^>]*\bclass=[\"'][^\"']*\beoTable3\b[^\"']*[\"']"
        r"[^>]*>(.*?)</table>", section, re.IGNORECASE | re.DOTALL)
    if not stats_match:
        return {}
    stats_cells = [
        _rendered_html_text(cell) for cell in re.findall(
            r"<td\b[^>]*>(.*?)</td>", stats_match.group(1),
            re.IGNORECASE | re.DOTALL)]
    if len(stats_cells) < 5:
        return {}

    avg_30, spread_30 = _average_cell(stats_cells[0])
    avg_90, spread_90 = _average_cell(stats_cells[1])
    all_time_avg, all_time_spread = _average_cell(stats_cells[2])
    range_values = [
        int(value.replace(",", "")) for value in re.findall(
            r"\d[\d,]*", stats_cells[3])[:2]]
    seen = _positive_number(stats_cells[4])

    history_match = re.search(
        r"<table\b[^>]*\bclass=[\"'][^\"']*\beoTable\b[^\"']*[\"']"
        r"[^>]*>(.*?)</table>", section, re.IGNORECASE | re.DOTALL)
    records = []
    if history_match:
        for row in re.findall(
                r"<tr\b[^>]*>(.*?)</tr>", history_match.group(1),
                re.IGNORECASE | re.DOTALL):
            cells = [
                _rendered_html_text(cell) for cell in re.findall(
                    r"<td\b[^>]*>(.*?)</td>", row,
                    re.IGNORECASE | re.DOTALL)]
            for offset in (0, 3):
                if len(cells) < offset + 3:
                    continue
                date, seller, raw_price = cells[offset:offset + 3]
                price = _positive_number(raw_price)
                if (re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
                        and seller and price > 0):
                    record = {"date": date, "seller": seller, "price": price}
                    if record not in records:
                        records.append(record)

    prices = [record["price"] for record in records]
    plausible = list(prices)
    if prices:
        median = float(statistics.median(prices))
        deviations = [abs(price - median) for price in prices]
        mad = float(statistics.median(deviations))
        threshold = max(median * .35, mad * 3, 25)
        plausible = [
            price for price in prices
            if abs(price - median) <= threshold
            and median * .25 <= price <= median * 4]
    robust_recent = round(statistics.median(plausible or prices)) if prices else 0
    outliers = len(prices) - len(plausible)

    reference = avg_30 or avg_90 or robust_recent
    reference_period = "30d" if avg_30 else ("90d" if avg_90 else "recent")
    warning = ""
    if robust_recent and reference:
        ratio = max(reference, robust_recent) / min(reference, robust_recent)
        if ratio > 2:
            reference = robust_recent
            reference_period = "recent median"
            warning = "The published average differs sharply from recent history."
    if len(plausible) >= 8 and outliers <= max(1, len(prices) * .2):
        quality = "High"
    elif len(plausible) >= 4 or (seen >= 20 and (avg_30 or avg_90)):
        quality = "Medium"
    else:
        quality = "Low"
    return {
        "source": "Project 1999 Wiki Auction Tracker · Green",
        "avg_30": avg_30,
        "spread_30": spread_30,
        "avg_90": avg_90,
        "spread_90": spread_90,
        "all_time_avg": all_time_avg,
        "all_time_spread": all_time_spread,
        "range_low": range_values[0] if range_values else 0,
        "range_high": range_values[1] if len(range_values) > 1 else 0,
        "seen": seen,
        "recent_median": robust_recent,
        "recent_samples": len(prices),
        "outliers": outliers,
        "last_date": records[0]["date"] if records else "",
        "reference": reference,
        "reference_period": reference_period,
        "quality": quality,
        "warning": warning,
        "records": records,
    }


def combined_market_price(item, wiki_auction, closeness=1.30):
    """Average PigParse and Wiki only when their recent signals agree."""
    pig_price = 0
    pig_period = ""
    for key, period in (("a30", "30d"), ("a60", "60d"), ("a90", "90d")):
        try:
            candidate = int(float(item.get(key) or 0))
        except (TypeError, ValueError):
            candidate = 0
        if candidate > 0:
            pig_price, pig_period = candidate, period
            break
    wiki_price = int((wiki_auction or {}).get("reference") or 0)
    if not pig_price or not wiki_price:
        return {
            "pig": pig_price, "pig_period": pig_period,
            "wiki": wiki_price, "combined": 0, "close": False,
            "difference_percent": 0,
        }
    ratio = max(pig_price, wiki_price) / min(pig_price, wiki_price)
    midpoint = (pig_price + wiki_price) / 2
    difference = abs(pig_price - wiki_price) / midpoint * 100
    close = ratio <= float(closeness)
    return {
        "pig": pig_price,
        "pig_period": pig_period,
        "wiki": wiki_price,
        "combined": round(midpoint) if close else 0,
        "close": close,
        "difference_percent": difference,
    }


def parse_wiki_entity_wikitext(wikitext, fallback_name="", kind="npc"):
    """Extract a short native NPC or zone summary from P99 Wiki markup."""
    source = str(wikitext or "")
    if kind == "npc":
        name = _plain_wiki_text(_wiki_template_field(source, "name"))
        facts = []
        for label, field_name in (
                ("Race", "race"), ("Class", "class"),
                ("Level", "level"), ("Zone", "zone"),
                ("Location", "location"), ("HP", "HP"),
                ("Damage per hit", "damage_per_hit")):
            value = _plain_wiki_text(
                _wiki_template_field(source, field_name))
            if value:
                facts.append((label, value))
        summary = _plain_wiki_text(
            _wiki_template_field(source, "description"))
        return {
            "name": name or fallback_name.replace("_", " "),
            "kind": "NPC",
            "facts": facts,
            "summary": summary or "The Wiki does not include a short description.",
        }

    lead = re.split(r"\n\s*(?:\{\||==)", source, maxsplit=1)[0]
    lead = re.sub(r"(?m)^\s*\{\{[^\n]+\}\}\s*$", "", lead)
    lead = re.sub(r"'{2,5}", "", lead)
    summary = _plain_wiki_text(lead)
    level_match = re.search(
        r"Level of Monsters:\s*'''\s*\|\s*([^\n|]+)", source,
        re.IGNORECASE)
    facts = []
    if level_match:
        facts.append(("Enemy levels", _plain_wiki_text(level_match.group(1))))
    return {
        "name": fallback_name.replace("_", " "),
        "kind": "ZONE",
        "facts": facts,
        "summary": summary or "The Wiki does not include a short introduction.",
    }


def _quality(item):
    """Cheap confidence hint; never mutates or discards PigParse values."""
    count = int(item.get("t30") or 0)
    prices = [float(item.get(k) or 0) for k in ("a30", "a60", "a90")]
    prices = [p for p in prices if p > 0]
    if not prices or count < 3:
        return "Low", 0
    consistency = max(prices) / min(prices)
    if count >= 12 and consistency <= 1.35:
        return "High", 2
    if count >= 5 and consistency <= 1.8:
        return "Medium", 1
    return "Low", 0


def market_price_references(items):
    """Return one price-reference row per item, preferring seller evidence."""
    selected = {}
    order = []
    for raw_item in items or ():
        item = dict(raw_item or {})
        key = _item_key(item.get("n"))
        if not key:
            continue
        candidate = (
            {0: 3, 2: 2, 1: 1}.get(item.get("t"), 0),
            int(item.get("t30") or 0),
            int(float(item.get("a30") or 0)))
        current = selected.get(key)
        if current is None:
            order.append(key)
        if current is None or candidate > current[0]:
            selected[key] = (candidate, item)
    return [selected[key][1] for key in order]


def _invalidate_proxy_rows(proxy):
    """Refresh one proxy filter using the current Qt row-only API."""
    proxy.beginFilterChange()
    proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)


class MarketModel(QAbstractTableModel):
    COLUMNS = (
        ("Item", "n"), ("30d price", "a30"),
        ("30d posts", "t30"), ("60d price", "a60"),
        ("90d price", "a90"), ("6m price", "a6m"),
        ("Quality", "quality"), ("Last seen", "l"))

    def __init__(self):
        super().__init__()
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        key = self.COLUMNS[index.column()][1]
        value = item.get(key, "")
        quality, quality_rank = _quality(item)
        if role == Qt.ItemDataRole.UserRole:
            return quality_rank if key == "quality" else value
        if role == Qt.ItemDataRole.ToolTipRole and key == "quality":
            return (
                "Calculated from price consistency and the number of listings. "
                "Original PigParse values are preserved unchanged.")
        if role == Qt.ItemDataRole.ToolTipRole and key == "n":
            return "Open the compact item card from Project 1999 Wiki"
        if role == Qt.ItemDataRole.ForegroundRole and key == "n":
            return QColor("#D2B873")
        if role == Qt.ItemDataRole.FontRole and key == "n":
            font = QFont()
            font.setBold(True)
            font.setUnderline(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole and key == "quality":
            return QColor({"High": "#34D399", "Medium": "#F59E0B"}.get(
                quality, "#FB7185"))
        if role == Qt.ItemDataRole.TextAlignmentRole and key in {
                "a30", "t30", "a60", "a90", "a6m"}:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if key == "quality":
            return quality
        if key.startswith("a"):
            return f"{int(value):,} pp" if value else "—"
        if key == "l":
            try:
                stamp = datetime.datetime.fromisoformat(str(value))
                return stamp.astimezone().strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                return str(value)
        return str(value)


class MarketFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.gear = {}
        self.class_bit = 0
        self.race_bit = 0
        self.slot_bit = 0
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_query(self, query):
        self.query = query.strip().casefold()
        _invalidate_proxy_rows(self)

    def set_gear(self, gear):
        self.gear = gear or {}
        _invalidate_proxy_rows(self)

    def set_gear_filter(self, kind, bit):
        setattr(self, f"{kind}_bit", int(bit or 0))
        _invalidate_proxy_rows(self)

    def filterAcceptsRow(self, source_row, source_parent):
        item = self.sourceModel().items[source_row]
        metadata = self.gear.get(_item_key(item.get("n")))
        if self.query:
            haystack = str(item.get("n", "")).casefold()
            if isinstance(metadata, GearItem):
                haystack = f"{haystack} {metadata.effect_text.casefold()}"
            if self.query not in haystack:
                return False
        if self.class_bit or self.race_bit or self.slot_bit:
            if not isinstance(metadata, GearItem):
                return False
            if self.class_bit and not metadata.classes & self.class_bit:
                return False
            if self.race_bit and not metadata.races & self.race_bit:
                return False
            if self.slot_bit and not metadata.slots & self.slot_bit:
                return False
        return True


class GearModel(QAbstractTableModel):
    """Sortable equipment catalog using local stats plus matched Pig prices."""

    COLUMNS = (
        ("Item", "name"), ("Effects", "effects"),
        ("30d price", "price"), ("Best AC", "selected"),
        ("AC", "ac"), ("HP", "hp"), ("Mana", "mana"),
        ("STR", "astr"), ("STA", "asta"), ("DEX", "adex"),
        ("AGI", "aagi"), ("INT", "aint"), ("WIS", "awis"),
        ("CHA", "acha"))

    def __init__(self):
        super().__init__()
        self.items = []
        self.active_stat = "ac"
        self._prices = {}

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items or [])
        self.endResetModel()

    def set_prices(self, market_items):
        prices = {}
        for item in market_items or ():
            key = _item_key(item.get("n"))
            if not key:
                continue
            candidate = (
                {0: 3, 2: 2, 1: 1}.get(item.get("t"), 0),
                int(item.get("t30") or 0),
                int(float(item.get("a30") or 0)))
            previous = prices.get(key)
            if previous is None or candidate > previous[0]:
                prices[key] = (candidate, dict(item))
        self._prices = {key: value[1] for key, value in prices.items()}
        if self.items:
            left = self.index(0, 2)
            right = self.index(len(self.items) - 1, 2)
            self.dataChanged.emit(left, right, [
                Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole])

    def set_active_stat(self, key):
        if key not in STAT_LABELS.values() or self.active_stat == key:
            return
        self.active_stat = key
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 3, 3)
        if self.items:
            self.dataChanged.emit(
                self.index(0, 3), self.index(len(self.items) - 1, 3), [
                    Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole])

    def price_item(self, name):
        return self._prices.get(_item_key(name))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        label, key = self.COLUMNS[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                f"Best {STAT_NAMES.get(self.active_stat, self.active_stat)}"
                if key == "selected" else label)
        if role == Qt.ItemDataRole.ToolTipRole:
            if key == "selected":
                return "Selected comparison stat; choose another stat above"
            if key in {"name", "effects"}:
                return (
                    "Click an item name to open its complete native card"
                    if key == "name" else
                    "Click, proc, worn, focus, and bard effects")
            return f"Click to sort equipment by {label}"
        return None

    def _value(self, item, key):
        if key == "name":
            return item.name
        if key == "price":
            price = self.price_item(item.name) or {}
            return int(float(price.get("a30") or 0))
        if key == "selected":
            return item.stat(self.active_stat)
        if key == "effects":
            return item.effect_text
        return item.stat(key)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        key = self.COLUMNS[index.column()][1]
        value = self._value(item, key)
        if role == Qt.ItemDataRole.UserRole:
            return value.casefold() if isinstance(value, str) else value
        if role == Qt.ItemDataRole.ToolTipRole:
            if key == "name":
                binding = "NO DROP" if item.nodrop else "Droppable"
                era = item.era.title() if item.era else "Era not indexed"
                return (
                    "Open stats, effects, prices, drops, and Wiki details\n"
                    f"{binding} · {era}")
            if key == "effects":
                return item.effect_text or "No click, proc, worn, focus, or bard effect"
            label = (
                STAT_NAMES.get(self.active_stat, self.active_stat)
                if key == "selected" else self.COLUMNS[index.column()][0])
            return f"{item.name} · {label}: {value:+d}" if value else f"{item.name} · {label}: 0"
        if role == Qt.ItemDataRole.ForegroundRole and key == "name":
            return QColor("#D2B873")
        if role == Qt.ItemDataRole.ForegroundRole and key == "effects" and value:
            return QColor("#8FD7C2")
        if role == Qt.ItemDataRole.FontRole and key == "name":
            font = QFont()
            font.setBold(True)
            font.setUnderline(True)
            return font
        if role == Qt.ItemDataRole.TextAlignmentRole and key not in {
                "name", "effects"}:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if key == "price":
            return f"{value:,} pp" if value else "—"
        if key in {"name", "effects"}:
            return str(value)
        return f"{value:+d}" if value else "—"


class GearFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.class_bit = 0
        self.race_bit = 0
        self.slot_bit = 0
        self.effect_kind = ""
        self.tradeability = ""
        self.era = ""
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_query(self, query):
        self.query = str(query or "").strip().casefold()
        _invalidate_proxy_rows(self)

    def set_gear_filter(self, kind, bit):
        setattr(self, f"{kind}_bit", int(bit or 0))
        _invalidate_proxy_rows(self)

    def set_effect_filter(self, kind):
        self.effect_kind = str(kind or "").casefold()
        _invalidate_proxy_rows(self)

    def set_tradeability_filter(self, value):
        self.tradeability = str(value or "").casefold()
        _invalidate_proxy_rows(self)

    def set_era_filter(self, value):
        self.era = str(value or "").casefold()
        _invalidate_proxy_rows(self)

    def filterAcceptsRow(self, source_row, source_parent):
        item = self.sourceModel().items[source_row]
        if self.query and self.query not in item.search_text:
            return False
        if self.class_bit and not item.classes & self.class_bit:
            return False
        if self.race_bit and not item.races & self.race_bit:
            return False
        if self.slot_bit and not item.slots & self.slot_bit:
            return False
        if self.effect_kind and not item.effects(self.effect_kind):
            return False
        if self.tradeability == "droppable" and item.nodrop:
            return False
        if self.tradeability == "nodrop" and not item.nodrop:
            return False
        if self.era and item.era != self.era:
            return False
        return True


class LocalAuctionModel(QAbstractTableModel):
    COLUMNS = (("Time", "time"), ("Seller", "seller"), ("Message", "message"))

    def __init__(self):
        super().__init__()
        self.items = []

    def add(self, item):
        self.beginInsertRows(QModelIndex(), 0, 0)
        self.items.insert(0, item)
        self.endInsertRows()
        if len(self.items) > 500:
            self.beginRemoveRows(QModelIndex(), 500, len(self.items) - 1)
            del self.items[500:]
            self.endRemoveRows()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.items[index.row()].get(self.COLUMNS[index.column()][1], "")


class LocalAuctionFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""

    def set_query(self, query):
        self.query = query.strip().casefold()
        _invalidate_proxy_rows(self)

    def filterAcceptsRow(self, source_row, source_parent):
        item = self.sourceModel().items[source_row]
        haystack = f"{item.get('seller', '')} {item.get('message', '')}".casefold()
        return not self.query or self.query in haystack


class WikiItemCard(UniformScaleDialog):
    """Small native EverQuest-style item card backed by P99 Wiki."""

    wiki_entity_requested = Signal(str, str, str)

    def __init__(self, item, parent=None):
        super().__init__(
            QSize(500, 430), parent, minimum_size=QSize(175, 151),
            initial_size=QSize(450, 387))
        self.item = item
        self.item_name = str(item.get("n") or "Item")
        self.wiki_name = self.item_name.replace("Spell: ", "")
        self.wiki_url = P99_WIKI_URL.format(
            slug=quote(self.wiki_name.replace(" ", "_")))
        self.setObjectName("WikiItemDialog")
        self.setWindowTitle(f"Vantage · {self.item_name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        outer = QVBoxLayout(self.scaled_surface)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        card = QFrame()
        card.setObjectName("WikiItemCard")
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setHorizontalSpacing(12)
        card_layout.setVerticalSpacing(5)

        self.icon = QLabel("?")
        self.icon.setObjectName("WikiItemIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFixedSize(66, 66)
        self.icon.setToolTip("Classic icon provided by Project 1999 Wiki")
        card_layout.addWidget(self.icon, 0, 0, 2, 1)

        self.name_label = QLabel(self.item_name)
        self.name_label.setObjectName("WikiItemName")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.name_label.setToolTip("Item name on Project 1999 Wiki")
        card_layout.addWidget(self.name_label, 0, 1)

        self.source = QLabel("PROJECT 1999 WIKI · LOADING…")
        self.source.setObjectName("WikiItemSource")
        self.source.setToolTip(
            "Stats and effects come from the local P99 item index; the item card, "
            "icon, drops, and secondary price come from Project 1999 Wiki; "
            "PigParse Green remains the price source of truth")
        card_layout.addWidget(self.source, 1, 1)

        self.attributes = QLabel(gear_item_summary_html(item.get("_gear")))
        self.attributes.setObjectName("WikiItemAttributes")
        self.attributes.setTextFormat(Qt.TextFormat.RichText)
        self.attributes.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.attributes.setWordWrap(True)
        self.attributes.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.attributes.setToolTip(
            "Sortable stats plus click, proc, worn, focus, and bard effects "
            "from the local P99 item index")
        card_layout.addWidget(self.attributes, 2, 0, 1, 2)

        self.stats = QLabel("Loading item details…")
        self.stats.setObjectName("WikiItemStats")
        self.stats.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.stats.setWordWrap(True)
        self.stats.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats.setToolTip("Item stats from the P99 Wiki page")
        card_layout.addWidget(self.stats, 3, 0, 1, 2)

        self.drops = QLabel("Loading drop source and location…")
        self.drops.setObjectName("WikiItemDrops")
        self.drops.setWordWrap(True)
        self.drops.setTextFormat(Qt.TextFormat.RichText)
        self.drops.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.drops.setOpenExternalLinks(False)
        self.drops.linkActivated.connect(self._internal_wiki_link)
        self.drops.setToolTip(
            "NPC and zone from Project 1999 Wiki; each name opens its card")
        card_layout.addWidget(self.drops, 4, 0, 1, 2)
        card_layout.setColumnStretch(1, 1)
        card_layout.setRowStretch(3, 1)
        outer.addWidget(scrollable(card, "WikiItemCardScroll"), 1)

        prices = []
        for label, key in (("30d", "a30"), ("60d", "a60"), ("90d", "a90")):
            value = item.get(key)
            if isinstance(value, (int, float)) and value > 0:
                prices.append(f"{label}: {int(value):,} pp")
        self._pig_price_text = (
            " · ".join(prices) if prices else "no recent price")
        self.price = QLabel(
            "PigParse Green · " + self._pig_price_text +
            "\nP99 Wiki Green · loading price…")
        self.price.setObjectName("WikiItemPrice")
        self.price.setWordWrap(True)
        self.price.setToolTip(
            "Vantage averages both sources only when their recent references "
            "differ by 30% or less")
        outer.addWidget(self.price)

        actions = QHBoxLayout()
        actions.addStretch(1)
        open_wiki = QPushButton("Open P99 Wiki")
        open_wiki.setIcon(game_icon("map"))
        open_wiki.setToolTip("Open the full item page in your browser")
        open_wiki.clicked.connect(lambda: webbrowser.open(self.wiki_url))
        actions.addWidget(open_wiki)
        close = QPushButton("Close")
        close.setToolTip("Close this card")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        outer.addLayout(actions)

    def set_item_data(self, data, cached=False):
        self.name_label.setText(data.get("name") or self.item_name)
        self.stats.setText(data.get("stats") or "No stats available.")
        drops = data.get("drops") or []
        if drops:
            rows = []
            for entry in drops:
                npc = html.escape(str(entry.get("npc") or "Unknown"))
                zone = html.escape(str(entry.get("zone") or "Zone not listed"))
                npc_url = html.escape(str(entry.get("npc_url") or ""), quote=True)
                zone_url = html.escape(str(entry.get("zone_url") or ""), quote=True)
                npc_target = quote(str(
                    entry.get("npc_target") or entry.get("npc") or ""), safe="")
                zone_target = quote(str(
                    entry.get("zone_target") or entry.get("zone") or ""), safe="")
                npc_link = (
                    f'<a href="vantage://wiki/npc/{npc_target}">{npc}</a>'
                    if npc_url else npc)
                zone_link = (
                    f'<a href="vantage://wiki/zone/{zone_target}">{zone}</a>'
                    if zone_url else zone)
                rows.append(
                    f'<tr><td><b>Dropped by</b></td><td>{npc_link}</td>'
                    f'<td><b>Where</b></td><td>{zone_link}</td></tr>')
            self.drops.setText(
                '<table cellspacing="0" cellpadding="2">' +
                "".join(rows) + "</table>")
        else:
            self.drops.setText(
                "<b>Origin</b> · The Wiki does not list a drop for this item.")
        self.source.setText(
            "PROJECT 1999 WIKI · " + ("LOCAL CACHE" if cached else "UPDATED"))
        self._set_auction_price(data.get("auction") or {})

    def _set_auction_price(self, auction):
        comparison = combined_market_price(self.item, auction)
        wiki_price = comparison["wiki"]
        if not wiki_price:
            self.price.setText(
                "PigParse Green · " + self._pig_price_text +
                "\nP99 Wiki Green · no recognized recent price")
            return
        wiki_period = str(auction.get("reference_period") or "recent")
        seen = int(auction.get("recent_samples") or 0)
        last_date = str(auction.get("last_date") or "")
        wiki_line = (
            f"P99 Wiki Green · {wiki_price:,} pp ({wiki_period}"
            + (f" · {seen} listings" if seen else "")
            + (f" · {last_date}" if last_date else "") + ")")
        if comparison["close"]:
            headline = (
                f"COMBINED ESTIMATE · {comparison['combined']:,} pp\n"
                f"Sources agree · {comparison['difference_percent']:.1f}% difference")
        elif comparison["pig"]:
            headline = (
                "NOT COMBINED · sources differ by "
                f"{comparison['difference_percent']:.1f}%")
        else:
            headline = "WIKI REFERENCE · PigParse has no recent price"
        warning = str(auction.get("warning") or "")
        self.price.setText(
            headline + "\nPigParse Green · " + self._pig_price_text +
            "\n" + wiki_line + ("\n⚠ " + warning if warning else ""))

    def _internal_wiki_link(self, link):
        prefix = "vantage://wiki/"
        if not str(link).startswith(prefix):
            return
        parts = str(link)[len(prefix):].split("/", 1)
        if len(parts) != 2:
            return
        kind, encoded_target = parts
        target = unquote(encoded_target)
        label = target.replace("_", " ")
        self.wiki_entity_requested.emit(target, label, kind)

    def set_icon_data(self, payload):
        pixmap = QPixmap()
        if pixmap.loadFromData(payload):
            self.icon.setText("")
            self.icon.setPixmap(pixmap.scaled(
                56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation))

    def set_error(self, message):
        self.source.setText("PROJECT 1999 WIKI · OFFLINE")
        if self.stats.text() == "Loading item details…":
            self.stats.setText(
                "The item card could not be loaded now. You can open the full page.\n\n"
                f"Details: {message}")


class WikiEntityCard(UniformScaleDialog):
    """In-app P99 Wiki summary for a drop NPC or zone."""

    def __init__(self, name, kind, parent=None):
        super().__init__(
            QSize(430, 310), parent, minimum_size=QSize(151, 109),
            initial_size=QSize(387, 279))
        self.target_name = name
        self.entity_kind = kind
        self.setObjectName("WikiEntityDialog")
        self.setWindowTitle(f"Vantage · {name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        outer = QVBoxLayout(self.scaled_surface)
        outer.setContentsMargins(7, 7, 7, 7)
        outer.setSpacing(5)
        self.name_label = QLabel(name.replace("_", " "))
        self.name_label.setObjectName("WikiEntityName")
        self.name_label.setWordWrap(True)
        self.name_label.setToolTip("Name from Project 1999 Wiki")
        outer.addWidget(self.name_label)
        self.source = QLabel("PROJECT 1999 WIKI · LOADING…")
        self.source.setObjectName("WikiItemSource")
        self.source.setToolTip("Information loaded inside Vantage")
        outer.addWidget(self.source)
        self.facts = QLabel("Loading details…")
        self.facts.setObjectName("WikiEntityFacts")
        self.facts.setWordWrap(True)
        self.facts.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.facts.setToolTip("Key facts from the Wiki page")
        outer.addWidget(self.facts)
        self.summary = QLabel("")
        self.summary.setObjectName("WikiEntitySummary")
        self.summary.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setToolTip("Short description from Project 1999 Wiki")
        outer.addWidget(scrollable(self.summary, "WikiEntityScroll"), 1)
        close = QPushButton("Close")
        close.setToolTip("Close this card")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(close)
        outer.addLayout(actions)

    def set_entity_data(self, data, cached=False):
        self.name_label.setText(data.get("name") or self.target_name)
        facts = data.get("facts") or []
        self.facts.setText(" · ".join(
            f"{label}: {value}" for label, value in facts) or
            "No additional structured details.")
        self.summary.setText(data.get("summary") or "No description available.")
        self.source.setText(
            f"PROJECT 1999 WIKI · {data.get('kind', '').upper()} · " +
            ("LOCAL CACHE" if cached else "UPDATED"))

    def set_error(self, message):
        self.source.setText("PROJECT 1999 WIKI · OFFLINE")
        self.facts.setText("This card could not be loaded right now.")
        self.summary.setText(str(message))


class AuctionQuantity(QFrame):
    """Compact themed quantity stepper without native Windows rockers."""

    valueChanged = Signal(int)

    def __init__(self, item_name="", parent=None):
        super().__init__(parent)
        self.setObjectName("AuctionQuantity")
        self._value = 1
        self.setAccessibleName(f"Quantity of {item_name}".strip())
        self.setToolTip(
            "Choose how many copies; 2 becomes ‘2x Item’ in the message")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)
        self.minus = QToolButton()
        self.minus.setObjectName("AuctionQuantityButton")
        self.minus.setText("−")
        self.minus.setAutoRaise(True)
        self.minus.setAccessibleName(f"Decrease quantity of {item_name}".strip())
        self.minus.setToolTip("Decrease quantity")
        self.minus.clicked.connect(lambda: self.setValue(self._value - 1))
        layout.addWidget(self.minus)
        self.label = QLabel("1")
        self.label.setObjectName("AuctionQuantityValue")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAccessibleName(f"Current quantity of {item_name}".strip())
        layout.addWidget(self.label, 1)
        self.plus = QToolButton()
        self.plus.setObjectName("AuctionQuantityButton")
        self.plus.setText("+")
        self.plus.setAutoRaise(True)
        self.plus.setAccessibleName(f"Increase quantity of {item_name}".strip())
        self.plus.setToolTip("Increase quantity")
        self.plus.clicked.connect(lambda: self.setValue(self._value + 1))
        layout.addWidget(self.plus)
        self._sync()

    def value(self):
        return self._value

    def setValue(self, value):
        value = max(1, min(99, int(value)))
        if value == self._value:
            return
        self._value = value
        self._sync()
        self.valueChanged.emit(value)

    def _sync(self):
        self.label.setText(str(self._value))
        self.label.setAccessibleDescription(
            f"{self._value} item{'s' if self._value != 1 else ''}")
        self.minus.setEnabled(self._value > 1)
        self.plus.setEnabled(self._value < 99)


class AuctionComposer(QWidget):
    """Compact WTS/WTB message builder backed by the local P99 item index."""

    def __init__(self, price_resolver=None, parent=None):
        super().__init__(parent)
        self._catalog = []
        self._by_name = {}
        self._price_resolver = price_resolver or (lambda _name: 0)
        self._raw_lines = []
        self._linked_lines = []
        self._copy_index = 0
        self._token_target = None

        root = QVBoxLayout(self)
        root.setContentsMargins(5, 4, 5, 5)
        root.setSpacing(4)

        self.guide = QLabel(
            "Search item → Add → set price and quantity → Copy WTS. "
            "Use EQ Hotbutton for clickable links.")
        self.guide.setObjectName("MarketStatSummary")
        self.guide.setWordWrap(True)
        self.guide.setToolTip(
            "Copy WTS pastes clean chat text immediately. EQ Hotbutton installs "
            "clickable Titanium links; no inventory export is required.")
        root.addWidget(self.guide)

        source_row = QHBoxLayout()
        source_row.setSpacing(4)
        self.link_status = QLabel(
            "Clickable links use an EQ social hotbutton · no inventory file needed")
        self.link_status.setObjectName("MarketGearSource")
        self.link_status.setAccessibleName("P99 item link source")
        self.link_status.setToolTip(
            "Titanium strips generated link bytes from normal chat paste. "
            "Vantage can install the same message into a character social button.")
        source_row.addWidget(self.link_status, 1)
        self.character_ini = QComboBox()
        self.character_ini.setObjectName("AuctionCharacterIni")
        self.character_ini.setMinimumContentsLength(12)
        self.character_ini.setAccessibleName(
            "EverQuest character for clickable auction links")
        self.character_ini.setToolTip(
            "Characters detected beside the linked EverQuest Logs folder")
        self.character_ini.currentIndexChanged.connect(
            self._sync_hotbutton_enabled)
        source_row.addWidget(self.character_ini)
        self.camped_out = QCheckBox("Fully camped out")
        self.camped_out.setAccessibleName(
            "Confirm the selected character is fully camped out")
        self.camped_out.setToolTip(
            "Required because EverQuest overwrites character INI files while "
            "the character is logged in")
        self.camped_out.toggled.connect(self._sync_hotbutton_enabled)
        source_row.addWidget(self.camped_out)
        self.paste_help_button = QPushButton("How to paste")
        self.paste_help_button.setIcon(game_icon("help"))
        self.paste_help_button.setCheckable(True)
        self.paste_help_button.setToolTip(
            "Show or hide the one-time EverQuest paste-key instructions")
        self.paste_help_button.clicked.connect(self.show_paste_help)
        source_row.addWidget(self.paste_help_button)
        root.addLayout(source_row)

        self.paste_help = QLabel(
            "In EverQuest: Alt+O → Keys → bind “Paste from Clipboard” once. "
            "Copy WTS pastes plain text. For clickable names, fully camp out and "
            "use EQ Hotbutton; the links load on the next character login.")
        self.paste_help.setObjectName("MarketGearSource")
        self.paste_help.setWordWrap(True)
        self.paste_help.setVisible(False)
        self.paste_help.setAccessibleName("EverQuest paste instructions")
        root.addWidget(self.paste_help)

        picker = QHBoxLayout()
        picker.setSpacing(4)
        self.trade_type = QComboBox()
        self.trade_type.addItems(("Sell items (WTS)", "Buy items (WTB)"))
        self.trade_type.setAccessibleName("Auction message type")
        self.trade_type.setToolTip(
            "WTS automatically creates clickable P99 item links; WTB uses plain names")
        self.trade_type.currentIndexChanged.connect(self._trade_type_changed)
        picker.addWidget(self.trade_type)

        self.item_search = QLineEdit()
        self.item_search.setPlaceholderText("Find an item to sell or buy…")
        self.item_search.setClearButtonEnabled(True)
        self.item_search.setAccessibleName("Find an item for the auction message")
        self.item_search.setToolTip(
            "Type any part of an item name, choose a suggestion, then press Enter or Add")
        clear_item_search = self.item_search.findChild(QToolButton)
        if clear_item_search:
            clear_item_search.setAccessibleName("Clear item search")
            clear_item_search.setToolTip("Clear the item search text")
        self._catalog_model = QStringListModel(self)
        self._completer = QCompleter(self._catalog_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setMaxVisibleItems(14)
        self.item_search.setCompleter(self._completer)
        self.item_search.returnPressed.connect(self.add_search_item)
        picker.addWidget(self.item_search, 1)
        self.add_button = QPushButton("Add")
        self.add_button.setIcon(game_icon("add"))
        self.add_button.setAccessibleName("Add selected item")
        self.add_button.setToolTip("Add this item to the message builder")
        self.add_button.clicked.connect(self.add_search_item)
        picker.addWidget(self.add_button)
        self.copy_button = QPushButton("Copy WTS")
        self.copy_button.setIcon(game_icon("copy"))
        self.copy_button.setAccessibleName("Copy the EverQuest WTS message")
        self.copy_button.setToolTip(
            "Copy clean WTS text; then use EverQuest's Paste from Clipboard key")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_next)
        picker.addWidget(self.copy_button)
        self.hotbutton_button = QPushButton("EQ Hotbutton…")
        self.hotbutton_button.setIcon(game_icon("export"))
        self.hotbutton_button.setAccessibleName(
            "EQ Hotbutton — install clickable WTS links")
        self.hotbutton_button.setToolTip(
            "Install real clickable item links into a free character social button; "
            "fully camp out first")
        self.hotbutton_button.setEnabled(False)
        self.hotbutton_button.clicked.connect(self.install_hotbuttons)
        picker.addWidget(self.hotbutton_button)
        root.addLayout(picker)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced wording (optional)")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setAccessibleName("Advanced wording (optional)")
        self.advanced_toggle.setAccessibleDescription(
            "Collapsed optional auction message customization")
        self.advanced_toggle.setToolTip(
            "Optional: change separators, ending text, templates, and tokens")
        root.addWidget(self.advanced_toggle)

        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(3)
        templates = QGridLayout()
        templates.setSpacing(4)
        templates.addWidget(QLabel("Message"), 0, 0)
        self.message_template = QLineEdit("{type} {items} {suffix}")
        self.message_template.setAccessibleName("Auction message template")
        self.message_template.setToolTip(
            "Arrange the sale type, selected items, and ending. Example: "
            "{type} {items: // } {suffix}")
        templates.addWidget(self.message_template, 0, 1, 1, 5)
        templates.addWidget(QLabel("Each item"), 1, 0)
        self.item_template = QLineEdit("{qty} {item} {price}")
        self.item_template.setAccessibleName("Item template")
        self.item_template.setToolTip(
            "Choose how every selected item, price, and optional quantity appears")
        templates.addWidget(self.item_template, 1, 1, 1, 2)
        templates.addWidget(QLabel("Between"), 1, 3)
        self.separator = QLineEdit(" // ")
        self.separator.setAccessibleName("Separator between items")
        self.separator.setToolTip(
            "Characters placed between items; try //, |, comma, or a single space")
        templates.addWidget(self.separator, 1, 4)
        templates.addWidget(QLabel("End"), 1, 5)
        self.suffix = QLineEdit("PST")
        self.suffix.setAccessibleName("Auction message ending")
        self.suffix.setToolTip("Optional ending such as PST, send tell, or OBO")
        templates.addWidget(self.suffix, 1, 6)
        templates.setColumnStretch(1, 1)
        advanced_layout.addLayout(templates)

        token_row = QHBoxLayout()
        token_row.setSpacing(3)
        token_label = QLabel("Insert token")
        token_label.setToolTip(
            "Click a field above, then click a token. No token spelling is required.")
        token_row.addWidget(token_label)
        for label, token, target in (
                ("Sale type", "{type}", self.message_template),
                ("Items", "{items}", self.message_template),
                ("Ending", "{suffix}", self.message_template),
                ("Item link/name", "{item}", self.item_template),
                ("Price", "{price}", self.item_template),
                ("Quantity", "{qty}", self.item_template)):
            button = QToolButton()
            button.setText(label)
            button.setAccessibleName(f"Insert {label} token")
            button.setToolTip(f"Insert {token} into the {target.accessibleName().lower()}")
            button.clicked.connect(
                lambda _checked=False, value=token, field=target:
                self._insert_token(value, field))
            token_row.addWidget(button)
        token_row.addStretch(1)
        advanced_layout.addLayout(token_row)
        self.advanced_panel.setVisible(False)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        root.addWidget(self.advanced_panel)

        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(("Item", "Price", "Quantity", ""))
        for column, tooltip in enumerate((
                "Selected P99 item name",
                "Editable asking or buying price",
                "Quantity advertised",
                "Remove this item")):
            self.items.horizontalHeaderItem(column).setToolTip(tooltip)
        self.items.setAccessibleName("Selected auction items")
        self.items.setToolTip(
            "Edit prices and quantities here; the preview updates immediately")
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.setAlternatingRowColors(True)
        self.items.verticalHeader().setVisible(False)
        self.items.verticalHeader().setDefaultSectionSize(28)
        header = self.items.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.items.setColumnWidth(1, 92)
        self.items.setColumnWidth(2, 82)
        self.items.setColumnWidth(3, 34)
        corner = self.items.findChild(QToolButton)
        if corner:
            corner.setAccessibleName("Select all auction items")
            corner.setToolTip("Select every item row")
        self.items.setFixedHeight(58)
        root.addWidget(self.items)

        preview_header = QHBoxLayout()
        self.preview_status = QLabel("Choose one or more items")
        self.preview_status.setObjectName("MarketStatSummary")
        self.preview_status.setToolTip(
            "EverQuest chat limit and the number of generated messages")
        preview_header.addWidget(self.preview_status, 1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setIcon(game_icon("delete"))
        self.clear_button.setToolTip("Remove all selected items")
        self.clear_button.clicked.connect(self.clear_items)
        preview_header.addWidget(self.clear_button)
        root.addLayout(preview_header)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumBlockCount(20)
        self.preview.setMaximumHeight(88)
        self.preview.setPlaceholderText(
            "The exact message that will paste into EverQuest appears here.")
        self.preview.setAccessibleName("Auction message preview")
        self.preview.setToolTip(
            "This is the exact plain-text message copied to the clipboard. "
            "Use EQ Hotbutton when you need clickable item names.")
        root.addWidget(self.preview)

        self.paste_note = QLabel(
            "Copy WTS = instant plain text · EQ Hotbutton = clickable item links.")
        self.paste_note.setObjectName("MarketGearSource")
        self.paste_note.setWordWrap(True)
        self.paste_note.setToolTip(
            "Titanium strips generated item-link bytes from ordinary chat paste, "
            "so linked messages must be loaded from a character social button.")
        root.addWidget(self.paste_note)
        root.addStretch(1)

        for field in (
                self.message_template, self.item_template,
                self.separator, self.suffix):
            field.installEventFilter(self)
            field.textChanged.connect(self._rebuild)
        self._token_target = self.message_template
        self._refresh_character_ini_choices()
        self._rebuild()

    def _toggle_advanced(self, shown):
        self.advanced_panel.setVisible(bool(shown))
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        self.advanced_toggle.setAccessibleDescription(
            f"{'Expanded' if shown else 'Collapsed'} optional auction message "
            "customization")

    def _trade_type_changed(self, *_args):
        selling = self.trade_type.currentIndex() == 0
        self.guide.setText(
            "Search item → Add → set price and quantity → Copy WTS. "
            "Use EQ Hotbutton for clickable links." if selling else
            "Search item → Add → set your offer and quantity → Copy WTB.")
        self.link_status.setVisible(selling)
        self.character_ini.setVisible(selling)
        self.camped_out.setVisible(selling)
        self.hotbutton_button.setVisible(selling)
        self.copy_button.setText("Copy WTS" if selling else "Copy WTB")
        self._sync_copy_button_accessibility()
        self.paste_note.setText(
            f"Copy {'WTS' if selling else 'WTB'} → focus EQ chat → press your "
            "Paste from Clipboard key.")
        self._refresh_catalog_model()
        self._rebuild()

    @staticmethod
    def _character_ini_label(path):
        match = re.match(
            r"^(?P<character>.+?)_(?P<server>project1999|p1999green|"
            r"p1999blue|p1999pvp|p1999red)\.ini$",
            path.name, re.IGNORECASE)
        if not match:
            return path.stem
        server = {
            "p1999green": "Green", "p1999blue": "Blue",
            "p1999pvp": "Red", "p1999red": "Red",
            "project1999": "P99",
        }.get(match.group("server").casefold(), match.group("server"))
        return f"{match.group('character')} · {server}"

    def _refresh_character_ini_choices(self):
        previous = str(self.character_ini.currentData() or "")
        logs = config.data.get("general", {}).get("eq_log_dir", "")
        root = everquest_root_from_logs(logs)
        candidates = []
        if root:
            try:
                candidates = sorted((
                    path for path in root.glob("*.ini")
                    if path.is_file() and not path.name.casefold().startswith("ui_")
                    and re.search(
                        r"_(?:project1999|p1999(?:green|blue|pvp|red))\.ini$",
                        path.name, re.IGNORECASE)
                ), key=lambda path: path.name.casefold())
            except OSError:
                candidates = []
        self.character_ini.blockSignals(True)
        self.character_ini.clear()
        if candidates:
            for path in candidates:
                self.character_ini.addItem(
                    self._character_ini_label(path), str(path))
            index = self.character_ini.findData(previous)
            self.character_ini.setCurrentIndex(max(0, index))
            self.character_ini.setEnabled(True)
        else:
            self.character_ini.addItem("No P99 character found", "")
            self.character_ini.setEnabled(False)
        self.character_ini.blockSignals(False)
        self._sync_hotbutton_enabled()
        return candidates

    def _sync_hotbutton_enabled(self, *_args):
        selling = self.trade_type.currentIndex() == 0
        self.hotbutton_button.setEnabled(bool(
            selling and self._linked_lines and
            self.character_ini.currentData() and
            self.camped_out.isChecked()))

    def _sync_copy_button_accessibility(self):
        trade_type = "WTB" if self.trade_type.currentIndex() == 1 else "WTS"
        action = "buy" if trade_type == "WTB" else "sale"
        self.copy_button.setAccessibleName(
            f"{self.copy_button.text()} auction message")
        self.copy_button.setAccessibleDescription(
            f"Copies the next plain-text {action} message to the clipboard")
        self.copy_button.setToolTip(
            f"Copy clean {trade_type} text; then use EverQuest's "
            "Paste from Clipboard key")

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.FocusIn and watched in {
                self.message_template, self.item_template,
                self.separator, self.suffix}):
            self._token_target = watched
        return super().eventFilter(watched, event)

    def _insert_token(self, token, preferred_field):
        field = self._token_target
        if field not in {self.message_template, self.item_template}:
            field = preferred_field
        # Item-only tokens always go to the per-item field; message-only tokens
        # always go to the message field. This keeps the simple buttons safe.
        if token in {"{item}", "{price}", "{qty}"}:
            field = self.item_template
        elif token in {"{type}", "{items}", "{suffix}"}:
            field = self.message_template
        field.insert(token)
        field.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_catalog(self, items):
        self._catalog = sorted(
            (item for item in (items or ()) if isinstance(item, GearItem)),
            key=lambda item: item.name.casefold())
        self._by_name = {_item_key(item.name): item for item in self._catalog}
        self._refresh_catalog_model()

    def _refresh_catalog_model(self):
        names = sorted(
            {item.name for item in self._catalog}, key=str.casefold)
        placeholder = (
            f"Find among {len(names):,} P99 items…" if names else
            "Search item name…")
        self._catalog_model.setStringList(names)
        self.item_search.setPlaceholderText(placeholder)

    def _matching_item(self, text):
        query = _item_key(text)
        exact = self._by_name.get(query)
        if exact:
            return exact
        return next((
            item for item in self._catalog
            if query and query in _item_key(item.name)), None)

    def add_search_item(self):
        item = self._matching_item(self.item_search.text())
        if not item:
            self._set_preview_status(
                "Choose an item from the suggestions", announce=True)
            self.item_search.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        for row in range(self.items.rowCount()):
            existing = self.items.item(row, 0)
            if existing and _item_key(existing.text()) == _item_key(item.name):
                self.items.selectRow(row)
                self._set_preview_status(
                    f"{item.name} is already selected", announce=True)
                return False

        row = self.items.rowCount()
        self.items.insertRow(row)
        name_cell = QTableWidgetItem(item.name)
        link_id = int(getattr(item, "peqId", 0) or 0)
        name_cell.setData(Qt.ItemDataRole.UserRole, link_id)
        name_cell.setFlags(name_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_cell.setToolTip(
            (f"Automatic clickable P99 link · item ID {link_id}"
             if link_id else
             "No verified P99 link ID · this item will use plain text"))
        self.items.setItem(row, 0, name_cell)

        price = QLineEdit()
        suggested = int(self._price_resolver(item.name) or 0)
        price.setText(f"{suggested}p" if suggested else "")
        price.setPlaceholderText("price")
        price.setAccessibleName(f"Price for {item.name}")
        price.setToolTip(
            "Editable asking price. Accepts 500, 500p, 500pp, 1k, or 1.5k")
        price.editingFinished.connect(
            lambda field=price: field.setText(
                normalize_auction_price(field.text())))
        price.textChanged.connect(self._rebuild)
        self.items.setCellWidget(row, 1, price)

        quantity = AuctionQuantity(item.name)
        quantity.valueChanged.connect(self._rebuild)
        self.items.setCellWidget(row, 2, quantity)

        remove = QToolButton()
        remove.setIcon(game_icon("delete"))
        remove.setAccessibleName(f"Remove {item.name}")
        remove.setToolTip(f"Remove {item.name} from this message")
        remove.clicked.connect(lambda _checked=False, cell=name_cell: self._remove_cell(cell))
        self.items.setCellWidget(row, 3, remove)

        self.item_search.clear()
        self._copy_index = 0
        self._resize_item_table()
        self._rebuild()
        _announce_accessible(self, f"Added {item.name} to the auction message")
        return True

    def _set_preview_status(self, text, announce=False, assertive=False):
        self.preview_status.setText(str(text))
        if announce:
            _announce_accessible(self, text, assertive=assertive)

    def _resize_item_table(self):
        visible_rows = max(1, min(7, self.items.rowCount()))
        self.items.setFixedHeight(
            self.items.horizontalHeader().height() + visible_rows * 28 + 3)

    def show_paste_help(self, shown=False):
        """Keep help inline so an embedded scaled surface is never detached."""
        self.paste_help.setVisible(bool(shown))
        self.paste_help_button.setText(
            "Hide paste help" if shown else "How to paste")
        self.paste_help_button.setAccessibleName(
            self.paste_help_button.text())
        self.paste_help_button.setAccessibleDescription(
            f"{'Expanded' if shown else 'Collapsed'} EverQuest paste instructions")

    def _remove_cell(self, name_cell):
        row = self.items.row(name_cell)
        if row >= 0:
            self.items.removeRow(row)
        self._copy_index = 0
        self._resize_item_table()
        self._rebuild()

    def clear_items(self):
        self.items.setRowCount(0)
        self._copy_index = 0
        self._resize_item_table()
        self._rebuild()

    def selected_entries(self):
        entries = []
        for row in range(self.items.rowCount()):
            name_cell = self.items.item(row, 0)
            price = self.items.cellWidget(row, 1)
            quantity = self.items.cellWidget(row, 2)
            if not name_cell:
                continue
            entries.append(AuctionEntry(
                int(name_cell.data(Qt.ItemDataRole.UserRole) or 0),
                name_cell.text(),
                price.text() if isinstance(price, QLineEdit) else "",
                quantity.value() if isinstance(quantity, AuctionQuantity) else 1))
        return entries

    def _rebuild(self, *_args):
        trade_type = "WTB" if self.trade_type.currentIndex() == 1 else "WTS"
        selected = self.selected_entries()
        try:
            self._raw_lines = compose_auction_lines(
                selected, trade_type,
                self.message_template.text(), self.item_template.text(),
                self.separator.text(), self.suffix.text(), clickable=False)
            self._linked_lines = compose_auction_lines(
                selected, trade_type,
                self.message_template.text(), self.item_template.text(),
                self.separator.text(), self.suffix.text(), clickable=True)
        except ValueError as error:
            self._raw_lines = []
            self._linked_lines = []
            self.preview.setPlainText("")
            self._set_preview_status(str(error))
            self.copy_button.setEnabled(False)
            self.hotbutton_button.setEnabled(False)
            return
        previews = [
            f"{index + 1}. {line}"
            for index, line in enumerate(self._raw_lines)]
        self.preview.setPlainText("\n".join(previews))
        self.copy_button.setEnabled(bool(self._raw_lines))
        self._sync_hotbutton_enabled()
        if not self._raw_lines:
            self._set_preview_status("Choose one or more items")
            self.copy_button.setText(
                "Copy WTB" if trade_type == "WTB" else "Copy WTS")
            self._sync_copy_button_accessibility()
            return
        self._copy_index %= len(self._raw_lines)
        lengths = [len(line) for line in self._raw_lines]
        too_long = any(length > P99_CHAT_LIMIT for length in lengths)
        linked = sum(1 for entry in selected if entry.id) \
            if trade_type == "WTS" else 0
        link_state = (
            f" · {linked} link{'s' if linked != 1 else ''} ready for EQ Hotbutton"
            if linked else " · plain text only")
        self._set_preview_status(
            f"{len(self._raw_lines)} message{'s' if len(self._raw_lines) != 1 else ''} · "
            f"{max(lengths)}/{P99_CHAT_LIMIT} characters" + link_state +
            (" · shorten it" if too_long else " · ready"))
        self.copy_button.setText(
            f"Copy {trade_type} {self._copy_index + 1}/{len(self._raw_lines)}")
        self._sync_copy_button_accessibility()
        self.copy_button.setEnabled(not too_long)

    def refresh_prices(self):
        for row in range(self.items.rowCount()):
            name_cell = self.items.item(row, 0)
            price = self.items.cellWidget(row, 1)
            if not name_cell or not isinstance(price, QLineEdit) or price.text().strip():
                continue
            suggested = int(self._price_resolver(name_cell.text()) or 0)
            if suggested:
                price.setText(f"{suggested}p")

    def copy_next(self):
        if not self._raw_lines or not self.copy_button.isEnabled():
            return False
        line = self._raw_lines[self._copy_index]
        if not set_eq_clipboard(line):
            self._set_preview_status(
                "Clipboard is busy · close another clipboard tool and try again",
                announce=True)
            return False
        copied = self._copy_index
        self._copy_index = (self._copy_index + 1) % len(self._raw_lines)
        self._set_preview_status(
            f"Copied {copied + 1}/{len(self._raw_lines)} · plain text ready for EQ",
            announce=True)
        self.copy_button.setText(
            f"Copy {'WTB' if self.trade_type.currentIndex() == 1 else 'WTS'} "
            f"{self._copy_index + 1}/{len(self._raw_lines)}")
        self._sync_copy_button_accessibility()
        return True

    def install_hotbuttons(self):
        if not self._linked_lines:
            self._set_preview_status(
                "Add at least one linked item before installing", announce=True)
            return False
        self._refresh_character_ini_choices()
        selected = str(self.character_ini.currentData() or "")
        if not selected:
            self._set_preview_status(
                "No P99 character found · link the EverQuest Logs folder in Settings",
                announce=True)
            return False
        if not self.camped_out.isChecked():
            self._set_preview_status(
                "Fully camp the selected character out, then check the confirmation",
                announce=True)
            return False
        try:
            slots, backup = install_auction_hotbuttons(
                selected, self._linked_lines)
        except (OSError, UnicodeError, ValueError) as error:
            self._set_preview_status(
                f"Hotbutton not installed · {error}", announce=True)
            return False
        slot_names = ", ".join(
            re.sub(r"^Page(\d+)Button(\d+)$", r"page \1, button \2", slot)
            for slot in slots)
        self._set_preview_status(
            f"Installed · {slot_names} · backup {backup.name} · relog and open Socials",
            announce=True)
        self.camped_out.setChecked(False)
        return True


class GreenMarket(ParserWindow):
    # Market contains search, filters and tables; click-through would make its
    # primary workflow impossible. Keep that overlay-only option out of here.
    _allow_clickthrough = False
    def __init__(self):
        self.name = "market"
        super().__init__()
        if config.data["market"].get("clickthrough"):
            config.data["market"]["clickthrough"] = False
            config.save()
        self.setWindowTitle("Green Market · PigParse")
        self._zone = ""
        self._loaded_online = False
        self._request_in_flight = False
        self._gear_source = "P99 Wiki metadata"
        self._mobile_items = ()
        self._mobile_revision = 0
        self._last_consider_name = ""
        self._consider_card = None
        self._live_alerted_at = {}

        self._network = QNetworkAccessManager(self)
        self._model = MarketModel()
        self._proxy = MarketFilter()
        self._proxy.setSourceModel(self._model)
        self._gear_model = GearModel()
        self._gear_proxy = GearFilter()
        self._gear_proxy.setSourceModel(self._gear_model)
        self._local_model = LocalAuctionModel()
        self._local_proxy = LocalAuctionFilter()
        self._local_proxy.setSourceModel(self._local_model)

        market_body = QWidget()
        self._market_body = market_body
        market_body.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._body_layout = QVBoxLayout(market_body)
        self._body_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._market_scroll = scrollable(market_body, "MarketScroll")
        self._market_scroll.setWidgetResizable(False)
        self._market_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content.addWidget(self._market_scroll, 1)

        toolbar = QWidget()
        toolbar.setObjectName("MarketToolbar")
        self._toolbar_layout = QGridLayout(toolbar)
        self._toolbar_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
        self._toolbar_layout.setContentsMargins(5, 5, 5, 5)
        self._toolbar_layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search item or effect…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search the Green market")
        self.search.setToolTip(
            "Type any part of an item, click, proc, worn, focus, or bard effect; "
            "results filter while you type")
        clear_search = self.search.findChild(QToolButton)
        if clear_search:
            clear_search.setAccessibleName("Clear market search")
            clear_search.setToolTip("Clear the search text")
        self.search.textChanged.connect(self._set_query)

        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.setIcon(game_icon("refresh"))
        self._refresh_button.setToolTip("Refresh prices from PigParse Green")
        self._refresh_button.clicked.connect(self.refresh)
        self._sources_button = QPushButton("Sources")
        self._sources_button.setIcon(game_icon("layers"))
        self._sources_button.setToolTip(
            "View the source of prices, attributes, and item metadata")
        self._sources_button.clicked.connect(self._show_sources)
        self._body_layout.addWidget(toolbar)

        filters = QWidget()
        filters.setObjectName("MarketFilters")
        self._filters_layout = QGridLayout(filters)
        self._filters_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
        self._filters_layout.setContentsMargins(5, 3, 5, 4)
        self._filters_layout.setSpacing(4)
        self.class_filter = self._equipment_combo(
            CLASS_BITS, "Filter by class",
            lambda bit: self._set_equipment_filter("class", bit))
        self.race_filter = self._equipment_combo(
            RACE_BITS, "Filter by race",
            lambda bit: self._set_equipment_filter("race", bit))
        self.slot_filter = self._equipment_combo(
            SLOT_BITS, "Filter by slot",
            lambda bit: self._set_equipment_filter("slot", bit))
        self.gear_status = QLabel("Loading P99 metadata…")
        self.gear_status.setObjectName("MarketGearSource")
        self.gear_status.setWordWrap(True)
        self.gear_status.setToolTip(
            "Class, race, slot, stats, and effect names come from the local "
            "P99 item index and are matched by item name; PigParse supplies prices.")
        self._body_layout.addWidget(filters)

        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(220)
        self.table = self._market_table()
        market_page = QWidget()
        market_layout = QVBoxLayout(market_page)
        market_layout.setContentsMargins(0, 0, 0, 0)
        market_layout.addWidget(self.table)
        self.tabs.addTab(market_page, "PigParse · prices")

        gear_page = QWidget()
        gear_layout = QVBoxLayout(gear_page)
        gear_layout.setContentsMargins(0, 0, 0, 0)
        gear_layout.setSpacing(0)
        gear_tools = QWidget()
        gear_tools.setObjectName("MarketStatToolbar")
        gear_tools_layout = QGridLayout(gear_tools)
        gear_tools_layout.setContentsMargins(5, 3, 5, 3)
        gear_tools_layout.setSpacing(4)
        self.stat_sort = QComboBox()
        for label, key in STAT_OPTIONS:
            self.stat_sort.addItem(f"Best {label}", key)
        self.stat_sort.setAccessibleName("Sort equipment by stat")
        self.stat_sort.setToolTip(
            "Choose the stat shown in the Best column; highest values sort first")
        self.stat_sort.currentIndexChanged.connect(
            lambda _: self._set_stat_sort(self.stat_sort.currentData()))
        gear_tools_layout.addWidget(self.stat_sort, 0, 0)
        self.effect_filter = QComboBox()
        for label, key in EFFECT_OPTIONS:
            self.effect_filter.addItem(label, key)
        self.effect_filter.setAccessibleName("Filter equipment by effect type")
        self.effect_filter.setToolTip(
            "Show items with any, click, proc, worn, focus, or bard effects")
        self.effect_filter.currentIndexChanged.connect(
            lambda _: self._set_effect_filter(self.effect_filter.currentData()))
        gear_tools_layout.addWidget(self.effect_filter, 0, 1)
        self.gear_results = QLabel("Loading equipment stats…")
        self.gear_results.setObjectName("MarketStatSummary")
        self.gear_results.setToolTip(
            "Visible equipment after search, class, race, slot, and effect filters")
        gear_tools_layout.addWidget(self.gear_results, 0, 2, 1, 2)
        self.tradeability_filter = QComboBox()
        for label, key in TRADEABILITY_OPTIONS:
            self.tradeability_filter.addItem(label, key)
        self.tradeability_filter.setAccessibleName(
            "Filter equipment by drop restriction")
        self.tradeability_filter.setToolTip(
            "Show all equipment, only tradable drops, or only NO DROP items")
        self.tradeability_filter.currentIndexChanged.connect(
            lambda _: self._set_tradeability_filter(
                self.tradeability_filter.currentData()))
        gear_tools_layout.addWidget(self.tradeability_filter, 1, 0)
        self.era_filter = QComboBox()
        for label, key in ERA_OPTIONS:
            self.era_filter.addItem(label, key)
        self.era_filter.setAccessibleName("Filter equipment by EverQuest era")
        self.era_filter.setToolTip(
            "Filter items using the Classic, Kunark, and Velious categories "
            "from Project 1999 Wiki")
        self.era_filter.currentIndexChanged.connect(
            lambda _: self._set_era_filter(self.era_filter.currentData()))
        gear_tools_layout.addWidget(self.era_filter, 1, 1)
        self.gear_filter_note = QLabel(
            "Drag a column divider to resize · full values stay in tooltips")
        self.gear_filter_note.setObjectName("MarketStatSummary")
        self.gear_filter_note.setToolTip(
            "Column widths are remembered when Vantage closes")
        gear_tools_layout.addWidget(self.gear_filter_note, 1, 2, 1, 2)
        gear_tools_layout.setColumnStretch(2, 1)
        gear_layout.addWidget(gear_tools)
        self._gear_width_save_timer = QTimer(self)
        self._gear_width_save_timer.setSingleShot(True)
        self._gear_width_save_timer.setInterval(350)
        self._gear_width_save_timer.timeout.connect(
            self._save_gear_column_widths)
        self.gear_table = self._gear_table()
        gear_layout.addWidget(self.gear_table, 1)
        self._gear_tab_index = self.tabs.addTab(gear_page, "Gear · stats")

        self.auction_composer = AuctionComposer(self._auction_price, self)
        self._auction_tab_index = self.tabs.addTab(
            self.auction_composer, "WTS / WTB Builder")

        live_page = QWidget()
        live_layout = QVBoxLayout(live_page)
        live_layout.setContentsMargins(5, 5, 5, 5)
        self.live_note = QLabel(
            "Live Log and Notification Service · monitors the local EverQuest "
            "log for /auction lines visible to your client in the EC tunnel. "
            "It is not an Internet-wide auction feed.")
        self.live_note.setWordWrap(True)
        self.live_note.setAccessibleName(self.live_note.text())
        self.live_note.setToolTip(
            "Only listings written to your own EQ log can appear here; keep logs "
            "enabled and remain where you can receive /auction chat")
        live_layout.addWidget(self.live_note)
        watch_tools = QWidget()
        watch_layout = QGridLayout(watch_tools)
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.setSpacing(4)
        self.live_watch_input = QLineEdit()
        self.live_watch_input.setPlaceholderText("Item to watch…")
        self.live_watch_input.setClearButtonEnabled(True)
        self.live_watch_input.setAccessibleName(
            "Item name for live auction notification")
        self.live_watch_input.setToolTip(
            "Enter a full item name or distinctive phrase from an auction message")
        clear_live_watch = self.live_watch_input.findChild(QToolButton)
        if clear_live_watch:
            clear_live_watch.setAccessibleName("Clear auction watch item")
            clear_live_watch.setToolTip("Clear the item alert field")
        self._live_watch_model = QStringListModel(self)
        self._live_watch_completer = QCompleter(
            self._live_watch_model, self.live_watch_input)
        self._live_watch_completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self._live_watch_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.live_watch_input.setCompleter(self._live_watch_completer)
        self.live_watch_input.returnPressed.connect(self._add_live_watch)
        watch_layout.addWidget(self.live_watch_input, 0, 0)
        self.live_watch_add = QPushButton("Add alert")
        self.live_watch_add.setIcon(game_icon("add"))
        self.live_watch_add.setAccessibleName(
            "Add alert — create live auction notification")
        self.live_watch_add.setToolTip(
            "Notify on the Vantage overlay when this item appears for sale")
        self.live_watch_add.clicked.connect(self._add_live_watch)
        watch_layout.addWidget(self.live_watch_add, 0, 1)
        self.live_watch_items = QComboBox()
        self.live_watch_items.setMinimumContentsLength(14)
        self.live_watch_items.setAccessibleName("Watched auction items")
        self.live_watch_items.setToolTip(
            "Items currently monitored by the Live Log and Notification Service")
        watch_layout.addWidget(self.live_watch_items, 0, 2)
        self.live_watch_remove = QPushButton("Remove")
        self.live_watch_remove.setIcon(game_icon("delete"))
        self.live_watch_remove.setAccessibleName(
            "Remove — selected auction alert")
        self.live_watch_remove.setToolTip("Stop watching the selected item")
        self.live_watch_remove.clicked.connect(self._remove_live_watch)
        watch_layout.addWidget(self.live_watch_remove, 0, 3)
        self.live_alerts_enabled = QCheckBox("Alerts on")
        self.live_alerts_enabled.setChecked(bool(
            config.data["market"].get("live_alerts_enabled", True)))
        self.live_alerts_enabled.setAccessibleName(
            "Alerts on — enable live auction overlay notifications")
        self.live_alerts_enabled.setToolTip(
            "Show a themed Vantage overlay when a watched sale reaches your log")
        self.live_alerts_enabled.toggled.connect(
            self._set_live_alerts_enabled)
        watch_layout.addWidget(self.live_alerts_enabled, 0, 4)
        watch_layout.setColumnStretch(0, 2)
        watch_layout.setColumnStretch(2, 1)
        live_layout.addWidget(watch_tools)
        self._refresh_live_watch_items()
        self.live_table = QTableView()
        self.live_table.setModel(self._local_proxy)
        self.live_table.setAccessibleName("Live EC auction log")
        self.live_table.setAccessibleDescription(
            "Auction messages received by this EverQuest client, newest first")
        self.live_table.setWordWrap(False)
        self.live_table.verticalHeader().setVisible(False)
        live_header = self.live_table.horizontalHeader()
        live_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        live_layout.addWidget(self.live_table, 1)
        self._live_tab_index = self.tabs.addTab(
            live_page, "Live Log & Alerts · 0")
        ensure_tab_tooltips(self.tabs, {
            "PigParse · prices": "Search cached PigParse Green listings and prices",
            "Gear · stats": (
                "Compare and sort P99 items by stats, class, race, slot, and effects"),
            "WTS / WTB Builder": (
                "Build customized auction messages; WTS uses real item links and "
                "WTB uses plain text"),
            "Live Log & Alerts · 0": (
                "Monitor EC tunnel /auction lines from your own EQ log and alert "
                "when watched items appear for sale"),
        })
        self._body_layout.addWidget(self.tabs, 1)

        footer = QWidget()
        self._footer_layout = QGridLayout(footer)
        self._footer_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
        self._footer_layout.setContentsMargins(5, 3, 5, 4)
        self._footer_layout.setSpacing(3)
        self.status = QLabel("Preparing PigParse Green…")
        self.status.setWordWrap(True)
        self._analyze_button = QPushButton("Evaluate Price")
        self._analyze_button.setIcon(game_icon("timer"))
        self._analyze_button.setToolTip(
            "Calculate a robust median without changing the original data")
        self._analyze_button.clicked.connect(self._analyze_selected)
        self._detail_button = QPushButton("PigParse History")
        self._detail_button.setIcon(game_icon("market"))
        self._detail_button.setToolTip(
            "Open the selected item's full history in PigParse")
        self._detail_button.clicked.connect(self._open_detail)
        self._wiki_button = QPushButton("Item + Wiki Price")
        self._wiki_button.setIcon(game_icon("map"))
        self._wiki_button.setToolTip(
            "Show the Project 1999 Wiki item card and Green price inside Vantage")
        self._wiki_button.clicked.connect(self._show_wiki_card)
        self._body_layout.addWidget(footer)
        self._responsive_widgets = (
            self.search, self._refresh_button,
            self._sources_button, self.class_filter, self.race_filter,
            self.slot_filter, self.gear_status, self.status,
            self.stat_sort, self.effect_filter, self.tradeability_filter,
            self.era_filter,
            self._analyze_button, self._detail_button, self._wiki_button)
        for widget in self._responsive_widgets:
            widget.setMinimumWidth(0)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                widget.sizePolicy().verticalPolicy())
        QTimer.singleShot(0, self._relayout_controls)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(
            config.data["market"].get("refresh_minutes", 10) * 60 * 1000)
        self._refresh_timer.timeout.connect(self._scheduled_refresh)
        self._refresh_timer.start()
        self._refresh_minutes = config.data["market"].get("refresh_minutes", 10)
        from PySide6.QtWidgets import QApplication
        QApplication.instance()._signals["settings"].config_updated.connect(
            self._market_config_updated)
        self._load_cache()
        self._load_gear_cache()
        # Cached data is usable immediately. Network initialization is delayed
        # until the event loop is settled so Windows can finish showing the
        # tray and parser tools without a startup CPU/network spike.
        QTimer.singleShot(1800, self._start_deferred_refresh)

    def _start_deferred_refresh(self):
        self._refresh_gear_index()
        if self._toggled and not self._loaded_online:
            self.refresh()

    @staticmethod
    def _equipment_combo(values, accessible_name, callback):
        combo = QComboBox()
        for label, bit in values:
            combo.addItem(label, bit)
        combo.setAccessibleName(accessible_name)
        combo.setToolTip(
            f"{accessible_name}; applies to both PigParse prices and Gear stats")
        combo.currentIndexChanged.connect(lambda _: callback(combo.currentData()))
        return combo

    def _set_equipment_filter(self, kind, bit):
        self._proxy.set_gear_filter(kind, bit)
        self._gear_proxy.set_gear_filter(kind, bit)
        self._update_gear_summary()

    def _set_effect_filter(self, kind):
        self._gear_proxy.set_effect_filter(kind)
        self._update_gear_summary()

    def _set_tradeability_filter(self, value):
        self._gear_proxy.set_tradeability_filter(value)
        self._update_gear_summary()

    def _set_era_filter(self, value):
        self._gear_proxy.set_era_filter(value)
        self._update_gear_summary()

    def _set_stat_sort(self, key):
        key = str(key or "ac")
        self._gear_model.set_active_stat(key)
        for column in CORE_STAT_COLUMNS.values():
            self.gear_table.setColumnHidden(column, False)
        duplicate_column = CORE_STAT_COLUMNS.get(key)
        if duplicate_column is not None:
            self.gear_table.setColumnHidden(duplicate_column, True)
        self.gear_table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self._update_gear_summary()

    def _update_gear_summary(self):
        if not hasattr(self, "gear_results"):
            return
        label = STAT_NAMES.get(self._gear_model.active_stat, "AC")
        visible = self._gear_proxy.rowCount()
        total = len(self._gear_model.items)
        self.gear_results.setText(
            f"{visible:,} / {total:,} items · highest {label} first")

    def _market_table(self):
        table = QTableView()
        table.setModel(self._proxy)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 250)
        table.setColumnWidth(6, 70)
        table.setToolTip(
            "Click an item's gold name to open its card")
        table.clicked.connect(self._market_item_clicked)
        return table

    def _gear_table(self):
        table = QTableView()
        table.setModel(self._gear_proxy)
        table.setSortingEnabled(True)
        table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(38)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setToolTip(
            "Click to sort · drag a divider to resize · double-click a divider to auto-fit")
        saved = config.data["market"].get("gear_column_widths", {})
        for column, (_, key) in enumerate(self._gear_model.COLUMNS):
            table.setColumnWidth(
                column, int(saved.get(key, GEAR_COLUMN_DEFAULT_WIDTHS[key])))
        header.sectionResized.connect(
            lambda *_: self._gear_width_save_timer.start())
        table.setToolTip(
            "Click a gold item name for stats, effects, prices, drops, and Wiki details; "
            "click any header to sort")
        table.clicked.connect(self._gear_item_clicked)
        return table

    def _save_gear_column_widths(self):
        if not hasattr(self, "gear_table"):
            return
        config.data["market"]["gear_column_widths"] = {
            key: self.gear_table.columnWidth(column)
            for column, (_, key) in enumerate(self._gear_model.COLUMNS)}
        if getattr(config, "_filename", ""):
            config.save()

    def _market_item_clicked(self, index):
        if index.isValid() and index.column() == 1:
            self._show_wiki_card(index)

    def _gear_item_clicked(self, index):
        if index.isValid() and index.column() == 0:
            self._show_wiki_card(index)

    def _show_wiki_card(self, index=None):
        item = self._selected_item(index)
        if not item:
            self.status.setText("Select an item name to open its card")
            return
        card = WikiItemCard(item, self)
        card.wiki_entity_requested.connect(self._show_wiki_entity)
        card.show()
        card.raise_()
        json_path, icon_path = _wiki_cache_paths(item.get("n"))
        try:
            cached = json.loads(json_path.read_text(encoding="utf-8"))
            card.set_item_data(cached, cached=True)
            if icon_path.is_file():
                card.set_icon_data(icon_path.read_bytes())
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        wiki_name = str(item.get("n") or "").replace("Spell: ", "")
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(wiki_name.replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
        reply = self._network.get(request)
        reply.finished.connect(
            lambda: self._wiki_item_finished(reply, card, json_path, icon_path))

    def _show_wiki_entity(self, target, label, kind):
        card = WikiEntityCard(label or target, kind, self)
        card.show()
        card.raise_()
        cache_path = _wiki_entity_cache_path(target)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            card.set_entity_data(cached, cached=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(str(target).replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._wiki_entity_finished(
            reply, card, cache_path, target, kind))
        return card

    def _considered_entity(self, name):
        context = getattr(self, '_character_context', None)
        if (context and context.pet_name and
                context.pet_name.casefold() == name.casefold()):
            self.status.setText(
                f"/consider · {name} · active pet · local EQ log")
            return
        self.status.setText(
            f"/consider · {name} · Project 1999 Wiki NPC lookup")
        if not config.data['market'].get('auto_consider_lookup', False):
            return
        if self._last_consider_name.casefold() == name.casefold():
            try:
                if self._consider_card and self._consider_card.isVisible():
                    self._consider_card.raise_()
                    return
            except RuntimeError:
                self._consider_card = None
        try:
            if self._consider_card:
                self._consider_card.close()
        except RuntimeError:
            pass
        self._last_consider_name = name
        self._consider_card = self._show_wiki_entity(name, name, 'npc')

    @staticmethod
    def _wiki_entity_finished(reply, card, cache_path, target, kind):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parse = payload.get("parse")
            if not isinstance(parse, dict):
                raise ValueError("the Wiki did not return a recognized page")
            wikitext = parse.get("wikitext", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            data = parse_wiki_entity_wikitext(
                wikitext, fallback_name=target, kind=kind)
            card.set_entity_data(data)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            try:
                card.set_error(str(error))
            except RuntimeError:
                pass
        finally:
            reply.deleteLater()

    def _wiki_item_finished(self, reply, card, json_path, icon_path):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parse = payload.get("parse")
            if not isinstance(parse, dict):
                raise ValueError("the item does not have a recognized page")
            wikitext = parse.get("wikitext", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            data = parse_wiki_item_wikitext(wikitext, card.item_name)
            rendered = parse.get("text", {})
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            data["auction"] = parse_wiki_green_auction_html(rendered)
            card.set_item_data(data)
            json_path.write_text(json.dumps(data), encoding="utf-8")

            image_name = data.get("image") or next(
                (name for name in parse.get("images", [])
                 if str(name).casefold().startswith("item_")), "")
            if image_name:
                image_request = QNetworkRequest(QUrl(P99_WIKI_IMAGE_URL.format(
                    filename=quote(str(image_name), safe="._-"))))
                image_request.setHeader(
                    QNetworkRequest.KnownHeaders.UserAgentHeader,
                    "Vantage/1.44.15")
                image_reply = self._network.get(image_request)
                image_reply.finished.connect(
                    lambda: self._wiki_icon_finished(
                        image_reply, card, icon_path))
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            try:
                card.set_error(str(error))
            except RuntimeError:
                pass
        finally:
            reply.deleteLater()

    @staticmethod
    def _wiki_icon_finished(reply, card, icon_path):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = bytes(reply.readAll())
            if not payload:
                raise ValueError("empty icon")
            card.set_icon_data(payload)
            icon_path.write_bytes(payload)
        except (OSError, RuntimeError, ValueError):
            pass
        finally:
            reply.deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_responsive_widgets"):
            self._relayout_controls()
            QTimer.singleShot(0, self._sync_market_body_size)

    def _sync_market_body_size(self):
        """Keep one canonical logical width while changing only list height."""
        viewport = self._market_scroll.viewport().size()
        if viewport.width() <= 0:
            return
        # A QScrollArea normally gives its scrollbar width back when the bar
        # hides. That made every market control grow by about ten logical pixels
        # at some replica sizes. Reserve the compact scrollbar gutter so a
        # horizontal resize scales the same layout instead of reflowing it.
        scrollbar_width = max(
            0, self._market_scroll.verticalScrollBar().sizeHint().width())
        body_width = max(1, self._design_size.width() - scrollbar_width)
        self._market_body.setFixedWidth(body_width)
        self._body_layout.activate()
        content_height = max(
            viewport.height(), self._body_layout.sizeHint().height())
        self._market_body.resize(body_width, content_height)

    def _relayout_controls(self):
        for widget in self._responsive_widgets:
            self._toolbar_layout.removeWidget(widget)
            self._filters_layout.removeWidget(widget)
            self._footer_layout.removeWidget(widget)
        for column in range(4):
            self._toolbar_layout.setColumnStretch(column, 0)
            self._filters_layout.setColumnStretch(column, 0)
            self._footer_layout.setColumnStretch(column, 0)
        # The complete market surface is uniformly scaled by ParserWindow.
        # Responsive breakpoints here would mutate the logical layout during a
        # physical resize, which is exactly the reflow the compact panels must
        # avoid.
        width = self._design_size.width()

        if width >= 760:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 2)
            self._toolbar_layout.addWidget(self._refresh_button, 0, 2)
            self._toolbar_layout.addWidget(self._sources_button, 0, 3)
        elif width >= 460:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 2)
            self._toolbar_layout.addWidget(self._refresh_button, 1, 0)
            self._toolbar_layout.addWidget(self._sources_button, 1, 1)
        else:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 2)
            self._toolbar_layout.addWidget(self._refresh_button, 1, 0)
            self._toolbar_layout.addWidget(self._sources_button, 1, 1)
        self._toolbar_layout.setColumnStretch(0, 1)

        if width >= 820:
            self._filters_layout.addWidget(self.class_filter, 0, 0)
            self._filters_layout.addWidget(self.race_filter, 0, 1)
            self._filters_layout.addWidget(self.slot_filter, 0, 2)
            self._filters_layout.addWidget(self.gear_status, 0, 3)
            self._filters_layout.setColumnStretch(3, 1)
        elif width >= 480:
            self._filters_layout.addWidget(self.class_filter, 0, 0)
            self._filters_layout.addWidget(self.race_filter, 0, 1)
            self._filters_layout.addWidget(self.slot_filter, 0, 2)
            self._filters_layout.addWidget(self.gear_status, 1, 0, 1, 3)
        else:
            self._filters_layout.addWidget(self.class_filter, 0, 0, 1, 2)
            self._filters_layout.addWidget(self.race_filter, 1, 0)
            self._filters_layout.addWidget(self.slot_filter, 1, 1)
            self._filters_layout.addWidget(self.gear_status, 2, 0, 1, 2)

        if width >= 760:
            self._footer_layout.addWidget(self.status, 0, 0)
            self._footer_layout.addWidget(self._analyze_button, 0, 1)
            self._footer_layout.addWidget(self._detail_button, 0, 2)
            self._footer_layout.addWidget(self._wiki_button, 0, 3)
            self._footer_layout.setColumnStretch(0, 1)
        elif width >= 500:
            self._footer_layout.addWidget(self.status, 0, 0, 1, 3)
            self._footer_layout.addWidget(self._analyze_button, 1, 0)
            self._footer_layout.addWidget(self._detail_button, 1, 1)
            self._footer_layout.addWidget(self._wiki_button, 1, 2)
        elif width >= 400:
            self._footer_layout.addWidget(self.status, 0, 0, 1, 2)
            self._footer_layout.addWidget(self._analyze_button, 1, 0)
            self._footer_layout.addWidget(self._detail_button, 1, 1)
            self._footer_layout.addWidget(self._wiki_button, 2, 0, 1, 2)
        else:
            self._footer_layout.addWidget(self.status, 0, 0)
            self._footer_layout.addWidget(self._analyze_button, 1, 0)
            self._footer_layout.addWidget(self._detail_button, 2, 0)
            self._footer_layout.addWidget(self._wiki_button, 3, 0)
        QTimer.singleShot(0, self._sync_market_body_size)

    def _load_gear_cache(self):
        path = _gear_cache_file()
        if not path.exists():
            return False
        try:
            items = load_gear_items(path)
            gear = {_item_key(item.name): item for item in items}
            self._proxy.set_gear(gear)
            self._gear_model.set_items(items)
            self._gear_model.set_prices(self._model.items)
            self.auction_composer.set_catalog(items)
            self.auction_composer.refresh_prices()
            self._live_watch_model.setStringList(
                [item.name for item in items])
            self._set_stat_sort(self.stat_sort.currentData())
            self._rebuild_mobile_items()
            self.gear_status.setText(
                f"P99 item index · {len(items):,} stats + effects")
            self._update_gear_summary()
            return True
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return False

    def _auction_price(self, item_name):
        """Prefer a recent PigParse WTS price for the editable message field."""
        item = self._gear_model.price_item(item_name) or {}
        try:
            return int(float(item.get("a30") or 0))
        except (TypeError, ValueError):
            return 0

    def _rebuild_mobile_items(self):
        rows = []
        gear = self._proxy.gear
        for item in self._model.items:
            metadata = gear.get(_item_key(item.get("n")))
            classes = metadata.classes if isinstance(metadata, GearItem) else 0
            races = metadata.races if isinstance(metadata, GearItem) else 0
            slots = metadata.slots if isinstance(metadata, GearItem) else 0
            quality, _ = _quality(item)
            stats = {}
            effects = []
            gear_id = 0
            if isinstance(metadata, GearItem):
                gear_id = metadata.id
                stats = {
                    key: metadata.stat(key) for key in (
                        "ac", "hp", "mana", "astr", "asta", "adex",
                        "aagi", "aint", "awis", "acha", "mr", "fr",
                        "cr", "dr", "pr", "attack", "haste", "regen",
                        "manaregen")
                    if metadata.stat(key)}
                effects = [
                    {"type": label, "name": value}
                    for label, value in metadata.effects()]
            name = str(item.get("n") or "")
            rows.append({
                "name": name,
                "price": int(item.get("a30") or 0),
                "posts": int(item.get("t30") or 0),
                "quality": quality,
                "last": str(item.get("l") or ""),
                "classes": classes,
                "races": races,
                "slots": slots,
                "nodrop": bool(metadata.nodrop) if isinstance(
                    metadata, GearItem) else False,
                "era": metadata.era if isinstance(metadata, GearItem) else "",
                "id": item.get("i"),
                "gear_id": gear_id,
                "stats": stats,
                "effects": effects,
                "wiki_url": _wiki_target_url(name),
            })
        # Replace the tuple atomically; the mobile thread never sees a partial rebuild.
        self._mobile_items = tuple(rows)
        self._mobile_revision += 1

    def mobile_snapshot(self):
        return {
            "source": "PigParse API · Green",
            "metadata_source": self._gear_source,
            "revision": self._mobile_revision,
            "items": self._mobile_items,
        }

    def price_for_spell(self, spell_name):
        """Return the best cached PigParse row for one spell scroll."""
        target = _item_key(spell_name)
        candidates = []
        for item in self._model.items:
            item_name = re.sub(
                r"^spell\s*:\s*", "", str(item.get("n") or ""),
                flags=re.IGNORECASE)
            if _item_key(item_name) != target:
                continue
            trade_rank = {0: 3, 2: 2, 1: 1}.get(item.get("t"), 0)
            candidates.append((
                trade_rank,
                int(item.get("t30") or 0),
                int(float(item.get("a30") or 0)),
                item))
        return dict(max(candidates, default=(0, 0, 0, {}))[-1])

    def _refresh_gear_index(self):
        request = QNetworkRequest(QUrl(GEAR_META_URL))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._gear_meta_finished(reply))

    def _gear_meta_finished(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                if not self._proxy.gear:
                    self.gear_status.setText("P99 item stats unavailable")
                return
            metadata = json.loads(bytes(reply.readAll()).decode("utf-8"))
            expected = str(metadata.get("sqlite", {}).get("sha256", ""))
            self._gear_source = str(metadata.get("source") or "Project 1999 Wiki")
            cache = _gear_cache_file()
            if cache.exists() and expected:
                digest = hashlib.sha256(cache.read_bytes()).hexdigest()
                if hmac.compare_digest(digest, expected):
                    self.gear_status.setText(
                        f"P99 item index · {len(self._gear_model.items):,} stats + effects · current")
                    return
            request = QNetworkRequest(QUrl(GEAR_DB_URL))
            request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
            db_reply = self._network.get(request)
            db_reply.setProperty("expected_sha256", expected)
            db_reply.finished.connect(lambda: self._gear_db_finished(db_reply))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            if not self._proxy.gear:
                self.gear_status.setText("P99 item stats unavailable")
        finally:
            reply.deleteLater()

    def _gear_db_finished(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = gzip.decompress(bytes(reply.readAll()))
            expected = str(reply.property("expected_sha256") or "")
            digest = hashlib.sha256(payload).hexdigest()
            if not expected or not hmac.compare_digest(digest, expected):
                raise ValueError("data signature does not match")
            if not payload.startswith(b"SQLite format 3\x00"):
                raise ValueError("invalid index format")
            target = _gear_cache_file()
            pending = target.with_suffix(".sqlite.part")
            pending.write_bytes(payload)
            pending.replace(target)
            if not self._load_gear_cache():
                raise ValueError("the index could not be opened")
            self.gear_status.setText(
                f"P99 item index · {len(self._gear_model.items):,} stats + effects · updated")
        except (OSError, EOFError, ValueError, sqlite3.Error) as error:
            if self._gear_model.items:
                self.gear_status.setText(
                    f"Cached P99 item index · {len(self._gear_model.items):,} "
                    "stats + effects · refresh deferred")
            else:
                self.gear_status.setText(f"P99 item stats unavailable · {error}")
        finally:
            reply.deleteLater()

    def parse(self, timestamp, text):
        zone = ZONE_RX.match(text)
        if zone:
            self._zone = zone.group("zone")
            self._set_live_note(
                "Live Log and Notification Service · "
                f"detected zone: {self._zone}. Monitoring /auction lines "
                "written to this client's local EQ log; EC tunnel coverage "
                "requires your character to receive auction chat there.",
                announce=True)
            return
        con_target = considered_name(text)
        if con_target:
            self._considered_entity(con_target)
            return
        match = LOCAL_AUCTION_RX.match(text)
        if not match:
            return
        self._local_model.add({
            "time": timestamp.strftime("%H:%M:%S"),
            "seller": match.group("seller"),
            "message": match.group("message"),
        })
        self.tabs.setTabText(
            self._live_tab_index,
            f"Live Log & Alerts · {len(self._local_model.items)}")
        self._notify_live_watches(
            timestamp, match.group("seller"), match.group("message"))

    def _set_live_note(self, text, announce=False):
        self.live_note.setText(str(text))
        self.live_note.setAccessibleName(str(text))
        if announce:
            _announce_accessible(self, text)

    def _refresh_live_watch_items(self, selected=""):
        watches = list(config.data["market"].get("live_watch_items", []))
        selected = str(selected or self.live_watch_items.currentText())
        self.live_watch_items.blockSignals(True)
        self.live_watch_items.clear()
        if watches:
            self.live_watch_items.addItems(watches)
            index = self.live_watch_items.findText(
                selected, Qt.MatchFlag.MatchFixedString)
            self.live_watch_items.setCurrentIndex(max(0, index))
            self.live_watch_items.setEnabled(True)
            self.live_watch_remove.setEnabled(True)
        else:
            self.live_watch_items.addItem("No watched items")
            self.live_watch_items.setEnabled(False)
            self.live_watch_remove.setEnabled(False)
        self.live_watch_items.blockSignals(False)

    def _add_live_watch(self):
        watch = str(self.live_watch_input.text() or "").strip()[:96]
        if not watch:
            self.live_watch_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        watches = config.data["market"].setdefault("live_watch_items", [])
        catalog_match = next((
            item.name for item in self._gear_model.items
            if _item_key(item.name) == _item_key(watch)), watch)
        if catalog_match.casefold() not in {
                item.casefold() for item in watches}:
            watches.append(catalog_match)
            del watches[64:]
        config.data["market"]["live_alerts_enabled"] = True
        self.live_alerts_enabled.blockSignals(True)
        self.live_alerts_enabled.setChecked(True)
        self.live_alerts_enabled.blockSignals(False)
        if getattr(config, "_filename", ""):
            config.save()
        self.live_watch_input.clear()
        self._refresh_live_watch_items(catalog_match)
        _announce_accessible(
            self, f"Alert added for {catalog_match}; auction alerts are on")
        return True

    def _remove_live_watch(self):
        selected = str(self.live_watch_items.currentText() or "")
        watches = config.data["market"].get("live_watch_items", [])
        updated = [
            item for item in watches if item.casefold() != selected.casefold()]
        if len(updated) == len(watches):
            return False
        config.data["market"]["live_watch_items"] = updated
        if getattr(config, "_filename", ""):
            config.save()
        self._refresh_live_watch_items()
        _announce_accessible(self, f"Alert removed for {selected}")
        return True

    def _set_live_alerts_enabled(self, enabled):
        config.data["market"]["live_alerts_enabled"] = bool(enabled)
        if getattr(config, "_filename", ""):
            config.save()
        _announce_accessible(
            self, "Live auction alerts on" if enabled else
            "Live auction alerts off")

    def _notify_live_watches(self, timestamp, seller, message):
        settings = config.data["market"]
        if not settings.get("live_alerts_enabled", True):
            return []
        matches = live_auction_watch_matches(
            message, settings.get("live_watch_items", []))
        now = (
            timestamp.timestamp() if hasattr(timestamp, "timestamp") else
            datetime.datetime.now().timestamp())
        app = QApplication.instance()
        notified = []
        for item in matches:
            key = (str(seller).casefold(), item.casefold())
            if now - float(self._live_alerted_at.get(key, 0)) < 60:
                continue
            self._live_alerted_at[key] = now
            if app and hasattr(app, "show_overlay_notification"):
                app.show_overlay_notification(
                    f"For sale · {item}",
                    f"{seller} · {message}", msecs=8500,
                    overlay_id="alerts", color="#7A3F2D",
                    text_color="#FFE6C2")
            _announce_accessible(
                self, f"For sale: {item}, seller {seller}", assertive=True)
            notified.append(item)
        return notified

    def _set_query(self, query):
        self._proxy.set_query(query)
        self._gear_proxy.set_query(query)
        self._local_proxy.set_query(query)
        self._update_gear_summary()

    def _scheduled_refresh(self):
        if self.isVisible():
            self.refresh()

    def _market_config_updated(self):
        minutes = config.data["market"].get("refresh_minutes", 10)
        if minutes != self._refresh_minutes:
            self._refresh_minutes = minutes
            self._refresh_timer.setInterval(minutes * 60 * 1000)

    def refresh(self):
        if self._request_in_flight:
            return
        self._loaded_online = True
        self._request_in_flight = True
        self._refresh_button.setEnabled(False)
        self._refresh_button.setText("Refreshing…")
        self.status.setText("Refreshing PigParse Green…")
        request = QNetworkRequest(QUrl(MARKET_ENDPOINT))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._finished(reply))

    def toggle(self):
        super().toggle()
        if self.isVisible() and not self._loaded_online:
            self.refresh()

    def _finished(self, reply):
        self._request_in_flight = False
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.status.setText(f"Offline · using cache · {reply.errorString()}")
                return
            items = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(items, list):
                raise ValueError("The response does not contain a list")
            references = market_price_references(items)
            self._model.set_items(references)
            self._gear_model.set_prices(references)
            self.auction_composer.refresh_prices()
            self._rebuild_mobile_items()
            payload = {
                "updated_at": datetime.datetime.now().astimezone().isoformat(),
                "source": MARKET_ENDPOINT,
                "items": items,
            }
            _cache_file().write_text(json.dumps(payload), encoding="utf-8")
            self.status.setText(
                f"PigParse API · {len(references):,} price references · updated now · "
                "10 min cycle")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            self.status.setText(f"Refresh failed · using cache · {error}")
        finally:
            self._refresh_button.setEnabled(True)
            self._refresh_button.setText("Refresh")
            reply.deleteLater()

    def _load_cache(self):
        try:
            payload = json.loads(_cache_file().read_text(encoding="utf-8"))
            self._model.set_items(market_price_references(
                payload.get("items", [])))
            self._gear_model.set_prices(self._model.items)
            self.auction_composer.refresh_prices()
            self._rebuild_mobile_items()
            stamp = datetime.datetime.fromisoformat(payload.get("updated_at", ""))
            self.status.setText(
                f"PigParse API · {len(self._model.items):,} cached price references · "
                f"{stamp.astimezone():%Y-%m-%d %H:%M}")
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def _selected_item(self, index=None):
        gear_index = (
            index is not None and not isinstance(index, bool)
            and index.model() is self._gear_proxy)
        if index is None or isinstance(index, bool):
            gear_index = self.tabs.currentIndex() == self._gear_tab_index
        if gear_index:
            if index is None or isinstance(index, bool):
                rows = self.gear_table.selectionModel().selectedRows()
                if not rows:
                    return None
                index = rows[0]
            source = self._gear_proxy.mapToSource(index)
            if not source.isValid():
                return None
            gear_item = self._gear_model.items[source.row()]
            payload = dict(self._gear_model.price_item(gear_item.name) or {})
            payload["n"] = gear_item.name
            payload["_gear"] = gear_item
            return payload
        if index is None or isinstance(index, bool):
            rows = self.table.selectionModel().selectedRows()
            if not rows:
                return None
            index = rows[0]
        source = self._proxy.mapToSource(index)
        if not source.isValid():
            return None
        payload = dict(self._model.items[source.row()])
        payload["_gear"] = self._proxy.gear.get(_item_key(payload.get("n")))
        return payload

    def _analyze_selected(self):
        item = self._selected_item()
        if not item:
            self.status.setText("Select an item to evaluate its history")
            return
        name = str(item.get("n", ""))
        self.status.setText(f"Evaluating PigParse history · {name}…")
        request = QNetworkRequest(QUrl(DETAIL_API.format(item_name=quote(name, safe=""))))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.15")
        reply = self._network.get(request)
        reply.setProperty("market_item_name", name)
        reply.finished.connect(lambda: self._analysis_finished(reply))

    def _analysis_finished(self, reply):
        name = reply.property("market_item_name")
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)
            seen = set()
            prices = []
            for row in payload.get("items", []):
                price = row.get("p")
                if not isinstance(price, (int, float)) or price <= 0:
                    continue
                try:
                    stamp = datetime.datetime.fromisoformat(str(row.get("t")))
                    if stamp.astimezone(datetime.timezone.utc) < cutoff:
                        continue
                except (TypeError, ValueError):
                    continue
                # Repeated tunnel spam should not count as independent evidence.
                key = (row.get("u"), row.get("i"), int(price), stamp.date())
                if key not in seen:
                    seen.add(key)
                    prices.append(float(price))
            if not prices:
                raise ValueError("there are no numeric prices in the last 90 days")
            median = statistics.median(prices)
            deviations = [abs(price - median) for price in prices]
            mad = statistics.median(deviations)
            threshold = max(median * .35, mad * 3, 25)
            plausible = [
                price for price in prices
                if abs(price - median) <= threshold and median * .25 <= price <= median * 4]
            robust = statistics.median(plausible or prices)
            outliers = len(prices) - len(plausible)
            if len(plausible) >= 12 and outliers <= len(prices) * .15:
                confidence = "High"
            elif len(plausible) >= 5:
                confidence = "Medium"
            else:
                confidence = "Low"
            QMessageBox.information(
                self, f"Price Evaluation · {name}",
                f"Estimated typical price: {robust:,.0f} pp\n"
                f"Confidence: {confidence}\n"
                f"Unique samples (90d): {len(prices)}\n"
                f"Values marked as outliers: {outliers}\n\n"
                "Method: robust median; repeats from the same seller/price/day "
                "count only once. Nothing is removed or changed in PigParse.\n\n"
                "Primary source: PigParse API · Green\n"
                "Secondary reference available: Project 1999 Wiki.")
            self.status.setText(f"Evaluated · {name} · estimate {robust:,.0f} pp")
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            self.status.setText(f"Could not evaluate {name} · {error}")
        finally:
            reply.deleteLater()

    def _open_detail(self, index=None):
        item = self._selected_item(index)
        if not item:
            return
        item_id = item.get("i")
        if item_id is None:
            self.status.setText(
                f"No PigParse history is available for {item.get('n', 'this item')}")
            return
        webbrowser.open(DETAIL_URL.format(item_id=item_id))

    def _open_wiki(self):
        item = self._selected_item()
        if item:
            name = str(item.get("n", "")).replace("Spell: ", "")
            webbrowser.open(P99_WIKI_URL.format(slug=quote(name.replace(" ", "_"))))

    def _show_sources(self):
        box = QMessageBox(self)
        box.setWindowTitle("Market Sources")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "<b>Primary source and source of truth:</b><br>"
            f"<a href='{PIGPARSE_URL}'>PigParse · Green</a> — catalog, averages, and history. "
            "The API reports a 10-minute rebuild cycle.<br><br>"
            "<b>Secondary reference:</b><br>"
            "<a href='https://wiki.project1999.com/Special:AuctionTracker'>"
            "Project 1999 Wiki Auction Tracker</a> — secondary Green price. "
            "Vantage creates a 50/50 average only when both recent references "
            "differ by 30% or less; otherwise it preserves and displays each value separately.<br><br>"
            "<b>Equipment stats, effects, and filters:</b><br>"
            f"<a href='{P99_PLANNER_URL}'>P99 Planner item index</a> — "
            f"{self._gear_source}. Supplies class, race, slot, AC, attributes, "
            "NO DROP state, resists, haste, regeneration, and "
            "click/proc/worn/focus/bard effect names. "
            "It is used only for equipment metadata, never for prices.<br><br>"
            "<b>Item era:</b><br>Project 1999 Wiki categories — "
            "Classic Era, Kunark Era, and Velious Era. The compact matched index "
            "is bundled for fast offline filtering.<br><br>"
            "<b>Live Log and Notification Service:</b><br>"
            "EverQuest log — monitors /auction listings received by your own "
            "client in places such as the EC tunnel and creates Vantage overlay "
            "alerts for watched items. It is not a permanent global feed.")
        box.exec()
