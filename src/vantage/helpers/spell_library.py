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
    QLineEdit, QPushButton, QSplitter, QTableView, QTextBrowser,
    QVBoxLayout, QWidget)

from vantage.helpers import resource_path
from vantage.helpers.icons import game_icon
from vantage.helpers.spell_icons import spell_icon_pixmap
from vantage.helpers.portable import data_dir
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spell_catalog import P99_SPELL_CLASSES, p99_spell_entries
from vantage.parsers.market import (
    combined_market_price, normalize_market_server,
    parse_wiki_auction_html)


P99_WIKI_API = (
    "https://wiki.project1999.com/api.php?action=parse&page={slug}"
    "&prop=text%7Cwikitext&format=json")
P99_WIKI_URL = "https://wiki.project1999.com/{slug}"
USER_AGENT = "Vantage/1.44.23"
ACQUISITION_WORDS = (
    "merchant", "sold by", "where to obtain", "where to find", "drop",
    "research", "recipe", "created by", "quest", "reward", "turn in",
)


def _cache_path(name, server="Green"):
    server = normalize_market_server(server).casefold()
    digest = hashlib.sha256(
        str(name).strip().casefold().encode("utf-8")).hexdigest()[:20]
    return data_dir("cache", "wiki-spells") / f"{server}-{digest}.json"


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
        r"\s(?:style|class|id|srcset|src|on\w+)=(?:\"[^\"]*\"|'[^']*')",
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
        self._linked_title = ""
        self._linked_url = QUrl()
        self._request_generation = 0
        self._network = QNetworkAccessManager(self)
        self.setObjectName("SpellLibraryDialog")
        self.setWindowTitle("Vantage · P99 Spell Library")

        root = QVBoxLayout(self.scaled_surface)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

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
        root.addLayout(controls)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

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
            "table { border-collapse: collapse; }"
            "th { color: #E8D59D; background: #1B2026; }"
            "td, th { border: 1px solid #3A3D3D; padding: 3px; }"
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
        QTimer.singleShot(0, self._select_first)

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
        if not fresh:
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
