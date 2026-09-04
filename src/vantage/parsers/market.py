"""Native, server-isolated UI for PigParse market data and local auctions."""

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
    QAbstractTableModel, QEvent, QModelIndex,
    QSignalBlocker, QSize,
    QSortFilterProxyModel, QStringListModel, Signal, Qt, QTimer, QUrl)
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QFont, QPixmap)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QStackedWidget, QTabWidget, QSystemTrayIcon, QTableView, QTableWidget,
    QTableWidgetItem, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config, resource_path
from vantage.helpers.audio import audio_muted, notification_sound, play_alert
from vantage.helpers.icons import game_icon
from vantage.helpers.eq_clipboard import set_eq_clipboard
from vantage.helpers.friends_manager import everquest_root_from_logs
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import (
    ensure_tab_tooltips, ensure_table_header_tooltips, scrollable)
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.parsers.maps.mapdata import MapData


MARKET_SERVERS = ("Green", "Blue")
MARKET_ALERT_VOLUME = 72
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


def deliver_market_alert(app, title, message, sound_enabled=False):
    """Deliver one explicit sale alert and report exactly what succeeded."""
    delivery = "inline only"
    shown = False
    if app is not None and hasattr(app, "show_overlay_notification"):
        shown = bool(app.show_overlay_notification(
            title, message, msecs=8500, overlay_id="alerts",
            color="#7A3F2D", text_color="#FFE6C2"))
        if shown:
            delivery = "overlay shown"
    if not shown:
        tray = getattr(app, "_system_tray", None)
        if tray is not None and tray.isVisible():
            try:
                tray.showMessage(
                    title, message,
                    QSystemTrayIcon.MessageIcon.Information, 8500)
                shown = True
                delivery = "Windows notification shown"
            except (AttributeError, RuntimeError):
                pass

    sounded = False
    sound_state = "sound off"
    if sound_enabled:
        sounded = play_alert(
            notification_sound("market_sale"), MARKET_ALERT_VOLUME, 1,
            source=title, allow_hidden=True)
        sound_state = (
            "sound played" if sounded else
            "sound muted" if audio_muted() else
            "sound unavailable")
    return delivery, sound_state


def normalize_market_server(value):
    """Return one supported PigParse server, defaulting safely to Green."""
    folded = str(value or "").strip().casefold()
    return next((server for server in MARKET_SERVERS
                 if server.casefold() == folded), "Green")


def market_endpoint(server="Green"):
    return ("https://pigparse.azurewebsites.net/api/item/getall/" +
            normalize_market_server(server))


def market_detail_api(server="Green"):
    return ("https://pigparse.azurewebsites.net/api/item/getdetails/" +
            normalize_market_server(server) + "/{item_name}")


def pigparse_server_url(server="Green"):
    return ("https://pigparse.azurewebsites.net/ServerIndex/" +
            normalize_market_server(server))


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
    effects = []
    for label, value in item.effects():
        target = quote(str(value).strip(), safe="")
        effects.append(
            f'<b>{html.escape(label)}</b> · '
            f'<a href="vantage://wiki/effect/{target}" '
            f'style="color:#F2D784;text-decoration:underline;" '
            f'title="Open what {html.escape(value, quote=True)} does on '
            f'Project 1999 Wiki">{html.escape(value)}</a>')
    if effects:
        groups.append("<br>".join(effects))
    return "<br>".join(groups) or "No numeric stats or effects are listed."


def _gear_mask_labels(mask, options):
    """Return readable class, race, or slot labels for one equipment mask."""
    return tuple(
        label for label, bit in options
        if bit and int(mask or 0) & bit)


def gear_comparison_rows(items):
    """Build deterministic numeric rows and deltas for item comparison."""
    gear_items = tuple(item for item in items if isinstance(item, GearItem))
    if not gear_items:
        return ()
    base = gear_items[0]
    rows = []
    for label, key in STAT_OPTIONS:
        values = tuple(item.stat(key) for item in gear_items)
        best = max(values)
        leaders = tuple(
            index for index, value in enumerate(values)
            if value == best and any(values))
        rows.append({
            "label": label,
            "key": key,
            "values": values,
            "deltas": tuple(value - base.stat(key) for value in values),
            "leaders": leaders,
        })
    return tuple(rows)


def _cache_file(server="Green"):
    server = normalize_market_server(server).casefold()
    return data_dir("cache") / f"pigparse-{server}-cache.json"


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


def install_auction_hotbuttons(ini_path, lines, trade_type="WTS"):
    """Install WTS or WTB auction lines into free P99 social buttons safely.

    WTS lines may contain Titanium item-link control bytes; WTB lines remain
    plain text. Each type owns only its own Vantage social slots, so installing
    WTB buttons never replaces an existing Vantage WTS set (or vice versa).
    """
    trade_type = "WTB" if str(trade_type).strip().upper() == "WTB" else "WTS"
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
            rf"^(Page\d+Button\d+)Name\s*=\s*Vantage{trade_type}\d*\s*$",
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
            f"{prefix}Name=Vantage{trade_type}{index}",
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


def _wiki_cache_paths(name, server="Green"):
    server = normalize_market_server(server)
    digest = hashlib.sha256(
        f"{server}|{_item_key(name)}".encode("utf-8")).hexdigest()[:20]
    icon_digest = hashlib.sha256(
        _item_key(name).encode("utf-8")).hexdigest()[:20]
    cache = data_dir("cache", "wiki-items")
    return cache / f"{digest}.json", cache / f"{icon_digest}.png"


