"""Lazy native spell catalog backed by bundled P99 data and the P99 Wiki."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
import hashlib
import html
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel,
    Qt, QTimer, QUrl)
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSplitter, QTableView, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget)

from vantage.helpers import resource_path
from vantage.helpers.icons import game_icon
from vantage.helpers.spell_icons import spell_icon_pixmap
from vantage.helpers.portable import data_dir
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spell_catalog import P99_SPELL_CLASSES, p99_spell_entries
from vantage.helpers.responsive import (
    ensure_tab_tooltips, ensure_table_header_tooltips)
from vantage.parsers.market import (
    combined_market_price, normalize_market_server,
    parse_wiki_auction_html)


P99_WIKI_API = (
    "https://wiki.project1999.com/api.php?action=parse&page={slug}"
    "&prop=text%7Cwikitext&format=json")
P99_WIKI_URL = "https://wiki.project1999.com/{slug}"
USER_AGENT = "Vantage/1.44.46"
ACQUISITION_WORDS = (
    "merchant", "sold by", "where to obtain", "where to find", "drop",
    "research", "recipe", "created by", "quest", "reward", "turn in",
)
P99_SKILL_CLASSES = (
    "Bard", "Cleric", "Druid", "Enchanter", "Magician", "Monk",
    "Necromancer", "Paladin", "Ranger", "Rogue", "Shadow Knight",
    "Shaman", "Warrior", "Wizard",
)


def _cache_path(name, server="Green"):
    server = normalize_market_server(server).casefold()
    digest = hashlib.sha256(
        str(name).strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-spells") / f"{server}-{digest}.json"


def _skills_cache_path(class_name):
    digest = hashlib.sha256(
        str(class_name).strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-skills") / f"class-{digest}.json"


def _skill_detail_cache_path(target):
    digest = hashlib.sha256(
        str(target).strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-skills") / f"skill-{digest}.json"


def _wiki_url(name):
    return P99_WIKI_URL.format(
        slug=quote(str(name).strip().replace(" ", "_"), safe=""))


def _wiki_title_from_url(url):
    parsed = urlparse(str(url or ""))
    if parsed.hostname and parsed.hostname.casefold() != "wiki.project1999.com":
        return ""
    if parsed.path.casefold().endswith("/index.php"):
        title = (parse_qs(parsed.query).get("title") or [""])[0]
    else:
        title = unquote(parsed.path.strip("/"))
    title = title.replace("_", " ")
    return " ".join(title.split())


def _plain_wiki_text(value):
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(
        r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda match: match.group(2), text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda match: match.group(1), text)
    text = re.sub(r"\[(?:https?://\S+)\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    clean = []
    for raw_line in html.unescape(text).splitlines():
        line = raw_line.strip()
        if not line or line in {"{|", "|}", "|-"}:
            continue
        line = re.sub(r"^[|!*#:;]+\s*", "", line)
        line = re.sub(r"\s*[|!]\s*", " · ", line)
        line = " ".join(line.split())
        if line:
            clean.append(line)
    return "\n".join(clean)


def extract_acquisition_text(wikitext):
    """Extract purchase, drop, quest, and research sections from Wiki markup."""
    source = str(wikitext or "")
    field_matches = list(re.finditer(
        r"(?m)^\|\s*(?P<field>[A-Za-z_][\w ]*)\s*=\s*", source))
    template_sections = []
    for index, match in enumerate(field_matches):
        field_name = match.group("field").strip().replace("_", " ")
        if not any(word in field_name.casefold() for word in ACQUISITION_WORDS):
            continue
        end = (
            field_matches[index + 1].start()
            if index + 1 < len(field_matches) else len(source))
        body = _plain_wiki_text(source[match.end():end].rsplit("}}", 1)[0])
        if body:
            template_sections.append(
                f"{field_name.upper()}\n{body}")

    headings = list(re.finditer(
        r"(?m)^(?P<marks>={2,5})\s*(?P<title>.*?)\s*(?P=marks)\s*$",
        source))
    sections = []
    for index, match in enumerate(headings):
        title = _plain_wiki_text(match.group("title"))
        if not any(word in title.casefold() for word in ACQUISITION_WORDS):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        body = _plain_wiki_text(source[match.end():end])
        if body:
            sections.append(f"{title.upper()}\n{body}")
    sections = template_sections + sections
    if sections:
        return "\n\n".join(sections)[:16000]

    # A few older spell pages keep vendor/research notes in their lead rather
    # than under a dedicated heading. Preserve those useful lines as fallback.
    lines = []
    for raw_line in source.splitlines():
        plain = _plain_wiki_text(raw_line)
        if plain and any(word in plain.casefold() for word in ACQUISITION_WORDS):
            lines.append(plain)
    return "\n".join(dict.fromkeys(lines))[:8000]


def sanitize_wiki_html(rendered_html):
    """Keep readable Wiki content while preventing active or remote embeds."""
    source = str(rendered_html or "")[:1_200_000]
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    source = re.sub(
        r"<(script|style|iframe|object|embed|form)\b.*?</\1\s*>",
        "", source, flags=re.IGNORECASE | re.DOTALL)
    source = re.sub(r"<img\b[^>]*>", "", source, flags=re.IGNORECASE)
    source = re.sub(
        r"\s(?:style|class|id|srcset|src|bgcolor|background|color|border|"
        r"cellpadding|cellspacing|on\w+)\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
        "", source, flags=re.IGNORECASE)
    source = re.sub(
        r'href=["\'](?:javascript|data):[^"\']*["\']',
        'href="#"', source, flags=re.IGNORECASE)
    source = re.sub(
        r'href=(["\'])/(?!/)(.*?)\1',
        r'href=\1https://wiki.project1999.com/\2\1', source,
        flags=re.IGNORECASE)
    source = re.sub(
        r'href=(["\'])\./(.*?)\1',
        r'href=\1https://wiki.project1999.com/\2\1', source,
        flags=re.IGNORECASE)
    return source


def _rendered_text(value):
    source = re.sub(
        r"<span\b[^>]*class=[\"'][^\"']*\beditsection\b[^\"']*"
        r"[\"'][^>]*>.*?</span>", "", str(value or ""),
        flags=re.IGNORECASE | re.DOTALL)
    source = re.sub(r"<br\s*/?>", "\n", source, flags=re.IGNORECASE)
    source = re.sub(r"<[^>]+>", " ", source)
    return " ".join(html.unescape(source).split())


def parse_class_skills_html(rendered_html, class_name=""):
    """Extract the P99 class skill tables and specialization guidance."""
    source = str(rendered_html or "")
    skills_marker = re.search(
        r'<span\b[^>]*id=["\']Skills["\'][^>]*>', source,
        re.IGNORECASE)
    if not skills_marker:
        return {"class": str(class_name), "specialization": "", "skills": []}
    section_start = skills_marker.start()
    next_h1 = re.search(r"<h1\b", source[skills_marker.end():], re.IGNORECASE)
    section_end = (
        skills_marker.end() + next_h1.start() if next_h1 else len(source))
    section = source[section_start:section_end]

    headings = list(re.finditer(
        r'<h2\b[^>]*>.*?<span\b[^>]*id=["\'](?P<id>[^"\']+)'
        r'["\'][^>]*>.*?</h2>', section,
        re.IGNORECASE | re.DOTALL))
    specialization = ""
    skills = []
    for index, heading in enumerate(headings):
        heading_id = heading.group("id")
        block_end = (
            headings[index + 1].start()
            if index + 1 < len(headings) else len(section))
        block = section[heading.end():block_end]
        if heading_id.casefold() == "specialization":
            specialization = _rendered_text(block)[:3000]
            continue
        if not heading_id.casefold().endswith("_skills"):
            continue
        category = heading_id.replace("_", " ").title().removesuffix(" Skills")
        table = re.search(
            r"<table\b[^>]*>(?P<body>.*?)</table>", block,
            re.IGNORECASE | re.DOTALL)
        if not table:
            continue
        raw_rows = re.findall(
                r"<tr\b[^>]*>(.*?)</tr>", table.group("body"),
                re.IGNORECASE | re.DOTALL)
        if not raw_rows:
            continue
        header_cells = re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw_rows[0],
            re.IGNORECASE | re.DOTALL)
        headers = [_rendered_text(cell).casefold() for cell in header_cells]

        def column_index(*needles):
            return next((index for index, label in enumerate(headers)
                         if any(needle in label for needle in needles)), -1)

        level_index = column_index("level")
        skill_index = column_index("skill")
        trained_index = column_index("trained", "train")
        cap_50_index = column_index("until 50", "through 50", "cap at 50")
        cap_60_index = column_index("above 50", "after 50", "cap at 60")
        max_index = column_index("max", "cap")
        if cap_50_index < 0:
            cap_50_index = max_index
        if cap_60_index < 0:
            cap_60_index = max_index
        required = (level_index, skill_index, trained_index, cap_50_index)
        if any(index < 0 for index in required):
            continue
        for raw_row in raw_rows[1:]:
            cells = re.findall(
                r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw_row,
                re.IGNORECASE | re.DOTALL)
            maximum_index = max(
                level_index, skill_index, trained_index,
                cap_50_index, cap_60_index)
            if len(cells) <= maximum_index:
                continue
            level_text = _rendered_text(cells[level_index])
            level_match = re.search(r"\d+", level_text)
            if not level_match:
                continue
            link = re.search(
                r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\']',
                cells[skill_index], re.IGNORECASE)
            skill_name = _rendered_text(cells[skill_index])
            if link:
                target = _wiki_title_from_url(link.group("href"))
            else:
                aliases = {
                    "1-hand blunt": "Skill 1H Blunt",
                    "2-hand blunt": "Skill 2H Blunt",
                    "1-hand slashing": "Skill 1H Slashing",
                    "2-hand slashing": "Skill 2H Slashing",
                    "hand to hand": "Skill Hand to Hand",
                }
                target = aliases.get(skill_name.casefold(), f"Skill {skill_name}")
            trained = _rendered_text(cells[trained_index])
            if trained.casefold() in {"y", "yes"}:
                trained = "Yes"
            elif trained.casefold() in {"n", "no"}:
                trained = "No"
            skills.append({
                "level": int(level_match.group()),
                "trained": trained,
                "name": skill_name,
                "cap_50": _rendered_text(cells[cap_50_index]),
                "cap_60": _rendered_text(cells[cap_60_index]),
                "category": category,
                "target": target,
            })
    return {
        "class": str(class_name),
        "specialization": specialization,
        "skills": skills,
    }


@dataclass(frozen=True)
class SpellListing:
    entry: object
    class_name: str
    level: int


class SpellLibraryModel(QAbstractTableModel):
    COLUMNS = ("Level", "Spell", "Class")

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = tuple(entries)
        self.listings = tuple(sorted((
            SpellListing(entry, class_name, level)
            for entry in self.entries
            for class_name, level in entry.class_levels
        ), key=lambda row: (
            row.level, row.entry.name.casefold(), row.class_name.casefold())))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.listings)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                "Required spell level, ordered from 1 through 60",
                "Click a spell to open its complete in-app Wiki card",
                "P99 class that learns the spell at this level",
            )[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        listing = self.listings[index.row()]
        values = (listing.level, listing.entry.name, listing.class_name)
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            value = values[index.column()]
            return value if isinstance(value, int) else value.casefold()
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QColor("#D7BD7B")
        if role == Qt.ItemDataRole.FontRole and index.column() == 1:
            font = QFont()
            font.setUnderline(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"Level {listing.level} {listing.class_name} · "
                f"click to open {listing.entry.name}")
        return None


class SpellLibraryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.class_name = ""
        self.level = 0
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_filters(self, query, class_name, level):
        self.beginFilterChange()
        self.query = str(query or "").strip().casefold()
        self.class_name = str(class_name or "")
        self.level = max(0, int(level or 0))
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row, _parent):
        listing = self.sourceModel().listings[source_row]
        if self.query and self.query not in listing.entry.name.casefold():
            return False
        if self.class_name and listing.class_name != self.class_name:
            return False
        return not self.level or listing.level == self.level


class SpellLibraryDialog(UniformScaleDialog):
    """Search class/level data locally and load Wiki detail only on demand."""

    def __init__(self, market=None, spells_panel=None, parent=None):
        super().__init__(
            QSize(1040, 650), parent, minimum_size=QSize(312, 195),
            initial_size=QSize(884, 552))
        self.market = market
        self.spells_panel = spells_panel
        self._entries = p99_spell_entries()
        self._entries_by_name = {
            entry.name.casefold(): entry for entry in self._entries}
        self._current = None
        self._pending = None
        self._reply = None
        self._skills_reply = None
        self._skill_detail_reply = None
        self._skills_generation = 0
        self._skill_detail_generation = 0
        self._skills_data = {}
        self._visible_skills = []
        self._current_skill = None
        self._linked_title = ""
        self._linked_url = QUrl()
        self._request_generation = 0
        self._network = QNetworkAccessManager(self)
        self.setObjectName("SpellLibraryDialog")
        self.setWindowTitle("Vantage · P99 Spells & Skills")

        root = QVBoxLayout(self.scaled_surface)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self.catalog_tabs = QTabWidget()
        self.catalog_tabs.setObjectName("SpellSkillTabs")
        root.addWidget(self.catalog_tabs, 1)

        spell_page = QWidget()
        spell_root = QVBoxLayout(spell_page)
        spell_root.setContentsMargins(0, 4, 0, 0)
        spell_root.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search spells…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search P99 spells")
        self.search.setToolTip("Filter spell names while you type")
        controls.addWidget(self.search, 1)

        self.class_filter = QComboBox()
        self.class_filter.addItem("Any class", "")
        for class_name in P99_SPELL_CLASSES:
            self.class_filter.addItem(class_name, class_name)
        self.class_filter.setAccessibleName("Filter spells by class")
        self.class_filter.setToolTip("Show only spells learnable by this class")
        controls.addWidget(self.class_filter)

        self.level_filter = QComboBox()
        self.level_filter.addItem("Any available level", 0)
        for level in sorted({
                level for entry in self._entries
                for _class_name, level in entry.class_levels}):
            self.level_filter.addItem(f"Level {level}", level)
        self.level_filter.setAccessibleName("Filter spells by required level")
        self.level_filter.setToolTip(
            "Shows only levels that contain spells for the selected class")
        controls.addWidget(self.level_filter)
        spell_root.addLayout(controls)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        spell_root.addWidget(splitter, 1)

        self.model = SpellLibraryModel(self._entries, self)
        self.proxy = SpellLibraryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setObjectName("SpellLibraryTable")
        self.table.setAccessibleName("P99 spell results")
        self.table.setToolTip(
            "Click any level 1–60 spell row to open its in-app Wiki details")
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(5)
        headline = QHBoxLayout()
        self.icon = QLabel("?")
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setAccessibleName("Selected spell icon")
        self.icon.setToolTip("Classic spell icon from the bundled client data")
        headline.addWidget(self.icon)
        identity = QVBoxLayout()
        self.name_label = QLabel("Choose a spell")
        self.name_label.setObjectName("SpellLibraryTitle")
        self.class_label = QLabel(
            "Filter by class and exact spell level, or search by name.")
        self.class_label.setWordWrap(True)
        self.class_label.setObjectName("SpellLibraryClasses")
        identity.addWidget(self.name_label)
        identity.addWidget(self.class_label)
        headline.addLayout(identity, 1)
        self.back_button = QPushButton("Back to spell")
        self.back_button.setAccessibleName("Return to selected spell")
        self.back_button.setToolTip(
            "Return from a linked mob, zone, item, or quest to the selected spell")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self._return_to_spell)
        headline.addWidget(self.back_button)
        self.refresh_button = QPushButton("Refresh Wiki")
        self.refresh_button.setIcon(game_icon("refresh"))
        self.refresh_button.setToolTip(
            "Reload the selected spell directly from Project 1999 Wiki")
        self.refresh_button.clicked.connect(self._refresh_current)
        headline.addWidget(self.refresh_button)
        self.open_button = QPushButton("Open source")
        self.open_button.setIcon(game_icon("map"))
        self.open_button.setToolTip(
            "Open the selected spell's Project 1999 Wiki source page")
        self.open_button.clicked.connect(self._open_current)
        headline.addWidget(self.open_button)
        detail_layout.addLayout(headline)

        self.price_label = QLabel("Prices appear after a spell is selected.")
        self.price_label.setObjectName("SpellLibraryPrice")
        self.price_label.setWordWrap(True)
        self.price_label.setToolTip(
            "PigParse and Wiki prices remain separate unless their recent values agree")
        detail_layout.addWidget(self.price_label)

        self.body = QTextBrowser()
        self.body.setObjectName("SpellLibraryDetail")
        self.body.setAccessibleName("Project 1999 Wiki spell information")
        self.body.setToolTip(
            "Click linked spells, mobs, zones, items, merchants, and quests to browse inside Vantage")
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self._open_detail_link)
        self.body.document().setDefaultStyleSheet(
            "body { color: #D9D2C3; background: #101419; }"
            "h1, h2, h3, h4 { color: #D7BD7B; }"
            "a { color: #D7BD7B; }"
            "table { color: #E6E2D9; background: #10161B; "
            "border-collapse: collapse; }"
            "th { color: #E8D59D; background: #1B2026; }"
            "td { color: #E6E2D9; background: #10161B; }"
            "td, th { border: 1px solid #3A4650; padding: 3px; }"
            ".source { color: #948D7E; }"
            ".acquisition { background: #171B20; border: 1px solid #4A4232; }"
        )
        self.body.setHtml(
            "<h2>P99 Spell Library</h2>"
            "<p>Choose a spell to load its complete Wiki page inside Vantage. "
            "The local class and level index works offline.</p>")
        detail_layout.addWidget(self.body, 1)

        self.source = QLabel(
            f"LOCAL CLASS INDEX · {len(self._entries):,} SPELLS · "
            "WIKI DETAILS LOAD ON SELECTION")
        self.source.setObjectName("SpellLibrarySource")
        self.source.setWordWrap(True)
        self.source.setToolTip(
            "Class and level come from bundled spells_us.txt; details and prices name their source")
        detail_layout.addWidget(self.source)
        splitter.addWidget(detail)
        splitter.setSizes((410, 630))
        self.catalog_tabs.addTab(spell_page, "Spells")
        self.skills_page = self._build_skills_page()
        self.catalog_tabs.addTab(self.skills_page, "Skills")
        ensure_tab_tooltips(self.catalog_tabs, {
            "Spells": (
                "Search P99 spells by class and level, then read their Wiki details"),
            "Skills": (
                "Choose a P99 class and search when each skill unlocks and its caps"),
        })

        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(180)
        self._selection_timer.timeout.connect(self._load_pending)
        self.search.textChanged.connect(self._filters_changed)
        self.class_filter.currentIndexChanged.connect(self._filters_changed)
        self.level_filter.currentIndexChanged.connect(self._filters_changed)
        self.table.selectionModel().currentRowChanged.connect(
            self._selection_changed)
        self.table.clicked.connect(self._activate_index)
        self.table.activated.connect(self._activate_index)
        self.catalog_tabs.currentChanged.connect(self._catalog_tab_changed)
        QTimer.singleShot(0, self._select_first)

    def _catalog_tab_changed(self, _index):
        if (self.catalog_tabs.currentWidget() is self.skills_page and
                not self._skills_data.get("skills") and
                self._skills_reply is None):
            self._load_selected_class_skills()

    def _build_skills_page(self):
        page = QWidget()
        page.setObjectName("SkillLibraryPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.skill_class_filter = QComboBox()
        for class_name in P99_SKILL_CLASSES:
            self.skill_class_filter.addItem(class_name, class_name)
        preferred = str(getattr(
            getattr(self.spells_panel, "_character_context", None),
            "player_class", "") or "")
        preferred_index = self.skill_class_filter.findData(preferred)
        self.skill_class_filter.setCurrentIndex(max(0, preferred_index))
        self.skill_class_filter.setAccessibleName("P99 class for skill lookup")
        self.skill_class_filter.setToolTip(
            "Choose a class to load its P99 skill unlock levels and caps")
        controls.addWidget(self.skill_class_filter)

        self.skill_search = QLineEdit()
        self.skill_search.setPlaceholderText("Search this class's skills…")
        self.skill_search.setClearButtonEnabled(True)
        self.skill_search.setAccessibleName("Search skills for selected class")
        self.skill_search.setToolTip(
            "Filter by skill name, category, level, training, or cap")
        clear_skill_search = self.skill_search.findChild(QToolButton)
        if clear_skill_search:
            clear_skill_search.setAccessibleName("Clear skill search")
            clear_skill_search.setToolTip("Show every skill for this class")
        controls.addWidget(self.skill_search, 1)

        self.skill_refresh_button = QPushButton("Refresh class")
        self.skill_refresh_button.setIcon(game_icon("refresh"))
        self.skill_refresh_button.setAccessibleName(
            "Refresh selected class skills from Project 1999 Wiki")
        self.skill_refresh_button.setToolTip(
            "Download the selected class's current P99 skill tables again")
        controls.addWidget(self.skill_refresh_button)
        layout.addLayout(controls)

        self.skill_summary = QLabel(
            "Choose a class to see its casting, combat, and miscellaneous skills.")
        self.skill_summary.setObjectName("SpellLibraryPrice")
        self.skill_summary.setWordWrap(True)
        self.skill_summary.setAccessibleName(self.skill_summary.text())
        layout.addWidget(self.skill_summary)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        self.skill_table = QTableWidget(0, 6)
        self.skill_table.setObjectName("SkillLibraryTable")
        self.skill_table.setHorizontalHeaderLabels((
            "Level", "Skill", "Category", "Trained", "Cap ≤50", "Cap >50"))
        self.skill_table.setAccessibleName("Skills for selected P99 class")
        self.skill_table.setAccessibleDescription(
            "Sortable class skills showing unlock level, trainer requirement, and caps")
        self.skill_table.setToolTip(
            "Select a skill for its class facts and Project 1999 Wiki guide")
        self.skill_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.skill_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.skill_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.skill_table.setAlternatingRowColors(True)
        self.skill_table.setSortingEnabled(True)
        self.skill_table.verticalHeader().setVisible(False)
        skill_header = self.skill_table.horizontalHeader()
        skill_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        skill_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        skill_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(3, 6):
            skill_header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        ensure_table_header_tooltips(
            self.skill_table, "the selected Project 1999 class")
        splitter.addWidget(self.skill_table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(5)
        headline = QHBoxLayout()
        skill_identity = QVBoxLayout()
        self.skill_name_label = QLabel("Choose a skill")
        self.skill_name_label.setObjectName("SpellLibraryTitle")
        self.skill_fact_label = QLabel(
            "Select a row to see when the skill unlocks and its cap.")
        self.skill_fact_label.setObjectName("SpellLibraryClasses")
        self.skill_fact_label.setWordWrap(True)
        skill_identity.addWidget(self.skill_name_label)
        skill_identity.addWidget(self.skill_fact_label)
        headline.addLayout(skill_identity, 1)
        self.skill_open_button = QPushButton("Open source")
        self.skill_open_button.setIcon(game_icon("map"))
        self.skill_open_button.setEnabled(False)
        self.skill_open_button.setAccessibleName(
            "Open selected skill on Project 1999 Wiki")
        self.skill_open_button.setToolTip(
            "Open the selected skill's source page in your browser")
        self.skill_open_button.clicked.connect(self._open_selected_skill)
        headline.addWidget(self.skill_open_button)
        detail_layout.addLayout(headline)

        self.skill_body = QTextBrowser()
        self.skill_body.setObjectName("SpellLibraryDetail")
        self.skill_body.setAccessibleName("Selected P99 skill information")
        self.skill_body.setOpenExternalLinks(True)
        self.skill_body.setToolTip(
            "Class guidance and Wiki information for the selected skill")
        self.skill_body.document().setDefaultStyleSheet(
            "body { color: #D9D2C3; background: #101419; }"
            "h1, h2, h3, h4 { color: #D7BD7B; }"
            "a { color: #D7BD7B; }"
            "table { color: #E6E2D9; background: #10161B; "
            "border-collapse: collapse; }"
            "th { color: #E8D59D; background: #1B2026; }"
            "td { color: #E6E2D9; background: #10161B; }"
            "td, th { border: 1px solid #3A4650; padding: 3px; }")
        self.skill_body.setHtml(
            "<h2>P99 Class Skills</h2><p>Loading the selected class…</p>")
        detail_layout.addWidget(self.skill_body, 1)
        self.skill_source = QLabel("PROJECT 1999 WIKI · CLASS SKILLS")
        self.skill_source.setObjectName("SpellLibrarySource")
        self.skill_source.setWordWrap(True)
        self.skill_source.setToolTip(
            "Unlock levels, training, caps, and guides come from Project 1999 Wiki")
        detail_layout.addWidget(self.skill_source)
        splitter.addWidget(detail)
        splitter.setSizes((590, 450))
        layout.addWidget(splitter, 1)

        self._skill_selection_timer = QTimer(self)
        self._skill_selection_timer.setSingleShot(True)
        self._skill_selection_timer.setInterval(180)
        self._skill_selection_timer.timeout.connect(self._load_skill_detail)
        self.skill_class_filter.currentIndexChanged.connect(
            self._load_selected_class_skills)
        self.skill_search.textChanged.connect(self._refresh_skill_rows)
        self.skill_refresh_button.clicked.connect(
            lambda: self._load_selected_class_skills(force=True))
        self.skill_table.itemSelectionChanged.connect(
            self._skill_selection_changed)
        self.skill_table.cellDoubleClicked.connect(
            lambda *_: self._open_selected_skill())
        return page

    def _load_selected_class_skills(self, *_args, force=False):
        class_name = str(self.skill_class_filter.currentData() or "").strip()
        if not class_name:
            return False
        self._skills_generation += 1
        generation = self._skills_generation
        if self._skills_reply is not None and self._skills_reply.isRunning():
            self._skills_reply.abort()
        cache_path = _skills_cache_path(class_name)
        cached = None
        if not force:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("skills"):
                    self._set_skills_data(cached, cached=True)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                cached = None
        self.skill_refresh_button.setEnabled(False)
        if not cached:
            self._skills_data = {}
            self._visible_skills = []
            self.skill_table.setRowCount(0)
            self.skill_summary.setText(
                f"Loading {class_name} skills from Project 1999 Wiki…")
            self.skill_summary.setAccessibleName(self.skill_summary.text())
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(class_name.replace(" ", "_"), safe=""))))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setTransferTimeout(12000)
        reply = self._network.get(request)
        self._skills_reply = reply
        reply.finished.connect(lambda: self._class_skills_finished(
            reply, class_name, generation, cache_path))
        return True

    def _class_skills_finished(self, reply, class_name, generation, cache_path):
        try:
            if generation != self._skills_generation:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload_bytes = bytes(reply.readAll())
            if len(payload_bytes) > 2_000_000:
                raise ValueError("Wiki response is larger than the safe limit")
            payload = json.loads(payload_bytes.decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("class page not found on P99 Wiki")
            rendered = parsed.get("text", {})
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            data = parse_class_skills_html(rendered, class_name)
            if not data.get("skills"):
                raise ValueError("no recognized skill tables on this class page")
            data["fetched_at"] = datetime.datetime.now(
                datetime.timezone.utc).isoformat()
            cache_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._set_skills_data(data)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            if not self._skills_data.get("skills"):
                self.skill_summary.setText(
                    f"Could not load {class_name} skills · {error}")
                self.skill_summary.setAccessibleName(self.skill_summary.text())
        finally:
            if self._skills_reply is reply:
                self._skills_reply = None
            self.skill_refresh_button.setEnabled(True)
            reply.deleteLater()

    def _set_skills_data(self, data, cached=False):
        self._skills_data = dict(data or {})
        skills = list(self._skills_data.get("skills") or [])
        class_name = str(self._skills_data.get("class") or
                         self.skill_class_filter.currentText())
        categories = len({row.get("category") for row in skills})
        suffix = "cached" if cached else "updated now"
        self.skill_summary.setText(
            f"{class_name} · {len(skills)} skills · {categories} categories · {suffix}")
        self.skill_summary.setAccessibleName(self.skill_summary.text())
        self._refresh_skill_rows()
        specialization = str(self._skills_data.get("specialization") or "")
        if specialization:
            self.skill_body.setHtml(
                f"<h2>{html.escape(class_name)} skills</h2>"
                "<h3>Specialization guidance</h3>"
                f"<p>{html.escape(specialization)}</p>"
                "<p>Select any skill for its unlock level, caps, and Wiki guide.</p>")
        else:
            self.skill_body.setHtml(
                f"<h2>{html.escape(class_name)} skills</h2>"
                "<p>Select any skill for its unlock level, caps, and Wiki guide.</p>")
        self.skill_source.setText(
            f"PROJECT 1999 WIKI · {class_name.upper()} CLASS TABLE · {suffix.upper()}")

    def _refresh_skill_rows(self, *_args):
        query = self.skill_search.text().strip().casefold()
        skills = list(self._skills_data.get("skills") or [])
        self._visible_skills = [row for row in skills if not query or query in
                                " ".join(str(value or "") for value in row.values()).casefold()]
        self.skill_table.setSortingEnabled(False)
        self.skill_table.setRowCount(len(self._visible_skills))
        for row_index, skill in enumerate(self._visible_skills):
            values = (
                skill.get("level"), skill.get("name"), skill.get("category"),
                skill.get("trained"), skill.get("cap_50"), skill.get("cap_60"))
            for column, value in enumerate(values):
                item = QTableWidgetItem()
                if column == 0:
                    item.setData(Qt.ItemDataRole.DisplayRole, int(value or 0))
                    item.setData(Qt.ItemDataRole.UserRole, skill)
                else:
                    item.setText(str(value or ""))
                item.setToolTip(str(value or ""))
                self.skill_table.setItem(row_index, column, item)
        self.skill_table.setSortingEnabled(True)
        self.skill_table.sortItems(0, Qt.SortOrder.AscendingOrder)
        if self.skill_table.rowCount():
            self.skill_table.selectRow(0)
        else:
            self._current_skill = None
            self.skill_name_label.setText("No matching skills")
            self.skill_fact_label.setText("Clear or change the search text.")

    def _selected_skill(self):
        row = self.skill_table.currentRow()
        item = self.skill_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return value if isinstance(value, dict) else None

    def _skill_selection_changed(self):
        self._current_skill = self._selected_skill()
        self.skill_open_button.setEnabled(bool(self._current_skill))
        if self._current_skill:
            self._skill_selection_timer.start()

    def _load_skill_detail(self):
        skill = self._current_skill
        if not skill:
            return False
        class_name = str(self._skills_data.get("class") or "Class")
        name = str(skill.get("name") or "Skill")
        self.skill_name_label.setText(name)
        self.skill_fact_label.setText(
            f"{class_name} · {skill.get('category')} · level {skill.get('level')} · "
            f"trained {skill.get('trained')} · caps {skill.get('cap_50')} / "
            f"{skill.get('cap_60')}")
        self.skill_body.setHtml(
            f"<h2>{html.escape(name)}</h2>"
            f"<p><b>{html.escape(class_name)}</b> gains this at level "
            f"<b>{skill.get('level')}</b>.</p>"
            f"<p>Category: {html.escape(str(skill.get('category') or ''))}<br>"
            f"Trainer: {html.escape(str(skill.get('trained') or ''))}<br>"
            f"Cap through 50: {html.escape(str(skill.get('cap_50') or ''))}<br>"
            f"Cap above 50: {html.escape(str(skill.get('cap_60') or ''))}</p>"
            "<p>Loading the detailed P99 Wiki guide…</p>")
        target = str(skill.get("target") or f"Skill {name}")
        cache_path = _skill_detail_cache_path(target)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("wiki_html"):
                self._render_skill_detail(skill, cached, cached=True)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        # Selection timers can still be queued while a reusable dialog is
        # closing. Cached/local facts are safe to render, but never start a
        # fresh network request for a surface that is no longer visible.
        if not self.isVisible():
            return True
        self._skill_detail_generation += 1
        generation = self._skill_detail_generation
        if (self._skill_detail_reply is not None and
                self._skill_detail_reply.isRunning()):
            self._skill_detail_reply.abort()
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(target.replace(" ", "_"), safe=""))))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setTransferTimeout(12000)
        reply = self._network.get(request)
        self._skill_detail_reply = reply
        reply.finished.connect(lambda: self._skill_detail_finished(
            reply, skill, target, generation, cache_path))
        return True

    def _skill_detail_finished(
            self, reply, skill, target, generation, cache_path):
        try:
            if generation != self._skill_detail_generation:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("skill guide not found")
            rendered = parsed.get("text", {})
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            record = {
                "target": target,
                "wiki_html": sanitize_wiki_html(rendered),
                "fetched_at": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
            }
            cache_path.write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8")
            self._render_skill_detail(skill, record)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            if self._current_skill is skill:
                self.skill_source.setText(
                    f"PROJECT 1999 WIKI · CLASS FACTS AVAILABLE · GUIDE OFFLINE · {error}")
        finally:
            if self._skill_detail_reply is reply:
                self._skill_detail_reply = None
            reply.deleteLater()

    def _render_skill_detail(self, skill, record, cached=False):
        if self._current_skill is not skill and (
                not self._current_skill or
                self._current_skill.get("name") != skill.get("name")):
            return
        class_name = str(self._skills_data.get("class") or "Class")
        name = str(skill.get("name") or "Skill")
        facts = (
            f"<p><b>{html.escape(class_name)}</b> · level {skill.get('level')} · "
            f"{html.escape(str(skill.get('category') or ''))} · "
            f"trained {html.escape(str(skill.get('trained') or ''))} · "
            f"caps {html.escape(str(skill.get('cap_50') or ''))} / "
            f"{html.escape(str(skill.get('cap_60') or ''))}</p>")
        self.skill_body.setHtml(
            f"<h1>{html.escape(name)}</h1>" + facts +
            str(record.get("wiki_html") or "") +
            "<p>Source: Project 1999 Wiki.</p>")
        self.skill_source.setText(
            "PROJECT 1999 WIKI · SKILL GUIDE · " +
            ("LOCAL CACHE" if cached else "UPDATED NOW"))

    def _open_selected_skill(self):
        skill = self._current_skill
        if not skill:
            return False
        QDesktopServices.openUrl(QUrl(_wiki_url(
            skill.get("target") or f"Skill {skill.get('name') or ''}")))
        return True

    def closeEvent(self, event):
        """Stop deferred Wiki work before this reusable dialog is hidden."""
        self._selection_timer.stop()
        self._skill_selection_timer.stop()
        for reply in (
                self._reply, self._skills_reply, self._skill_detail_reply):
            if reply is not None and reply.isRunning():
                reply.abort()
        super().closeEvent(event)

    def _filters_changed(self, *_args):
        self._sync_available_levels()
        self.proxy.set_filters(
            self.search.text(), self.class_filter.currentData(),
            self.level_filter.currentData())
        QTimer.singleShot(0, self._select_first)

    def _sync_available_levels(self):
        """Keep the level menu limited to real levels for the chosen class."""
        class_name = str(self.class_filter.currentData() or "")
        available = sorted({
            level for entry in self._entries
            for listed_class, level in entry.class_levels
            if not class_name or listed_class == class_name})
        current = int(self.level_filter.currentData() or 0)
        values = [
            int(self.level_filter.itemData(index) or 0)
            for index in range(self.level_filter.count())]
        wanted = [0, *available]
        if values == wanted:
            return
        self.level_filter.blockSignals(True)
        self.level_filter.clear()
        self.level_filter.addItem("Any available level", 0)
        for level in available:
            self.level_filter.addItem(f"Level {level}", level)
        index = self.level_filter.findData(current)
        self.level_filter.setCurrentIndex(max(0, index))
        self.level_filter.blockSignals(False)

    def _select_first(self):
        if self.proxy.rowCount() <= 0:
            self._current = None
            self.name_label.setText("No matching spells")
            self.class_label.setText("Change the class, level, or search text.")
            return
        current = self.table.currentIndex()
        if not current.isValid() or current.row() >= self.proxy.rowCount():
            self.table.selectRow(0)
            self.table.setCurrentIndex(self.proxy.index(0, 0))

    def _selection_changed(self, current, _previous):
        if not current.isValid():
            return
        source = self.proxy.mapToSource(current)
        if not source.isValid():
            return
        self._pending = self.model.listings[source.row()].entry
        self._selection_timer.start()

    def _activate_index(self, index):
        """Open a clicked or keyboard-activated spell without hidden delay."""
        if not index.isValid():
            return
        source = self.proxy.mapToSource(index)
        if not source.isValid():
            return
        self.table.selectRow(index.row())
        self._pending = self.model.listings[source.row()].entry
        self._selection_timer.stop()
        self._load_pending()

    def _load_pending(self):
        entry = self._pending
        if entry is None:
            return
        self._current = entry
        self._linked_title = ""
        self._linked_url = QUrl()
        self.back_button.setEnabled(False)
        self.name_label.setText(entry.name)
        self.class_label.setText(entry.levels_text)
        self._set_icon(entry.icon_id)
        self._render_local(entry)
        cache_path = _cache_path(entry.name, self._market_server())
        cached = None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self._render_record(entry, cached, cached=True)
        except (OSError, ValueError, json.JSONDecodeError):
            cached = None
        fresh = False
        if cached:
            try:
                stamp = datetime.datetime.fromisoformat(cached["fetched_at"])
                fresh = (
                    datetime.datetime.now(datetime.timezone.utc) -
                    stamp.astimezone(datetime.timezone.utc)
                ).days < 7
            except (KeyError, TypeError, ValueError):
                pass
        if not fresh and self.isVisible():
            self._fetch(entry)

    def _set_icon(self, icon_id):
        self.icon.setPixmap(spell_icon_pixmap(icon_id or 0, 40))
        self.icon.setAccessibleName(
            f"Velious spell icon for {self._current.name}")

    def _market_item(self, entry):
        lookup = getattr(self.market, "price_for_spell", None)
        return lookup(entry.name) if callable(lookup) else {}

    def _market_server(self):
        return normalize_market_server(getattr(self.market, "_server", "Green"))

    def _price_html(self, entry, auction=None):
        server = self._market_server()
        item = self._market_item(entry) or {}
        combined = combined_market_price(item, auction or {})
        parts = []
        pig = int(combined.get("pig") or 0)
        wiki = int(combined.get("wiki") or 0)
        if pig:
            parts.append(
                f"PigParse {server} {html.escape(combined.get('pig_period') or '')}: "
                f"<b>{pig:,} pp</b>")
        if wiki:
            parts.append(f"P99 Wiki {server}: <b>{wiki:,} pp</b>")
        if combined.get("close"):
            parts.append(
                f"Sources agree · cautious average: "
                f"<b>{int(combined['combined']):,} pp</b>")
        elif pig and wiki:
            parts.append(
                f"Sources differ by {combined.get('difference_percent', 0):.0f}% · "
                "kept separate")
        if not parts:
            parts.append(
                f"No current {server} auction price found for this spell scroll")
        return " · ".join(parts)

    def _render_local(self, entry):
        prices = self._price_html(entry)
        self.price_label.setTextFormat(Qt.TextFormat.RichText)
        self.price_label.setText(prices)
        self.body.setHtml(
            f"<h2>{html.escape(entry.name)}</h2>"
            f"<p><b>Classes:</b> {html.escape(entry.levels_text)}</p>"
            "<p>Loading description, spell details, merchants, drops, quests, "
            "research recipes, and Wiki price history…</p>")
        self.source.setText(
            "CLASS + LEVEL · BUNDLED CLASSIC SPELL DATA · WIKI REQUEST PENDING")

    def _render_record(self, entry, record, cached=False):
        if self._current is None or self._current.name != entry.name:
            return
        auction = record.get("auction") or {}
        self.price_label.setTextFormat(Qt.TextFormat.RichText)
        self.price_label.setText(self._price_html(entry, auction))
        acquisition = str(record.get("acquisition") or "").strip()
        acquisition_html = ""
        if acquisition:
            acquisition_html = (
                "<div class='acquisition'><h3>Where to buy or obtain</h3><pre>" +
                html.escape(acquisition) + "</pre></div>")
        elif not record.get("wiki_html"):
            acquisition_html = (
                "<p>No merchant, drop, quest, or research section was found.</p>")
        page = str(record.get("wiki_html") or "")
        self.body.setHtml(
            f"<h1>{html.escape(entry.name)}</h1>"
            f"<p><b>Classes:</b> {html.escape(entry.levels_text)}</p>" +
            acquisition_html + page +
            "<p class='source'>Source: Project 1999 Wiki. "
            "Class/level source: bundled classic spells_us.txt.</p>")
        self.source.setText(
            "PROJECT 1999 WIKI · " +
            ("LOCAL CACHE" if cached else "UPDATED NOW") +
            f" · PIGPARSE {self._market_server().upper()} PRICES SHOWN SEPARATELY")

    def _open_detail_link(self, url):
        """Keep P99 Wiki navigation inside Vantage whenever possible."""
        target = QUrl(url)
        title = _wiki_title_from_url(target.toString())
        if not title:
            QDesktopServices.openUrl(target)
            return
        spell = self._entries_by_name.get(title.casefold())
        if spell is not None:
            self._select_spell(spell)
            return
        self._fetch_linked_page(title, target)

    def _select_spell(self, entry):
        self.search.blockSignals(True)
        self.class_filter.blockSignals(True)
        self.level_filter.blockSignals(True)
        self.search.clear()
        self.class_filter.setCurrentIndex(0)
        self._sync_available_levels()
        self.level_filter.setCurrentIndex(0)
        self.search.blockSignals(False)
        self.class_filter.blockSignals(False)
        self.level_filter.blockSignals(False)
        self.proxy.set_filters("", "", 0)
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            if (source.isValid()
                    and self.model.listings[source.row()].entry == entry):
                index = self.proxy.index(row, 1)
                self.table.scrollTo(index)
                self.table.setCurrentIndex(index)
                self._activate_index(index)
                return

    def _fetch_linked_page(self, title, source_url=None):
        if self._reply is not None and self._reply.isRunning():
            self._reply.abort()
        self._request_generation += 1
        generation = self._request_generation
        self._linked_title = str(title)
        self._linked_url = QUrl(source_url or _wiki_url(title))
        self.back_button.setEnabled(self._current is not None)
        self.name_label.setText(self._linked_title)
        self.class_label.setText(
            "Linked Project 1999 Wiki reference · browsing inside Vantage")
        self.icon.clear()
        self.icon.setText("↗")
        self.icon.setAccessibleName(f"Wiki reference for {self._linked_title}")
        self.price_label.setText(
            "Linked Wiki reference · use Back to spell to restore spell prices.")
        self.body.setHtml(
            f"<h2>{html.escape(self._linked_title)}</h2>"
            "<p>Loading linked Wiki information inside Vantage…</p>")
        self.source.setText("PROJECT 1999 WIKI · LINKED REFERENCE · LOADING")
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(self._linked_title.replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setTransferTimeout(12000)
        reply = self._network.get(request)
        self._reply = reply
        self.refresh_button.setEnabled(False)
        selected_title = self._linked_title
        reply.finished.connect(lambda: self._linked_page_finished(
            reply, selected_title, generation))

    def _linked_page_finished(self, reply, title, generation):
        try:
            if generation != self._request_generation:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload_bytes = bytes(reply.readAll())
            if len(payload_bytes) > 2_000_000:
                raise ValueError("Wiki response is larger than the safe limit")
            payload = json.loads(payload_bytes.decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("Project 1999 Wiki does not have this page")
            rendered = parsed.get("text", {})
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            wikitext = parsed.get("wikitext", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            acquisition = extract_acquisition_text(wikitext)
            acquisition_html = (
                "<div class='acquisition'><h3>Where to obtain</h3><pre>" +
                html.escape(acquisition) + "</pre></div>"
                if acquisition else "")
            self.body.setHtml(
                f"<h1>{html.escape(title)}</h1>" + acquisition_html +
                sanitize_wiki_html(rendered) +
                "<p class='source'>Source: Project 1999 Wiki.</p>")
            self.source.setText(
                "PROJECT 1999 WIKI · LINKED REFERENCE · INTERNAL VIEW")
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            self.body.setHtml(
                f"<h2>{html.escape(title)}</h2>"
                f"<p>Unable to load this linked Wiki page: "
                f"{html.escape(str(error))}</p>")
            self.source.setText("PROJECT 1999 WIKI · LINKED REFERENCE · OFFLINE")
        finally:
            if self._reply is reply:
                self._reply = None
            self.refresh_button.setEnabled(True)
            reply.deleteLater()

    def _return_to_spell(self):
        if self._current is not None:
            self._pending = self._current
            self._load_pending()

    def _fetch(self, entry):
        if self._reply is not None and self._reply.isRunning():
            self._reply.abort()
        self._request_generation += 1
        generation = self._request_generation
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(entry.name.replace(" ", "_"), safe=""))))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setTransferTimeout(12000)
        reply = self._network.get(request)
        self._reply = reply
        self.refresh_button.setEnabled(False)
        server = self._market_server()
        reply.finished.connect(
            lambda: self._finished(reply, entry, generation, server))

    def _finished(self, reply, entry, generation, server="Green"):
        try:
            if generation != self._request_generation:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload_bytes = bytes(reply.readAll())
            if len(payload_bytes) > 2_000_000:
                raise ValueError("Wiki response is larger than the safe limit")
            payload = json.loads(payload_bytes.decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("Project 1999 Wiki does not have this spell page")
            rendered = parsed.get("text", {})
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            wikitext = parsed.get("wikitext", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            record = {
                "name": entry.name,
                "url": _wiki_url(entry.name),
                "fetched_at": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
                "acquisition": extract_acquisition_text(wikitext),
                "wiki_html": sanitize_wiki_html(rendered),
                "auction": parse_wiki_auction_html(rendered, server),
            }
            _cache_path(entry.name, server).write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8")
            if server == self._market_server():
                self._render_record(entry, record)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            if self._current is not None and self._current.name == entry.name:
                self.source.setText(
                    f"PROJECT 1999 WIKI · OFFLINE · {error} · LOCAL CLASS INDEX ACTIVE")
        finally:
            if self._reply is reply:
                self._reply = None
            self.refresh_button.setEnabled(True)
            reply.deleteLater()

    def _refresh_current(self):
        if self._linked_title:
            self._fetch_linked_page(self._linked_title, self._linked_url)
        elif self._current is not None:
            self._fetch(self._current)

    def _open_current(self):
        if self._linked_title:
            QDesktopServices.openUrl(
                self._linked_url or QUrl(_wiki_url(self._linked_title)))
        elif self._current is not None:
            QDesktopServices.openUrl(QUrl(_wiki_url(self._current.name)))
