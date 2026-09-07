"""Independent Project 1999 zone browser."""

from __future__ import annotations

import json
from urllib.parse import quote
import webbrowser

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.responsive import (
    ensure_tab_tooltips, ensure_table_header_tooltips)
from vantage.parsers.maps.mapdata import MapData
from vantage.parsers.market import (
    P99_WIKI_API, _announce_accessible, _wiki_entity_cache_path,
    _wiki_target_url, _wiki_zone_cache_path, parse_wiki_entity_wikitext,
    parse_wiki_zone_payload)


class Zones(ParserWindow):
    """Search P99 zone content without coupling the workflow to Market."""

    name = "zones"
    _allow_clickthrough = False
    _minimum_scale = 0.80
    COLUMN_DEFAULTS = {
        "items": (320, 240),
        "mobs": (220, 65, 90, 105, 280, 180),
        "nameds": (220, 65, 90, 105, 280, 180),
    }

    def __init__(self):
        super().__init__()
        if config.data["zones"].get("clickthrough"):
            config.data["zones"]["clickthrough"] = False
            config.save()
        self.setWindowTitle("Zones · Project 1999")
        self._title.setText("Zones")
        self._network = QNetworkAccessManager(self)
        self._zone_data = {}
        self._zone_mobs = []
        self._zone_drop_requests = set()
        self._zone_reply = None
        self._zone_request_id = 0
        self._drop_reply_contexts = {}
        self._suppress_zone_selection = True
        self._zone_tables = {}
        self._column_width_save_timer = QTimer(self)
        self._column_width_save_timer.setSingleShot(True)
        self._column_width_save_timer.setInterval(350)
        self._column_width_save_timer.timeout.connect(
            self._save_column_widths)
        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cancel_network_requests)

    def _build_ui(self):
        controls = QFrame()
        controls.setObjectName("ZoneBrowserControls")
        control_layout = QGridLayout(controls)
        control_layout.setContentsMargins(7, 6, 7, 6)
        control_layout.setSpacing(5)

        self.zone_selector = QComboBox()
        self.zone_selector.setObjectName("ZoneSelector")
        self.zone_selector.setEditable(False)
        self.zone_selector.addItem("Choose a zone…", "")
        for name in sorted(MapData.get_zone_dict(), key=str.casefold):
            self.zone_selector.addItem(name.title(), name)
        self.zone_selector.setAccessibleName("Project 1999 zone")
        self.zone_selector.setAccessibleDescription(
            "Choose a zone; its items, mobs, named NPCs, and context load automatically")
        self.zone_selector.setToolTip(
            "Choose a Project 1999 zone · zone information loads automatically")
        self.zone_selector.currentIndexChanged.connect(self._zone_selected)
        control_layout.addWidget(self.zone_selector, 0, 0, 1, 3)

        self.zone_load_button = QPushButton("Reload zone")
        self.zone_load_button.setIcon(game_icon("refresh"))
        self.zone_load_button.setAccessibleName("Reload selected zone")
        self.zone_load_button.setToolTip(
            "Refresh the selected zone's mobs, nameds, and items from Project 1999 Wiki")
        self.zone_load_button.clicked.connect(self._load_zone)
        control_layout.addWidget(self.zone_load_button, 0, 3)

        self.zone_search = QLineEdit()
        self.zone_search.setPlaceholderText("Filter this zone's mobs, items, or drops…")
        self.zone_search.setClearButtonEnabled(True)
        self.zone_search.setAccessibleName("Filter loaded zone information")
        self.zone_search.setToolTip(
            "Filter the loaded zone's mobs, nameds, item drops, and locations")
        clear_button = self.zone_search.findChild(QToolButton)
        if clear_button:
            clear_button.setAccessibleName("Clear zone results filter")
            clear_button.setToolTip("Show all information in the loaded zone")
        self._filter_announce_timer = QTimer(self)
        self._filter_announce_timer.setSingleShot(True)
        self._filter_announce_timer.setInterval(300)
        self._filter_announce_timer.timeout.connect(
            lambda: self._refresh_views(announce=True))
        self.zone_search.textChanged.connect(self._schedule_filter_refresh)
        control_layout.addWidget(self.zone_search, 1, 0, 1, 4)
        control_layout.setColumnStretch(0, 1)
        self.content.addWidget(controls)

        self.zone_summary = QLabel(
            "Choose a zone to browse its items, mobs, nameds, and map.")
        self.zone_summary.setObjectName("ZoneBrowserSummary")
        self.zone_summary.setWordWrap(True)
        self.zone_summary.setAccessibleName(self.zone_summary.text())
        self.content.addWidget(self.zone_summary)
        self.zone_description = QLabel("")
        self.zone_description.setObjectName("ZoneBrowserDescription")
        self.zone_description.setWordWrap(True)
        self.zone_description.setAccessibleName("Selected zone summary")
        self.zone_description.hide()
        self.content.addWidget(self.zone_description)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ZoneBrowserTabs")
        self.item_table = self._table(
            "items", ("Item", "Source"), "Items in selected zone")
        self.mob_table = self._table(
            "mobs",
            ("NPC", "Level", "Class", "Race", "Drops", "Location"),
            "Mobs in selected zone")
        self.named_table = self._table(
            "nameds",
            ("Named NPC", "Level", "Class", "Race", "Drops", "Location"),
            "Named NPCs in selected zone")
        # Compatibility name for integrations that previously inspected the
        # Market tab's mixed NPC table.
        self.zone_table = self.mob_table
        for table, label in (
                (self.item_table, "Items"), (self.mob_table, "Mobs"),
                (self.named_table, "Nameds")):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(table)
            self.tabs.addTab(page, label)
        ensure_tab_tooltips(self.tabs, {
            "Items": "Unique items and known drops found in this zone",
            "Mobs": "Every NPC parsed from this zone's Project 1999 Wiki table",
            "Nameds": "Only notable or named NPCs in this zone",
        })
        self.tabs.currentChanged.connect(self._selection_changed)
        self.content.addWidget(self.tabs, 1)

        actions = QFrame()
        actions.setObjectName("ZoneBrowserActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(6, 4, 6, 4)
        action_layout.setSpacing(5)
        self.zone_result_count = QLabel("No zone loaded")
        self.zone_result_count.setObjectName("ZoneBrowserResultCount")
        action_layout.addWidget(self.zone_result_count, 1)

        self.zone_columns_button = QToolButton()
        self.zone_columns_button.setObjectName("ZoneColumnsButton")
        self.zone_columns_button.setText("&Columns")
        self.zone_columns_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.zone_columns_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.zone_columns_button.setAccessibleName("Resize zone table columns")
        self.zone_columns_button.setAccessibleDescription(
            "Open keyboard controls for the current table column. Columns "
            "can also be resized by dragging their header dividers")
        self.zone_columns_button.setToolTip(
            "Resize the current column · Alt+C · headers can also be dragged")
        self.zone_columns_menu = QMenu(self.zone_columns_button)
        self.zone_columns_menu.setAccessibleName("Zone column size controls")
        self.zone_columns_menu.setToolTipsVisible(True)
        self.zone_column_wider_action = self.zone_columns_menu.addAction(
            "Make &wider")
        self.zone_column_wider_action.setToolTip(
            "Increase the current column width")
        self.zone_column_wider_action.triggered.connect(
            lambda: self._resize_current_column(40))
        self.zone_column_narrower_action = self.zone_columns_menu.addAction(
            "Make &narrower")
        self.zone_column_narrower_action.setToolTip(
            "Decrease the current column width")
        self.zone_column_narrower_action.triggered.connect(
            lambda: self._resize_current_column(-40))
        self.zone_column_autofit_action = self.zone_columns_menu.addAction(
            "&Auto-fit current column")
        self.zone_column_autofit_action.setToolTip(
            "Fit the current column to its heading and visible content")
        self.zone_column_autofit_action.triggered.connect(
            self._autofit_current_column)
        self.zone_columns_menu.addSeparator()
        self.zone_column_reset_action = self.zone_columns_menu.addAction(
            "&Reset this tab")
        self.zone_column_reset_action.setToolTip(
            "Restore the default widths for every column on this tab")
        self.zone_column_reset_action.triggered.connect(
            self._reset_current_table_columns)
        self.zone_columns_menu.aboutToShow.connect(
            self._update_column_action_state)
        self.zone_columns_button.setMenu(self.zone_columns_menu)
        action_layout.addWidget(self.zone_columns_button)

        self.zone_detail_button = QPushButton("Open details")
        self.zone_detail_button.setIcon(game_icon("ph-file-search"))
        self.zone_detail_button.setAccessibleName("Open selected zone result details")
        self.zone_detail_button.setToolTip(
            "Open the selected NPC, item, or quest details")
        self.zone_detail_button.setEnabled(False)
        self.zone_detail_button.clicked.connect(self._open_selected)
        action_layout.addWidget(self.zone_detail_button)

        self.zone_drop_selector = QComboBox()
        self.zone_drop_selector.setMinimumContentsLength(14)
        self.zone_drop_selector.setAccessibleName("Drop from selected NPC")
        self.zone_drop_selector.setToolTip("Choose a known drop from the selected NPC")
        self.zone_drop_selector.setEnabled(False)
        action_layout.addWidget(self.zone_drop_selector)

        self.zone_drop_button = QPushButton("Item details")
        self.zone_drop_button.setIcon(game_icon("market"))
        self.zone_drop_button.setAccessibleName("Open selected NPC drop details")
        self.zone_drop_button.setToolTip("Open the selected drop as a Vantage item card")
        self.zone_drop_button.setEnabled(False)
        self.zone_drop_button.clicked.connect(self._open_selected_drop)
        action_layout.addWidget(self.zone_drop_button)

        self.zone_map_button = QPushButton("Vantage map")
        self.zone_map_button.setIcon(game_icon("map"))
        self.zone_map_button.setAccessibleName("Open selected zone in Vantage Maps")
        self.zone_map_button.setToolTip("Open this zone in Vantage's interactive map window")
        self.zone_map_button.setEnabled(False)
        self.zone_map_button.clicked.connect(self._open_zone_map)
        action_layout.addWidget(self.zone_map_button)

        self.zone_wiki_button = QPushButton("Zone Wiki")
        self.zone_wiki_button.setIcon(game_icon("ph-spellbook"))
        self.zone_wiki_button.setAccessibleName("Open selected zone on Project 1999 Wiki")
        self.zone_wiki_button.setToolTip("Open the complete zone page on Project 1999 Wiki")
        self.zone_wiki_button.setEnabled(False)
        self.zone_wiki_button.clicked.connect(self._open_zone_wiki)
        action_layout.addWidget(self.zone_wiki_button)
        self.content.addWidget(actions)

        last_zone = str(config.data["zones"].get("last_zone", "") or "")
        if last_zone:
            self._select_zone(last_zone)
        self._suppress_zone_selection = False

    def _table(self, table_key, headers, accessible_name):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setSortingEnabled(True)
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.verticalHeader().setVisible(False)
        table.setAccessibleName(accessible_name)
        table.setAccessibleDescription(
            "Sortable results. Drag a header divider to resize columns; use "
            "the Columns menu for keyboard resizing and the horizontal "
            "scrollbar for wide content. Press Enter or double-click to open "
            "the selected result")
        ensure_table_header_tooltips(table, accessible_name.casefold())
        header = table.horizontalHeader()
        header.setAccessibleName(f"Resizable columns for {accessible_name}")
        header.setAccessibleDescription(
            "Click a heading to sort. Drag the divider between headings to "
            "make a column wider or narrower")
        header.setToolTip(
            "Click a heading to sort · drag a divider to resize · saved per tab")
        header.setMinimumSectionSize(38)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        saved = config.data["zones"].get("column_widths", {}).get(table_key)
        widths = saved if isinstance(saved, list) else self.COLUMN_DEFAULTS[table_key]
        for column, width in enumerate(widths):
            table.setColumnWidth(column, int(width))
        self._zone_tables[table_key] = table
        header.sectionResized.connect(
            lambda *_args: self._column_width_save_timer.start())
        table.itemSelectionChanged.connect(self._selection_changed)
        table.cellDoubleClicked.connect(lambda *_: self._open_selected())
        table.installEventFilter(self)
        return table

    def _capture_column_widths(self):
        if not getattr(self, "_zone_tables", None):
            return
        config.data["zones"]["column_widths"] = {
            table_key: [
                table.columnWidth(column)
                for column in range(table.columnCount())]
            for table_key, table in self._zone_tables.items()
        }

    def _save_column_widths(self):
        self._capture_column_widths()
        if getattr(config, "_filename", ""):
            config.save()

    def _save_geometry(self):
        # Update/install checkpoints call this synchronously. Capture widths
        # before the base class writes the same atomic settings file.
        self._capture_column_widths()
        super()._save_geometry()

    def _current_column_context(self):
        table = self._current_table()
        column = table.currentColumn()
        if column < 0 or column >= table.columnCount():
            column = 0 if table.columnCount() else -1
        header_item = table.horizontalHeaderItem(column) if column >= 0 else None
        name = header_item.text() if header_item is not None else "column"
        return table, column, name

    def _update_column_action_state(self):
        table, column, _name = self._current_column_context()
        available = column >= 0
        self.zone_column_wider_action.setEnabled(
            available and table.columnWidth(column) < 1200)
        self.zone_column_narrower_action.setEnabled(
            available and table.columnWidth(column) >
            table.horizontalHeader().minimumSectionSize())
        self.zone_column_autofit_action.setEnabled(available)
        self.zone_column_reset_action.setEnabled(table.columnCount() > 0)

    def _announce_column_width(self, name, width):
        _announce_accessible(self, f"{name} column width {width} pixels")

    def _resize_current_column(self, adjustment):
        table, column, name = self._current_column_context()
        if column < 0:
            return False
        minimum = table.horizontalHeader().minimumSectionSize()
        width = max(minimum, min(1200, table.columnWidth(column) + adjustment))
        table.setColumnWidth(column, width)
        self._column_width_save_timer.start()
        self._announce_column_width(name, table.columnWidth(column))
        return True

    def _autofit_current_column(self):
        table, column, name = self._current_column_context()
        if column < 0:
            return False
        table.resizeColumnToContents(column)
        width = max(
            table.horizontalHeader().minimumSectionSize(),
            min(1200, table.columnWidth(column)))
        table.setColumnWidth(column, width)
        self._column_width_save_timer.start()
        self._announce_column_width(name, table.columnWidth(column))
        return True

    def _reset_current_table_columns(self):
        table = self._current_table()
        table_key = next(
            (key for key, candidate in self._zone_tables.items()
             if candidate is table), None)
        if table_key is None:
            return False
        for column, width in enumerate(self.COLUMN_DEFAULTS[table_key]):
            table.setColumnWidth(column, width)
        self._column_width_save_timer.start()
        tab_name = self.tabs.tabText(self.tabs.currentIndex())
        _announce_accessible(self, f"{tab_name} column widths reset")
        return True

    def eventFilter(self, watched, event):
        zone_tables = tuple(
            table for name in ("item_table", "mob_table", "named_table")
            if (table := getattr(self, name, None)) is not None)
        if (watched in zone_tables
                and event.type() == QEvent.Type.KeyPress
                and isinstance(event, QKeyEvent)
                and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}):
            self._open_selected()
            return True
        return super().eventFilter(watched, event)

    def _zone_selected(self, _index):
        if self._suppress_zone_selection:
            return False
        if not self._selected_zone_name():
            self._clear_zone_results()
            self.zone_summary.setText("Choose a zone first.")
            self.zone_summary.setAccessibleName(self.zone_summary.text())
            return False
        self._clear_zone_results()
        return self._load_zone(announce=True)

    def _clear_zone_results(self):
        """Remove the previous zone immediately while a new one is loading."""
        self._zone_data = {}
        self._zone_mobs = []
        self.zone_description.clear()
        self.zone_description.hide()
        self.zone_map_button.setEnabled(False)
        self.zone_wiki_button.setEnabled(False)
        self._refresh_views(announce=False)

    def toggle(self):
        was_visible = self.isVisible()
        super().toggle()
        if not was_visible and self.isVisible():
            # Opening this task is an explicit navigation action. Put keyboard
            # users at the first decision without opening the popup for them.
            QTimer.singleShot(
                0, lambda: self.zone_selector.setFocus(
                    Qt.FocusReason.OtherFocusReason))

    def _selected_zone_name(self):
        return str(self.zone_selector.currentData() or "").strip()

    def _selected_wiki_name(self):
        """Return display casing because MediaWiki title text is case-sensitive."""
        return str(self.zone_selector.currentText() or "").strip()

    def _select_zone(self, name):
        resolved = MapData.resolve_zone_name(name)
        if not resolved:
            return False
        for index in range(self.zone_selector.count()):
            if str(self.zone_selector.itemData(index) or "").casefold() == resolved.casefold():
                blocker = QSignalBlocker(self.zone_selector)
                self.zone_selector.setCurrentIndex(index)
                del blocker
                return True
        return False

    def _load_zone(self, _checked=False, announce=True):
        requested = self._selected_wiki_name()
        if not requested:
            self.zone_summary.setText("Choose a zone first.")
            self.zone_summary.setAccessibleName(self.zone_summary.text())
            self.zone_selector.setFocus()
            if announce:
                _announce_accessible(self, "Choose a zone first")
            return False
        if self._zone_reply is not None:
            previous = self._zone_reply
            # Mark it stale and disconnect before abort(); Qt may emit finished
            # synchronously from abort(), which previously allowed a nested
            # table rebuild inside currentIndexChanged on Windows.
            self._zone_reply = None
            try:
                previous.finished.disconnect(self._zone_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                previous.abort()
            except RuntimeError:
                pass
            try:
                previous.deleteLater()
            except RuntimeError:
                pass
        self.zone_load_button.setEnabled(False)
        self.zone_load_button.setText("Loading…")
        self.zone_summary.setText(f"Loading {requested.title()} from Project 1999 Wiki…")
        self.zone_summary.setAccessibleName(self.zone_summary.text())
        if announce:
            _announce_accessible(self, self.zone_summary.text())
        cache_path = _wiki_zone_cache_path(requested)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("mobs"):
                self._set_zone_data(cached, cached=True, announce=announce)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(requested.replace(" ", "_"), safe="")) +
            "&redirects=1"))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.52")
        reply = self._network.get(request)
        self._zone_request_id += 1
        reply.setProperty("zoneRequestId", self._zone_request_id)
        reply.setProperty("zoneRequested", requested)
        reply.setProperty("zoneCachePath", str(cache_path))
        reply.setProperty("zoneAnnounce", bool(announce))
        self._zone_reply = reply
        reply.finished.connect(self._zone_finished)
        return True

    def _zone_finished(self):
        reply = self.sender()
        if reply is None:
            return
        requested = str(reply.property("zoneRequested") or "")
        cache_path = _wiki_zone_cache_path(requested)
        announce = bool(reply.property("zoneAnnounce"))
        current = bool(
            reply is self._zone_reply and
            int(reply.property("zoneRequestId") or -1) ==
            self._zone_request_id)
        try:
            if not current:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse")
            if not isinstance(parsed, dict):
                raise ValueError("zone not found on Project 1999 Wiki")
            wikitext = parsed.get("wikitext", {})
            rendered = parsed.get("text", {})
            if isinstance(wikitext, dict):
                wikitext = wikitext.get("*", "")
            if isinstance(rendered, dict):
                rendered = rendered.get("*", "")
            data = parse_wiki_zone_payload(
                wikitext, rendered, parsed.get("title") or requested)
            if not data.get("mobs"):
                raise ValueError("the Wiki page has no recognized zone mob table")
            self._set_zone_data(data, announce=announce)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, RuntimeError, UnicodeError, ValueError,
                json.JSONDecodeError) as error:
            if current and not self._zone_mobs:
                self.zone_summary.setText(f"Could not load {requested.title()} · {error}")
                self.zone_summary.setAccessibleName(self.zone_summary.text())
                if announce:
                    _announce_accessible(
                        self, self.zone_summary.text(), assertive=True)
        finally:
            if current:
                self._zone_reply = None
                self.zone_load_button.setEnabled(True)
                self.zone_load_button.setText("Reload zone")
            reply.deleteLater()

    def _set_zone_data(self, data, cached=False, announce=True):
        self._zone_data = dict(data or {})
        self._zone_mobs = list(self._zone_data.get("mobs") or [])
        name = str(self._zone_data.get("name") or self._selected_zone_name()).strip()
        self._select_zone(name)
        config.data["zones"]["last_zone"] = self._selected_zone_name() or name
        if getattr(config, "_filename", ""):
            config.save()
        notable_count = sum(bool(mob.get("named")) for mob in self._zone_mobs)
        facts = [value for value in (
            name,
            self._zone_data.get("era"),
            f"Levels {self._zone_data.get('levels')}" if self._zone_data.get("levels") else "",
            f"{len(self._zone_mobs):,} mobs",
            f"{notable_count:,} nameds",
            "Vantage map available" if MapData.resolve_zone_name(name) else "No Vantage map") if value]
        suffix = " · cached" if cached else " · updated now"
        self.zone_summary.setText(" · ".join(facts) + suffix)
        self.zone_summary.setAccessibleName(self.zone_summary.text())
        description = " ".join(
            str(self._zone_data.get("summary") or "").split())
        visible_description = (
            description if len(description) <= 300 else
            description[:297].rstrip() + "…")
        self.zone_description.setText(visible_description)
        self.zone_description.setToolTip(description)
        self.zone_description.setVisible(bool(visible_description))
        self.zone_map_button.setEnabled(bool(MapData.resolve_zone_name(name)))
        self.zone_wiki_button.setEnabled(True)
        self._refresh_views(announce=False)
        if announce:
            _announce_accessible(
                self, f"Loaded {name}: {len(self._zone_mobs)} mobs, "
                f"{notable_count} named NPCs")

    def _items(self):
        rows = []
        seen = set()
        for item in self._zone_data.get("unique_items") or []:
            key = str(item).strip().casefold()
            if key and key not in seen:
                seen.add(key)
                rows.append((str(item).strip(), "Zone unique item"))
        for mob in self._zone_mobs:
            for item in mob.get("drops") or []:
                key = str(item).strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    rows.append((str(item).strip(), str(mob.get("name") or "Known drop")))
        return rows

    def _refresh_views(self, *_args, announce=True):
        query = self.zone_search.text().strip().casefold()
        items = [row for row in self._items() if not query or query in " ".join(row).casefold()]
        mobs = [mob for mob in self._zone_mobs if not query or query in " ".join(
            str(value or "") for value in (
                mob.get("name"), mob.get("level"), mob.get("class"), mob.get("race"),
                mob.get("loot"), mob.get("location"), mob.get("description"))).casefold()]
        nameds = [mob for mob in mobs if mob.get("named")]
        self._fill_simple(self.item_table, items)
        self._fill_mobs(self.mob_table, mobs)
        self._fill_mobs(self.named_table, nameds)
        counts = (f"{len(items)} items · {len(mobs)} mobs · "
                  f"{len(nameds)} nameds")
        self.zone_result_count.setText(counts)
        self.zone_result_count.setAccessibleName(counts)
        self._selection_changed()
        if announce and self._zone_data:
            _announce_accessible(self, f"Zone filter results: {counts}")

    def _schedule_filter_refresh(self, *_args):
        self._filter_announce_timer.start()

    @staticmethod
    def _fill_simple(table, rows):
        blocker = QSignalBlocker(table)
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_number, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                item.setData(Qt.ItemDataRole.UserRole, str(values[0]))
                table.setItem(row_number, column, item)
        table.setSortingEnabled(True)
        del blocker

    @staticmethod
    def _fill_mobs(table, mobs):
        blocker = QSignalBlocker(table)
        table.setSortingEnabled(False)
        table.setRowCount(len(mobs))
        for row_number, mob in enumerate(mobs):
            values = (mob.get("name"), mob.get("level"), mob.get("class"),
                      mob.get("race"), mob.get("loot") or "—",
                      mob.get("location") or "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, mob)
                table.setItem(row_number, column, item)
        table.setSortingEnabled(True)
        del blocker

    def _current_table(self):
        return (self.item_table, self.mob_table,
                self.named_table)[self.tabs.currentIndex()]

    def _selected_value(self):
        table = self._current_table()
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, *_):
        value = self._selected_value()
        self.zone_detail_button.setEnabled(bool(value))
        mob = value if isinstance(value, dict) else None
        self.zone_drop_selector.clear()
        for drop in (mob or {}).get("drops", []):
            self.zone_drop_selector.addItem(str(drop))
        has_drops = self.zone_drop_selector.count() > 0
        self.zone_drop_selector.setEnabled(has_drops)
        self.zone_drop_button.setEnabled(has_drops)
        if mob and not has_drops and str(mob.get("loot") or "").casefold() == "various":
            self._load_selected_drops(mob)

    def _market(self):
        return getattr(QApplication.instance(), "_parsers_dict", {}).get("market")

    def _open_selected(self):
        value = self._selected_value()
        if not value:
            return False
        market = self._market()
        if self.tabs.currentIndex() in (1, 2):
            if market:
                market._show_wiki_entity(
                    value.get("target") or value.get("name"), value.get("name"), "npc")
                return True
            target = value.get("target") or value.get("name")
        else:
            target = str(value)
            if self.tabs.currentIndex() == 0 and market:
                market._show_wiki_item_name(target)
                return True
        return bool(webbrowser.open(_wiki_target_url(target)))

    def _open_selected_drop(self):
        name = self.zone_drop_selector.currentText().strip()
        if not name:
            return False
        market = self._market()
        return bool(market._show_wiki_item_name(name)) if market else bool(
            webbrowser.open(_wiki_target_url(name)))

    def _load_selected_drops(self, mob):
        target = str(mob.get("target") or mob.get("name") or "").strip()
        key = target.casefold()
        if not target or key in self._zone_drop_requests:
            return False
        cache_path = _wiki_entity_cache_path(target, "npc")
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            drops = list(cached.get("drops") or [])
            if drops:
                return self._apply_drops(mob, drops)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        self._zone_drop_requests.add(key)
        request = QNetworkRequest(QUrl(P99_WIKI_API.format(
            slug=quote(target.replace(" ", "_"), safe=""))))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Vantage/1.44.52")
        reply = self._network.get(request)
        self._drop_reply_contexts[reply] = (mob, target, key, cache_path)
        reply.finished.connect(self._drops_finished)
        return True

    def _drops_finished(self):
        reply = self.sender()
        if reply is None:
            return
        context = self._drop_reply_contexts.pop(reply, None)
        if context is None:
            reply.deleteLater()
            return
        mob, target, key, cache_path = context
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
            entity = parse_wiki_entity_wikitext(wikitext, fallback_name=target, kind="npc")
            cache_path.write_text(json.dumps(entity), encoding="utf-8")
            self._apply_drops(mob, entity.get("drops") or [])
        except (OSError, RuntimeError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        finally:
            self._zone_drop_requests.discard(key)
            reply.deleteLater()

    def _cancel_network_requests(self):
        """Make every late network completion harmless during app teardown."""
        zone_reply = self._zone_reply
        self._zone_reply = None
        self._zone_request_id += 1
        if zone_reply is not None:
            try:
                zone_reply.finished.disconnect(self._zone_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                zone_reply.abort()
            except RuntimeError:
                pass
            try:
                zone_reply.deleteLater()
            except RuntimeError:
                pass
        pending = list(self._drop_reply_contexts)
        self._drop_reply_contexts.clear()
        self._zone_drop_requests.clear()
        for reply in pending:
            try:
                reply.finished.disconnect(self._drops_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                reply.abort()
            except RuntimeError:
                pass
            try:
                reply.deleteLater()
            except RuntimeError:
                pass

    def _apply_drops(self, mob, drops):
        drops = [str(value).strip() for value in drops if str(value).strip()]
        if not drops:
            return False
        mob["drops"] = drops
        mob["loot"] = ", ".join(drops)
        self._refresh_views(announce=False)
        return True

    def _open_zone_map(self):
        name = str(self._zone_data.get("name") or self._selected_zone_name())
        maps = getattr(QApplication.instance(), "_parsers_dict", {}).get("maps")
        if not maps or not maps._load_zone(name):
            self.zone_summary.setText(f"No bundled Vantage map matches {name}.")
            self.zone_summary.setAccessibleName(self.zone_summary.text())
            _announce_accessible(self, self.zone_summary.text(), assertive=True)
            return False
        if not maps.isVisible():
            maps.toggle()
        else:
            maps.raise_()
            maps.activateWindow()
        return True

    def _open_zone_wiki(self):
        name = str(self._zone_data.get("name") or self._selected_zone_name()).strip()
        return bool(name and webbrowser.open(_wiki_target_url(name)))

    def parse(self, _timestamp, text):
        prefix = "You have entered "
        if str(text).casefold().startswith(prefix.casefold()) and str(text).endswith("."):
            zone = str(text)[len(prefix):-1]
            if self._select_zone(zone):
                self._load_zone(announce=False)