def _wiki_entity_cache_path(target, kind=""):
    digest = hashlib.sha256(
        f"{kind}|{target}".encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-entities") / f"{digest}.json"


def _wiki_zone_cache_path(target):
    digest = hashlib.sha256(
        str(target or "").strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-zones") / f"{digest}.json"


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


def _wiki_zone_field(source, label):
    """Extract one value from the standard P99 zone summary table."""
    match = re.search(
        rf"!\s*'{{0,5}}\s*{re.escape(label)}\s*:?\s*'{{0,5}}\s*\n"
        rf"\|\s*(.*?)(?=\n\|-\s*\n|\n!\s*'{{0,5}}|\n\|\}}|\Z)",
        str(source or ""), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _wiki_link_labels(value):
    labels = []
    for target, label in re.findall(
            r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]",
            str(value or "")):
        visible = _plain_wiki_text(label or target)
        if visible and visible.casefold() not in {
                item.casefold() for item in labels}:
            labels.append(visible)
    return labels


def parse_wiki_zone_payload(wikitext, rendered_html, fallback_name=""):
    """Return a searchable zone and NPC catalog from one P99 Wiki page."""
    source = str(wikitext or "")
    zone_name = str(fallback_name or "").replace("_", " ").strip()
    level_range = _plain_wiki_text(
        _wiki_zone_field(source, "Level of Monsters"))
    mob_types = _plain_wiki_text(
        _wiki_zone_field(source, "Types of Monsters"))
    notable = _wiki_link_labels(_wiki_zone_field(source, "Notable NPCs"))
    notable_keys = {name.casefold() for name in notable}
    unique_raw = _wiki_zone_field(source, "Unique Items")
    unique_items = _wiki_link_labels(unique_raw)
    for item in re.findall(r"\{\{:\s*([^}|]+)", unique_raw):
        label = _plain_wiki_text(item)
        if label and label.casefold() not in {
                value.casefold() for value in unique_items}:
            unique_items.append(label)

    lead = source.split("{|", 1)[0]
    lead = re.sub(r"(?m)^\s*\{\{[^\n]+\}\}\s*$", "", lead)
    summary = _plain_wiki_text(re.sub(r"'{2,5}", "", lead))
    era_match = re.search(r"\{\{\s*(Classic|Kunark|Velious)\s+Era\s*\}\}",
                          source, re.IGNORECASE)
    map_match = re.search(
        r"\[\[(?:Image|File):\s*([^\]|]+)", source, re.IGNORECASE)

    html_source = str(rendered_html or "")
    heading = html_source.rfind("What's in this zone?")
    if heading >= 0:
        html_source = html_source[heading:]
    table_match = re.search(
        r"<table\b[^>]*class=[\"'][^\"']*\beoTable3\b[^\"']*"
        r"\bsortable\b[^\"']*[\"'][^>]*>(.*?)</table>",
        html_source, re.IGNORECASE | re.DOTALL)
    mobs = []
    if table_match:
        for raw_row in re.findall(
                r"<tr\b[^>]*>(.*?)</tr>", table_match.group(1),
                re.IGNORECASE | re.DOTALL):
            raw_cells = re.findall(
                r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw_row,
                re.IGNORECASE | re.DOTALL)
            if len(raw_cells) < 6:
                continue
            clean_cells = [
                re.sub(r"<span\b[^>]*class=[\"'][^\"']*\bhb\b[^\"']*"
                       r"[\"'][^>]*>.*?</span>", "", cell,
                       flags=re.IGNORECASE | re.DOTALL)
                for cell in raw_cells]
            name_links = re.findall(
                r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                clean_cells[0], re.IGNORECASE | re.DOTALL)
            name = (_rendered_html_text(name_links[0][1]) if name_links else
                    _rendered_html_text(clean_cells[0]))
            if not name or name.casefold() == "npc name":
                continue
            target = (unquote(name_links[0][0].lstrip("/"))
                      if name_links else name.replace(" ", "_"))
            drop_links = re.findall(
                r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                clean_cells[5], re.IGNORECASE | re.DOTALL)
            drops = []
            for _, raw_label in drop_links:
                label = _rendered_html_text(raw_label)
                if label and label.casefold() not in {
                        value.casefold() for value in drops}:
                    drops.append(label)
            fallback_loot = _rendered_html_text(clean_cells[5])
            if not drops and fallback_loot and fallback_loot.casefold() not in {
                    "none", "various", "need info", "?"}:
                drops.append(fallback_loot)
            mobs.append({
                "name": name,
                "target": target,
                "named": name.casefold() in notable_keys,
                "race": _rendered_html_text(clean_cells[1]),
                "class": _rendered_html_text(clean_cells[2]),
                "level": _rendered_html_text(clean_cells[3]),
                "location": _rendered_html_text(clean_cells[4]),
                "drops": drops,
                "loot": ", ".join(drops) if drops else fallback_loot,
                "description": (
                    _rendered_html_text(clean_cells[6])
                    if len(clean_cells) > 6 else ""),
            })
    return {
        "name": zone_name,
        "summary": summary,
        "era": era_match.group(1).title() if era_match else "",
        "levels": level_range,
        "types": mob_types,
        "notable": notable,
        "unique_items": unique_items,
        "map_image": map_match.group(1).strip() if map_match else "",
        "mobs": mobs,
    }


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


def parse_wiki_auction_html(rendered_html, server="Green"):
    """Extract one server's Auction Tracker values from rendered Wiki HTML.

    The tracker is injected by a MediaWiki extension and is not present in the
    page's wikitext. Only recent server values are candidates for comparison;
    the all-time average is retained for context but never used as an estimate.
    """
    server = normalize_market_server(server)
    source = str(rendered_html or "")
    section_match = re.search(
        rf"<div\b[^>]*\bid=[\"']auc_{re.escape(server)}[\"'][^>]*>(.*?)"
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
        "source": f"Project 1999 Wiki Auction Tracker · {server}",
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


def parse_wiki_green_auction_html(rendered_html):
    """Compatibility wrapper for callers that explicitly request Green."""
    return parse_wiki_auction_html(rendered_html, "Green")


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
    if kind == "effect":
        name = (
            _plain_wiki_text(_wiki_template_field(source, "spellname")) or
            _plain_wiki_text(_wiki_template_field(source, "name")) or
            fallback_name.replace("_", " "))
        description = _plain_wiki_text(
            _wiki_template_field(source, "description"))
        effects = []
        for raw_effect in re.findall(
                r"(?is)\{\{SpellSlotRow(?:Smart)?\s*\|\s*\d+\s*\|\s*"
                r"(.*?)(?=\|\s*simple\s*=|\}\})", source):
            effect = _plain_wiki_text(raw_effect)
            if effect and effect not in effects:
                effects.append(effect)

        facts = []
        for label, field_name in (
                ("Type", "spell_type"), ("Target", "target_type"),
                ("Duration", "duration"), ("Resist", "resist"),
                ("Casting", "casting_time"), ("Recast", "recast_time"),
                ("Range", "range"), ("Mana", "mana"), ("Skill", "skill")):
            value = _plain_wiki_text(
                _wiki_template_field(source, field_name))
            if value:
                facts.append((label, value))

        sections = []
        if description:
            sections.append(description)
        if effects:
            sections.append(
                "WHAT IT DOES\n" + "\n".join(f"• {value}" for value in effects))
        messages = []
        for label, field_name in (
                ("Cast on you", "msg_cast_on_you"),
                ("Wears off", "msg_wears_off")):
            value = _plain_wiki_text(
                _wiki_template_field(source, field_name))
            if value:
                messages.append(f"{label}: {value}")
        if messages:
            sections.append("GAME MESSAGES\n" + "\n".join(messages))
        return {
            "name": name,
            "kind": "EFFECT",
            "facts": facts,
            "summary": "\n\n".join(sections) or
                       "The Wiki page does not include a spell-effect summary.",
        }

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
        known_loot = _wiki_template_field(source, "known_loot")
        drops = _wiki_link_labels(known_loot)
        for item in re.findall(r"\{\{:\s*([^}|]+)", known_loot):
            label = _plain_wiki_text(item)
            if label and label.casefold() not in {
                    value.casefold() for value in drops}:
                drops.append(label)
        if drops:
            facts.append(("Known loot", f"{len(drops)} listed items"))
            loot_summary = "KNOWN LOOT\n" + "\n".join(
                f"• {value}" for value in drops)
            summary = (summary + "\n\n" + loot_summary).strip()
        return {
            "name": name or fallback_name.replace("_", " "),
            "kind": "NPC",
            "facts": facts,
            "drops": drops,
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


class ItemComparePanel(QWidget):
    """Independent P99 item finder and side-by-side stat comparison."""

    back_requested = Signal()
    MAX_ITEMS = 8

    META_ROWS = (
        ("Binding", lambda item: "NO DROP" if item.nodrop else "Droppable"),
        ("Era", lambda item: item.era.title() if item.era else "Not indexed"),
        ("Slots", lambda item: ", ".join(
            _gear_mask_labels(item.slots, SLOT_BITS)) or "Not listed"),
        ("Classes", lambda item: ", ".join(
            _gear_mask_labels(item.classes, CLASS_BITS)) or "Not listed"),
        ("Races", lambda item: ", ".join(
            _gear_mask_labels(item.races, RACE_BITS)) or "Not listed"),
    )
    EFFECT_ROWS = (
        ("Click", "clickName"), ("Proc", "procName"),
        ("Worn", "wornName"), ("Focus", "focusName"),
        ("Bard", "bardName"))

    def __init__(self, base, catalog=(), price_lookup=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ItemComparePanel")
        self.base = base if isinstance(base, GearItem) else None
        unique = {}
        for item in catalog or ():
            if isinstance(item, GearItem):
                unique.setdefault(_item_key(item.name), item)
        if self.base is not None:
            unique[_item_key(self.base.name)] = self.base
        self.catalog = tuple(sorted(unique.values(), key=lambda item: item.name.casefold()))
        self._catalog_by_key = {
            _item_key(item.name): item for item in self.catalog}
        self._price_lookup = price_lookup or (lambda _name: 0)
        self.items = [self.base] if self.base is not None else []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(9, 9, 9, 9)
        outer.setSpacing(6)

        header = QHBoxLayout()
        self.back_button = QPushButton("Back to item")
        self.back_button.setIcon(game_icon("back"))
        self.back_button.setAccessibleName("Back to item details")
        self.back_button.setToolTip("Return to the item card")
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        title = QLabel("COMPARE GEAR")
        title.setObjectName("ItemCompareTitle")
        title.setAccessibleName(title.text())
        header.addWidget(title)
        self.base_label = QLabel(
            f"BASE · {self.base.name}" if self.base else "NO BASE")
        self.base_label.setObjectName("ItemCompareBase")
        self.base_label.setToolTip("Every stat change is measured from this item")
        self.base_label.setAccessibleName(self.base_label.text())
        header.addWidget(self.base_label, 1)
        legend = QLabel("GAIN +   LOSS −   SAME =")
        legend.setObjectName("ItemCompareLegend")
        legend.setToolTip(
            "Teal is a stat gain, coral is a stat loss, and gray is unchanged")
        legend.setAccessibleName(
            "Comparison legend: gain, loss, and same")
        header.addWidget(legend)
        outer.addLayout(header)

        finder_layout = QHBoxLayout()
        finder_layout.setContentsMargins(0, 0, 0, 0)
        finder_layout.setSpacing(5)
        finder_label = QLabel("Add item")
        finder_label.setObjectName("ItemCompareSectionLabel")
        finder_layout.addWidget(finder_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search full P99 catalog, then choose a suggestion…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search all P99 items to compare")
        self.search.setAccessibleDescription(
            "Searches the full local item catalog, independently of the main Market list")
        self.search.setToolTip(
            "Type 2 or more characters and choose a suggestion; Enter also adds a unique result")
        self._search_matches = []
        self._completion_model = QStringListModel(self)
        self.completer = QCompleter(self._completion_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(9)
        self.completer.setWrapAround(False)
        self.completer.activated[str].connect(self._add_completion)
        self.search.setCompleter(self.completer)
        self.search.textChanged.connect(self._refresh_search_results)
        self.search.returnPressed.connect(self._add_selected)
        finder_layout.addWidget(self.search, 1)
        self.add_button = QPushButton("Add")
        self.add_button.setIcon(game_icon("plus"))
        self.add_button.setEnabled(False)
        self.add_button.setAccessibleName("Add matching item to comparison")
        self.add_button.setToolTip(
            "Add an exact or uniquely matching item from the full catalog")
        self.add_button.clicked.connect(self._add_selected)
        finder_layout.addWidget(self.add_button)
        outer.addLayout(finder_layout)

        self.search_status = QLabel(
            "Search is independent from Market filters · price is reference only")
        self.search_status.setObjectName("ItemCompareSearchStatus")
        self.search_status.setToolTip(
            "Search includes item names plus click, proc, worn, focus, and bard effects")
        outer.addWidget(self.search_status)

        selected_bar = QHBoxLayout()
        selected_label = QLabel("Comparing")
        selected_label.setObjectName("ItemCompareSectionLabel")
        selected_bar.addWidget(selected_label)
        self.selected_items = QListWidget()
        self.selected_items.setObjectName("ItemCompareSelectedItems")
        self.selected_items.setFixedHeight(38)
        self.selected_items.setFlow(QListWidget.Flow.LeftToRight)
        self.selected_items.setWrapping(False)
        self.selected_items.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.selected_items.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selected_items.setAccessibleName("Items currently being compared")
        self.selected_items.itemSelectionChanged.connect(
            self._selected_item_changed)
        selected_bar.addWidget(self.selected_items, 1)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setIcon(game_icon("trash"))
        self.remove_button.setEnabled(False)
        self.remove_button.setAccessibleName("Remove selected comparison item")
        self.remove_button.setToolTip("BASE is locked; select another item to remove it")
        self.remove_button.clicked.connect(self._remove_selected)
        selected_bar.addWidget(self.remove_button)
        outer.addLayout(selected_bar)

        self.summary = QLabel()
        self.summary.setObjectName("ItemCompareSummary")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setWordWrap(False)
        outer.addWidget(self.summary)

        self.table = QTableWidget()
        self.table.setObjectName("ItemCompareTable")
        self.table.setAccessibleName("Item stat comparison")
        self.table.setAccessibleDescription(
            "Items are columns. GAIN, LOSS, or SAME text and color show each numeric difference from BASE.")
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.table, 1)
        self._refresh_selected_items()
        self._render_comparison()

    def focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _refresh_search_results(self, query):
        query = str(query or "").strip().casefold()
        self._search_matches = []
        self._completion_model.setStringList([])
        self.add_button.setEnabled(False)
        if len(query) < 2:
            self.search_status.setText(
                "Type 2+ characters · full P99 catalog · independent from Market filters")
            return
        selected = {_item_key(item.name) for item in self.items}
        self._search_matches = [
            item for item in self.catalog
            if query in item.search_text and _item_key(item.name) not in selected]
        suggestions = [item.name for item in self._search_matches[:50]]
        self._completion_model.setStringList(suggestions)
        exact = self._catalog_by_key.get(_item_key(self.search.text()))
        ready = exact if exact not in self.items else None
        self.add_button.setEnabled(bool(ready or len(self._search_matches) == 1))
        self.search_status.setText(
            f"{len(self._search_matches):,} matches · choose a suggestion"
            if self._search_matches else "No matching item · try another name or effect")
        if suggestions and self.search.hasFocus():
            self.completer.complete()

    def _add_selected(self):
        exact = self._catalog_by_key.get(_item_key(self.search.text()))
        gear = exact if exact not in self.items else None
        if gear is None and len(self._search_matches) == 1:
            gear = self._search_matches[0]
        if gear is None:
            self.search_status.setText("Choose one item from the suggestions first")
            return False
        return self._add_item(gear)

    def _add_completion(self, name):
        gear = self._catalog_by_key.get(_item_key(name))
        return self._add_item(gear)

    def _add_item(self, gear):
        if not isinstance(gear, GearItem):
            return False
        if len(self.items) >= self.MAX_ITEMS:
            self.search_status.setText(
                f"Comparison limit reached · {self.MAX_ITEMS} items including BASE")
            return False
        key = _item_key(gear.name)
        if gear is None or key in {_item_key(item.name) for item in self.items}:
            return False
        self.items.append(gear)
        self._refresh_selected_items()
        self._render_comparison()
        with QSignalBlocker(self.search):
            self.search.clear()
        self._search_matches = []
        self._completion_model.setStringList([])
        self.add_button.setEnabled(False)
        self.search_status.setText(f"Added {gear.name} · {len(self.items)} items")
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def _selected_item_changed(self):
        selected = self.selected_items.currentRow()
        self.remove_button.setEnabled(selected > 0)
        self.remove_button.setToolTip(
            "Remove this item from the comparison" if selected > 0 else
            "BASE is locked; select another item to remove it")

    def _remove_selected(self):
        row = self.selected_items.currentRow()
        if row <= 0 or row >= len(self.items):
            return False
        removed = self.items.pop(row)
        self._refresh_selected_items()
        self._render_comparison()
        if self.search.text().strip():
            self._refresh_search_results(self.search.text())
        self.search_status.setText(f"Removed {removed.name} · {len(self.items)} items")
        return True

    def _refresh_selected_items(self):
        self.selected_items.clear()
        for index, gear in enumerate(self.items):
            row = QListWidgetItem(("BASE · " if index == 0 else "") + gear.name)
            row.setToolTip(
                "Locked comparison base" if index == 0 else
                "Select this item to remove it")
            self.selected_items.addItem(row)
        self.remove_button.setEnabled(False)

    def _render_comparison(self):
        row_count = len(self.META_ROWS) + 1 + len(STAT_OPTIONS) + len(self.EFFECT_ROWS)
        self.table.clear()
        self.table.setRowCount(row_count)
        self.table.setColumnCount(len(self.items))
        self.table.setHorizontalHeaderLabels([
            ("BASE · " if index == 0 else "") + item.name
            for index, item in enumerate(self.items)])
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(150)
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch if len(self.items) <= 4 else
            QHeaderView.ResizeMode.Interactive)

        row = 0
        for label, value_getter in self.META_ROWS:
            self._set_row_label(row, label, f"{label} for every compared item")
            for column, item in enumerate(self.items):
                self._set_text_cell(row, column, value_getter(item))
            row += 1

        self._set_row_label(
            row, "30d price", "Recent PigParse price; lower is not marked as better")
        base_price = int(self._price_lookup(self.items[0].name) or 0) if self.items else 0
        for column, item in enumerate(self.items):
            price = int(self._price_lookup(item.name) or 0)
            text = f"{price:,} pp" if price else "—"
            if price and column:
                text += f" · PRICE {price - base_price:+,} pp"
            elif price:
                text += " · BASE"
            self._set_text_cell(row, column, text)
        row += 1

        comparison = gear_comparison_rows(self.items)
        lead_counts = [0 for _ in self.items]
        for comparison_row in comparison:
            label = comparison_row["label"]
            self._set_row_label(
                row, label, f"{label}; higher values receive a star")
            for column, item in enumerate(self.items):
                value = comparison_row["values"][column]
                delta = comparison_row["deltas"][column]
                leading = column in comparison_row["leaders"]
                if leading:
                    lead_counts[column] += 1
                value_text = f"{value:+d}" if value else "0"
                state = "BASE" if column == 0 else (
                    f"GAIN {delta:+d}" if delta > 0 else
                    f"LOSS {delta:+d}" if delta < 0 else "SAME 0")
                text = ("BEST · " if leading else "") + value_text + " · " + state
                detail = (
                    f"{item.name} · {label} {value:+d} · " +
                    ("highest value · " if leading else "") +
                    ("comparison base" if column == 0 else
                     f"difference from base {delta:+d}"))
                self._set_text_cell(
                    row, column, text, detail, emphasized=leading,
                    delta=None if column == 0 else delta)
            row += 1

        for label, key in self.EFFECT_ROWS:
            self._set_row_label(
                row, label, f"{label} effect; effects are not numerically ranked")
            for column, item in enumerate(self.items):
                self._set_text_cell(
                    row, column, str(getattr(item, key, "") or "—"))
            row += 1

        if len(self.items) < 2:
            self.summary.setText(
                "Search above and choose an item to compare.")
            accessible_summary = self.summary.text()
        else:
            summaries = []
            accessible_parts = []
            rows = gear_comparison_rows(self.items)
            for column, item in enumerate(self.items[1:], 1):
                gains = sum(row["deltas"][column] > 0 for row in rows)
                losses = sum(row["deltas"][column] < 0 for row in rows)
                summaries.append(
                    f"<b>{html.escape(item.name)}</b> "
                    f"<span style='color:#8CF0C3'>+{gains} GAIN</span> · "
                    f"<span style='color:#FFAA9D'>−{losses} LOSS</span> · "
                    f"<span style='color:#F2D77F'>{lead_counts[column]} BEST</span>")
                accessible_parts.append(
                    f"{item.name}: {gains} gains, {losses} losses, "
                    f"{lead_counts[column]} best stats")
            self.summary.setText(" &nbsp; | &nbsp; ".join(summaries))
            accessible_summary = "; ".join(accessible_parts)
        self.summary.setAccessibleName(accessible_summary)
        self.summary.setToolTip(
            "Counts are unweighted; class, slot, and effects still determine the useful choice")

        if len(self.items) > 4:
            self.table.resizeColumnsToContents()
            for column in range(self.table.columnCount()):
                self.table.setColumnWidth(
                    column, min(260, max(160, self.table.columnWidth(column))))

    def _set_row_label(self, row, label, tooltip):
        item = QTableWidgetItem(label)
        item.setToolTip(tooltip)
        self.table.setVerticalHeaderItem(row, item)

    def _set_text_cell(
            self, row, column, text, tooltip="", emphasized=False, delta=None):
        item = QTableWidgetItem(str(text))
        item.setToolTip(tooltip or str(text))
        if delta is not None and delta > 0:
            item.setForeground(QColor("#8CF0C3"))
            item.setBackground(QColor("#10271F"))
        elif delta is not None and delta < 0:
            item.setForeground(QColor("#FFAA9D"))
            item.setBackground(QColor("#2B1716"))
        elif delta == 0:
            item.setForeground(QColor("#B8C1C5"))
            item.setBackground(QColor("#171C20"))
        if emphasized:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            if delta is None:
                item.setForeground(QColor("#F2D77F"))
        self.table.setItem(row, column, item)


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

    def __init__(self, item, parent=None, server="Green", catalog=(),
                 price_lookup=None):
        super().__init__(
            QSize(500, 430), parent, minimum_size=QSize(175, 151),
            initial_size=QSize(450, 387))
        self.item = item
        self.server = normalize_market_server(server)
        self.item_name = str(item.get("n") or "Item")
        self.wiki_name = self.item_name.replace("Spell: ", "")
        self.wiki_url = P99_WIKI_URL.format(
            slug=quote(self.wiki_name.replace(" ", "_")))
        self.setObjectName("WikiItemDialog")
        self.setWindowTitle(f"Vantage · {self.item_name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self.scaled_surface)
        root.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        self.pages.setObjectName("WikiItemPages")
        root.addWidget(self.pages)
        self.item_page = QWidget()
        outer = QVBoxLayout(self.item_page)
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
            f"PigParse {self.server} remains the price source of truth")
        card_layout.addWidget(self.source, 1, 1)

        self.attributes = QLabel(gear_item_summary_html(item.get("_gear")))
        self.attributes.setObjectName("WikiItemAttributes")
        self.attributes.setTextFormat(Qt.TextFormat.RichText)
        self.attributes.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.attributes.setWordWrap(True)
        self.attributes.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.attributes.setOpenExternalLinks(False)
        self.attributes.linkActivated.connect(self._internal_wiki_link)
        self.attributes.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.attributes.setAccessibleName("Item stats and effect links")
        self.attributes.setAccessibleDescription(
            "Click, proc, worn, focus, and bard effect names open a compact "
            "Project 1999 Wiki explanation")
        self.attributes.setToolTip(
            "Sortable local P99 stats. Select an underlined effect to see "
            "what it does according to Project 1999 Wiki")
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
            f"PigParse {self.server} · " + self._pig_price_text +
            f"\nP99 Wiki {self.server} · loading price…")
        self.price.setObjectName("WikiItemPrice")
        self.price.setWordWrap(True)
        self.price.setToolTip(
            "Vantage averages both sources only when their recent references "
            "differ by 30% or less")
        outer.addWidget(self.price)

        actions = QHBoxLayout()
        actions.addStretch(1)
        compare = QPushButton("Compare items")
        compare.setObjectName("ItemCardCompare")
        compare.setIcon(game_icon("compare"))
        compare.setEnabled(isinstance(item.get("_gear"), GearItem))
        compare.setAccessibleName(
            f"Compare {self.item_name} with other P99 items")
        compare.setToolTip(
            "Open an independent full-catalog search with this item locked as BASE"
            if compare.isEnabled() else
            "Comparison needs the local P99 item stats index")
        compare.clicked.connect(self._show_comparison)
        self.compare_button = compare
        actions.addWidget(compare)
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

        self.pages.addWidget(self.item_page)
        self.compare_panel = ItemComparePanel(
            item.get("_gear"), catalog=catalog,
            price_lookup=price_lookup, parent=self.pages)
        self.compare_panel.back_requested.connect(self._show_item)
        self.pages.addWidget(self.compare_panel)

    def _show_comparison(self):
        if not self.compare_button.isEnabled():
            return False
        self._item_window_size = self.size()
        self.pages.setCurrentWidget(self.compare_panel)
        self._set_page_design(
            QSize(800, 500), QSize(600, 375), QSize(800, 500))
        self.setWindowTitle(f"Vantage · Compare · {self.item_name}")
        self.compare_panel.focus_search()
        _announce_accessible(
            self, f"Independent item comparison opened. {self.item_name} is BASE")
        return True

    def _show_item(self):
        restore = getattr(self, "_item_window_size", QSize(450, 387))
        self.pages.setCurrentWidget(self.item_page)
        self._set_page_design(
            QSize(500, 430), QSize(175, 151), restore)
        self.setWindowTitle(f"Vantage · {self.item_name}")
        self.compare_button.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _set_page_design(self, design_size, minimum_size, window_size):
        """Keep both stacked pages crisp at their own native geometry."""
        self._dialog_design_size = QSize(design_size)
        old_proxy = self._dialog_proxy
        old_proxy.setWidget(None)
        self._dialog_scene.removeItem(old_proxy)
        old_proxy.deleteLater()
        self.scaled_surface.setFixedSize(self._dialog_design_size)
        self._dialog_proxy = self._dialog_scene.addWidget(self.scaled_surface)
        layout = self.scaled_surface.layout()
        if layout is not None:
            layout.invalidate()
            layout.setGeometry(self.scaled_surface.rect())
        self.setMinimumSize(QSize(minimum_size))
        self.resize(QSize(window_size))
        self._update_dialog_scale()

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
                f"PigParse {self.server} · " + self._pig_price_text +
                f"\nP99 Wiki {self.server} · no recognized recent price")
            return
        wiki_period = str(auction.get("reference_period") or "recent")
        seen = int(auction.get("recent_samples") or 0)
        last_date = str(auction.get("last_date") or "")
        wiki_line = (
            f"P99 Wiki {self.server} · {wiki_price:,} pp ({wiki_period}"
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
            headline + f"\nPigParse {self.server} · " + self._pig_price_text +
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
    """In-app P99 Wiki summary for a drop NPC, zone, or item effect."""

    def __init__(self, name, kind, parent=None):
        super().__init__(
            QSize(430, 310), parent, minimum_size=QSize(151, 109),
            initial_size=QSize(387, 279))
        self.target_name = name
        self.entity_kind = kind
        self.wiki_url = _wiki_target_url(name)
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
        open_wiki = QPushButton("Open P99 Wiki")
        open_wiki.setIcon(game_icon("map"))
        open_wiki.setToolTip(
            "Open the full Project 1999 Wiki page in your browser")
        open_wiki.clicked.connect(lambda: webbrowser.open(self.wiki_url))
        close = QPushButton("Close")
        close.setToolTip("Close this card")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(open_wiki)
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
            "Use Install WTS button for clickable links.")
        self.guide.setObjectName("MarketStatSummary")
        self.guide.setWordWrap(True)
        self.guide.setToolTip(
            "Copy pastes clean chat text immediately. Install WTS/WTB button "
            "creates EQ Socials; WTS keeps clickable Titanium links.")
        root.addWidget(self.guide)

        source_row = QHBoxLayout()
        source_row.setSpacing(4)
        self.link_status = QLabel(
            "WTS Social buttons preserve clickable links · no inventory file needed")
        self.link_status.setObjectName("MarketGearSource")
        self.link_status.setAccessibleName("P99 item link source")
        self.link_status.setToolTip(
            "Vantage can install WTS with clickable links or plain-text WTB into "
            "separate character Social buttons.")
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
            "Copy WTS/WTB pastes plain text. To create Social buttons, fully camp "
            "out and use Install WTS/WTB button; they load on the next login.")
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
        self.hotbutton_button = QPushButton("Install WTS button…")
        self.hotbutton_button.setIcon(game_icon("export"))
        self.hotbutton_button.setAccessibleName(
            "Install WTS Social button with clickable item links")
        self.hotbutton_button.setToolTip(
            "Install this WTS into free EQ Social buttons with clickable item links; "
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
            "Search item → Add → set your offer and quantity → Copy WTB or "
            "Install WTB button.")
        trade_type = "WTS" if selling else "WTB"
        self.link_status.setText(
            "WTS Social buttons preserve clickable links · no inventory file needed"
            if selling else
            "WTB Social buttons use clean plain text · no inventory file needed")
        self.hotbutton_button.setText(f"Install {trade_type} button…")
        self.hotbutton_button.setAccessibleName(
            f"Install {trade_type} EQ Social button" +
            (" with clickable item links" if selling else " using plain text"))
        self.hotbutton_button.setToolTip(
            f"Install this {trade_type} into free EQ Social buttons" +
            (" with clickable item links" if selling else " as plain text") +
            "; fully camp out first")
        self.copy_button.setText("Copy WTS" if selling else "Copy WTB")
        self._sync_copy_button_accessibility()
        self.paste_note.setText(
            ("Copy WTS = plain text · Install WTS button = clickable Social."
             if selling else
             "Copy WTB = plain text · Install WTB button = plain-text Social."))
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
        self.hotbutton_button.setEnabled(bool(
            self._linked_lines and
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
        if trade_type == "WTB":
            link_state = " · plain-text WTB Social ready"
        else:
            link_state = (
                f" · {linked} link{'s' if linked != 1 else ''} ready for WTS Social"
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
                "Add at least one item before installing", announce=True)
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
            trade_type = "WTB" if self.trade_type.currentIndex() == 1 else "WTS"
            slots, backup = install_auction_hotbuttons(
                selected, self._linked_lines, trade_type)
        except (OSError, UnicodeError, ValueError) as error:
            self._set_preview_status(
                f"Hotbutton not installed · {error}", announce=True)
            return False
        slot_names = ", ".join(
            re.sub(r"^Page(\d+)Button(\d+)$", r"page \1, button \2", slot)
            for slot in slots)
        self._set_preview_status(
            f"Installed {trade_type} · {slot_names} · backup {backup.name} · "
            "relog and open Socials",
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
        self._server = normalize_market_server(
            config.data["market"].get("server", "Green"))
        self.setWindowTitle(f"{self._server} Market · PigParse")
        self._title.setText(f"Market · {self._server}")
        self._zone = ""
        self._loaded_online = False
        self._requests_in_flight = set()
        self._gear_source = "P99 Wiki metadata"
        self._mobile_items = ()
        self._mobile_revision = 0
        self._last_consider_name = ""
        self._consider_card = None
        self._live_alerted_at = {}
        self._live_match_count = 0
        self._last_live_alert = ""
        self._last_live_alert_state = "ready"

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
        self.search.setAccessibleName(f"Search the {self._server} market")
        self.search.setAccessibleDescription(
            f"Filters PigParse {self._server} prices and the shared P99 item "
            "metadata while you type")
        self.search.setToolTip(
            "Type any part of an item, click, proc, worn, focus, or bard effect; "
            "results filter while you type")
        clear_search = self.search.findChild(QToolButton)
        if clear_search:
            clear_search.setAccessibleName("Clear market search")
            clear_search.setToolTip("Clear the search text")
        self.search.textChanged.connect(self._set_query)

        self.server_selector = QComboBox()
        self.server_selector.setObjectName("MarketServerSelector")
        self.server_selector.addItems(MARKET_SERVERS)
        self.server_selector.setCurrentText(self._server)
        self.server_selector.setAccessibleName("PigParse market server")
        self.server_selector.setAccessibleDescription(
            "Choose Green or Blue; prices and Wiki Auction Tracker values stay "
            "separate while item stats remain shared")
        self.server_selector.setToolTip(
            "Choose PigParse Green or Blue prices · selection is remembered · "
            "local /auction history is not changed")
        self.server_selector.currentTextChanged.connect(self._server_changed)

        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.setIcon(game_icon("refresh"))
        self._refresh_button.setToolTip(
            f"Refresh prices from PigParse {self._server}")
        self._refresh_button.clicked.connect(self.refresh)
        self._sources_button = QPushButton("Sources")
        self._sources_button.setIcon(game_icon("layers"))
        self._sources_button.setToolTip(
            "View the source of prices, attributes, and item metadata")
        self._sources_button.clicked.connect(self._show_sources)
        self._live_status_button = QPushButton("Sale alerts · 0")
        self._live_status_button.setObjectName("MarketLiveStatus")
        self._live_status_button.setIcon(game_icon("ph-storefront"))
        self._live_status_button.setAccessibleName(
            "Open live item sale alerts")
        self._live_status_button.setToolTip(
            "Open watched-item alerts from /auction messages in this EQ log")
        self._live_status_button.clicked.connect(self._open_live_alerts)
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
        self.clear_filters_button = QPushButton("Clear filters")
        self.clear_filters_button.setIcon(game_icon("filter-clear"))
        self.clear_filters_button.setAccessibleName(
            "Clear all Market search and equipment filters")
        self.clear_filters_button.setAccessibleDescription(
            "Restores the default item search, equipment filters, and sorting "
            "without changing the selected server or sale-alert watchlist")
        self.clear_filters_button.setToolTip(
            "Clear search, class, race, slot, effect, binding, era, and stat sort · "
            "keeps the server and watchlist")
        self.clear_filters_button.clicked.connect(self._clear_filters)
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
            "Click an item name to view its card and compare it")
        self.gear_filter_note.setObjectName("MarketStatSummary")
        self.gear_filter_note.setAccessibleName(self.gear_filter_note.text())
        self.gear_filter_note.setToolTip(
            "Comparison opens inside the item card and has its own full-catalog search")
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

        self._zone_tab_index = self.tabs.addTab(
            self._zone_explorer_page(), "Zones")

        self.auction_composer = AuctionComposer(self._auction_price, self)
        self._auction_tab_index = self.tabs.addTab(
            self.auction_composer, "WTS / WTB Builder")

        live_page = QWidget()
        live_page.setObjectName("MarketSaleAlertsPage")
        live_layout = QVBoxLayout(live_page)
        live_layout.setContentsMargins(8, 8, 8, 8)
        live_layout.setSpacing(6)
        self.live_note = QLabel(
            "EC TUNNEL REQUIRED · Keep /log on and Vantage running while your "
            "character is in East Commonlands Tunnel. Search and alerts only "
            "include /auction messages received there during this Vantage session.")
        self.live_note.setObjectName("MarketSaleAlertsIntro")
        self.live_note.setWordWrap(True)
        self.live_note.setAccessibleName(self.live_note.text())
        self.live_note.setToolTip(
            "Only listings written to your own EQ log can appear here; keep logs "
            "enabled and remain where you can receive /auction chat")
        live_layout.addWidget(self.live_note)
        watch_tools = QFrame()
        watch_tools.setObjectName("MarketSaleAlertSetup")
        watch_layout = QGridLayout(watch_tools)
        watch_layout.setContentsMargins(8, 7, 8, 7)
        watch_layout.setHorizontalSpacing(6)
        watch_layout.setVerticalSpacing(5)
        self.live_watch_input = QLineEdit()
        self.live_watch_input.setObjectName("MarketSaleAlertInput")
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
        watch_layout.addWidget(self.live_watch_input, 0, 0, 1, 6)
        self.live_watch_add = QPushButton("Add to watchlist")
        self.live_watch_add.setObjectName("MarketSaleAlertAdd")
        self.live_watch_add.setIcon(game_icon("add"))
        self.live_watch_add.setAccessibleName(
            "Add alert — create live auction notification")
        self.live_watch_add.setToolTip(
            "Notify on the Vantage overlay when this item appears for sale")
        self.live_watch_add.clicked.connect(self._add_live_watch)
        watch_layout.addWidget(self.live_watch_add, 0, 6)
        self.live_watch_label = QLabel("Watching")
        self.live_watch_label.setObjectName("MarketSaleAlertLabel")
        self.live_watch_items = QListWidget()
        self.live_watch_items.setObjectName("MarketSaleAlertItems")
        self.live_watch_items.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.live_watch_items.setAlternatingRowColors(True)
        self.live_watch_items.setMinimumHeight(62)
        self.live_watch_items.setMaximumHeight(118)
        self.live_watch_items.setAccessibleName("Watched auction items")
        self.live_watch_items.setAccessibleDescription(
            "Visible list of every item monitored in this character's EQ log")
        self.live_watch_items.setToolTip(
            "Every watched item is shown here; select one to remove or test")
        self.live_watch_label.setBuddy(self.live_watch_items)
        watch_layout.addWidget(self.live_watch_label, 1, 0, 1, 7)
        watch_layout.addWidget(self.live_watch_items, 2, 0, 1, 7)
        self.live_watch_remove = QPushButton("Remove selected")
        self.live_watch_remove.setIcon(game_icon("delete"))
        self.live_watch_remove.setAccessibleName(
            "Remove — selected auction alert")
        self.live_watch_remove.setToolTip("Stop watching the selected item")
        self.live_watch_remove.clicked.connect(self._remove_live_watch)
        watch_layout.addWidget(self.live_watch_remove, 3, 0, 1, 2)
        self.live_alerts_enabled = QCheckBox("Notifications")
        self.live_alerts_enabled.setChecked(bool(
            config.data["market"].get("live_alerts_enabled", True)))
        self.live_alerts_enabled.setAccessibleName(
            "Notifications — enable watched-item sale notifications")
        self.live_alerts_enabled.setToolTip(
            "Notify when a watched sale reaches this character's EQ log; "
            "uses the Vantage overlay or Windows notifications")
        self.live_alerts_enabled.toggled.connect(
            self._set_live_alerts_enabled)
        watch_layout.addWidget(self.live_alerts_enabled, 3, 3)
        self.live_alert_sound = QCheckBox("Sound")
        self.live_alert_sound.setChecked(bool(
            config.data["market"].get("live_alert_sound_enabled", False)))
        self.live_alert_sound.setAccessibleName(
            "Sound — play the sale alert chime")
        self.live_alert_sound.setToolTip(
            "Play one Soft Notify chime for a matched sale; Master Mute on "
            "the Quick Bar always wins")
        self.live_alert_sound.toggled.connect(
            self._set_live_alert_sound_enabled)
        watch_layout.addWidget(self.live_alert_sound, 3, 4)
        self.live_alert_test = QPushButton("Test")
        self.live_alert_test.setObjectName("MarketSaleAlertTest")
        self.live_alert_test.setIcon(game_icon("check"))
        self.live_alert_test.setAccessibleName(
            "Test the selected live sale alert")
        self.live_alert_test.setToolTip(
            "Show a sample sale notification using the selected watched item")
        self.live_alert_test.clicked.connect(self._preview_live_alert)
        watch_layout.addWidget(self.live_alert_test, 3, 6)
        watch_layout.setColumnStretch(0, 0)
        watch_layout.setColumnStretch(1, 1)
        watch_layout.setColumnStretch(2, 1)
        live_layout.addWidget(watch_tools)
        self.live_alert_status = QLabel(
            "No watched items · select a market row and choose Watch sale")
        self.live_alert_status.setObjectName("MarketLiveAlertStatus")
        self.live_alert_status.setProperty("State", "empty")
        self.live_alert_status.setWordWrap(True)
        self.live_alert_status.setAccessibleName(
            "Live sale alert service status")
        self.live_alert_status.setToolTip(
            "Matched sales stay visible here even if notification overlays are disabled")
        live_layout.addWidget(self.live_alert_status)
        live_search_bar = QFrame()
        live_search_bar.setObjectName("MarketAuctionSearchBar")
        live_search_layout = QHBoxLayout(live_search_bar)
        live_search_layout.setContentsMargins(7, 6, 7, 6)
        live_search_layout.setSpacing(7)
        self.live_search = QLineEdit()
        self.live_search.setObjectName("MarketAuctionSearchInput")
        self.live_search.setPlaceholderText("Search heard auctions…")
        self.live_search.setClearButtonEnabled(True)
        self.live_search.setAccessibleName(
            "Search auctions heard in East Commonlands Tunnel")
        self.live_search.setAccessibleDescription(
            "Filters seller names and auction messages received by this "
            "EverQuest character during the current Vantage session")
        self.live_search.setToolTip(
            "Search seller or item text from /auction messages heard while this "
            "character was in East Commonlands Tunnel; results update as messages arrive")
        clear_live_search = self.live_search.findChild(QToolButton)
        if clear_live_search:
            clear_live_search.setAccessibleName("Clear heard-auction search")
            clear_live_search.setToolTip("Show every auction heard this session")
        self.live_search.textChanged.connect(self._set_live_query)
        live_search_layout.addWidget(self.live_search, 1)
        self.live_search_count = QLabel("0 heard auctions")
        self.live_search_count.setObjectName("MarketAuctionSearchCount")
        self.live_search_count.setAccessibleName("No auctions heard this session")
        self.live_search_count.setToolTip(
            "Up to the 500 most recent /auction messages remain searchable until Vantage closes")
        live_search_layout.addWidget(self.live_search_count)
        live_layout.addWidget(live_search_bar)
        self._refresh_live_watch_items()
        self.live_table = QTableView()
        self.live_table.setObjectName("MarketLiveAuctionTable")
        self.live_table.setModel(self._local_proxy)
        self.live_table.setAccessibleName("Live EC auction log")
        self.live_table.setAccessibleDescription(
            "Searchable auction messages received by this EverQuest client during "
            "the current Vantage session, newest first")
        self.live_table.setWordWrap(False)
        self.live_table.verticalHeader().setVisible(False)
        live_header = self.live_table.horizontalHeader()
        live_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        live_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        live_layout.addWidget(self.live_table, 1)
        self._live_tab_index = self.tabs.addTab(
            live_page, "Sale Alerts · 0")
        self._update_live_search_count()
        ensure_tab_tooltips(self.tabs, {
            "PigParse · prices": (
                f"Search cached PigParse {self._server} listings and prices"),
            "Gear · stats": (
                "Compare and sort P99 items by stats, class, race, slot, and effects"),
            "Zones": (
                "Search a P99 zone, then browse its mobs, nameds, drops, and map"),
            "WTS / WTB Builder": (
                "Build customized auction messages; WTS uses real item links and "
                "WTB uses plain text"),
            "Sale Alerts · 0": (
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
        self.status = QLabel(f"Preparing PigParse {self._server}…")
        self.status.setWordWrap(True)
        self._analyze_button = QPushButton("Evaluate Price")
        self._analyze_button.setIcon(game_icon("timer"))
        self._analyze_button.setToolTip(
            "Calculate a robust median without changing the original data")
        self._analyze_button.clicked.connect(self._analyze_selected)
        self._detail_button = QPushButton("PigParse History")
        self._detail_button.setIcon(game_icon("market"))
        self._detail_button.setToolTip(
            f"Open the selected item's full PigParse {self._server} history")
        self._detail_button.clicked.connect(self._open_detail)
        self._wiki_button = QPushButton("Item + Wiki Price")
        self._wiki_button.setIcon(game_icon("map"))
        self._wiki_button.setToolTip(
            f"Show the item card and P99 Wiki {self._server} price inside Vantage")
        self._wiki_button.clicked.connect(self._show_wiki_card)
        self._watch_selected_button = QPushButton("Watch sale")
        self._watch_selected_button.setIcon(game_icon("ph-storefront"))
        self._watch_selected_button.setAccessibleName(
            "Watch the selected item for a live sale")
        self._watch_selected_button.setToolTip(
            "Alert when the selected item appears in a /auction line received by this EQ client")
        self._watch_selected_button.clicked.connect(self._watch_selected_item)
        self._body_layout.addWidget(footer)
        self._responsive_widgets = (
            self.search, self.server_selector, self._refresh_button,
            self._sources_button, self._live_status_button,
            self.class_filter, self.race_filter,
            self.slot_filter, self.clear_filters_button,
            self.gear_status, self.status,
            self.stat_sort, self.effect_filter, self.tradeability_filter,
            self.era_filter,
            self._watch_selected_button, self._analyze_button,
            self._detail_button, self._wiki_button)
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
        self._load_cache(self._server)
        self._load_gear_cache()
        # Cached data is usable immediately. Network initialization is delayed
        # until the event loop is settled so Windows can finish showing the
        # tray and parser tools without a startup CPU/network spike.
        QTimer.singleShot(1800, self._start_deferred_refresh)

    def _start_deferred_refresh(self):
        self._refresh_gear_index()
        if self._toggled and not self._loaded_online:
            self.refresh()

    def _zone_explorer_page(self):
        """Build the compact P99 zone browser inside Market."""
        page = QWidget()
        page.setObjectName("MarketZonesPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        controls = QFrame()
        controls.setObjectName("MarketZoneControls")
        control_layout = QGridLayout(controls)
        control_layout.setContentsMargins(7, 6, 7, 6)
        control_layout.setSpacing(5)
        self.zone_selector = QComboBox()
        self.zone_selector.setEditable(True)
        self.zone_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zone_selector.addItems(sorted(
            MapData.get_zone_dict(), key=str.casefold))
        self.zone_selector.setCurrentText(
            str(config.data["market"].get("zone_explorer_last", "") or ""))
        self.zone_selector.setAccessibleName("Zone to explore")
        self.zone_selector.setAccessibleDescription(
            "Search the bundled Project 1999 zone names and load its Wiki catalog")
        self.zone_selector.setToolTip(
            "Type a zone name, choose it from the list, then press Enter or Load")
        self.zone_selector.lineEdit().setAccessibleName("Zone name search")
        self.zone_selector.lineEdit().setToolTip(
            "Type all or part of a Project 1999 zone name")
        zone_completer = self.zone_selector.completer()
        if zone_completer:
            zone_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            zone_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.zone_selector.lineEdit().returnPressed.connect(self._load_zone_explorer)
        control_layout.addWidget(self.zone_selector, 0, 0, 1, 3)

        self.zone_load_button = QPushButton("Load zone")
        self.zone_load_button.setIcon(game_icon("search"))
        self.zone_load_button.setAccessibleName("Load selected P99 zone")
        self.zone_load_button.setToolTip(
            "Load mobs, nameds, drops, level range, and zone facts from P99 Wiki")
        self.zone_load_button.clicked.connect(self._load_zone_explorer)
        control_layout.addWidget(self.zone_load_button, 0, 3)

        self.zone_search = QLineEdit()
        self.zone_search.setPlaceholderText("Search this zone: mob, drop, level…")
        self.zone_search.setClearButtonEnabled(True)
        self.zone_search.setAccessibleName("Search within the loaded zone")
        self.zone_search.setToolTip(
            "Filter the loaded zone by NPC, level, class, race, location, drop, or notes")
        clear_zone_search = self.zone_search.findChild(QToolButton)
        if clear_zone_search:
            clear_zone_search.setAccessibleName("Clear zone result search")
            clear_zone_search.setToolTip("Show every mob in the loaded zone")
        self.zone_search.textChanged.connect(self._refresh_zone_rows)
        control_layout.addWidget(self.zone_search, 1, 0, 1, 3)

        self.zone_named_only = QCheckBox("Nameds only")
        self.zone_named_only.setAccessibleName("Show named NPCs only")
        self.zone_named_only.setToolTip(
            "Show only NPCs listed as notable on this P99 Wiki zone page")
        self.zone_named_only.toggled.connect(self._refresh_zone_rows)
        control_layout.addWidget(self.zone_named_only, 1, 3)
        control_layout.setColumnStretch(0, 1)
        layout.addWidget(controls)

        self.zone_summary = QLabel(
            "Choose a zone to browse its mobs, nameds, drops, and Vantage map.")
        self.zone_summary.setObjectName("MarketZoneSummary")
        self.zone_summary.setWordWrap(True)
        self.zone_summary.setAccessibleName(self.zone_summary.text())
        layout.addWidget(self.zone_summary)

        headers = ("Named", "NPC", "Level", "Class", "Race", "Drops", "Location")
        self.zone_table = QTableWidget(0, len(headers))
        self.zone_table.setObjectName("MarketZoneTable")
        self.zone_table.setHorizontalHeaderLabels(headers)
        self.zone_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.zone_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.zone_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.zone_table.setAlternatingRowColors(True)
        self.zone_table.setSortingEnabled(True)
        self.zone_table.verticalHeader().setVisible(False)
        self.zone_table.setAccessibleName("Mobs in selected Project 1999 zone")
        self.zone_table.setAccessibleDescription(
            "Sortable and searchable NPC list with named status, levels, drops, and locations")
        ensure_table_header_tooltips(
            self.zone_table, "the selected Project 1999 zone")
        zone_header = self.zone_table.horizontalHeader()
        zone_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        zone_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        zone_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((58, 180, 60, 92, 92, 220, 170)):
            self.zone_table.setColumnWidth(column, width)
        self.zone_table.itemSelectionChanged.connect(
            self._zone_selection_changed)
        self.zone_table.cellDoubleClicked.connect(self._open_zone_row)
        actions = QFrame()
        actions.setObjectName("MarketZoneActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(6, 4, 6, 4)
        action_layout.setSpacing(5)
        self.zone_result_count = QLabel("No zone loaded")
        self.zone_result_count.setObjectName("MarketStatSummary")
        action_layout.addWidget(self.zone_result_count, 1)
        self.zone_npc_button = QPushButton("NPC details")
        self.zone_npc_button.setIcon(game_icon("poi"))
        self.zone_npc_button.setEnabled(False)
        self.zone_npc_button.setToolTip(
            "Open the selected NPC's level, location, combat facts, and Wiki summary")
        self.zone_npc_button.clicked.connect(self._open_selected_zone_npc)
        action_layout.addWidget(self.zone_npc_button)
        self.zone_drop_selector = QComboBox()
        self.zone_drop_selector.setMinimumContentsLength(14)
        self.zone_drop_selector.setAccessibleName("Drop from selected NPC")
        self.zone_drop_selector.setToolTip(
            "Choose one known drop from the selected NPC")
        self.zone_drop_selector.setEnabled(False)
        action_layout.addWidget(self.zone_drop_selector)
        self.zone_drop_button = QPushButton("Item details")
        self.zone_drop_button.setIcon(game_icon("market"))
        self.zone_drop_button.setEnabled(False)
        self.zone_drop_button.setToolTip(
            "Open the selected drop as a full Vantage item card")
        self.zone_drop_button.clicked.connect(self._open_selected_zone_drop)
        action_layout.addWidget(self.zone_drop_button)
        self.zone_map_button = QPushButton("Vantage map")
        self.zone_map_button.setIcon(game_icon("map"))
        self.zone_map_button.setEnabled(False)
        self.zone_map_button.setToolTip(
            "Open this zone in Vantage's interactive map window")
        self.zone_map_button.clicked.connect(self._open_zone_map)
        action_layout.addWidget(self.zone_map_button)
        self.zone_wiki_button = QPushButton("Zone Wiki")
        self.zone_wiki_button.setIcon(game_icon("ph-file-search"))
        self.zone_wiki_button.setEnabled(False)
        self.zone_wiki_button.setToolTip(
            "Open the complete zone page on Project 1999 Wiki")
        self.zone_wiki_button.clicked.connect(self._open_zone_wiki)
        action_layout.addWidget(self.zone_wiki_button)
        layout.addWidget(actions)
        layout.addWidget(self.zone_table, 1)

        self._zone_data = {}
        self._zone_mobs = []
        self._zone_drop_requests = set()
        return page

    def _load_zone_explorer(self):
        requested = self.zone_selector.currentText().strip()
        if not requested:
            self.zone_summary.setText("Enter or choose a zone first.")
            self.zone_selector.setFocus()
            return False
        self.zone_load_button.setEnabled(False)
        self.zone_load_button.setText("Loading…")
        self.zone_summary.setText(
            f"Loading {requested} from Project 1999 Wiki…")
        cached_path = _wiki_zone_cache_path(requested)
        try:
            cached = json.loads(cached_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("mobs"):
                self._set_zone_data(cached, cached=True)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(requested.replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._zone_finished(
            reply, requested, cached_path))
        return True

    def _zone_finished(self, reply, requested, cache_path):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("zone not found on P99 Wiki")
            wikitext = parsed.get("wikitext", {})
            rendered = parsed.get("text", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            data = parse_wiki_zone_payload(
                wikitext, rendered, parsed.get("title") or requested)
            if not data.get("mobs"):
                raise ValueError("this page has no recognized P99 zone mob table")
            self._set_zone_data(data)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            if not self._zone_mobs:
                self.zone_summary.setText(
                    f"Could not load {requested} · {error}")
                self.zone_summary.setAccessibleName(self.zone_summary.text())
        finally:
            self.zone_load_button.setEnabled(True)
            self.zone_load_button.setText("Load zone")
            reply.deleteLater()

    def _set_zone_data(self, data, cached=False):
        self._zone_data = dict(data or {})
        self._zone_mobs = list(self._zone_data.get("mobs") or [])
        name = str(self._zone_data.get("name") or
                   self.zone_selector.currentText()).strip()
        self.zone_selector.setCurrentText(name)
        config.data["market"]["zone_explorer_last"] = name
        if getattr(config, "_filename", ""):
            config.save()
        notable_count = sum(bool(mob.get("named")) for mob in self._zone_mobs)
        facts = [value for value in (
            self._zone_data.get("era"),
            f"Levels {self._zone_data.get('levels')}"
            if self._zone_data.get("levels") else "",
            f"{len(self._zone_mobs):,} mobs",
            f"{notable_count:,} nameds",
            self._zone_data.get("types")) if value]
        suffix = " · cached" if cached else " · updated now"
        self.zone_summary.setText(" · ".join(facts) + suffix)
        self.zone_summary.setAccessibleName(self.zone_summary.text())
        self.zone_map_button.setEnabled(bool(MapData.resolve_zone_name(name)))
        self.zone_wiki_button.setEnabled(True)
        self._refresh_zone_rows()
        _announce_accessible(
            self, f"Loaded {name}: {len(self._zone_mobs)} mobs, "
            f"{notable_count} named NPCs")

    def _refresh_zone_rows(self, *_):
        if not hasattr(self, "zone_table"):
            return
        query = self.zone_search.text().strip().casefold()
        named_only = self.zone_named_only.isChecked()
        visible = []
        for mob in self._zone_mobs:
            if named_only and not mob.get("named"):
                continue
            haystack = " ".join(str(value or "") for value in (
                mob.get("name"), mob.get("level"), mob.get("class"),
                mob.get("race"), mob.get("loot"), mob.get("location"),
                mob.get("description"))).casefold()
            if query and query not in haystack:
                continue
            visible.append(mob)
        self.zone_table.setSortingEnabled(False)
        self.zone_table.setRowCount(len(visible))
        for row, mob in enumerate(visible):
            values = (
                "Yes" if mob.get("named") else "",
                mob.get("name"), mob.get("level"), mob.get("class"),
                mob.get("race"), mob.get("loot") or "—",
                mob.get("location") or "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(Qt.ItemDataRole.UserRole, mob)
                self.zone_table.setItem(row, column, item)
        self.zone_table.setSortingEnabled(True)
        self.zone_result_count.setText(
            f"{len(visible):,} / {len(self._zone_mobs):,} mobs")
        self.zone_result_count.setAccessibleName(self.zone_result_count.text())
        self._zone_selection_changed()

    def _selected_zone_mob(self):
        row = self.zone_table.currentRow()
        if row < 0:
            return None
        item = self.zone_table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return value if isinstance(value, dict) else None

    def _zone_selection_changed(self):
        mob = self._selected_zone_mob()
        self.zone_npc_button.setEnabled(bool(mob))
        self.zone_drop_selector.clear()
        for drop in (mob or {}).get("drops", []):
            self.zone_drop_selector.addItem(str(drop))
        has_drops = self.zone_drop_selector.count() > 0
        self.zone_drop_selector.setEnabled(has_drops)
        self.zone_drop_button.setEnabled(has_drops)
        if (mob and not has_drops and
                str(mob.get("loot") or "").casefold() == "various"):
            self._load_selected_zone_drops(mob)

    def _load_selected_zone_drops(self, mob):
        target = str(mob.get("target") or mob.get("name") or "").strip()
        key = target.casefold()
        if not target or key in self._zone_drop_requests:
            return False
        cache_path = _wiki_entity_cache_path(target, "npc")
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            drops = list(cached.get("drops") or [])
            if drops:
                self._apply_zone_npc_drops(mob, drops)
                return True
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        self._zone_drop_requests.add(key)
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(target.replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._zone_npc_drops_finished(
            reply, mob, target, key, cache_path))
        return True

    def _zone_npc_drops_finished(self, reply, mob, target, key, cache_path):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                return
            wikitext = parsed.get("wikitext", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            entity = parse_wiki_entity_wikitext(
                wikitext, fallback_name=target, kind="npc")
            cache_path.write_text(json.dumps(entity), encoding="utf-8")
            self._apply_zone_npc_drops(mob, entity.get("drops") or [])
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError):
            pass
        finally:
            self._zone_drop_requests.discard(key)
            reply.deleteLater()

    def _apply_zone_npc_drops(self, mob, drops):
        drops = [str(value).strip() for value in drops if str(value).strip()]
        if not drops:
            return False
        mob["drops"] = drops
        mob["loot"] = ", ".join(drops)
        selected = self._selected_zone_mob()
        if selected is mob:
            self.zone_drop_selector.clear()
            self.zone_drop_selector.addItems(drops)
            self.zone_drop_selector.setEnabled(True)
            self.zone_drop_button.setEnabled(True)
            row = self.zone_table.currentRow()
            item = self.zone_table.item(row, 5)
            if item:
                item.setText(mob["loot"])
                item.setToolTip(mob["loot"])
        return True

    def _open_zone_row(self, row, column):
        if column == 5 and self._selected_zone_mob() and (
                self._selected_zone_mob().get("drops")):
            return self._open_selected_zone_drop()
        return self._open_selected_zone_npc()

    def _open_selected_zone_npc(self):
        mob = self._selected_zone_mob()
        if not mob:
            return False
        self._show_wiki_entity(
            mob.get("target") or mob.get("name"), mob.get("name"), "npc")
        return True

    def _open_selected_zone_drop(self):
        name = self.zone_drop_selector.currentText().strip()
        if not name:
            return False
        self._show_wiki_item_name(name)
        return True

    def _open_zone_map(self):
        name = str(self._zone_data.get("name") or "")
        app = QApplication.instance()
        maps = getattr(app, "_parsers_dict", {}).get("maps")
        if not maps or not maps._load_zone(name):
            self.zone_summary.setText(
                f"No bundled Vantage map matches {name}.")
            return False
        if not maps.isVisible():
            maps.toggle()
        else:
            maps.raise_()
            maps.activateWindow()
        return True

    def _open_zone_wiki(self):
        name = str(self._zone_data.get("name") or "").strip()
        if not name:
            return False
        return bool(webbrowser.open(_wiki_target_url(name)))

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

    def _clear_filters(self):
        """Restore every Market result filter without touching user data."""
        controls = (
            self.search, self.class_filter, self.race_filter,
            self.slot_filter, self.stat_sort, self.effect_filter,
            self.tradeability_filter, self.era_filter)
        blockers = [QSignalBlocker(control) for control in controls]
        self.search.clear()
        for combo in controls[1:]:
            combo.setCurrentIndex(0)

        self._proxy.set_query("")
        self._gear_proxy.set_query("")
        for kind in ("class", "race", "slot"):
            self._proxy.set_gear_filter(kind, 0)
            self._gear_proxy.set_gear_filter(kind, 0)
        self._gear_proxy.set_effect_filter("")
        self._gear_proxy.set_tradeability_filter("")
        self._gear_proxy.set_era_filter("")
        self._gear_model.set_active_stat("ac")
        for column in CORE_STAT_COLUMNS.values():
            self.gear_table.setColumnHidden(column, False)
        self.gear_table.setColumnHidden(CORE_STAT_COLUMNS["ac"], True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.gear_table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.table.clearSelection()
        self.gear_table.clearSelection()
        self.live_table.clearSelection()
        self._update_gear_summary()
        self.status.setText(
            f"Filters cleared · PigParse {self._server} and watchlist unchanged")
        _announce_accessible(
            self, "Market filters cleared; server and watchlist unchanged")
        # Keep blockers alive until every model receives its final state.
        del blockers
        return True

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
        if index.isValid() and index.column() == 0:
            self._show_wiki_card(index)

    def _gear_item_clicked(self, index):
        if index.isValid() and index.column() == 0:
            self._show_wiki_card(index)

    def _show_wiki_card(self, index=None):
        item = self._selected_item(index)
        if not item:
            self.status.setText("Select an item name to open its card")
            return
        return self._show_wiki_item_payload(item)

    def _show_wiki_item_name(self, name):
        """Open a full item card from a zone drop without changing filters."""
        wanted = str(name or "").strip()
        if not wanted:
            return None
        gear = next((item for item in self._gear_model.items
                     if item.name.casefold() == wanted.casefold()), None)
        item = dict(self._gear_model.price_item(wanted) or {})
        item["n"] = gear.name if gear else wanted
        item["_gear"] = gear
        return self._show_wiki_item_payload(item)

    def _show_wiki_item_payload(self, item):
        server = self._server
        card = WikiItemCard(
            item, self, server=server, catalog=self._gear_model.items,
            price_lookup=self._auction_price)
        card.wiki_entity_requested.connect(self._show_wiki_entity)
        card.show()
        card.raise_()
        json_path, icon_path = _wiki_cache_paths(item.get("n"), server)
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
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
        reply = self._network.get(request)
        reply.finished.connect(
            lambda: self._wiki_item_finished(reply, card, json_path, icon_path))
        return card

    def _show_wiki_entity(self, target, label, kind):
        kind = str(kind or "").casefold()
        if kind not in {"npc", "zone", "effect"}:
            return None
        card = WikiEntityCard(label or target, kind, self)
        card.show()
        card.raise_()
        cache_path = _wiki_entity_cache_path(target, kind)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            card.set_entity_data(cached, cached=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(str(target).replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
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
            data["auction"] = parse_wiki_auction_html(
                rendered, card.server)
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
                    "Vantage/1.44.46")
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
        for column in range(6):
            self._toolbar_layout.setColumnStretch(column, 0)
            self._filters_layout.setColumnStretch(column, 0)
            self._footer_layout.setColumnStretch(column, 0)
        # The complete market surface is uniformly scaled by ParserWindow.
        # Responsive breakpoints here would mutate the logical layout during a
        # physical resize, which is exactly the reflow the compact panels must
        # avoid.
        width = self._design_size.width()

        if width >= 900:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 2)
            self._toolbar_layout.addWidget(self.server_selector, 0, 2)
            self._toolbar_layout.addWidget(self._refresh_button, 0, 3)
            self._toolbar_layout.addWidget(self._sources_button, 0, 4)
            self._toolbar_layout.addWidget(self._live_status_button, 0, 5)
        elif width >= 460:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 3)
            self._toolbar_layout.addWidget(self.server_selector, 1, 0)
            self._toolbar_layout.addWidget(self._refresh_button, 1, 1)
            self._toolbar_layout.addWidget(self._sources_button, 1, 2)
            self._toolbar_layout.addWidget(
                self._live_status_button, 2, 0, 1, 3)
        else:
            self._toolbar_layout.addWidget(self.search, 0, 0, 1, 2)
            self._toolbar_layout.addWidget(self.server_selector, 1, 0)
            self._toolbar_layout.addWidget(self._refresh_button, 1, 1)
            self._toolbar_layout.addWidget(self._sources_button, 2, 0, 1, 2)
            self._toolbar_layout.addWidget(
                self._live_status_button, 3, 0, 1, 2)
        self._toolbar_layout.setColumnStretch(0, 1)

        if width >= 820:
            self._filters_layout.addWidget(self.class_filter, 0, 0)
            self._filters_layout.addWidget(self.race_filter, 0, 1)
            self._filters_layout.addWidget(self.slot_filter, 0, 2)
            self._filters_layout.addWidget(self.clear_filters_button, 0, 3)
            self._filters_layout.addWidget(self.gear_status, 0, 4)
            self._filters_layout.setColumnStretch(4, 1)
        elif width >= 480:
            self._filters_layout.addWidget(self.class_filter, 0, 0)
            self._filters_layout.addWidget(self.race_filter, 0, 1)
            self._filters_layout.addWidget(self.slot_filter, 0, 2)
            self._filters_layout.addWidget(self.clear_filters_button, 1, 0)
            self._filters_layout.addWidget(self.gear_status, 1, 1, 1, 2)
        else:
            self._filters_layout.addWidget(self.class_filter, 0, 0, 1, 2)
            self._filters_layout.addWidget(self.race_filter, 1, 0)
            self._filters_layout.addWidget(self.slot_filter, 1, 1)
            self._filters_layout.addWidget(
                self.clear_filters_button, 2, 0, 1, 2)
            self._filters_layout.addWidget(self.gear_status, 3, 0, 1, 2)

        if width >= 900:
            self._footer_layout.addWidget(self.status, 0, 0)
            self._footer_layout.addWidget(self._watch_selected_button, 0, 1)
            self._footer_layout.addWidget(self._analyze_button, 0, 2)
            self._footer_layout.addWidget(self._detail_button, 0, 3)
            self._footer_layout.addWidget(self._wiki_button, 0, 4)
            self._footer_layout.setColumnStretch(0, 1)
        elif width >= 760:
            self._footer_layout.addWidget(self.status, 0, 0, 1, 4)
            self._footer_layout.addWidget(self._watch_selected_button, 1, 0)
            self._footer_layout.addWidget(self._analyze_button, 1, 1)
            self._footer_layout.addWidget(self._detail_button, 1, 2)
            self._footer_layout.addWidget(self._wiki_button, 1, 3)
        elif width >= 500:
            self._footer_layout.addWidget(self.status, 0, 0, 1, 3)
            self._footer_layout.addWidget(self._watch_selected_button, 1, 0)
            self._footer_layout.addWidget(self._analyze_button, 1, 1)
            self._footer_layout.addWidget(self._detail_button, 1, 2)
            self._footer_layout.addWidget(self._wiki_button, 2, 0, 1, 3)
        elif width >= 400:
            self._footer_layout.addWidget(self.status, 0, 0, 1, 2)
            self._footer_layout.addWidget(self._watch_selected_button, 1, 0)
            self._footer_layout.addWidget(self._analyze_button, 1, 1)
            self._footer_layout.addWidget(self._detail_button, 2, 0)
            self._footer_layout.addWidget(self._wiki_button, 2, 1)
        else:
            self._footer_layout.addWidget(self.status, 0, 0)
            self._footer_layout.addWidget(self._watch_selected_button, 1, 0)
            self._footer_layout.addWidget(self._analyze_button, 2, 0)
            self._footer_layout.addWidget(self._detail_button, 3, 0)
            self._footer_layout.addWidget(self._wiki_button, 4, 0)
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
            "server": self._server,
            "source": f"PigParse API · {self._server}",
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
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
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
                QNetworkRequest.KnownHeaders.UserAgentHeader,
                "Vantage/1.44.46")
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
            if (hasattr(self, "zone_selector") and
                    not self._zone_data.get("name")):
                self.zone_selector.setCurrentText(self._zone)
            in_ec = self._zone.casefold() in {
                "east commonlands", "east commonlands tunnel"}
            if in_ec:
                note = (
                    "EC TUNNEL READY · East Commonlands detected. Stay in the "
                    "tunnel with /log on; search and alerts update from every "
                    "/auction message this character receives during this session.")
            else:
                note = (
                    f"EC TUNNEL REQUIRED · Current zone: {self._zone}. Return to "
                    "East Commonlands Tunnel with /log on to receive the auction "
                    "messages used by search and sale alerts.")
            self._set_live_note(note, announce=True)
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
            f"Sale Alerts · {len(self._local_model.items)}")
        self._update_live_search_count()
        self._notify_live_watches(
            timestamp, match.group("seller"), match.group("message"))

    def _set_live_note(self, text, announce=False):
        self.live_note.setText(str(text))
        self.live_note.setAccessibleName(str(text))
        if announce:
            _announce_accessible(self, text)

    def _open_live_alerts(self):
        """Expose the sale watcher instead of hiding it behind tab four."""
        self.tabs.setCurrentIndex(self._live_tab_index)
        self.live_search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _set_live_query(self, query):
        self._local_proxy.set_query(query)
        self._update_live_search_count()

    def _update_live_search_count(self):
        visible = self._local_proxy.rowCount()
        total = len(self._local_model.items)
        if self.live_search.text().strip():
            text = f"Showing {visible} of {total} heard auctions"
        else:
            text = f"{total} heard auction{'s' if total != 1 else ''}"
        self.live_search_count.setText(text)
        self.live_search_count.setAccessibleName(text)

    def _update_live_alert_status(self):
        watches = list(config.data["market"].get("live_watch_items", []))
        enabled = bool(config.data["market"].get(
            "live_alerts_enabled", True))
        sound_enabled = bool(config.data["market"].get(
            "live_alert_sound_enabled", False))
        alert_state = "on" if enabled else "off"
        self._live_status_button.setText(
            f"Sale alerts {alert_state} · {len(watches)}")
        self._live_status_button.setProperty(
            "Active", bool(enabled and watches))
        self._live_status_button.setStyle(self._live_status_button.style())
        state = "on" if enabled else "off"
        self._live_status_button.setToolTip(
            f"Live sale alerts are {state} · {len(watches)} watched item"
            f"{'s' if len(watches) != 1 else ''} · click to manage")
        self._live_status_button.setAccessibleDescription(
            self._live_status_button.toolTip())
        self.live_alert_test.setEnabled(bool(watches))
        if self._last_live_alert:
            self._set_live_alert_status_text(
                self._last_live_alert, self._last_live_alert_state)
        elif watches and enabled:
            self._set_live_alert_status_text(
                f"Listening for {len(watches)} watched item"
                f"{'s' if len(watches) != 1 else ''} in this EQ log · "
                f"sound {'on' if sound_enabled else 'off'}", "listening")
        elif watches:
            self._set_live_alert_status_text(
                f"{len(watches)} watched item"
                f"{'s' if len(watches) != 1 else ''} · notifications are off",
                "off")
        else:
            self._set_live_alert_status_text(
                "No watched items · search above or select a market row, then "
                "choose Watch sale", "empty")

    def _set_live_alert_status_text(self, text, state="ready"):
        self.live_alert_status.setText(str(text))
        self.live_alert_status.setAccessibleName(str(text))
        state = str(state)
        if self.live_alert_status.property("State") != state:
            self.live_alert_status.setProperty("State", state)
            self.live_alert_status.style().unpolish(self.live_alert_status)
            self.live_alert_status.style().polish(self.live_alert_status)

    def _watch_selected_item(self):
        item = self._selected_item()
        if not item:
            self.status.setText(
                "Select a PigParse or Gear row, then choose Watch sale")
            return False
        return self._add_live_watch_name(str(item.get("n", "")))

    def _refresh_live_watch_items(self, selected=""):
        watches = list(config.data["market"].get("live_watch_items", []))
        current = self.live_watch_items.currentItem()
        selected = str(selected or (current.text() if current else ""))
        self.live_watch_items.blockSignals(True)
        self.live_watch_items.clear()
        if watches:
            self.live_watch_items.addItems(watches)
            matches = self.live_watch_items.findItems(
                selected, Qt.MatchFlag.MatchFixedString)
            self.live_watch_items.setCurrentItem(
                matches[0] if matches else self.live_watch_items.item(0))
            self.live_watch_items.setEnabled(True)
            self.live_watch_remove.setEnabled(True)
        else:
            self.live_watch_items.setEnabled(False)
            self.live_watch_remove.setEnabled(False)
        self.live_watch_items.blockSignals(False)
        self.live_watch_label.setText(f"Watching ({len(watches)})")
        self._update_live_alert_status()

    def _add_live_watch(self):
        watch = str(self.live_watch_input.text() or "").strip()[:96]
        if not watch:
            self.live_watch_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        return self._add_live_watch_name(watch)

    def _add_live_watch_name(self, watch):
        watch = str(watch or "").strip()[:96]
        if not watch:
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
        self.status.setText(
            f"Watching live EQ auction lines for {catalog_match}")
        _announce_accessible(
            self, f"Alert added for {catalog_match}; auction alerts are on")
        return True

    def _remove_live_watch(self):
        current = self.live_watch_items.currentItem()
        selected = str(current.text() if current else "")
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
        self._update_live_alert_status()
        _announce_accessible(
            self, "Live auction alerts on" if enabled else
            "Live auction alerts off")

    def _set_live_alert_sound_enabled(self, enabled):
        config.data["market"]["live_alert_sound_enabled"] = bool(enabled)
        if getattr(config, "_filename", ""):
            config.save()
        self._last_live_alert = ""
        self._last_live_alert_state = "ready"
        self._update_live_alert_status()
        _announce_accessible(
            self, "Sale alert sound on" if enabled else
            "Sale alert sound off")

    def _preview_live_alert(self):
        current = self.live_watch_items.currentItem()
        item = str(current.text() if current else "").strip()
        if not self.live_watch_items.isEnabled() or not item:
            self._set_live_alert_status_text(
                "Add or watch an item before testing a sale alert", "off")
            return False
        app = QApplication.instance()
        delivery, sound_state = deliver_market_alert(
            app, f"Test sale alert · {item}",
            f"{item} for sale · EC Tunnel Trader · WTS sample listing",
            self.live_alert_sound.isChecked())
        self._last_live_alert = (
            f"TEST · {item} · {delivery} · {sound_state}")
        self._last_live_alert_state = (
            "matched" if delivery != "inline only" else "off")
        self._update_live_alert_status()
        _announce_accessible(self, self._last_live_alert, assertive=True)
        return delivery != "inline only" or sound_state == "sound played"

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
            delivery, sound_state = deliver_market_alert(
                app, f"For sale · {item}",
                f"{item} for sale · {seller} · {message}",
                bool(settings.get("live_alert_sound_enabled", False)))
            self._live_match_count = int(getattr(
                self, "_live_match_count", 0)) + 1
            self._last_live_alert = (
                f"MATCH {self._live_match_count} · {item} · {seller}"
                f" · {delivery} · {sound_state}")
            self._last_live_alert_state = "matched"
            _announce_accessible(
                self, f"For sale: {item}, seller {seller}", assertive=True)
            notified.append(item)
        if notified and hasattr(self, "live_alert_status"):
            self._update_live_alert_status()
        return notified

    def _set_query(self, query):
        self._proxy.set_query(query)
        self._gear_proxy.set_query(query)
        self._update_gear_summary()

    def _set_server_labels(self):
        server = self._server
        self.setWindowTitle(f"{server} Market · PigParse")
        self._title.setText(f"Market · {server}")
        self.search.setAccessibleName(f"Search the {server} market")
        self.search.setAccessibleDescription(
            f"Filters PigParse {server} prices and the shared P99 item metadata "
            "while you type")
        self._refresh_button.setToolTip(
            f"Refresh prices from PigParse {server}")
        self._detail_button.setToolTip(
            f"Open the selected item's full PigParse {server} history")
        self._wiki_button.setToolTip(
            f"Show the item card and P99 Wiki {server} price inside Vantage")
        self.tabs.setTabToolTip(
            0, f"Search cached PigParse {server} listings and prices")

    def _server_changed(self, value):
        server = normalize_market_server(value)
        if server == self._server:
            return
        self._server = server
        config.data["market"]["server"] = server
        config.save()
        self._set_server_labels()
        if not self._load_cache(server):
            self._model.set_items([])
            self._gear_model.set_prices([])
            self.auction_composer.refresh_prices()
            self._rebuild_mobile_items()
            self.status.setText(
                f"PigParse {server} · no local cache · refreshing…")
        self.refresh()
        _announce_accessible(
            self, f"PigParse {server} selected; loading isolated prices")

    def _scheduled_refresh(self):
        if self.isVisible():
            self.refresh()

    def _market_config_updated(self):
        minutes = config.data["market"].get("refresh_minutes", 10)
        if minutes != self._refresh_minutes:
            self._refresh_minutes = minutes
            self._refresh_timer.setInterval(minutes * 60 * 1000)
        server = normalize_market_server(
            config.data["market"].get("server", self._server))
        if server != self._server:
            self.server_selector.setCurrentText(server)
        alerts_enabled = bool(config.data["market"].get(
            "live_alerts_enabled", True))
        sound_enabled = bool(config.data["market"].get(
            "live_alert_sound_enabled", False))
        for checkbox, checked in (
                (self.live_alerts_enabled, alerts_enabled),
                (self.live_alert_sound, sound_enabled)):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._update_live_alert_status()

    def refresh(self):
        server = self._server
        if server in self._requests_in_flight:
            return
        self._loaded_online = True
        self._requests_in_flight.add(server)
        self._refresh_button.setEnabled(False)
        self._refresh_button.setText("Refreshing…")
        self.status.setText(f"Refreshing PigParse {server}…")
        request = QNetworkRequest(QUrl(market_endpoint(server)))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
        reply = self._network.get(request)
        reply.setProperty("market_server", server)
        reply.finished.connect(lambda: self._finished(reply))

    def toggle(self):
        super().toggle()
        if self.isVisible() and not self._loaded_online:
            self.refresh()

    def _finished(self, reply):
        server = normalize_market_server(
            reply.property("market_server") or self._server)
        self._requests_in_flight.discard(server)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                if server == self._server:
                    self.status.setText(
                        f"PigParse {server} offline · using its cache · "
                        f"{reply.errorString()}")
                return
            items = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(items, list):
                raise ValueError("The response does not contain a list")
            references = market_price_references(items)
            payload = {
                "updated_at": datetime.datetime.now().astimezone().isoformat(),
                "source": market_endpoint(server),
                "server": server,
                "items": items,
            }
            _cache_file(server).write_text(
                json.dumps(payload), encoding="utf-8")
            # A reply for a server the user already left may warm that
            # server's cache, but it must never replace the visible model.
            if server != self._server:
                return
            self._model.set_items(references)
            self._gear_model.set_prices(references)
            self.auction_composer.refresh_prices()
            self._rebuild_mobile_items()
            self.status.setText(
                f"PigParse API · {server} · {len(references):,} price references · updated now · "
                "10 min cycle")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            if server == self._server:
                self.status.setText(
                    f"PigParse {server} refresh failed · using its cache · {error}")
        finally:
            if server == self._server:
                self._refresh_button.setEnabled(
                    server not in self._requests_in_flight)
                self._refresh_button.setText(
                    "Refreshing…" if server in self._requests_in_flight else
                    "Refresh")
            reply.deleteLater()

    def _load_cache(self, server=None):
        server = normalize_market_server(server or self._server)
        # Cache loads are allowed to affect only the server currently shown.
        # This keeps future background/preload callers from accidentally
        # mixing one server's observations into the other server's model.
        if server != self._server:
            return False
        try:
            payload = json.loads(
                _cache_file(server).read_text(encoding="utf-8"))
            cached_server = payload.get("server")
            if (cached_server is not None
                    and normalize_market_server(cached_server) != server):
                raise ValueError("Cache belongs to another PigParse server")
            self._model.set_items(market_price_references(
                payload.get("items", [])))
            self._gear_model.set_prices(self._model.items)
            self.auction_composer.refresh_prices()
            self._rebuild_mobile_items()
            stamp = datetime.datetime.fromisoformat(payload.get("updated_at", ""))
            self.status.setText(
                f"PigParse API · {server} · {len(self._model.items):,} cached price references · "
                f"{stamp.astimezone():%Y-%m-%d %H:%M}")
            return True
        except (OSError, ValueError, json.JSONDecodeError):
            return False

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
        server = self._server
        self.status.setText(
            f"Evaluating PigParse {server} history · {name}…")
        request = QNetworkRequest(QUrl(market_detail_api(server).format(
            item_name=quote(name, safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.46")
        reply = self._network.get(request)
        reply.setProperty("market_item_name", name)
        reply.setProperty("market_server", server)
        reply.finished.connect(lambda: self._analysis_finished(reply))

    def _analysis_finished(self, reply):
        name = reply.property("market_item_name")
        server = normalize_market_server(reply.property("market_server"))
        try:
            # A late detail response belongs to the market it was requested
            # from; do not display it over a newly selected server.
            if server != self._server:
                return
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
                f"Primary source: PigParse API · {server}\n"
                "Secondary reference available: Project 1999 Wiki.")
            if server == self._server:
                self.status.setText(
                    f"Evaluated · {server} · {name} · estimate {robust:,.0f} pp")
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            if server == self._server:
                self.status.setText(
                    f"Could not evaluate {server} · {name} · {error}")
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
        server = self._server
        box = QMessageBox(self)
        box.setWindowTitle("Market Sources")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "<b>Primary source and source of truth:</b><br>"
            f"<a href='{pigparse_server_url(server)}'>PigParse · {server}</a> — catalog, averages, and history. "
            "The API reports a 10-minute rebuild cycle.<br><br>"
            "<b>Secondary reference:</b><br>"
            "<a href='https://wiki.project1999.com/Special:AuctionTracker'>"
            f"Project 1999 Wiki Auction Tracker</a> — secondary {server} price. "
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
            "alerts for watched items. This local history is independent of "
            "the selected PigParse server and is not a permanent global feed.")
        box.exec()
